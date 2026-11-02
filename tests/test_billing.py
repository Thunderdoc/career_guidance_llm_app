"""Tests for billing: plans, trials, webhook signatures, payments ledger."""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from career_guidance.billing import (
    BillingStore,
    effective_plan,
    load_billing_config,
    plans_payload,
    trial_active,
    trial_used,
    verify_razorpay_signature,
)


def _config(**overrides):
    from career_guidance.billing import BillingConfig

    base = {
        "pro_price_inr": None,
        "institute_price_inr": None,
        "trial_days": 7,
        "enforce_pro": True,
        "razorpay_key_id": "",
        "razorpay_key_secret": "",
    }
    base.update(overrides)
    return BillingConfig(**base)


def test_plans_report_unset_prices_as_none():
    plans = plans_payload(_config())
    by_id = {p["id"]: p for p in plans}
    assert by_id["free"]["price_inr"] == 0
    assert by_id["pro"]["price_inr"] is None
    assert by_id["institute"]["price_inr"] is None
    assert by_id["pro"]["trial_days"] == 7


def test_plans_report_configured_prices():
    plans = plans_payload(_config(pro_price_inr=199, institute_price_inr=4999))
    by_id = {p["id"]: p for p in plans}
    assert by_id["pro"]["price_inr"] == 199
    assert by_id["institute"]["price_inr"] == 4999


def test_trial_window_and_one_time_rule():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert trial_active(future) is True
    assert trial_active(past) is False
    assert trial_active("") is False
    assert trial_used(future) is True
    assert trial_used("") is False


def test_effective_plan_resolution():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert effective_plan("free", future) == "pro"
    assert effective_plan("free", "") == "free"
    assert effective_plan("pro", "") == "pro"
    assert effective_plan("institute", "") == "institute"


def test_webhook_signature_verification():
    secret = "test-secret"
    body = b'{"event": "payment.captured"}'
    good = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_razorpay_signature(secret, body, good) is True
    assert verify_razorpay_signature(secret, body, "0" * 64) is False
    assert verify_razorpay_signature(secret, body, "") is False
    assert verify_razorpay_signature("", body, good) is False


def test_payments_ledger_round_trip(tmp_path):
    store = BillingStore(str(tmp_path / "billing.db"))
    # The table is created by migration 3; create it here for isolation.
    import sqlite3

    with sqlite3.connect(str(tmp_path / "billing.db")) as conn:
        conn.execute(
            "CREATE TABLE payments (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user_id TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'razorpay',"
            " provider_order_id TEXT NOT NULL UNIQUE, plan TEXT NOT NULL DEFAULT 'pro',"
            " amount_paise INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'INR',"
            " status TEXT NOT NULL DEFAULT 'created', created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL)"
        )
    payment_id = store.create_payment("user-1", "order_test123", "pro", 19900)
    assert payment_id > 0
    row = store.payment_by_order("order_test123")
    assert row is not None
    assert row["status"] == "created"
    assert row["plan"] == "pro"
    captured = store.mark_captured("order_test123")
    assert captured is not None and captured["status"] == "captured"
    assert store.payment_by_order("order_missing") is None


def test_config_reads_env(monkeypatch):
    monkeypatch.setenv("BILLING_PRO_PRICE_INR", "199")
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "14")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_x")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret_x")
    config = load_billing_config()
    assert config.pro_price_inr == 199
    assert config.trial_days == 14
    assert config.payments_configured is True
    monkeypatch.delenv("RAZORPAY_KEY_SECRET")
    assert load_billing_config().payments_configured is False


def test_config_ignores_bad_price(monkeypatch):
    monkeypatch.setenv("BILLING_PRO_PRICE_INR", "not-a-number")
    assert load_billing_config().pro_price_inr is None
