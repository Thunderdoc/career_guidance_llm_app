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
    # Phase 3 public profile: user-chosen unique slug + opt-in switch.
    handle: str = ""
    public_profile: bool = False
    # Phase 3/5: minors never get a public profile, regardless of opt-in.
    is_minor: bool = False
    # Phase 4: at most one institute per user; institute_role is one of
    # institute_admin | counsellor | student ("" when not a member).
    institute_id: int | None = None
    institute_role: str = ""
    # Phase 5: least-data age declaration — band + optional birth YEAR
    # only (never a full date of birth). is_minor is derived from these.
    age_band: str = ""
    birth_year: int | None = None

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
            # Phase 3 columns (migration v5 adds them on the app path; the
            # store also self-heals so standalone use keeps working).
            ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            for col, ddl in (
                ("institute_id", "ALTER TABLE users ADD COLUMN institute_id INTEGER"),
                (
                    "institute_role",
                    "ALTER TABLE users ADD COLUMN institute_role TEXT NOT NULL DEFAULT ''",
                ),
                ("handle", "ALTER TABLE users ADD COLUMN handle TEXT NOT NULL DEFAULT ''"),
                (
                    "public_profile",
                    "ALTER TABLE users ADD COLUMN public_profile INTEGER NOT NULL DEFAULT 0",
                ),
                ("is_minor", "ALTER TABLE users ADD COLUMN is_minor INTEGER NOT NULL DEFAULT 0"),
                ("age_band", "ALTER TABLE users ADD COLUMN age_band TEXT NOT NULL DEFAULT ''"),
                ("birth_year", "ALTER TABLE users ADD COLUMN birth_year INTEGER"),
            ):
                if col not in ucols:
                    conn.execute(ddl)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- users -------------------------------------------------------- #

    @staticmethod
    def _row(row: sqlite3.Row | None) -> User | None:
        if not row:
            return None
        keys = row.keys()
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
            handle=row["handle"] if "handle" in keys else "",
            public_profile=bool(row["public_profile"]) if "public_profile" in keys else False,
            is_minor=bool(row["is_minor"]) if "is_minor" in keys else False,
            institute_id=row["institute_id"] if "institute_id" in keys else None,
            institute_role=row["institute_role"] if "institute_role" in keys else "",
            age_band=row["age_band"] if "age_band" in keys else "",
            birth_year=row["birth_year"] if "birth_year" in keys else None,
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
        """Delete a user and ALL of their personal data (Phase 5 fix).

        Root-cause note: the pre-Phase-5 version deleted only the user
        row, skill progress and runs — verifications, quiz attempts,
        projects, 90-day plans, payments, tool events, consent records
        (with the guardian's e-mail), reviews and more survived as orphan
        personal data, and the journey purge was only wired into the
        *admin* delete path, never into self-delete. This method is now
        the single comprehensive path used by both.

        Behaviour (matches the privacy notice): runs are hard-deleted;
        feedback is anonymised (user_id → NULL, the rating itself is
        product data); audit rows keep the action but the actor e-mail is
        anonymised. Tables that do not exist yet are skipped.
        """
        user = self.get(user_id)
        email = user.email if user else ""
        # Tables keyed by user_id whose rows are purely the user's data.
        hard_delete = [
            "skill_progress",
            "recommendation_runs",
            "profiles",
            "targets",
            "plans",
            "plans_90day",
            "skill_ratings",
            "saved_resources",
            "resource_progress",
            "interview_sessions",
            "xp_events",
            "badges",
            "assessment_runs",
            "skill_verifications",
            "quiz_attempts",
            "skill_projects",
            "tool_events",
            "payments",
            "consent_records",
        ]
        with self._connect() as conn:
            existing = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            # Reviews OF this user's runs go with the runs; reviews BY this
            # user (as counsellor/reviewer) are their personal data too.
            if "run_reviews" in existing and "recommendation_runs" in existing:
                conn.execute(
                    "DELETE FROM run_reviews WHERE run_id IN "
                    "(SELECT id FROM recommendation_runs WHERE user_id = ?)",
                    (user_id,),
                )
            if "run_reviews" in existing:
                conn.execute("DELETE FROM run_reviews WHERE reviewer_id = ?", (user_id,))
            # Phase 8: share links the user minted die with the account
            # (the table keys its owner column ``created_by``, not user_id).
            if "share_tokens" in existing:
                conn.execute("DELETE FROM share_tokens WHERE created_by = ?", (user_id,))
            for table in hard_delete:
                if table in existing:
                    conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))  # noqa: S608
            if "feedback" in existing:
                conn.execute("UPDATE feedback SET user_id = NULL WHERE user_id = ?", (user_id,))
            if email:
                if "magic_links" in existing:
                    conn.execute("DELETE FROM magic_links WHERE email = ?", (email,))
                if "institute_invites" in existing:
                    conn.execute("DELETE FROM institute_invites WHERE email = ?", (email,))
                if "audit_log" in existing:
                    conn.execute(
                        "UPDATE audit_log SET actor = 'deleted-user' WHERE actor = ?", (email,)
                    )
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))

    def set_prefs(self, user_id: str, prefs: dict) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET prefs_json=? WHERE id=?", (json.dumps(prefs), user_id))

    # ---- public profile (Phase 3) --------------------------------------- #

    def set_public_profile(self, user_id: str, handle: str, enabled: bool) -> User:
        """Set the public-profile handle + opt-in. Raises ValueError on a
        malformed or already-taken handle."""
        import re

        handle = (handle or "").strip().lower()
        if enabled or handle:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,29}", handle):
                raise ValueError(
                    "Handle must be 3–30 characters: lower-case letters, digits and hyphens."
                )
            with self._connect() as conn:
                clash = conn.execute(
                    "SELECT id FROM users WHERE handle = ? AND id <> ?", (handle, user_id)
                ).fetchone()
                if clash:
                    raise ValueError("That handle is already taken.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET handle = ?, public_profile = ? WHERE id = ?",
                (handle, int(bool(enabled)), user_id),
            )
            return self._row(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def set_minor(self, user_id: str, is_minor: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET is_minor = ? WHERE id = ?", (int(is_minor), user_id))

    def set_age_declaration(
        self, user_id: str, age_band: str = "", birth_year: int | None = None
    ) -> User:
        """Record the least-data age declaration and derive ``is_minor``.

        Validation lives in career_guidance.consent (single source); this
        method stores the normalised values and the derived flag together
        so Phase 3/4 enforcement (public profile, …) keeps working.
        """
        from career_guidance.consent import derive_is_minor, validate_age_declaration

        band, year = validate_age_declaration(age_band, birth_year)
        is_minor = derive_is_minor(band, year)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET age_band = ?, birth_year = ?, is_minor = ? WHERE id = ?",
                (band, year, int(is_minor), user_id),
            )
            return self._row(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def get_by_handle(self, handle: str) -> User | None:
        with self._connect() as conn:
            return self._row(
                conn.execute(
                    "SELECT * FROM users WHERE handle = ?", ((handle or "").strip().lower(),)
                ).fetchone()
            )

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

    # ---- billing ------------------------------------------------------- #

    def plan_of(self, user_id: str) -> dict:
        """Billing state for a user: assigned plan + trial window."""
        with self._connect() as conn:
            try:
                row = conn.execute(
                    "SELECT plan, trial_ends_at FROM users WHERE id=?", (user_id,)
                ).fetchone()
            except sqlite3.OperationalError:
                # Database predates migration 3 (no billing columns yet).
                return {"plan": "free", "trial_ends_at": ""}
            if not row:
                return {"plan": "free", "trial_ends_at": ""}
            return {"plan": row["plan"] or "free", "trial_ends_at": row["trial_ends_at"] or ""}

    def set_plan(self, user_id: str, plan: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET plan=? WHERE id=?", (plan, user_id))

    def start_trial(self, user_id: str, ends_at: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET trial_ends_at=? WHERE id=?", (ends_at, user_id))

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
