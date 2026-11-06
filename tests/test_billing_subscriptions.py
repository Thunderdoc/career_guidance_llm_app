"""Phase 9 tests: Razorpay subscriptions (core + API + webhook).

Honesty contract under test: while keys are unset subscribing is a 501,
while a plan id is unset it is a 409 — never a fake success. Webhook
tests use a FAKE secret and (for creation) a mocked transport /
monkeypatched httpx — no real network, no real keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone

import httpx
import pytest

from career_guidance.billing import (
    BillingConfig,
    BillingError,
    SubscriptionStore,
    create_subscription,
    load_billing_config,
)
from career_guidance.migrations import migrate
from tests.conftest import login

SECRET = "fake-webhook-secret"


def _config(**overrides) -> BillingConfig:
    base = {
        "pro_price_inr": 199,
        "institute_price_inr": 4999,
        "trial_days": 7,
        "enforce_pro": True,
        "razorpay_key_id": "rzp_test_fake",
        "razorpay_key_secret": SECRET,
        "razorpay_pro_plan_id": "plan_fake_pro",
        "razorpay_institute_plan_id": "",
    }
    base.update(overrides)
    return BillingConfig(**base)


def _store(tmp_path) -> SubscriptionStore:
    path = str(tmp_path / "subs.db")
    migrate(path)
    return SubscriptionStore(path)


# ---------------------------------------------------------------- core


def test_config_subscriptions_flags(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    monkeypatch.delenv("RAZORPAY_PRO_PLAN_ID", raising=False)
    assert load_billing_config().subscriptions_configured is False
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", SECRET)
    assert load_billing_config().subscriptions_configured is False  # no plan id yet
    monkeypatch.setenv("RAZORPAY_PRO_PLAN_ID", "plan_fake_pro")
    config = load_billing_config()
    assert config.subscriptions_configured is True
    assert config.subscription_plan_id("pro") == "plan_fake_pro"
    assert config.subscription_plan_id("institute") == ""


def test_create_subscription_501_without_keys(tmp_path):
    config = _config(razorpay_key_id="", razorpay_key_secret="")
    with pytest.raises(BillingError) as caught:
        create_subscription(config, _store(tmp_path), "user-1", "pro")
    assert caught.value.status_code == 501


def test_create_subscription_409_without_plan_id(tmp_path):
    config = _config(razorpay_pro_plan_id="")
    with pytest.raises(BillingError) as caught:
        create_subscription(config, _store(tmp_path), "user-1", "pro")
    assert caught.value.status_code == 409
    assert "not configured" in caught.value.message


def test_create_subscription_rejects_free_plan(tmp_path):
    with pytest.raises(BillingError) as caught:
        create_subscription(_config(), _store(tmp_path), "user-1", "free")
    assert caught.value.status_code == 400


def test_create_subscription_mocked_transport(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"id": "sub_fake_1", "status": "created"})

    store = _store(tmp_path)
    result = create_subscription(
        _config(), store, "user-1", "pro", transport=httpx.MockTransport(handler)
    )
    assert result["subscription_id"] == "sub_fake_1"
    assert result["status"] == "created"
    assert seen["url"].endswith("/v1/subscriptions")
    assert seen["body"]["plan_id"] == "plan_fake_pro"  # env plan id, never invented
    assert seen["body"]["notes"] == {"plan": "pro", "user_id": "user-1"}
    assert seen["auth"]  # basic auth with the configured key was sent
    row = store.by_razorpay_id("sub_fake_1")
    assert row is not None and row["user_id"] == "user-1" and row["plan"] == "pro"
    assert store.for_user("user-1")["razorpay_subscription_id"] == "sub_fake_1"


def test_create_subscription_provider_failure_is_502(tmp_path):
    transport = httpx.MockTransport(lambda req: httpx.Response(500, json={"error": "x"}))
    with pytest.raises(BillingError) as caught:
        create_subscription(_config(), _store(tmp_path), "user-1", "pro", transport=transport)
    assert caught.value.status_code == 502


def test_subscription_store_webhook_ledger_is_idempotent(tmp_path):
    store = _store(tmp_path)
    assert store.record_webhook_event("k1", "subscription.charged") is True
    assert store.record_webhook_event("k1", "subscription.charged") is False


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
    monkeypatch.delenv("RAZORPAY_PRO_PLAN_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_INSTITUTE_PLAN_ID", raising=False)


def test_plans_subscriptions_enabled_flag(client, paid_env, monkeypatch):
    body = client.get("/api/v1/billing/plans").json()
    assert body["payments_configured"] is True
    assert body["subscriptions_enabled"] is False  # keys set, plan ids unset
    monkeypatch.setenv("RAZORPAY_INSTITUTE_PLAN_ID", "plan_fake_inst")
    body = client.get("/api/v1/billing/plans").json()
    assert body["subscriptions_enabled"] is True


def test_subscribe_api_honest_placeholders(auth_client, paid_env, monkeypatch):
    # Keys set but no plan id → 409, never a fake subscription.
    r = auth_client.post("/api/v1/billing/subscribe", json={"plan": "pro"})
    assert r.status_code == 409
    # Plan id now set → provider is called (mocked); free plan → 400.
    monkeypatch.setenv("RAZORPAY_PRO_PLAN_ID", "plan_fake_pro")
    r = auth_client.post("/api/v1/billing/subscribe", json={"plan": "free"})
    assert r.status_code == 400


def test_subscribe_api_501_without_keys(auth_client, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    r = auth_client.post("/api/v1/billing/subscribe", json={"plan": "pro"})
    assert r.status_code == 501


def test_subscribe_api_success_with_mocked_provider(auth_client, paid_env, monkeypatch):
    monkeypatch.setenv("RAZORPAY_PRO_PLAN_ID", "plan_fake_pro")

    def fake_post(url, auth=None, json=None, timeout=None):  # noqa: A002 - mirrors httpx
        assert url.endswith("/v1/subscriptions")
        assert json["plan_id"] == "plan_fake_pro"
        return _FakeResponse(200, {"id": "sub_api_1", "status": "created"})

    monkeypatch.setattr(httpx, "post", fake_post)
    r = auth_client.post("/api/v1/billing/subscribe", json={"plan": "pro"})
    assert r.status_code == 200, r.text
    assert r.json()["subscription_id"] == "sub_api_1"
    me = auth_client.get("/api/v1/billing/me").json()
    assert me["subscription"]["status"] == "created"
    assert me["subscription"]["plan"] == "pro"


def test_billing_me_subscription_defaults_to_none(auth_client):
    assert auth_client.get("/api/v1/billing/me").json()["subscription"] is None


# ---------------------------------------------------------------- webhook


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post_webhook(client, payload: dict, secret: str = SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/api/v1/billing/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body, secret), "Content-Type": "application/json"},
    )


def _seed_subscription(app_module, user_id: str, rzp_id: str = "sub_hook_1") -> SubscriptionStore:
    store = SubscriptionStore(app_module.settings.database_path)
    store.create(user_id, "pro", rzp_id, "created")
    return store


def _sub_payload(event: str, rzp_id: str, current_end: int, payment_id: str = "") -> dict:
    payload: dict = {
        "event": event,
        "payload": {
            "subscription": {
                "entity": {"id": rzp_id, "status": "active", "current_end": current_end}
            }
        },
    }
    if payment_id:
        payload["payload"]["payment"] = {"entity": {"id": payment_id}}
    return payload


END_1 = 1_800_000_000  # 2027-01-15
END_2 = 1_802_592_000  # 2027-02-14 (one monthly cycle later)


def _expected(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def test_webhook_subscription_charged_extends_and_activates(app_module, client, paid_env):
    me = login(client, "hook@example.com")
    store = _seed_subscription(app_module, me["id"])
    r = _post_webhook(client, _sub_payload("subscription.charged", "sub_hook_1", END_1, "pay_1"))
    assert r.status_code == 200, r.text
    row = store.by_razorpay_id("sub_hook_1")
    assert row["status"] == "active"
    assert row["current_period_end"] == _expected(END_1)
    state = client.get("/api/v1/billing/me").json()
    assert state["plan"] == "pro"  # charged activates the plan
    # Next cycle extends to the new absolute period end.
    r = _post_webhook(client, _sub_payload("subscription.charged", "sub_hook_1", END_2, "pay_2"))
    assert r.status_code == 200
    assert store.by_razorpay_id("sub_hook_1")["current_period_end"] == _expected(END_2)


def test_webhook_replay_is_idempotent(app_module, client, paid_env):
    me = login(client, "replay@example.com")
    store = _seed_subscription(app_module, me["id"])
    payload = _sub_payload("subscription.charged", "sub_hook_1", END_1, "pay_1")
    assert _post_webhook(client, payload).status_code == 200
    assert _post_webhook(client, payload).status_code == 200  # replayed delivery
    row = store.by_razorpay_id("sub_hook_1")
    assert row["current_period_end"] == _expected(END_1)  # NOT extended twice
    with sqlite3.connect(app_module.settings.database_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM webhook_events WHERE event='subscription.charged'"
        ).fetchone()[0]
    assert count == 1


def test_webhook_cancel_and_halt_keep_plan_until_period_end(app_module, client, paid_env):
    me = login(client, "cancel@example.com")
    store = _seed_subscription(app_module, me["id"])
    _post_webhook(client, _sub_payload("subscription.charged", "sub_hook_1", END_1, "pay_1"))
    r = _post_webhook(client, _sub_payload("subscription.cancelled", "sub_hook_1", END_1))
    assert r.status_code == 200
    row = store.by_razorpay_id("sub_hook_1")
    assert row["status"] == "cancelled"
    assert row["current_period_end"] == _expected(END_1)  # period end retained
    # The plan itself is NOT downgraded by a cancellation — it stays
    # until the recorded period end (documented behaviour).
    assert client.get("/api/v1/billing/me").json()["plan"] == "pro"
    r = _post_webhook(client, _sub_payload("subscription.halted", "sub_hook_1", END_1))
    assert r.status_code == 200
    assert store.by_razorpay_id("sub_hook_1")["status"] == "halted"


def test_webhook_tampered_signature_rejected(app_module, client, paid_env):
    me = login(client, "tamper@example.com")
    _seed_subscription(app_module, me["id"])
    payload = _sub_payload("subscription.charged", "sub_hook_1", END_1, "pay_1")
    r = _post_webhook(client, payload, secret="the-wrong-secret")
    assert r.status_code == 401


def test_webhook_unknown_event_and_unknown_subscription_ignored(app_module, client, paid_env):
    login(client, "unknown@example.com")
    r = _post_webhook(client, {"event": "order.paid", "payload": {}})
    assert r.status_code == 200 and r.json() == {"ok": True}
    r = _post_webhook(client, _sub_payload("subscription.charged", "sub_nope", END_1, "pay_9"))
    assert r.status_code == 200 and r.json() == {"ok": True}
