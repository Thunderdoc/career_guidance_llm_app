"""Shareable report links (Phase 8) — signed by possession, expiring, revocable.

Design (see docs/SECURITY.md § "Share tokens"):

- A share link carries a URL-safe random token (``secrets.token_urlsafe(32)``,
  256 bits). Only its **SHA-256 hash** is stored (``share_tokens.token_hash``,
  migration v8) — the raw token exists only in the link handed to the owner
  at creation time, so a database leak yields no usable links and the owner
  cannot re-display a link later (revoke + create a new one instead).
- Every link **expires** (default 7 days, max 30 — a module constant, not an
  env var, so the privacy posture cannot drift per deployment) and can be
  **revoked** by its owner at any time (``revoked_at``). Expired and revoked
  links both answer 410 at the API layer; unknown tokens answer 404.
- The public payload is built **from an allowlist** (:func:`build_shared_report`):
  the builder names every field it copies, starting from an empty dict. It
  never reads the stored profile (skills text, goals, education, résumé
  excerpt, constraints — city/budget are personal), never touches the user
  record (name/e-mail/handle), institute data or counsellor reviews, and
  never copies a recommendation's ``provenance`` blob wholesale.
  The fixed scope is :data:`SHARE_SCOPE` / :data:`SHARE_FIELDS`:

    run_id, created_at (of the run), priority_skills,
    recommendations[].career_id / title / match_percent,
    recommendations[].matching_skills / missing_skills / learning_path,
    recommendations[].reality.score / confidence / components
      (key, label, value, explanation, kind, source),
    recommendations[].reality.salary_ladder
      (fresher / 3-year / 7-year INR ranges, kind, source, as_of —
      labelled estimates, exactly as the owner's own report labels them)

  Salary figures come from the Reality Score's India layer recomputed
  deterministically for the stored careers (the stored run does not persist
  the Phase 2 ``reality`` block), so a shared report can never drift from
  what the matcher + India seed say today.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from career_guidance.migrations import migrate
from career_guidance.models import CareerRecommendation
from career_guidance.storage import StoredRun

#: Fixed share scope identifier stored on every token row. The scope is a
#: single documented field set (below) — it is not per-link configurable,
#: so a link can never quietly widen what it exposes.
SHARE_SCOPE = "report_v1"

#: The exact share-safe field set for SHARE_SCOPE (documented contract).
SHARE_FIELDS = (
    "run_id",
    "created_at",
    "priority_skills",
    "recommendations.career_id",
    "recommendations.title",
    "recommendations.match_percent",
    "recommendations.matching_skills",
    "recommendations.missing_skills",
    "recommendations.learning_path",
    "recommendations.reality.score",
    "recommendations.reality.confidence",
    "recommendations.reality.components",
    "recommendations.reality.salary_ladder",
)

DEFAULT_EXPIRY_DAYS = 7
MAX_EXPIRY_DAYS = 30

#: created_by value for links created over an anonymous (guest) run.
GUEST_CREATOR = "guest"

SOURCE_LINE = (
    "Source: O*NET occupational catalogue (974 occupations), this app's "
    "hybrid matcher; India salary/demand figures are labelled estimates "
    "derived from the project market seed — not official statistics."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def validate_expiry_days(expiry_days: int | None) -> int:
    """Normalise the requested lifetime; raises ValueError outside 1..30."""
    if expiry_days is None:
        return DEFAULT_EXPIRY_DAYS
    try:
        days = int(expiry_days)
    except (TypeError, ValueError) as error:
        raise ValueError("expiry_days must be a whole number of days.") from error
    if days < 1 or days > MAX_EXPIRY_DAYS:
        raise ValueError(f"expiry_days must be between 1 and {MAX_EXPIRY_DAYS}.")
    return days


# --------------------------------------------------------------------------- #
# Store                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ShareRecord:
    id: int
    run_id: int
    created_by: str
    created_at: str
    expires_at: str
    revoked_at: str = ""
    fields_scope: str = SHARE_SCOPE

    @property
    def expired(self) -> bool:
        try:
            return datetime.fromisoformat(self.expires_at) <= _now()
        except ValueError:
            return True

    @property
    def revoked(self) -> bool:
        return bool(self.revoked_at)

    @property
    def active(self) -> bool:
        return not self.revoked and not self.expired

    def status(self) -> str:
        if self.revoked:
            return "revoked"
        if self.expired:
            return "expired"
        return "active"

    def public(self) -> dict:
        """Owner-facing metadata — never the token or its hash."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at or None,
            "fields_scope": self.fields_scope,
            "status": self.status(),
        }


