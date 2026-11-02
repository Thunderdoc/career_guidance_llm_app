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
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

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


@dataclass(frozen=True)
class BillingConfig:
    pro_price_inr: int | None
    institute_price_inr: int | None
    trial_days: int
    enforce_pro: bool
    razorpay_key_id: str
    razorpay_key_secret: str

    @property
    def payments_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


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
    ) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO payments (user_id, provider, provider_order_id, plan,"
                " amount_paise, currency, status, created_at, updated_at)"
                " VALUES (?, 'razorpay', ?, ?, ?, ?, 'created', ?, ?)",
                (user_id, provider_order_id, plan, amount_paise, currency, now, now),
            )
            return int(cur.lastrowid or 0)

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
