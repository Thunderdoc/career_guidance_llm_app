"""Billing: commercial plans, trials and Razorpay payments.

Sell-standard core, kept deliberately boring:

- Plans are data (Free / Pro / Institute). Prices come from env; when a
  price is unset the plan reports ``price_inr=None`` and the API/frontend
  show "Contact us" instead of an invented number.
- A trial is a one-time Pro window (``BILLING_TRIAL_DAYS``, default 7).
- Pro gating is controlled by ``BILLING_ENFORCE_PRO`` (default on): the
  roadmap PDF export requires Pro while it is on. Turning it off restores
  the old behaviour for every signed-in user; it is the owner's go-live
  switch, not a silent change.
- Razorpay is the only provider in v1 (UPI + cards for India). Without
  ``RAZORPAY_KEY_ID``/``RAZORPAY_KEY_SECRET`` checkout and the webhook
  answer 501 — never a fake success.
- Phase 9 adds Razorpay **subscriptions** as an additional option beside
  the one-time checkout (the manual flow stays). Subscription plan ids
  come only from env (``RAZORPAY_PRO_PLAN_ID`` /
  ``RAZORPAY_INSTITUTE_PLAN_ID``); while either the keys or a plan id
  are unset, subscribing answers the same honest 501/409 as checkout —
  never a fake success and never an invented plan id.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

FREE_FEATURES = [
    "Career matching across 974 occupations",
    "Skills assessment (RIASEC) and career search",
    "Learning paths and dashboard",
    "Markdown and JSON exports",
]

PRO_FEATURES = [
    "Everything in Free",
    "Roadmap PDF export",
    "Resume scoring and job-fit analysis",
    "Full history and progress tracking",
]

INSTITUTE_FEATURES = [
    "Everything in Pro",
    "Seats for a whole batch or institute",
    "Admin-managed enrolment",
]

TRIAL_PLAN = "pro"


class BillingError(Exception):
    """Billing failure carrying the HTTP status the API should answer.

    Used by the subscription core so the honest-placeholder behaviour
    (501 while keys are unset, 409 while a plan id is unset) is identical
    in core tests and in the API.
    """

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


#: Razorpay subscriptions need a finite billing-cycle count at creation.
#: 12 cycles (12 months on a monthly plan) is the shipped product term;
#: when it completes the customer can subscribe again. Documented in
#: README/SELLING — not a hidden renewal trap.
SUBSCRIPTION_TOTAL_COUNT = 12

_RAZORPAY_SUBSCRIPTIONS_URL = "https://api.razorpay.com/v1/subscriptions"


@dataclass(frozen=True)
class BillingConfig:
    pro_price_inr: int | None
    institute_price_inr: int | None
    trial_days: int
    enforce_pro: bool
    razorpay_key_id: str
    razorpay_key_secret: str
    # Phase 9: Razorpay *plan* ids for subscriptions (dashboard-created).
    # Env-only — a plan id is never invented in code.
    razorpay_pro_plan_id: str = ""
    razorpay_institute_plan_id: str = ""

    @property
    def payments_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    def subscription_plan_id(self, plan: str) -> str:
        if plan == "pro":
            return self.razorpay_pro_plan_id
        if plan == "institute":
            return self.razorpay_institute_plan_id
        return ""

    @property
    def subscriptions_configured(self) -> bool:
        """True only when keys AND at least one Razorpay plan id are set."""
        return self.payments_configured and bool(
            self.razorpay_pro_plan_id or self.razorpay_institute_plan_id
        )


def _price(env_name: str) -> int | None:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def load_billing_config() -> BillingConfig:
    """Read billing config from env (no secrets are ever logged)."""
    trial_days = os.getenv("BILLING_TRIAL_DAYS", "7").strip()
    try:
        trial_days_int = int(trial_days)
    except ValueError:
        trial_days_int = 7
    return BillingConfig(
        pro_price_inr=_price("BILLING_PRO_PRICE_INR"),
        institute_price_inr=_price("BILLING_INSTITUTE_PRICE_INR"),
        trial_days=max(0, trial_days_int),
        enforce_pro=os.getenv("BILLING_ENFORCE_PRO", "true").strip().lower()
        in {"1", "true", "yes", "on"},
        razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", "").strip(),
        razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", "").strip(),
        razorpay_pro_plan_id=os.getenv("RAZORPAY_PRO_PLAN_ID", "").strip(),
        razorpay_institute_plan_id=os.getenv("RAZORPAY_INSTITUTE_PLAN_ID", "").strip(),
    )


def plans_payload(config: BillingConfig) -> list[dict]:
    """Public plan catalogue: prices are None when unconfigured."""
    return [
        {
            "id": "free",
            "name": "Free",
            "tagline": "Start exploring careers.",
            "features": FREE_FEATURES,
            "price_inr": 0,
            "trial_days": 0,
        },
        {
            "id": "pro",
            "name": "Pro",
            "tagline": "The full toolkit for a serious job search.",
            "features": PRO_FEATURES,
            "price_inr": config.pro_price_inr,
            "trial_days": config.trial_days,
        },
        {
            "id": "institute",
            "name": "Institute",
            "tagline": "For colleges, coaching centres and batches.",
            "features": INSTITUTE_FEATURES,
            "price_inr": config.institute_price_inr,
            "trial_days": 0,
        },
    ]


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def trial_active(trial_ends_at: str, now: datetime | None = None) -> bool:
    """True while a started trial has not expired yet."""
    ends = _parse_time(trial_ends_at)
    if ends is None:
        return False
    return ends > (now or datetime.now(timezone.utc))


def trial_used(trial_ends_at: str) -> bool:
    """A trial is one-time: any recorded end date means it was started."""
    return bool(trial_ends_at)


def effective_plan(plan: str, trial_ends_at: str, now: datetime | None = None) -> str:
    """Resolve the plan that actually applies right now.

    Institute and Pro stay as assigned; an active trial upgrades any
    other plan to Pro for its window; anything else is Free.
    """
    if plan in ("pro", "institute"):
        return plan
    if trial_active(trial_ends_at, now):
        return TRIAL_PLAN
    return "free"


def verify_razorpay_signature(secret: str, body: bytes, signature: str) -> bool:
    """HMAC-SHA256 webhook check, constant-time comparison."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class BillingStore:
    """Payments ledger (SQLite, same database as the user store)."""

    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_payment(
        self,
        user_id: str,
        provider_order_id: str,
        plan: str,
        amount_paise: int,
        currency: str = "INR",
        discount_paise: int = 0,
        coupon: dict | None = None,
        coupon_code: str = "",
        referral_code: str = "",
        referrer_user_id: str | None = None,
    ) -> int:
        """Record a checkout order — atomically with its coupon/referral rows.

        ``amount_paise`` is the amount actually charged (after discount).
        When ``coupon`` is given, the redemption is re-validated and
        inserted in the SAME transaction as the payment row (a limit hit
        raises :class:`career_guidance.coupons.CouponError` and rolls the
        payment row back too). When ``referrer_user_id`` is given, the
        referral attribution + pending valueless reward are written in
        the same transaction.
        """
        from career_guidance.coupons import insert_attribution, insert_redemption

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            # The discount/code columns arrive with migration v9; tolerate
            # a pre-v9 ledger (older tests / un-migrated files) by writing
            # only the columns that exist.
            columns = {r[1] for r in conn.execute("PRAGMA table_info(payments)")}
            extra_cols = [
                c for c in ("discount_paise", "coupon_code", "referral_code") if c in columns
            ]
            extra_vals = {
                "discount_paise": int(discount_paise),
                "coupon_code": coupon_code,
                "referral_code": referral_code,
            }
            col_sql = "".join(f", {c}" for c in extra_cols)
            val_sql = "".join(", ?" for _ in extra_cols)
            cur = conn.execute(
                "INSERT INTO payments (user_id, provider, provider_order_id, plan,"
                f" amount_paise, currency, status, created_at, updated_at{col_sql})"
                f" VALUES (?, 'razorpay', ?, ?, ?, ?, 'created', ?, ?{val_sql})",
                (
                    user_id,
                    provider_order_id,
                    plan,
                    amount_paise,
                    currency,
                    now,
                    now,
                    *[extra_vals[c] for c in extra_cols],
                ),
            )
            payment_id = int(cur.lastrowid or 0)
            if coupon is not None:
                insert_redemption(conn, coupon, user_id, provider_order_id, discount_paise)
            if referrer_user_id:
                insert_attribution(conn, referrer_user_id, user_id, provider_order_id)
            return payment_id

    def payment_by_order(self, provider_order_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE provider_order_id=?", (provider_order_id,)
            ).fetchone()
            return dict(row) if row else None

    def mark_captured(self, provider_order_id: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE payments SET status='captured', updated_at=? WHERE provider_order_id=?",
                (now, provider_order_id),
            )
            row = conn.execute(
                "SELECT * FROM payments WHERE provider_order_id=?", (provider_order_id,)
            ).fetchone()
            return dict(row) if row else None


