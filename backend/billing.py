"""Billing API (thin adapter over ``career_guidance.billing``).

- ``GET /plans`` is public: the pricing page needs it without sign-in.
- Checkout and the webhook answer 501 while Razorpay keys are unset;
  a payment is never faked.
- The webhook verifies the HMAC-SHA256 signature before touching any
  row, and only ``payment.captured`` activates a plan.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from career_guidance.billing import (
    BillingStore,
    effective_plan,
    load_billing_config,
    plans_payload,
    trial_active,
    trial_used,
    verify_razorpay_signature,
)

logger = logging.getLogger(__name__)

_RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class CheckoutRequest(BaseModel):
    plan: str


def require_pro(user, users) -> None:
    """Gate for premium routes: 401 for guests, 402 for Free users.

    Honoured only while ``BILLING_ENFORCE_PRO`` is on (default on); the
    owner flips it off with one env var to restore open access.
    """
    config = load_billing_config()
    if not config.enforce_pro:
        return
    if user.id == "guest":
        raise HTTPException(401, "Sign in required.")
    state = users.plan_of(user.id)
    if effective_plan(state["plan"], state["trial_ends_at"]) not in ("pro", "institute"):
        raise HTTPException(402, "Pro required for this feature.")


def build_router(current_user, users, db_path) -> APIRouter:
    """Billing routes: plans, own status, trial, checkout, webhook."""
    router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
    store = BillingStore(db_path)

    @router.get("/plans")
    def plans() -> dict:
        config = load_billing_config()
        return {
            "plans": plans_payload(config),
            "payments_configured": config.payments_configured,
            "trial_days": config.trial_days,
        }

    @router.get("/me")
    def billing_me(user=Depends(current_user)) -> dict:  # noqa: B008
        state = users.plan_of(user.id)
        return {
            "plan": state["plan"],
            "effective_plan": effective_plan(state["plan"], state["trial_ends_at"]),
            "trial_ends_at": state["trial_ends_at"],
            "trial_active": trial_active(state["trial_ends_at"]),
            "trial_used": trial_used(state["trial_ends_at"]),
        }

    @router.post("/trial/start")
    def start_trial(user=Depends(current_user)) -> dict:  # noqa: B008
        config = load_billing_config()
        state = users.plan_of(user.id)
        if state["plan"] in ("pro", "institute"):
            raise HTTPException(400, "Already on a paid plan.")
        if trial_used(state["trial_ends_at"]):
            raise HTTPException(400, "Trial already used.")
        if config.trial_days <= 0:
            raise HTTPException(400, "Trials are not enabled.")
        ends = (datetime.now(timezone.utc) + timedelta(days=config.trial_days)).isoformat(
            timespec="seconds"
        )
        users.start_trial(user.id, ends)
        return {
            "plan": "pro",
            "effective_plan": "pro",
            "trial_ends_at": ends,
            "trial_active": True,
        }

    @router.post("/checkout")
    def checkout(body: CheckoutRequest, user=Depends(current_user)) -> dict:  # noqa: B008
        config = load_billing_config()
        if not config.payments_configured:
            raise HTTPException(501, "Payments are not configured yet.")
        if body.plan not in ("pro", "institute"):
            raise HTTPException(400, "Checkout is only for Pro or Institute plans.")
        price = config.pro_price_inr if body.plan == "pro" else config.institute_price_inr
        if price is None:
            raise HTTPException(409, "Price is not configured for this plan.")
        receipt = f"cg-{user.id}-{int(time.time())}"
        try:
            response = httpx.post(
                _RAZORPAY_ORDERS_URL,
                auth=(config.razorpay_key_id, config.razorpay_key_secret),
                json={
                    "amount": price * 100,
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": {"plan": body.plan, "user_id": user.id},
                },
                timeout=15,
            )
        except httpx.HTTPError:
            raise HTTPException(502, "Payment provider unreachable.")  # noqa: B904
        if response.status_code != 201:
            logger.warning("Razorpay order failed: HTTP %s", response.status_code)
            raise HTTPException(502, "Payment provider rejected the order.")
        order_id = response.json().get("id", "")
        if not order_id:
            raise HTTPException(502, "Payment provider returned no order id.")
        store.create_payment(user.id, order_id, body.plan, price * 100, "INR")
        return {
            "order_id": order_id,
            "key_id": config.razorpay_key_id,
            "amount_paise": price * 100,
            "currency": "INR",
            "plan": body.plan,
        }

    @router.post("/webhook")
    async def webhook(request: Request) -> dict:
        config = load_billing_config()
        if not config.payments_configured:
            raise HTTPException(501, "Payments are not configured yet.")
        body = await request.body()
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not verify_razorpay_signature(config.razorpay_key_secret, body, signature):
            raise HTTPException(401, "Invalid webhook signature.")
        try:
            event = json.loads(body or b"{}")
        except ValueError:
            raise HTTPException(400, "Invalid webhook payload.")  # noqa: B904
        if event.get("event") != "payment.captured":
            return {"ok": True}
        entity = (event.get("payload") or {}).get("payment", {}).get("entity", {})
        order_id = entity.get("order_id", "")
        payment = store.payment_by_order(order_id) if order_id else None
        if payment is None:
            logger.warning("Webhook for unknown order id received; ignored.")
            return {"ok": True}
        store.mark_captured(order_id)
        users.set_plan(payment["user_id"], payment["plan"])
        return {"ok": True}

    return router
