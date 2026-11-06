"""Phase 9 tests: coupons + referrals (core rules + API + checkout).

Rule enforcement under test (each rejection is asserted):
unknown code · inactive (deactivated) · expired · total redemption cap
(max_redemptions) · per-user cap (per_user_limit, default 1). Plus:
discounts are computed server-side, redemption is recorded atomically
with the payment row, and referrals record attribution only (a pending,
valueless reward) — no discount exists unless an admin created a coupon.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from career_guidance.billing import BillingStore
from career_guidance.coupons import CouponStore, ReferralStore, compute_discount
from tests.conftest import login

SECRET = "fake-webhook-secret"


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds")


# ---------------------------------------------------------------- core


def test_coupon_create_and_validation_rules(tmp_path):
    store = CouponStore(str(tmp_path / "c.db"))
    coupon = store.create("WELCOME10", "percent", 10, created_by="boss@example.com")
    assert coupon["code"] == "WELCOME10" and coupon["per_user_limit"] == 1
    with pytest.raises(ValueError):
        store.create("welcome10", "percent", 10)  # duplicate (case-insensitive)
    with pytest.raises(ValueError):
        store.create("BADKIND", "bogus", 10)
    with pytest.raises(ValueError):
        store.create("TOOBIG", "percent", 101)
    with pytest.raises(ValueError):
        store.create("ZEROFLAT", "flat_inr", 0)
    found, reason = store.validate_for("WELCOME10", "user-1")
    assert found is not None and reason is None
    found, reason = store.validate_for("NOPE", "user-1")
    assert found is None and "not recognised" in reason


def test_compute_discount_percent_flat_and_min_charge_cap():
    percent = {"kind": "percent", "value": 10}
    assert compute_discount(percent, 19900) == 1990
    flat = {"kind": "flat_inr", "value": 50}
    assert compute_discount(flat, 19900) == 5000
    # 100% off still leaves the ₹1 minimum charge.
    full = {"kind": "percent", "value": 100}
    assert compute_discount(full, 19900) == 19900 - 100
    assert compute_discount(flat, 300) == 200  # capped by the same rule


def test_coupon_rejections_expired_inactive_caps(tmp_path):
    path = str(tmp_path / "c.db")
    coupons = CouponStore(path)
    billing = BillingStore(path)
    coupons.create("EXPIRED", "percent", 10, expires_at=_past())
    coupons.create("FUTUREOK", "percent", 10, expires_at=_future())

    _, reason = coupons.validate_for("EXPIRED", "user-1")
    assert "expired" in reason
    found, _ = coupons.validate_for("FUTUREOK", "user-1")
    assert found is not None

    coupons.create("GONE", "percent", 10)
    assert coupons.deactivate("gone") is True
    _, reason = coupons.validate_for("GONE", "user-1")
    assert "no longer active" in reason
    assert coupons.deactivate("missing") is False

    # Total cap: max_redemptions=1 — first user redeems, second is refused.
    capped = coupons.create("ONLYONE", "percent", 10, max_redemptions=1)
    billing.create_payment("user-1", "order_1", "pro", 17910, coupon=capped, coupon_code="ONLYONE")
    assert coupons.redemption_count(capped["id"]) == 1
    _, reason = coupons.validate_for("ONLYONE", "user-2")
    assert "redemption limit" in reason

    # Per-user cap (default 1): same user refused, another user allowed.
    per_user = coupons.create("ONCE", "flat_inr", 20, max_redemptions=10)
    billing.create_payment("user-1", "order_2", "pro", 17900, coupon=per_user, coupon_code="ONCE")
    _, reason = coupons.validate_for("ONCE", "user-1")
    assert "already used" in reason
    found, _ = coupons.validate_for("ONCE", "user-9")
    assert found is not None

    # The atomic path enforces too: redeeming past the per-user cap inside
    # create_payment raises and rolls the payment row back.
    from career_guidance.coupons import CouponError

    with pytest.raises(CouponError):
        billing.create_payment(
            "user-1", "order_3", "pro", 17900, coupon=per_user, coupon_code="ONCE"
        )
    assert billing.payment_by_order("order_3") is None  # rolled back


def test_referral_core_attribution_only(tmp_path):
    path = str(tmp_path / "r.db")
    referrals = ReferralStore(path)
    code = referrals.code_for("referrer-1")
    assert code.startswith("CG-") and referrals.code_for("referrer-1") == code  # stable
    assert referrals.owner_of(code.lower()) == "referrer-1"
    assert referrals.owner_of("CG-DOESNOTEXIST") is None
    assert referrals.summary("referrer-1") == {
        "code": code,
        "referrals": 0,
        "pending_rewards": 0,
    }
    billing = BillingStore(path)
    billing.create_payment(
        "buyer-1", "order_r1", "pro", 19900, referral_code=code, referrer_user_id="referrer-1"
    )
    summary = referrals.summary("referrer-1")
    assert summary["referrals"] == 1 and summary["pending_rewards"] == 1
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT status, coupon_id FROM referral_rewards WHERE referrer_user_id='referrer-1'"
        ).fetchone()
    assert row == ("pending", None)  # pending + NO value until an admin links a coupon


# ---------------------------------------------------------------- API


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture()
def paid_env(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", SECRET)
    monkeypatch.setenv("BILLING_PRO_PRICE_INR", "199")
    counter = {"n": 0}

    def fake_post(url, auth=None, json=None, timeout=None):  # noqa: A002 - mirrors httpx
        counter["n"] += 1
        return _FakeResponse(201, {"id": f"order_fake_{counter['n']}"})

    monkeypatch.setattr(httpx, "post", fake_post)


def test_admin_coupon_routes_require_platform_admin(app_module):
    from fastapi.testclient import TestClient

    anon = TestClient(app_module.app)
    user_client = TestClient(app_module.app)
    login(user_client, "plain@example.com")
    admin_client = TestClient(app_module.app)
    login(admin_client, "boss@example.com")
    body = {"code": "ADMIN10", "kind": "percent", "value": 10}
    assert anon.post("/api/v1/billing/admin/coupons", json=body).status_code == 401
    assert user_client.post("/api/v1/billing/admin/coupons", json=body).status_code == 403
    r = admin_client.post("/api/v1/billing/admin/coupons", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["coupon"]["created_by"] == "boss@example.com"
    listing = admin_client.get("/api/v1/billing/admin/coupons").json()["coupons"]
    assert [c["code"] for c in listing] == ["ADMIN10"]
    assert user_client.get("/api/v1/billing/admin/coupons").status_code == 403
    # Audit-logged: the admin audit feed shows both coupon actions.
    admin_client.post("/api/v1/billing/admin/coupons/ADMIN10/deactivate")
    actions = {row["action"] for row in admin_client.get("/api/v1/admin/audit").json()["log"]}
    assert "coupon:create" in actions and "coupon:deactivate" in actions
    r = admin_client.post("/api/v1/billing/admin/coupons/NOPE/deactivate")
    assert r.status_code == 404


def test_coupon_validate_preview(auth_client, admin_client, paid_env):
    admin_client.post(
        "/api/v1/billing/admin/coupons",
        json={"code": "PREVIEW10", "kind": "percent", "value": 10},
    )
    r = auth_client.post(
        "/api/v1/billing/coupon/validate", json={"code": "preview10", "plan": "pro"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["discount_preview_paise"] == 1990  # 10% of ₹199, server-side
    assert body["final_amount_paise"] == 19900 - 1990
    bad = auth_client.post(
        "/api/v1/billing/coupon/validate", json={"code": "missing", "plan": "pro"}
    ).json()
    assert bad["valid"] is False and bad["reason"]
    r = auth_client.post(
        "/api/v1/billing/coupon/validate", json={"code": "PREVIEW10", "plan": "free"}
    )
    assert r.status_code == 400


def test_checkout_with_coupon_records_redemption_atomically(
    app_module, auth_client, admin_client, paid_env
):
    admin_client.post(
        "/api/v1/billing/admin/coupons",
        json={"code": "CHECKOUT10", "kind": "percent", "value": 10},
    )
    me = auth_client.get("/api/v1/auth/me").json()["user"]
    r = auth_client.post(
        "/api/v1/billing/checkout", json={"plan": "pro", "coupon_code": "CHECKOUT10"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["amount_paise"] == 19900 - 1990
    assert r.json()["discount_paise"] == 1990
    with sqlite3.connect(app_module.settings.database_path) as conn:
        conn.row_factory = sqlite3.Row
        payment = conn.execute("SELECT * FROM payments WHERE user_id=?", (me["id"],)).fetchone()
        redemption = conn.execute("SELECT * FROM coupon_redemptions").fetchone()
    assert payment["amount_paise"] == 17910 and payment["discount_paise"] == 1990
    assert payment["coupon_code"] == "CHECKOUT10"
    assert redemption["user_id"] == me["id"] and redemption["discount_paise"] == 1990
    assert redemption["order_ref"] == payment["provider_order_id"]
    # Per-user limit: the same user cannot redeem it again at checkout.
    r = auth_client.post(
        "/api/v1/billing/checkout", json={"plan": "pro", "coupon_code": "CHECKOUT10"}
    )
    assert r.status_code == 400


def test_checkout_rejects_expired_and_unknown_coupons(auth_client, admin_client, paid_env):
    admin_client.post(
        "/api/v1/billing/admin/coupons",
        json={"code": "OLD10", "kind": "percent", "value": 10, "expires_at": _past()},
    )
    r = auth_client.post("/api/v1/billing/checkout", json={"plan": "pro", "coupon_code": "OLD10"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    r = auth_client.post("/api/v1/billing/checkout", json={"plan": "pro", "coupon_code": "GHOST"})
    assert r.status_code == 400


def test_checkout_referral_attribution_and_self_referral_skip(app_module, client, paid_env):
    referrer = login(client, "referrer@example.com")
    code = client.get("/api/v1/me/referral").json()["code"]
    # Self-referral records nothing.
    r = client.post("/api/v1/billing/checkout", json={"plan": "pro", "referral_code": code})
    assert r.status_code == 200
    assert client.get("/api/v1/me/referral").json()["referrals"] == 0
    # Another buyer using the code records attribution + pending reward.
    from fastapi.testclient import TestClient

    buyer_client = TestClient(app_module.app)
    login(buyer_client, "buyer@example.com")
    r = buyer_client.post("/api/v1/billing/checkout", json={"plan": "pro", "referral_code": code})
    assert r.status_code == 200, r.text
    summary = client.get("/api/v1/me/referral").json()
    assert summary["code"] == code and summary["referrals"] == 1
    assert summary["pending_rewards"] == 1
    # Unknown referral codes never block a purchase and record nothing.
    r = buyer_client.post(
        "/api/v1/billing/checkout", json={"plan": "pro", "referral_code": "CG-UNKNOWN1"}
    )
    assert r.status_code == 200
    assert client.get("/api/v1/me/referral").json()["referrals"] == 1
    assert referrer["email"] == "referrer@example.com"


def test_me_referral_requires_sign_in(client):
    assert client.get("/api/v1/me/referral").status_code == 401