class SubscriptionStore:
    """Subscriptions ledger + webhook idempotency (migration v9 tables)."""

    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)
        from career_guidance.migrations import migrate

        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(
        self, user_id: str, plan: str, razorpay_subscription_id: str, status: str = "created"
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO subscriptions (user_id, plan, razorpay_subscription_id, status,"
                " current_period_end, created_at, updated_at) VALUES (?,?,?,?, '', ?, ?)"
                " ON CONFLICT(razorpay_subscription_id) DO UPDATE SET status=excluded.status,"
                " updated_at=excluded.updated_at",
                (user_id, plan, razorpay_subscription_id, status, now, now),
            )
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE razorpay_subscription_id=?",
                (razorpay_subscription_id,),
            ).fetchone()
        return dict(row)

    def by_razorpay_id(self, razorpay_subscription_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE razorpay_subscription_id=?",
                (razorpay_subscription_id,),
            ).fetchone()
        return dict(row) if row else None

    def for_user(self, user_id: str) -> dict | None:
        """The user's most recent subscription, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def update(
        self, razorpay_subscription_id: str, status: str | None = None, period_end: str = ""
    ) -> dict | None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            if status is not None:
                conn.execute(
                    "UPDATE subscriptions SET status=?, updated_at=? WHERE razorpay_subscription_id=?",  # noqa: E501
                    (status, now, razorpay_subscription_id),
                )
            if period_end:
                conn.execute(
                    "UPDATE subscriptions SET current_period_end=?, updated_at=?"
                    " WHERE razorpay_subscription_id=?",
                    (period_end, now, razorpay_subscription_id),
                )
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE razorpay_subscription_id=?",
                (razorpay_subscription_id,),
            ).fetchone()
        return dict(row) if row else None

    def record_webhook_event(self, event_key: str, event: str) -> bool:
        """True the FIRST time an event key is seen; False on replay."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO webhook_events (event_key, event, created_at)"
                " VALUES (?,?,?)",
                (event_key, event, now),
            )
            return cur.rowcount > 0


