"""Parental consent + minor protections (Phase 5 — engineering side only).

This module is software, not legal advice. It implements the *mechanics*
the privacy notice describes:

- a **least-data age declaration**: an ``age_band`` ("adult" / "minor")
  plus an OPTIONAL birth **year** only. A full date of birth is never
  collected — the band is all the rules below need, and the year is a
  light corroborating signal. The declaration is the authoritative input;
  ``users.is_minor`` stays the derived enforcement flag (Phase 3/4).
  Fail-safe rule: if a declared birth year implies under-18, the account
  is treated as a minor even when the band says "adult".
- a **versioned consent record** (migration v7, ``consent_records``).
  The guardian e-mail is stored **in plain text, only inside this
  access-controlled table**: the confirm/revoke flow has to be able to
  show and re-contact that address, and the table is never exposed by any
  public endpoint (only the owning user's own status endpoint reads it).
  The confirm **token is stored hashed** (SHA-256) — the raw token exists
  only in the link sent to the guardian.
- a :class:`ConsentProvider` abstraction with one working implementation,
  :class:`ManualEmailConsentProvider`: guardian e-mail captured → request
  recorded with a token → guardian confirms/denies through a public,
  token-secured link (no account needed) → status flips. Delivery goes
  through the existing :mod:`career_guidance.notifications` providers —
  SMTP when configured, otherwise the log-only provider (the request is
  still recorded; nothing pretends an e-mail was delivered).

Notice versioning: :data:`NOTICE_VERSION` identifies the privacy-notice
text the guardian agreed to. Bumping it makes every previously *granted*
consent read as ``needs_reconsent`` (a computed status, never stored) —
restrictions re-apply until a guardian confirms the new notice.

Minor rules (for a minor WITHOUT granted consent) — see
:func:`restrictions_for`:

- public profile: blocked (already force-off for all minors, Phase 3);
- behavioural analytics events (``tool_events``): not recorded;
- streak / gamification nudges: suppressed server-side (no XP awards,
  dashboard streak surfaces zeroed, plan reminders not sent);
- institute needs-attention individual lists: the student is excluded.
  Institute membership itself is guardian/school-mediated, so cohort
  *aggregates* keep counting the student — only the individual list is
  filtered;
- core guidance (recommend, plan, assessments) keeps working: the
  minimal processing set is account + profile + runs + plans needed to
  deliver the guidance the user asked for.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from career_guidance.migrations import migrate

logger = logging.getLogger("career_guidance.consent")

#: Version of the plain-language privacy notice a guardian consents to.
#: Bump this (with the notice text) to invalidate older grants.
NOTICE_VERSION = "2026-11-v1"

#: How long a guardian confirm/deny token stays usable.
TOKEN_TTL_HOURS = 72

AGE_BANDS = ("adult", "minor")
CONSENT_STATUSES = ("pending", "granted", "denied", "revoked")
EFFECTIVE_STATUSES = CONSENT_STATUSES + ("needs_reconsent", "none")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def derive_is_minor(age_band: str = "", birth_year: int | None = None) -> bool:
    """Derive the enforcement flag from the least-data declaration.

    The band is authoritative; a birth year that implies under-18 wins
    over an "adult" band (fail-safe — a mistyped band must never strip a
    minor's protections). A birth year alone implies minor when the
    person cannot yet have turned 18 this year.
    """
    band = (age_band or "").strip().lower()
    if birth_year:
        try:
            if _now().year - int(birth_year) < 18:
                return True
        except (TypeError, ValueError):
            pass
    if band in AGE_BANDS:
        return band == "minor"
    return False


def validate_age_declaration(
    age_band: str = "", birth_year: int | None = None
) -> tuple[str, int | None]:
    """Normalise + validate a declaration; raises ValueError on bad input."""
    band = (age_band or "").strip().lower()
    if band and band not in AGE_BANDS:
        raise ValueError("age_band must be 'adult' or 'minor'.")
    year: int | None = None
    if birth_year is not None and birth_year != "":
        try:
            year = int(birth_year)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise ValueError("birth_year must be a year, e.g. 2012.") from error
        current = _now().year
        if year < current - 120 or year > current:
            raise ValueError("birth_year is out of range.")
    if not band and year is None:
        raise ValueError("Tell us whether you are 18 or older, or under 18.")
    return band, year


# --------------------------------------------------------------------------- #
# Store                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConsentRecord:
    id: int
    user_id: str
    guardian_email: str
    notice_version: str
    status: str  # stored status: pending | granted | denied | revoked
    method: str
    requested_at: str
    decided_at: str = ""
    token_expires_at: str = ""

    @property
    def effective_status(self) -> str:
        """Stored status, with stale grants computed as needs_reconsent."""
        if self.status == "granted" and self.notice_version != NOTICE_VERSION:
            return "needs_reconsent"
        return self.status

    def public(self, *, include_email: bool = False) -> dict:
        """Status payload. The guardian e-mail is included only for the
        owning user's own status view (``include_email=True``)."""
        out = {
            "id": self.id,
            "notice_version": self.notice_version,
            "current_notice_version": NOTICE_VERSION,
            "status": self.status,
            "effective_status": self.effective_status,
            "method": self.method,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "token_expires_at": self.token_expires_at,
        }
        if include_email:
            out["guardian_email"] = self.guardian_email
        return out


class ConsentStore:
    """SQLite store for consent records (table from migration v7)."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> ConsentRecord | None:
        if row is None:
            return None
        return ConsentRecord(
            id=int(row["id"]),
            user_id=row["user_id"],
            guardian_email=row["guardian_email"],
            notice_version=row["notice_version"],
            status=row["status"],
            method=row["method"],
            requested_at=row["requested_at"],
            decided_at=row["decided_at"],
            token_expires_at=row["token_expires_at"],
        )

    def create_request(
        self,
        user_id: str,
        guardian_email: str,
        *,
        method: str = "manual_email",
        notice_version: str = NOTICE_VERSION,
        ttl_hours: int = TOKEN_TTL_HOURS,
    ) -> tuple[ConsentRecord, str]:
        """Record a pending request; returns (record, raw_token).

        Any earlier pending request for the same user is superseded
        (marked revoked) so only one live token exists per user.
        """
        email = (guardian_email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("A valid guardian e-mail address is required.")
        now = _now()
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "UPDATE consent_records SET status = 'revoked' "
                "WHERE user_id = ? AND status = 'pending'",
                (user_id,),
            )
            cur = conn.execute(
                "INSERT INTO consent_records (user_id, guardian_email, notice_version, "
                "status, method, token_hash, token_expires_at, requested_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)",
                (
                    user_id,
                    email,
                    notice_version,
                    method,
                    _hash_token(token),
                    _iso(now + timedelta(hours=ttl_hours)),
                    _iso(now),
                ),
            )
            row = conn.execute(
                "SELECT * FROM consent_records WHERE id = ?", (int(cur.lastrowid or 0),)
            ).fetchone()
        return self._row(row), token  # type: ignore[return-value]

    def latest(self, user_id: str) -> ConsentRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM consent_records WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._row(row)

    def list_for_user(self, user_id: str) -> list[ConsentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM consent_records WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    def by_token(self, token: str) -> ConsentRecord | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM consent_records WHERE token_hash = ?", (_hash_token(token),)
            ).fetchone()
        return self._row(row)

    def token_expired(self, record: ConsentRecord) -> bool:
        if not record.token_expires_at:
            return True
        try:
            return datetime.fromisoformat(record.token_expires_at) < _now()
        except ValueError:
            return True

    def decide(self, token: str, granted: bool) -> ConsentRecord:
        """Guardian decision via token. Raises ValueError with a stable
        message for unknown / expired / already-decided tokens."""
        record = self.by_token(token)
        if record is None:
            raise ValueError("unknown_token")
        if record.status != "pending":
            raise ValueError("already_decided")
        if self.token_expired(record):
            raise ValueError("expired_token")
        status = "granted" if granted else "denied"
        with self._connect() as conn:
            conn.execute(
                "UPDATE consent_records SET status = ?, decided_at = ?, token_hash = '' "
                "WHERE id = ?",
                (status, _iso(_now()), record.id),
            )
            row = conn.execute(
                "SELECT * FROM consent_records WHERE id = ?", (record.id,)
            ).fetchone()
        return self._row(row)  # type: ignore[return-value]

    def revoke(self, user_id: str) -> ConsentRecord | None:
        """Revoke the current grant/pending request (user or guardian)."""
        record = self.latest(user_id)
        if record is None or record.status == "revoked":
            return record
        with self._connect() as conn:
            conn.execute(
                "UPDATE consent_records SET status = 'revoked', decided_at = ?, "
                "token_hash = '' WHERE id = ?",
                (_iso(_now()), record.id),
            )
            row = conn.execute(
                "SELECT * FROM consent_records WHERE id = ?", (record.id,)
            ).fetchone()
        return self._row(row)

    def revoke_by_token(self, token: str) -> ConsentRecord:
        """Guardian revokes a *granted* consent. The grant clears the
        decision token, so revocation by token uses a fresh token issued
        on the granted record — see :meth:`issue_action_token`."""
        record = self.by_token(token)
        if record is None:
            raise ValueError("unknown_token")
        if self.token_expired(record):
            raise ValueError("expired_token")
        return self.revoke(record.user_id)  # type: ignore[return-value]

    def issue_action_token(self, user_id: str, ttl_hours: int = TOKEN_TTL_HOURS) -> str:
        """Attach a fresh action token to the latest record (guardian
        revoke links). Returns the raw token."""
        record = self.latest(user_id)
        if record is None:
            raise ValueError("no_consent_record")
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "UPDATE consent_records SET token_hash = ?, token_expires_at = ? WHERE id = ?",
                (_hash_token(token), _iso(_now() + timedelta(hours=ttl_hours)), record.id),
            )
        return token

    def delete_for_user(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM consent_records WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------ status
    def effective_status(self, user_id: str) -> str:
        record = self.latest(user_id)
        return record.effective_status if record else "none"

    def has_granted_consent(self, user_id: str) -> bool:
        return self.effective_status(user_id) == "granted"


# --------------------------------------------------------------------------- #
# Provider                                                                     #
# --------------------------------------------------------------------------- #


class ConsentProvider(ABC):
    """How consent is asked for and confirmed."""

    name = "base"

    @abstractmethod
    def request_consent(self, user: dict, guardian_email: str) -> dict:
        """Record a consent request for ``user`` and notify the guardian.

        Returns the status payload plus, when the channel cannot deliver
        (log-only fallback), the confirm link so a dev/test surface can
        show it — mirroring the magic-link ``dev_link`` pattern.
        """

    @abstractmethod
    def confirm(self, token: str, granted: bool) -> ConsentRecord:
        """Apply the guardian's decision carried by ``token``."""


class ManualEmailConsentProvider(ConsentProvider):
    """Guardian confirms by a link sent to their e-mail address.

    Delivery uses the notifications abstraction: SMTP when configured,
    otherwise the log-only provider (the request is still recorded and
    the link is logged, never silently dropped).
    """

    name = "manual_email"

    def __init__(self, store: ConsentStore, base_url: str = "", notifier=None) -> None:
        self.store = store
        self.base_url = (base_url or "").rstrip("/")
        self._notifier = notifier

    def _notify(self, guardian_email: str, link: str) -> tuple[bool, str]:
        """Returns (handed_to_channel, channel_name). The log channel
        "succeeds" without delivering anything — callers must not treat
        it as an e-mail the guardian received."""
        from career_guidance.notifications import default_provider

        provider = self._notifier or default_provider()
        body = (
            "A Career Guidance AI account holder under 18 has listed you as "
            "their parent or guardian.\n\n"
            "The app is designed to give career guidance with extra "
            "protections for under-18 accounts. Please review the privacy "
            "notice in the app, then confirm or decline consent:\n\n"
            f"Confirm: {link}?decision=grant\n"
            f"Decline: {link}?decision=deny\n\n"
            f"This link works for {TOKEN_TTL_HOURS} hours. If you did not "
            "expect this, decline or ignore it."
        )
        try:
            sent = provider.send(
                {"email": guardian_email},
                "Career Guidance AI — parental consent request",
                body,
            )
            return bool(sent), getattr(provider, "name", "custom")
        except Exception:  # noqa: BLE001 - delivery must not break the request
            logger.exception("consent notification failed")
            return False, getattr(provider, "name", "custom")

    def confirm_link(self, token: str) -> str:
        return f"{self.base_url}/api/v1/consent/confirm/{token}"

    def request_consent(self, user: dict, guardian_email: str) -> dict:
        record, token = self.store.create_request(user["id"], guardian_email, method=self.name)
        link = self.confirm_link(token)
        sent, channel = self._notify(record.guardian_email, link)
        payload = record.public(include_email=True)
        # Only a real mail channel counts as delivered; the log provider
        # hands the message to nobody.
        payload["delivered"] = bool(sent and channel != "log")
        if not payload["delivered"] and os.getenv("APP_ENV", "development") != "production":
            # Log-fallback parity with magic links: surface the link so the
            # flow stays usable/testable when no mail channel is configured.
            # Never in production — there a dev link would let the account
            # holder confirm their own consent.
            payload["dev_link"] = link
        return payload

    def confirm(self, token: str, granted: bool) -> ConsentRecord:
        return self.store.decide(token, granted)


# --------------------------------------------------------------------------- #
# Minor rules engine                                                           #
# --------------------------------------------------------------------------- #


def is_unconsented_minor(user, consent_store: ConsentStore | None) -> bool:
    """True when ``user`` is a minor without currently-granted consent."""
    if user is None or not getattr(user, "is_minor", False):
        return False
    if consent_store is None:
        return True
    return not consent_store.has_granted_consent(user.id)


def restrictions_for(user, consent_store: ConsentStore | None) -> dict:
    """The documented minimal-processing rule set for one user.

    ``core_guidance`` is always allowed — a minor can always get the
    guidance they asked for. Everything behavioural or individual-level
    external is off until a guardian grants consent.
    """
    restricted = is_unconsented_minor(user, consent_store)
    return {
        "is_minor": bool(getattr(user, "is_minor", False)),
        "restricted": restricted,
        "core_guidance_allowed": True,
        "public_profile_allowed": not bool(getattr(user, "is_minor", False)),
        "behavioural_analytics_allowed": not restricted,
        "streak_nudges_allowed": not restricted,
        "needs_attention_individual_allowed": not restricted,
    }


__all__ = [
    "AGE_BANDS",
    "NOTICE_VERSION",
    "TOKEN_TTL_HOURS",
    "ConsentProvider",
    "ConsentRecord",
    "ConsentStore",
    "ManualEmailConsentProvider",
    "derive_is_minor",
    "is_unconsented_minor",
    "restrictions_for",
    "validate_age_declaration",
]
