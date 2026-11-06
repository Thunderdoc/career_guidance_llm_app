"""Billing API (thin adapter over ``career_guidance.billing``).

- ``GET /plans`` is public: the pricing page needs it without sign-in.
- Checkout and the webhook answer 501 while Razorpay keys are unset;
  a payment is never faked.
- The webhook verifies the HMAC-SHA256 signature before touching any
  row. ``payment.captured`` activates a plan (one-time checkout);
  subscription events drive the Phase 9 subscription ledger:

  ==========================  ============================================
  event                       effect
  ==========================  ============================================
  ``subscription.activated``  status=active, period end set, plan on
  ``subscription.charged``    status=active, period end EXTENDED to
                              Razorpay's absolute ``current_end``, plan on
  ``subscription.cancelled``  status=cancelled — plan STAYS until the
                              recorded period end (no instant downgrade)
  ``subscription.halted``     status=halted — plan stays until period end
  ``subscription.paused``     status=paused — plan stays until period end
  ``subscription.resumed``    status=active, plan on
  ``subscription.completed``  status=completed (all cycles billed)
  anything else               acknowledged, ignored
  ==========================  ============================================

  Every subscription event is recorded in the ``webhook_events``
  idempotency ledger (key = event + subscription id + payment id /
  period end) before side effects run, so a replayed delivery is
  acknowledged without re-applying anything.
- Phase 9 coupons/referrals: discounts exist only for coupons a
  platform admin created; redemption + referral attribution are written
  in the same transaction as the payment row.
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
    BillingError,
    BillingStore,
    DemoRequestStore,
    SubscriptionStore,
    create_subscription,
    effective_plan,
    load_billing_config,
    plans_payload,
    trial_active,
    trial_used,
    verify_razorpay_signature,
)
from career_guidance.coupons import CouponError, CouponStore, ReferralStore, compute_discount

logger = logging.getLogger(__name__)

_RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class CheckoutRequest(BaseModel):
    plan: str
    coupon_code: str = ""
    referral_code: str = ""


class SubscribeRequest(BaseModel):
    plan: str


class CouponValidateRequest(BaseModel):
    code: str
    plan: str


class CouponCreateRequest(BaseModel):
    code: str
    kind: str = "percent"
    value: int
    max_redemptions: int | None = None
    per_user_limit: int = 1
    expires_at: str = ""


class DemoRequest(BaseModel):
    name: str
    email: str
    organisation: str
    seats: int | None = None
    message: str = ""


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


def build_router(current_user, users, db_path, admin_user=None) -> APIRouter:
    """Billing routes: plans, own status, trial, checkout, webhook."""
    router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
    store = BillingStore(db_path)
    demo_store = DemoRequestStore(db_path)
    subscriptions = SubscriptionStore(db_path)
    coupon_store = CouponStore(db_path)
    referral_store = ReferralStore(db_path)

    @router.post("/demo-request")
    def demo_request(body: DemoRequest) -> dict:
        """Public institute lead capture (landing 'Request a demo' form).

        Validates and stores the lead only — no e-mail is sent. Admins read
        the leads via ``GET /demo-requests`` (admin role, server-side).
        """
        name = body.name.strip()
        email = body.email.strip()
        organisation = body.organisation.strip()
        if len(name) < 2 or len(organisation) < 2:
            raise HTTPException(422, "Name and organisation are required.")
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise HTTPException(422, "A valid e-mail address is required.")
        if body.seats is not None and not (1 <= body.seats <= 100_000):
            raise HTTPException(422, "Seats must be between 1 and 100000.")
        lead_id = demo_store.create(
            name[:120], email[:200], organisation[:200], body.seats, body.message.strip()[:2000]
        )
        return {"id": lead_id, "stored": True}

    @router.get("/demo-requests")
    def demo_requests(user=Depends(admin_user) if admin_user else Depends(current_user)) -> dict:  # noqa: B008
        if admin_user is None:
            raise HTTPException(403, "Admin only.")
        return {"requests": demo_store.list()}

    @router.get("/plans")
    def plans() -> dict:
        config = load_billing_config()
        return {
            "plans": plans_payload(config),
            "payments_configured": config.payments_configured,
            # Phase 9: the frontend shows the auto-renew option ONLY when
            # this is true (keys + at least one Razorpay plan id set).
            "subscriptions_enabled": config.subscriptions_configured,
            "trial_days": config.trial_days,
        }

    @router.get("/me")
    def billing_me(user=Depends(current_user)) -> dict:  # noqa: B008
        state = users.plan_of(user.id)
        subscription = subscriptions.for_user(user.id)
        return {
            "plan": state["plan"],
            "effective_plan": effective_plan(state["plan"], state["trial_ends_at"]),
            "trial_ends_at": state["trial_ends_at"],
            "trial_active": trial_active(state["trial_ends_at"]),
            "trial_used": trial_used(state["trial_ends_at"]),
            # Additive (Phase 9): latest subscription ledger row or None.
            "subscription": (
                {
                    "plan": subscription["plan"],
                    "status": subscription["status"],
                    "current_period_end": subscription["current_period_end"],
                }
                if subscription
                else None
            ),
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
        gross_paise = price * 100
        # Coupon: validated + priced SERVER-SIDE; the client's amounts
        # are never trusted. Rejection happens before any order exists.
        coupon = None
        discount_paise = 0
        if body.coupon_code.strip():
            coupon, reason = coupon_store.validate_for(body.coupon_code, user.id)
            if coupon is None:
                raise HTTPException(400, reason or "Coupon is not valid.")
            discount_paise = compute_discount(coupon, gross_paise)
        # Referral: attribution only; an unknown or self code records
        # nothing and never blocks the purchase.
        referrer_user_id = None
        if body.referral_code.strip():
            owner = referral_store.owner_of(body.referral_code)
            if owner and owner != user.id:
                referrer_user_id = owner
        amount_paise = gross_paise - discount_paise
        receipt = f"cg-{user.id}-{int(time.time())}"
        try:
            response = httpx.post(
                _RAZORPAY_ORDERS_URL,
                auth=(config.razorpay_key_id, config.razorpay_key_secret),
                json={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": {
                        "plan": body.plan,
                        "user_id": user.id,
                        "coupon_code": coupon["code"] if coupon else "",
                        "referral_code": body.referral_code.strip().upper()
                        if referrer_user_id
                        else "",
                    },
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
        try:
            store.create_payment(
                user.id,
                order_id,
                body.plan,
                amount_paise,
                "INR",
                discount_paise=discount_paise,
                coupon=coupon,
                coupon_code=coupon["code"] if coupon else "",
                referral_code=body.referral_code.strip().upper() if referrer_user_id else "",
                referrer_user_id=referrer_user_id,
            )
        except CouponError as error:
            # A limit was hit between validation and the atomic write;
            # the payment row rolled back with the redemption.
            raise HTTPException(409, str(error)) from error
        return {
            "order_id": order_id,
            "key_id": config.razorpay_key_id,
            "amount_paise": amount_paise,
            "discount_paise": discount_paise,
            "currency": "INR",
            "plan": body.plan,
        }

    @router.post("/subscribe")
    def subscribe(body: SubscribeRequest, user=Depends(current_user)) -> dict:  # noqa: B008
        """Phase 9: start a Razorpay subscription (auto-renew option).

        The manual one-time checkout above stays untouched. While keys
        or the plan's Razorpay plan id are unset this answers the same
        honest 501/409 as the core — never a fake success.
        """
        config = load_billing_config()
        try:
            return create_subscription(config, subscriptions, user.id, body.plan)
        except BillingError as error:
            raise HTTPException(error.status_code, error.message) from error

    # ------------------------------------------------------------- coupons
    @router.post("/coupon/validate")
    def validate_coupon(body: CouponValidateRequest, user=Depends(current_user)) -> dict:  # noqa: B008
        """Preview a coupon for a plan — NO state changes here.

        Redemption happens only inside checkout. ``valid: false`` with a
        human reason is a normal answer (200), not an error.
        """
        if body.plan not in ("pro", "institute"):
            raise HTTPException(400, "Coupons apply to Pro or Institute plans.")
        coupon, reason = coupon_store.validate_for(body.code, user.id)
        if coupon is None:
            return {"valid": False, "reason": reason or "Coupon is not valid."}
        config = load_billing_config()
        price = config.pro_price_inr if body.plan == "pro" else config.institute_price_inr
        preview = compute_discount(coupon, price * 100) if price is not None else None
        return {
            "valid": True,
            "code": coupon["code"],
            "kind": coupon["kind"],
            "value": coupon["value"],
            "discount_preview_paise": preview,
            "final_amount_paise": (price * 100 - preview) if preview is not None else None,
        }

    @router.get("/admin/coupons")
    def list_coupons(user=Depends(admin_user) if admin_user else Depends(current_user)) -> dict:  # noqa: B008
        if admin_user is None:
            raise HTTPException(403, "Admin only.")
        return {"coupons": coupon_store.list()}

    @router.post("/admin/coupons", status_code=201)
    def create_coupon(
        body: CouponCreateRequest,
        user=Depends(admin_user) if admin_user else Depends(current_user),  # noqa: B008
    ) -> dict:
        if admin_user is None:
            raise HTTPException(403, "Admin only.")
        try:
            coupon = coupon_store.create(
                body.code,
                body.kind,
                body.value,
                body.max_redemptions,
                body.per_user_limit,
                body.expires_at,
                created_by=user.email,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(user.email, "coupon:create", coupon["code"])
        return {"coupon": coupon}

    @router.post("/admin/coupons/{code}/deactivate")
    def deactivate_coupon(
        code: str,
        user=Depends(admin_user) if admin_user else Depends(current_user),  # noqa: B008
    ) -> dict:
        if admin_user is None:
            raise HTTPException(403, "Admin only.")
        if not coupon_store.deactivate(code):
            raise HTTPException(404, "Coupon not found.")
        users.audit(user.email, "coupon:deactivate", code.upper())
        return {"deactivated": True, "code": code.upper()}

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
        event_type = event.get("event")
        if event_type == "payment.captured":
            entity = (event.get("payload") or {}).get("payment", {}).get("entity", {})
            order_id = entity.get("order_id", "")
            payment = store.payment_by_order(order_id) if order_id else None
            if payment is None:
                logger.warning("Webhook for unknown order id received; ignored.")
                return {"ok": True}
            store.mark_captured(order_id)
            users.set_plan(payment["user_id"], payment["plan"])
            return {"ok": True}
        if isinstance(event_type, str) and event_type.startswith("subscription."):
            return _handle_subscription_event(event_type, event)
        return {"ok": True}

    def _handle_subscription_event(event_type: str, event: dict) -> dict:
        """Apply one subscription webhook event (see module docstring).

        Idempotent: the event key is recorded in the ``webhook_events``
        ledger before any side effect; replays return ok untouched.
        Period ends come from Razorpay's ABSOLUTE ``current_end``, so a
        charge extends the period exactly once even in principle.
        Cancel/halt/pause change only the status — the plan stays until
        the recorded period end (no instant downgrade on cancel).
        """
        payload = event.get("payload") or {}
        entity = (payload.get("subscription") or {}).get("entity", {})
        payment_entity = (payload.get("payment") or {}).get("entity", {})
        razorpay_id = entity.get("id", "")
        subscription = subscriptions.by_razorpay_id(razorpay_id) if razorpay_id else None
        if subscription is None:
            logger.warning("Webhook for unknown subscription id received; ignored.")
            return {"ok": True}
        period_end = ""
        current_end = entity.get("current_end")
        if isinstance(current_end, (int, float)) and current_end > 0:
            period_end = datetime.fromtimestamp(current_end, tz=timezone.utc).isoformat(
                timespec="seconds"
            )
        dedup_part = payment_entity.get("id") or current_end or entity.get("status", "")
        event_key = f"{event_type}:{razorpay_id}:{dedup_part}"
        if not subscriptions.record_webhook_event(event_key, event_type):
            return {"ok": True}  # replay — already applied
        action = event_type.split(".", 1)[1]
        status_by_action = {
            "activated": "active",
            "charged": "active",
            "resumed": "active",
            "cancelled": "cancelled",
            "halted": "halted",
            "paused": "paused",
            "completed": "completed",
        }
        status = status_by_action.get(action)
        if status is None:
            return {"ok": True}  # known prefix, unhandled action — ignore
        subscriptions.update(razorpay_id, status=status, period_end=period_end)
        if status == "active":
            users.set_plan(subscription["user_id"], subscription["plan"])
        return {"ok": True}

    return router
