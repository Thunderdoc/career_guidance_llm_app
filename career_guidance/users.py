"""User, session, feedback and content-override storage (SQLite).

Kept separate from ``storage.Database`` (runs) so the recommendation core
stays independent of accounts. Anonymous usage remains first-class: a run
may or may not carry a ``user_id``.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    picture TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    last_login_at TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    prefs_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS magic_links (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    user_id TEXT,
    run_id INTEGER,
    career_title TEXT NOT NULL DEFAULT '',
    rating INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS resource_overrides (
    skill TEXT PRIMARY KEY,
    resources_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS skill_progress (
    user_id TEXT NOT NULL,
    skill TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, skill)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    picture: str
    provider: str
    role: str
    created_at: str
    last_login_at: str
    disabled: bool = False
    prefs: dict | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict:
        d = asdict(self)
        d["is_admin"] = self.is_admin
        return d


class UserStore:
    def __init__(self, path: str, admin_emails: set[str] | None = None) -> None:
        self._path = path
        self._admins = {e.lower() for e in (admin_emails or set()) if e}
        parent = Path(path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Add user_id to runs table if the runs DB shares this file.
            cols = [r[1] for r in conn.execute("PRAGMA table_info(recommendation_runs)")]
            if cols and "user_id" not in cols:
                conn.execute("ALTER TABLE recommendation_runs ADD COLUMN user_id TEXT")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- users -------------------------------------------------------- #

    @staticmethod
    def _row(row: sqlite3.Row | None) -> User | None:
        if not row:
            return None
        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            picture=row["picture"],
            provider=row["provider"],
            role=row["role"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            disabled=bool(row["disabled"]),
            prefs=json.loads(row["prefs_json"] or "{}"),
        )

    def upsert_login(self, email: str, provider: str, name: str = "", picture: str = "") -> User:
        email = email.strip().lower()
        role = "admin" if email in self._admins else None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET last_login_at=?, name=COALESCE(NULLIF(?,''), name), "
                    "picture=COALESCE(NULLIF(?,''), picture), role=COALESCE(?, role) WHERE id=?",
                    (_now(), name, picture, role, row["id"]),
                )
                uid = row["id"]
            else:
                uid = secrets.token_urlsafe(12)
                conn.execute(
                    "INSERT INTO users (id,email,name,picture,provider,role,created_at,"
                    "last_login_at) VALUES (?,?,?,?,?,?,?,?)",
                    (uid, email, name, picture, provider, role or "user", _now(), _now()),
                )
            return self._row(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())

    def get(self, user_id: str) -> User | None:
        with self._connect() as conn:
            return self._row(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def list_users(self, q: str = "", limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT u.*, (SELECT COUNT(*) FROM recommendation_runs r WHERE r.user_id=u.id) "
                "AS runs FROM users u WHERE u.email LIKE ? OR u.name LIKE ? "
                "ORDER BY u.last_login_at DESC LIMIT ?",
                (f"%{q}%", f"%{q}%", limit),
            ).fetchall()
        out = []
        for r in rows:
            u = self._row(r).public()
            u["runs"] = r["runs"]
            out.append(u)
        return out

    def count_users(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            new7 = conn.execute(
                "SELECT COUNT(*) n FROM users WHERE created_at >= ?", (week,)
            ).fetchone()["n"]
            active7 = conn.execute(
                "SELECT COUNT(*) n FROM users WHERE last_login_at >= ?", (week,)
            ).fetchone()["n"]
        return {"total": total, "new_7d": new7, "active_7d": active7}

    def set_role(self, user_id: str, role: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))

    def set_disabled(self, user_id: str, disabled: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(disabled), user_id))

    def delete_user(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.execute("DELETE FROM skill_progress WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM recommendation_runs WHERE user_id=?", (user_id,))

    def set_prefs(self, user_id: str, prefs: dict) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET prefs_json=? WHERE id=?", (json.dumps(prefs), user_id))

    # ---- magic links --------------------------------------------------- #

    def create_magic_link(self, email: str, ttl_minutes: int = 15) -> str:
        token = secrets.token_urlsafe(32)
        exp = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO magic_links (token,email,expires_at) VALUES (?,?,?)",
                (token, email.strip().lower(), exp),
            )
        return token

    def consume_magic_link(self, token: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM magic_links WHERE token=?", (token,)).fetchone()
            if not row or row["used"] or row["expires_at"] < _now():
                return None
            conn.execute("UPDATE magic_links SET used=1 WHERE token=?", (token,))
            return row["email"]

    # ---- progress ------------------------------------------------------ #

    def progress(self, user_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT skill FROM skill_progress WHERE user_id=? AND done=1", (user_id,)
            ).fetchall()
        return [r["skill"] for r in rows]

    def set_progress(self, user_id: str, skill: str, done: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_progress (user_id,skill,done,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id,skill) DO UPDATE SET done=excluded.done, "
                "updated_at=excluded.updated_at",
                (user_id, skill.strip().lower(), int(done), _now()),
            )

    # ---- feedback ------------------------------------------------------ #

    def add_feedback(
        self,
        rating: int,
        comment: str,
        user_id: str | None,
        run_id: int | None,
        career: str,
        tool: str = "",
    ) -> int:
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO feedback (created_at,user_id,run_id,career_title,rating,comment,tool) "  # noqa: E501
                    "VALUES (?,?,?,?,?,?,?)",
                    (_now(), user_id, run_id, career[:200], rating, comment[:2000], tool[:40]),
                )
            except sqlite3.OperationalError:  # pre-v2 database without the tool column
                cur = conn.execute(
                    "INSERT INTO feedback (created_at,user_id,run_id,career_title,rating,comment) "
                    "VALUES (?,?,?,?,?,?)",
                    (_now(), user_id, run_id, career[:200], rating, comment[:2000]),
                )
            return int(cur.lastrowid or 0)

    def list_feedback(self, status: str | None = None, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            sql = (
                "SELECT f.*, u.email FROM feedback f LEFT JOIN users u ON u.id=f.user_id "
                + ("WHERE f.status=? " if status else "")
                + "ORDER BY f.id DESC LIMIT ?"
            )
            rows = conn.execute(sql, (status, limit) if status else (limit,)).fetchall()
        return [dict(r) for r in rows]

    def feedback_stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) n, AVG(rating) avg, "
                "SUM(CASE WHEN status='new' THEN 1 ELSE 0 END) open FROM feedback"
            ).fetchone()
        return {
            "total": row["n"],
            "avg_rating": round(row["avg"] or 0, 2),
            "open": row["open"] or 0,
        }

    def set_feedback_status(self, fid: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE feedback SET status=? WHERE id=?", (status, fid))

    # ---- resource overrides -------------------------------------------- #

    def resource_overrides(self) -> dict[str, list[dict]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT skill, resources_json FROM resource_overrides").fetchall()
        return {r["skill"]: json.loads(r["resources_json"]) for r in rows}

    def set_resources(self, skill: str, resources: list[dict], actor: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO resource_overrides (skill,resources_json,updated_at,updated_by) "
                "VALUES (?,?,?,?) ON CONFLICT(skill) DO UPDATE SET "
                "resources_json=excluded.resources_json, updated_at=excluded.updated_at, "
                "updated_by=excluded.updated_by",
                (skill.strip().lower(), json.dumps(resources), _now(), actor),
            )

    def delete_resources(self, skill: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM resource_overrides WHERE skill=?", (skill.strip().lower(),))

    # ---- audit --------------------------------------------------------- #

    def audit(self, actor: str, action: str, target: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (created_at,actor,action,target) VALUES (?,?,?,?)",
                (_now(), actor, action, target),
            )

    def audit_log(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