def create_subscription(
    config: BillingConfig,
    store: SubscriptionStore,
    user_id: str,
    plan: str,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Create a Razorpay subscription for ``user_id`` on ``plan``.

    Honest-placeholder contract (same as one-time checkout):
    - keys unset → :class:`BillingError` 501, nothing is faked;
    - the plan's Razorpay plan id unset (``RAZORPAY_PRO_PLAN_ID`` /
      ``RAZORPAY_INSTITUTE_PLAN_ID``) → 409 "subscriptions not
      configured" — a plan id is never invented;
    - provider failure → 502.

    ``transport`` is injectable so tests drive the Razorpay HTTP layer
    with ``httpx.MockTransport`` — no real network in tests.
    """
    if not config.payments_configured:
        raise BillingError(501, "Payments are not configured yet.")
    if plan not in ("pro", "institute"):
        raise BillingError(400, "Subscriptions are only for Pro or Institute plans.")
    plan_id = config.subscription_plan_id(plan)
    if not plan_id:
        raise BillingError(409, "Subscriptions are not configured for this plan.")
    payload = {
        "plan_id": plan_id,
        "total_count": SUBSCRIPTION_TOTAL_COUNT,
        "quantity": 1,
        "customer_notify": 1,
        "notes": {"plan": plan, "user_id": user_id},
    }
    try:
        if transport is not None:
            with httpx.Client(transport=transport, timeout=15) as client:
                response = client.post(
                    _RAZORPAY_SUBSCRIPTIONS_URL,
                    auth=(config.razorpay_key_id, config.razorpay_key_secret),
                    json=payload,
                )
        else:
            response = httpx.post(
                _RAZORPAY_SUBSCRIPTIONS_URL,
                auth=(config.razorpay_key_id, config.razorpay_key_secret),
                json=payload,
                timeout=15,
            )
    except httpx.HTTPError:
        raise BillingError(502, "Payment provider unreachable.") from None
    if response.status_code not in (200, 201):
        raise BillingError(502, "Payment provider rejected the subscription.")
    data = response.json()
    subscription_id = data.get("id", "")
    if not subscription_id:
        raise BillingError(502, "Payment provider returned no subscription id.")
    row = store.create(user_id, plan, subscription_id, str(data.get("status") or "created"))
    return {
        "subscription_id": subscription_id,
        "key_id": config.razorpay_key_id,
        "plan": plan,
        "status": row["status"],
    }


class DemoRequestStore:
    """Institute demo-request leads (Phase 1 landing form).

    Stored in the same SQLite database; visible to admins through the
    billing router's admin-only list endpoint. Deliberately minimal:
    validate, store, list — no e-mail is sent and nothing is inferred.
    """

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS demo_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    organisation TEXT NOT NULL,
                    seats INTEGER,
                    message TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'new'
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(
        self, name: str, email: str, organisation: str, seats: int | None, message: str
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO demo_requests (created_at, name, email, organisation, seats, message) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (created_at, name, email, organisation, seats, message),
            )
            return int(cur.lastrowid or 0)

    def list(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM demo_requests ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
