"""Coupons + referrals (Phase 9, Revenue v2).

Design decisions (deliberate, owner-aligned):

- **No discount exists unless an admin creates it.** Coupons are created
  only through the platform-admin API (audit-logged). There are no seeded
  codes, no campaigns, no invented offers in code.
- **Discounts are computed server-side** from the coupon row and the
  plan's configured price. Client-supplied amounts are never trusted.
- **Redemption is transactional**: the redemption row is written in the
  SAME SQLite transaction as the payment row (see
  :meth:`career_guidance.billing.BillingStore.create_payment`), after a
  re-check of every limit inside that transaction, so a race cannot
  over-redeem.
- **Referrals v1 = attribution + admin-visible counts only.** A referral
  code identifies who referred a buyer; the checkout records an
  attribution and a *pending, valueless* reward record
  (``referral_rewards`` with ``coupon_id`` NULL). Any actual discount for
  a referred user comes only from a coupon code that user redeems — a
  coupon the OWNER created. No reward amount is invented here.
"""

from __future__ import annotations

import secrets
import sqlite3
import string
from datetime import datetime, timezone

from career_guidance.migrations import migrate

#: A discounted order must still charge at least ₹1 (Razorpay's minimum
#: order amount is 100 paise); discounts are capped to leave that much.
MIN_CHARGE_PAISE = 100

COUPON_KINDS = ("percent", "flat_inr")


class CouponError(ValueError):
    """A coupon cannot be redeemed (reason is safe to show the user)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def validate_coupon_fields(kind: str, value: int) -> None:
    """Field rules for admin coupon creation; raises ValueError."""
    if kind not in COUPON_KINDS:
        raise ValueError("Coupon kind must be 'percent' or 'flat_inr'.")
    if kind == "percent" and not (1 <= int(value) <= 100):
        raise ValueError("A percent coupon must be between 1 and 100.")
    if kind == "flat_inr" and int(value) < 1:
        raise ValueError("A flat coupon must be at least ₹1.")


def compute_discount(coupon: dict, amount_paise: int) -> int:
    """Discount in paise for ``coupon`` against a gross amount.

    Percent: floor(amount × value / 100). Flat: value rupees → paise.
    The result is capped so the charge left is at least
    :data:`MIN_CHARGE_PAISE` (when the gross amount exceeds it).
    """
    if coupon["kind"] == "percent":
        discount = amount_paise * int(coupon["value"]) // 100
    else:  # flat_inr — value is whole rupees
        discount = int(coupon["value"]) * 100
    cap = max(0, amount_paise - MIN_CHARGE_PAISE) if amount_paise > MIN_CHARGE_PAISE else 0
    return max(0, min(discount, cap))


def coupon_rejection(
    conn: sqlite3.Connection, coupon: dict | None, user_id: str, now: datetime | None = None
) -> str | None:
    """Why ``coupon`` cannot be redeemed by ``user_id`` right now, or None.

    Pure check over an open connection so the checkout transaction can
    re-run it atomically before inserting the redemption row. Rules, in
    order: unknown code → inactive → expired → total redemption cap →
    per-user cap.
    """
    if coupon is None:
        return "Coupon code not recognised."
    if not coupon.get("active", 1):
        return "This coupon is no longer active."
    expires_at = coupon.get("expires_at") or ""
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            expiry = None
        if expiry is not None:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= (now or datetime.now(timezone.utc)):
                return "This coupon has expired."
    coupon_id = int(coupon["id"])
    max_redemptions = coupon.get("max_redemptions")
    if max_redemptions is not None:
        row = conn.execute(
            "SELECT COUNT(*) n FROM coupon_redemptions WHERE coupon_id=?", (coupon_id,)
        ).fetchone()
        if int(row["n"]) >= int(max_redemptions):
            return "This coupon has reached its redemption limit."
    per_user_limit = int(coupon.get("per_user_limit") or 1)
    row = conn.execute(
        "SELECT COUNT(*) n FROM coupon_redemptions WHERE coupon_id=? AND user_id=?",
        (coupon_id, user_id),
    ).fetchone()
    if int(row["n"]) >= per_user_limit:
        return "You have already used this coupon."
    return None


def insert_redemption(
    conn: sqlite3.Connection,
    coupon: dict,
    user_id: str,
    order_ref: str,
    discount_paise: int,
    now: datetime | None = None,
) -> None:
    """Re-check + insert a redemption inside the caller's transaction."""
    reason = coupon_rejection(conn, coupon, user_id, now)
    if reason:
        raise CouponError(reason)
    conn.execute(
        "INSERT INTO coupon_redemptions (coupon_id, user_id, order_ref, discount_paise,"
        " created_at) VALUES (?,?,?,?,?)",
        (int(coupon["id"]), user_id, order_ref, int(discount_paise), _now()),
    )