class ShareStore:
    """SQLite store for share tokens (table from migration v8)."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> ShareRecord | None:
        if row is None:
            return None
        return ShareRecord(
            id=int(row["id"]),
            run_id=int(row["run_id"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"] or "",
            fields_scope=row["fields_scope"] or SHARE_SCOPE,
        )

    def create(
        self, run_id: int, created_by: str, expiry_days: int | None = None
    ) -> tuple[ShareRecord, str]:
        """Mint a link; returns (record, raw_token). Only the hash is stored."""
        days = validate_expiry_days(expiry_days)
        now = _now()
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO share_tokens (token_hash, run_id, created_by, created_at, "
                "expires_at, revoked_at, fields_scope) VALUES (?, ?, ?, ?, ?, '', ?)",
                (
                    _hash_token(token),
                    int(run_id),
                    created_by or GUEST_CREATOR,
                    _iso(now),
                    _iso(now + timedelta(days=days)),
                    SHARE_SCOPE,
                ),
            )
            row = conn.execute(
                "SELECT * FROM share_tokens WHERE id = ?", (int(cur.lastrowid or 0),)
            ).fetchone()
        return self._row(row), token  # type: ignore[return-value]

    def by_token(self, token: str) -> ShareRecord | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM share_tokens WHERE token_hash = ?", (_hash_token(token),)
            ).fetchone()
        return self._row(row)

    def get(self, token_id: int) -> ShareRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM share_tokens WHERE id = ?", (int(token_id),)
            ).fetchone()
        return self._row(row)

    def list_for_run(self, run_id: int) -> list[ShareRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM share_tokens WHERE run_id = ? ORDER BY id DESC", (int(run_id),)
            ).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    def revoke(self, token_id: int) -> ShareRecord | None:
        """Mark a link revoked (idempotent); returns the updated record."""
        record = self.get(token_id)
        if record is None or record.revoked:
            return record
        with self._connect() as conn:
            conn.execute(
                "UPDATE share_tokens SET revoked_at = ? WHERE id = ?",
                (_iso(_now()), int(token_id)),
            )
        return self.get(token_id)

    def delete_for_user(self, user_id: str) -> None:
        """Account deletion: the user's share links die with the account."""
        with self._connect() as conn:
            conn.execute("DELETE FROM share_tokens WHERE created_by = ?", (user_id,))


# --------------------------------------------------------------------------- #
# Allowlist payload builder                                                    #
# --------------------------------------------------------------------------- #


def _salary_ladder(reality: dict | None) -> dict | None:
    """The labelled-estimate salary ladder from a Reality payload (or None)."""
    if not reality:
        return None
    market = (reality.get("india") or {}).get("market")
    if not market:
        return None
    return {
        "fresher_salary_inr": list(market.get("fresher_salary_inr") or []),
        "salary_3yr_inr": list(market.get("salary_3yr_inr") or []),
        "salary_7yr_inr": list(market.get("salary_7yr_inr") or []),
        "currency": "INR",
        "kind": market.get("kind") or "estimate",
        "source": market.get("source") or "",
        "as_of": market.get("as_of") or "",
    }


def _shared_reality(rec: CareerRecommendation, taxonomy) -> dict | None:
    """Reality score + ladder for one stored recommendation (allowlisted)."""
    if taxonomy is None or not rec.career_id:
        return None
    occupation = taxonomy.get(rec.career_id)
    if occupation is None:
        return None
    from career_guidance.reality import compute_reality

    reality = compute_reality(occupation)
    return {
        "score": reality.get("score"),
        "confidence": reality.get("confidence"),
        "components": [
            {
                "key": c.get("key"),
                "label": c.get("label"),
                "value": c.get("value"),
                "explanation": c.get("explanation"),
                "kind": c.get("kind"),
                "source": c.get("source"),
            }
            for c in reality.get("components", [])
        ],
        "salary_ladder": _salary_ladder(reality),
    }


def _priority_skills(recommendations: list[CareerRecommendation], limit: int = 3) -> list[str]:
    seen: list[str] = []
    for rec in recommendations[:3]:
        for skill in rec.missing_skills:
            if skill not in seen:
                seen.append(skill)
    return seen[:limit]


def build_shared_report(run: StoredRun, taxonomy=None) -> dict:
    """Build the public, share-safe view of a stored run — allowlist only.

    The stored profile is deliberately never read (beyond nothing at all):
    no skills text, goals, education, résumé excerpt or constraints can
    leak through a field the builder forgot to strip, because the builder
    copies nothing it does not name here.
    """
    if taxonomy is None:
        from career_guidance.taxonomy import load_taxonomy

        taxonomy = load_taxonomy()
    recommendations = []
    for rec in run.recommendations:
        recommendations.append(
            {
                "career_id": rec.career_id,
                "title": rec.title,
                "match_percent": round(rec.match_score * 100, 1) if rec.match_score else 0.0,
                "matching_skills": list(rec.matching_skills),
                "missing_skills": list(rec.missing_skills),
                "learning_path": list(rec.learning_path),
                "reality": _shared_reality(rec, taxonomy),
            }
        )
    return {
        "run_id": run.id,
        "created_at": run.created_at,
        "scope": SHARE_SCOPE,
        "fields": list(SHARE_FIELDS),
        "priority_skills": _priority_skills(run.recommendations),
        "recommendations": recommendations,
        "source": SOURCE_LINE,
    }


__all__ = [
    "DEFAULT_EXPIRY_DAYS",
    "GUEST_CREATOR",
    "MAX_EXPIRY_DAYS",
    "SHARE_FIELDS",
    "SHARE_SCOPE",
    "ShareRecord",
    "ShareStore",
    "build_shared_report",
    "validate_expiry_days",
]
