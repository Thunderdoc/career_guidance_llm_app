"""Versioned, idempotent SQLite migrations.

Every schema change in this project ships as a numbered migration here, so a
production ``career_guidance.db`` upgrades **in place, without data loss** the
first time the new build starts. Migrations are applied in order inside a single
transaction per version and recorded in ``schema_migrations``.

Usage::

    from career_guidance.migrations import migrate
    migrate("/app/data/career_guidance.db")   # -> [1, 2, 3]
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("career_guidance.migrations")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- v1: baseline tables that older builds created inline ---------------------
_V1 = [
    """CREATE TABLE IF NOT EXISTS recommendation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        provider TEXT NOT NULL,
        is_demo INTEGER NOT NULL,
        profile_json TEXT NOT NULL,
        recommendations_json TEXT NOT NULL,
        user_id TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_runs_created_at ON recommendation_runs (created_at)",
    """CREATE TABLE IF NOT EXISTS users (
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
    )""",
    """CREATE TABLE IF NOT EXISTS magic_links (
        token TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        user_id TEXT,
        run_id INTEGER,
        career_title TEXT NOT NULL DEFAULT '',
        rating INTEGER NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new'
    )""",
    """CREATE TABLE IF NOT EXISTS resource_overrides (
        skill TEXT PRIMARY KEY,
        resources_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS skill_progress (
        user_id TEXT NOT NULL,
        skill TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, skill)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT ''
    )""",
]