def insert_attribution(
    conn: sqlite3.Connection, referrer_user_id: str, referred_user_id: str, order_ref: str
) -> None:
    """Record a referral attribution + a pending, valueless reward row."""
    conn.execute(
        "INSERT INTO referral_attributions (referrer_user_id, referred_user_id, order_ref,"
        " created_at) VALUES (?,?,?,?)",
        (referrer_user_id, referred_user_id, order_ref, _now()),
    )
    conn.execute(
        "INSERT INTO referral_rewards (referrer_user_id, referred_user_id, status, coupon_id,"
        " created_at) VALUES (?,?,'pending',NULL,?)",
        (referrer_user_id, referred_user_id, _now()),
    )


class CouponStore:
    """SQLite store for coupons and their redemptions."""

    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(
        self,
        code: str,
        kind: str,
        value: int,
        max_redemptions: int | None = None,
        per_user_limit: int = 1,
        expires_at: str = "",
        created_by: str = "",
    ) -> dict:
        code = normalize_code(code)
        if len(code) < 3:
            raise ValueError("Coupon code must be at least 3 characters.")
        validate_coupon_fields(kind, value)
        if max_redemptions is not None and int(max_redemptions) < 1:
            raise ValueError("max_redemptions must be at least 1 when set.")
        if int(per_user_limit) < 1:
            raise ValueError("per_user_limit must be at least 1.")
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM coupons WHERE code=?", (code,)).fetchone():
                raise ValueError("A coupon with this code already exists.")
            cur = conn.execute(
                "INSERT INTO coupons (code, kind, value, max_redemptions, per_user_limit,"
                " expires_at, active, created_by, created_at) VALUES (?,?,?,?,?,?,1,?,?)",
                (
                    code,
                    kind,
                    int(value),
                    max_redemptions,
                    int(per_user_limit),
                    (expires_at or "").strip(),
                    created_by,
                    _now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM coupons WHERE id=?", (int(cur.lastrowid or 0),)
            ).fetchone()
        return dict(row)

    def get_by_code(self, code: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM coupons WHERE code=?", (normalize_code(code),)
            ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM coupon_redemptions r"
                " WHERE r.coupon_id=c.id) AS redeemed_count FROM coupons c ORDER BY c.id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def deactivate(self, code: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE coupons SET active=0 WHERE code=?", (normalize_code(code),))
        return cur.rowcount > 0

    def validate_for(self, code: str, user_id: str) -> tuple[dict | None, str | None]:
        """(coupon, None) when redeemable by this user, else (None, reason)."""
        coupon = self.get_by_code(code)
        with self._connect() as conn:
            reason = coupon_rejection(conn, coupon, user_id)
        if reason:
            return None, reason
        return coupon, None

    def redemption_count(self, coupon_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) n FROM coupon_redemptions WHERE coupon_id=?", (coupon_id,)
            ).fetchone()
        return int(row["n"])


class ReferralStore:
    """One referral code per user; attribution + counts (no values)."""

    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def code_for(self, user_id: str) -> str:
        """The user's referral code, created on first use (stable after)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT code FROM referral_codes WHERE user_id=?", (user_id,)
            ).fetchone()
            if row:
                return str(row["code"])
            alphabet = string.ascii_uppercase + string.digits
            for _ in range(8):
                code = "CG-" + "".join(secrets.choice(alphabet) for _ in range(8))
                try:
                    conn.execute(
                        "INSERT INTO referral_codes (user_id, code, created_at) VALUES (?,?,?)",
                        (user_id, code, _now()),
                    )
                    return code
                except sqlite3.IntegrityError:
                    continue  # code collision — mint another
        raise RuntimeError("Could not mint a unique referral code.")

    def owner_of(self, code: str) -> str | None:
        if not code or not str(code).strip():
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM referral_codes WHERE code=?",
                (str(code).strip().upper(),),
            ).fetchone()
        return str(row["user_id"]) if row else None

    def summary(self, user_id: str) -> dict:
        """{code, referrals, pending_rewards} — counts only, never values."""
        code = self.code_for(user_id)
        with self._connect() as conn:
            referrals = conn.execute(
                "SELECT COUNT(*) n FROM referral_attributions WHERE referrer_user_id=?",
                (user_id,),
            ).fetchone()["n"]
            pending = conn.execute(
                "SELECT COUNT(*) n FROM referral_rewards WHERE referrer_user_id=?"
                " AND status='pending'",
                (user_id,),
            ).fetchone()["n"]
        return {"code": code, "referrals": int(referrals), "pending_rewards": int(pending)}


__all__ = [
    "COUPON_KINDS",
    "MIN_CHARGE_PAISE",
    "CouponError",
    "CouponStore",
    "ReferralStore",
    "compute_discount",
    "coupon_rejection",
    "insert_attribution",
    "insert_redemption",
    "normalize_code",
    "validate_coupon_fields",
]
