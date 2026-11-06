"""Institute public API keys (Phase 10).

An institute admin (or a platform admin) can mint API keys for an
institute. A key authenticates **read-only, aggregate-only** public
endpoints under ``/api/v1/public/institutes/{slug}/…`` via the
``X-API-Key`` header — no session cookie is involved.

Security posture (same pattern as Phase 8 share tokens):
- the raw key (``cgk_`` + 256-bit URL-safe secret) is returned **once**,
  at creation; only its SHA-256 hash is stored, so a database leak
  yields no usable keys and a key can never be re-displayed;
- keys can be revoked (``revoked_at``); revoked, unknown and missing
  keys all fail authentication at the API layer;
- every successful authentication stamps ``last_used_at``;
- a key is bound to ONE institute: presenting it against another
  institute's slug does not authenticate for that institute.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from career_guidance.migrations import migrate

KEY_PREFIX = "cgk_"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _public_row(row: sqlite3.Row) -> dict:
    """Key metadata safe to list — never the hash, never a raw key."""
    return {
        "id": row["id"],
        "institute_id": row["institute_id"],
        "label": row["label"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "revoked_at": row["revoked_at"],
        "last_used_at": row["last_used_at"],
        "active": not row["revoked_at"],
    }


class InstituteApiKeyStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        migrate(self.path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_key(self, institute_id: int, label: str, created_by: str) -> dict:
        """Mint a key; the returned dict carries the RAW key (once only)."""
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO institute_api_keys"
                " (institute_id, key_hash, label, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (institute_id, _hash_key(raw), label[:120], created_by, _now()),
            )
            row = conn.execute(
                "SELECT * FROM institute_api_keys WHERE id = ?", (int(cur.lastrowid or 0),)
            ).fetchone()
        return {**_public_row(row), "api_key": raw}

    def list_keys(self, institute_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM institute_api_keys WHERE institute_id = ? ORDER BY id",
                (institute_id,),
            ).fetchall()
        return [_public_row(r) for r in rows]

    def revoke_key(self, institute_id: int, key_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE institute_api_keys SET revoked_at = ?"
                " WHERE id = ? AND institute_id = ? AND revoked_at = ''",
                (_now(), key_id, institute_id),
            )
            return cur.rowcount > 0

    def authenticate(self, raw: str | None) -> dict | None:
        """Resolve a raw key to its (active) key row, stamping last use."""
        if not raw or not raw.startswith(KEY_PREFIX):
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM institute_api_keys WHERE key_hash = ?", (_hash_key(raw),)
            ).fetchone()
            if row is None or row["revoked_at"]:
                return None
            conn.execute(
                "UPDATE institute_api_keys SET last_used_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
            updated = conn.execute(
                "SELECT * FROM institute_api_keys WHERE id = ?", (row["id"],)
            ).fetchone()
        return _public_row(updated)