# --- v2: S2–S4 stores ---------------------------------------------------------
_V2 = [
    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS profiles (
        user_id TEXT PRIMARY KEY,
        persona TEXT NOT NULL DEFAULT '',
        education TEXT NOT NULL DEFAULT '',
        current_role TEXT NOT NULL DEFAULT '',
        experience_level TEXT NOT NULL DEFAULT '',
        skills_json TEXT NOT NULL DEFAULT '[]',
        goals TEXT NOT NULL DEFAULT '',
        interests TEXT NOT NULL DEFAULT '',
        hours_per_week INTEGER NOT NULL DEFAULT 6,
        language TEXT NOT NULL DEFAULT 'en',
        country TEXT NOT NULL DEFAULT 'in',
        onboarded INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS unmatched_skills (
        term TEXT PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 1,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        mapped_to TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS synonyms (
        alias TEXT PRIMARY KEY,
        canonical TEXT NOT NULL,
        locale TEXT NOT NULL DEFAULT 'en',
        source TEXT NOT NULL DEFAULT 'admin',
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS career_overrides (
        career_id TEXT PRIMARY KEY,
        hidden INTEGER NOT NULL DEFAULT 0,
        salary_p25 INTEGER, salary_p50 INTEGER, salary_p75 INTEGER,
        trend TEXT NOT NULL DEFAULT '',
        remote INTEGER,
        indian_titles TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS custom_careers (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        job_zone INTEGER NOT NULL DEFAULT 3,
        skills_json TEXT NOT NULL DEFAULT '[]',
        knowledge_json TEXT NOT NULL DEFAULT '[]',
        technology_json TEXT NOT NULL DEFAULT '[]',
        alt_titles_json TEXT NOT NULL DEFAULT '[]',
        holland_code TEXT NOT NULL DEFAULT '',
        interests_json TEXT NOT NULL DEFAULT '{}',
        related_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT '',
        level TEXT NOT NULL DEFAULT 'beginner',
        language TEXT NOT NULL DEFAULT 'en',
        free INTEGER NOT NULL DEFAULT 1,
        duration_minutes INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        last_checked TEXT NOT NULL DEFAULT '',
        uses INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT '',
        UNIQUE (skill, url)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_resources_skill ON resources (skill)",
    """CREATE TABLE IF NOT EXISTS saved_resources (
        user_id TEXT NOT NULL,
        resource_id INTEGER NOT NULL,
        saved_at TEXT NOT NULL,
        PRIMARY KEY (user_id, resource_id)
    )""",
    """CREATE TABLE IF NOT EXISTS resource_progress (
        user_id TEXT NOT NULL,
        resource_id INTEGER NOT NULL,
        done INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, resource_id)
    )""",
    """CREATE TABLE IF NOT EXISTS assessment_items (
        id TEXT PRIMARY KEY,
        dim TEXT NOT NULL,
        text TEXT NOT NULL,
        locale TEXT NOT NULL DEFAULT 'en',
        weight REAL NOT NULL DEFAULT 1.0,
        active INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS assessment_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        created_at TEXT NOT NULL,
        answers_json TEXT NOT NULL,
        scores_json TEXT NOT NULL,
        holland_code TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS interview_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL DEFAULT 'behavioural',
        template TEXT NOT NULL,
        skill TEXT NOT NULL DEFAULT '',
        career_id TEXT NOT NULL DEFAULT '',
        locale TEXT NOT NULL DEFAULT 'en',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS interview_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        career_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        seconds INTEGER NOT NULL DEFAULT 0,
        notes_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS targets (
        user_id TEXT PRIMARY KEY,
        career_id TEXT NOT NULL,
        set_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        career_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        hours_per_week INTEGER NOT NULL DEFAULT 6,
        readiness REAL NOT NULL DEFAULT 0,
        weeks INTEGER NOT NULL DEFAULT 0,
        eta TEXT NOT NULL DEFAULT '',
        plan_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS skill_ratings (
        user_id TEXT NOT NULL,
        career_id TEXT NOT NULL,
        skill TEXT NOT NULL,
        rating INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, career_id, skill)
    )""",
    """CREATE TABLE IF NOT EXISTS xp_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        points INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_xp_user_day ON xp_events (user_id, created_at)",
    """CREATE TABLE IF NOT EXISTS badges (
        user_id TEXT NOT NULL,
        badge_id TEXT NOT NULL,
        earned_at TEXT NOT NULL,
        PRIMARY KEY (user_id, badge_id)
    )""",
    """CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        level TEXT NOT NULL DEFAULT 'info',
        active INTEGER NOT NULL DEFAULT 1,
        pinned INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS tool_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        user_id TEXT,
        tool TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tool_events_tool ON tool_events (tool, created_at)",
    """CREATE TABLE IF NOT EXISTS system_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        kind TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS error_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        path TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        created_at TEXT NOT NULL,
        finished_at TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT ''
    )""",
    # additive columns on tables that shipped in v1
    "ALTER TABLE recommendation_runs ADD COLUMN tool TEXT NOT NULL DEFAULT 'recommend'",
    "ALTER TABLE recommendation_runs ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE recommendation_runs ADD COLUMN readiness REAL NOT NULL DEFAULT 0",
    "ALTER TABLE audit_log ADD COLUMN detail TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE feedback ADD COLUMN note TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE feedback ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE feedback ADD COLUMN tool TEXT NOT NULL DEFAULT ''",
]

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "baseline (runs, users, progress, feedback, overrides, audit)", _V1),
    (2, "journey, content, admin, gamification stores", _V2),
]

LATEST_VERSION = max(v for v, _, _ in MIGRATIONS)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:  # pragma: no cover - defensive
        return set()


def _apply_statements(conn: sqlite3.Connection, statements: list[str]) -> None:
    """Run statements, tolerating "already exists" style errors (idempotency)."""
    for statement in statements:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as error:
            message = str(error).lower()
            if "duplicate column name" in message or "already exists" in message:
                continue
            raise


def applied_versions(path: str | Path) -> list[int]:
    """Return the migration versions already applied to ``path``."""
    if not Path(path).exists():
        return []
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        return sorted(int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations"))


def migrate(path: str | Path) -> list[int]:
    """Apply pending migrations and return the versions applied by this call."""
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    done = applied_versions(path)
    applied: list[int] = []
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        for version, name, statements in MIGRATIONS:
            if version in done:
                continue
            with conn:  # one transaction per migration
                _apply_statements(conn, statements)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _now()),
                )
            applied.append(version)
            logger.info("Applied migration %s (%s)", version, name)
    return applied
