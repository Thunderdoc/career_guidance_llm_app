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

_V3 = [
    "ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'",
    "ALTER TABLE users ADD COLUMN trial_ends_at TEXT NOT NULL DEFAULT ''",
    """CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'razorpay',
        provider_order_id TEXT NOT NULL UNIQUE,
        plan TEXT NOT NULL DEFAULT 'pro',
        amount_paise INTEGER NOT NULL,
        currency TEXT NOT NULL DEFAULT 'INR',
        status TEXT NOT NULL DEFAULT 'created',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
]

# --- v4: Phase 1 institute demo-request leads --------------------------------
_V4 = [
    """CREATE TABLE IF NOT EXISTS demo_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        organisation TEXT NOT NULL,
        seats INTEGER,
        message TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_demo_requests_created ON demo_requests (created_at)",
]

# --- v5: Phase 3 proof-of-skill, public profiles, 90-day plans --------------
_V5 = [
    # Public-profile fields on the user record (Phase 3.2). The handle is a
    # user-chosen unique slug; ``public_profile`` is the opt-in switch and
    # ``is_minor`` force-disables the public profile regardless of opt-in.
    "ALTER TABLE users ADD COLUMN handle TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN public_profile INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN is_minor INTEGER NOT NULL DEFAULT 0",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_handle ON users (handle) WHERE handle <> ''",
    """CREATE TABLE IF NOT EXISTS skill_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        skill TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'unverified',
        source TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        UNIQUE (user_id, skill)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_verif_user ON skill_verifications (user_id)",
    """CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        skill TEXT NOT NULL,
        score_percent REAL NOT NULL,
        passed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_attempts_user_skill ON quiz_attempts (user_id, skill, created_at)",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS skill_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        skill TEXT NOT NULL,
        title TEXT NOT NULL,
        link TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        checklist_json TEXT NOT NULL DEFAULT '[]',
        self_reported INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_projects_user ON skill_projects (user_id)",
    """CREATE TABLE IF NOT EXISTS plans_90day (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        run_id INTEGER,
        created_at TEXT NOT NULL,
        hours_per_week INTEGER NOT NULL DEFAULT 6,
        plan_json TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_plans90_user ON plans_90day (user_id, id)",
]

# --- v6: Phase 4 institute portal -------------------------------------------
_V6 = [
    """CREATE TABLE IF NOT EXISTS institutes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        logo_url TEXT NOT NULL DEFAULT '',
        accent_color TEXT NOT NULL DEFAULT '',
        plan TEXT NOT NULL DEFAULT 'institute',
        seat_limit INTEGER NOT NULL DEFAULT 50,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    # A user belongs to at most one institute in v1 (enforced in
    # career_guidance/institutes.py); the global users.role stays untouched.
    "ALTER TABLE users ADD COLUMN institute_id INTEGER",
    "ALTER TABLE users ADD COLUMN institute_role TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_users_institute ON users (institute_id)",
    """CREATE TABLE IF NOT EXISTS institute_invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        institute_id INTEGER NOT NULL,
        email TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        institute_role TEXT NOT NULL DEFAULT 'student',
        status TEXT NOT NULL DEFAULT 'pending',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (institute_id, email)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_invites_email ON institute_invites (email, status)",
    """CREATE TABLE IF NOT EXISTS run_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        reviewer_id TEXT NOT NULL,
        reviewer_role TEXT NOT NULL DEFAULT 'counsellor',
        note TEXT NOT NULL DEFAULT '',
        approved INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE (run_id, reviewer_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_reviews_run ON run_reviews (run_id)",
]

# --- v8: Phase 8 shareable report links -------------------------------------
_V8 = [
    # Only the SHA-256 hash of a share token is ever stored (see
    # career_guidance/sharing.py); the raw token exists only in the link
    # handed to the owner at creation. ``created_by`` is the owning user's
    # id, or the literal "guest" for links over an anonymous run.
    """CREATE TABLE IF NOT EXISTS share_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_hash TEXT NOT NULL UNIQUE,
        run_id INTEGER NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT NOT NULL DEFAULT '',
        fields_scope TEXT NOT NULL DEFAULT 'report_v1'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_share_tokens_hash ON share_tokens (token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_share_tokens_run ON share_tokens (run_id)",
]

# --- v7: Phase 5 privacy, consent & age declaration -------------------------
_V7 = [
    # Least-data age declaration (see career_guidance/consent.py): a band
    # ("adult" | "minor" | "") plus an OPTIONAL birth YEAR only — never a
    # full date of birth. ``is_minor`` (v5) stays the derived enforcement
    # flag; age_band/birth_year are the declared inputs it is derived from.
    "ALTER TABLE users ADD COLUMN age_band TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN birth_year INTEGER",
    """CREATE TABLE IF NOT EXISTS consent_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        guardian_email TEXT NOT NULL DEFAULT '',
        notice_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        method TEXT NOT NULL DEFAULT 'manual_email',
        token_hash TEXT NOT NULL DEFAULT '',
        token_expires_at TEXT NOT NULL DEFAULT '',
        requested_at TEXT NOT NULL,
        decided_at TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_consent_user ON consent_records (user_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_consent_token ON consent_records (token_hash)",
]

# --- v9: Phase 9 revenue v2 (subscriptions, coupons, referrals, analytics) --
_V9 = [
    # Razorpay subscriptions (an ADDITIONAL option beside one-time checkout).
    # ``status`` mirrors Razorpay's lifecycle (created/active/charged via
    # webhook, cancelled, halted, completed, paused); ``current_period_end``
    # is Razorpay's absolute period end, set from webhook payloads.
    """CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        plan TEXT NOT NULL,
        razorpay_subscription_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'created',
        current_period_end TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (user_id)",
    # Webhook idempotency ledger: one row per processed event key
    # (event type + entity id + payment id / period end). A replayed
    # delivery finds its key and is acknowledged without side effects.
    """CREATE TABLE IF NOT EXISTS webhook_events (
        event_key TEXT PRIMARY KEY,
        event TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    # Coupons are created ONLY by a platform admin (owner). No discount
    # exists in the system until a row exists here.
    """CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'percent',
        value INTEGER NOT NULL,
        max_redemptions INTEGER,
        per_user_limit INTEGER NOT NULL DEFAULT 1,
        expires_at TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS coupon_redemptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coupon_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        order_ref TEXT NOT NULL DEFAULT '',
        discount_paise INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_redemptions_coupon ON coupon_redemptions (coupon_id)",
    "CREATE INDEX IF NOT EXISTS idx_redemptions_user ON coupon_redemptions (coupon_id, user_id)",
    # Referrals v1 = attribution only. A referral code identifies the
    # referrer; any actual discount comes only from a coupon the referred
    # user redeems (a coupon the OWNER created). referral_rewards rows are
    # pending, valueless credit records until an admin links a coupon.
    """CREATE TABLE IF NOT EXISTS referral_codes (
        user_id TEXT PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS referral_attributions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_user_id TEXT NOT NULL,
        referred_user_id TEXT NOT NULL,
        order_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_attributions_referrer ON referral_attributions (referrer_user_id)",  # noqa: E501
    """CREATE TABLE IF NOT EXISTS referral_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_user_id TEXT NOT NULL,
        referred_user_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        coupon_id INTEGER,
        created_at TEXT NOT NULL
    )""",
    # Checkout records the discount actually applied + the codes used, in
    # the same transaction as the redemption/attribution rows.
    "ALTER TABLE payments ADD COLUMN discount_paise INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE payments ADD COLUMN coupon_code TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN referral_code TEXT NOT NULL DEFAULT ''",
    # Institute analytics v2: report-schedule PREFERENCE only (no scheduler
    # exists yet — see career_guidance.institutes.report_schedule_payload).
    "ALTER TABLE institutes ADD COLUMN report_schedule TEXT NOT NULL DEFAULT 'none'",
    "ALTER TABLE institutes ADD COLUMN report_schedule_updated_at TEXT NOT NULL DEFAULT ''",
]

# --- v10: Phase 10 index review + institute public API keys ----------------
_V10 = [
    # Index review (Phase 10): the hot per-user lookups that had no index.
    # recommendation_runs is filtered by user_id on history / cohort /
    # review-queue / export paths and in the account-deletion sweep;
    # assessment_runs / plans / interview_sessions / payments are all
    # read "latest by user" or "all by user" in journey.py + riasec.py.
    # Already indexed (verified, not duplicated): users by e-mail (UNIQUE)
    # and handle (v5 partial UNIQUE), skill_progress by user (PK prefix),
    # share_tokens by hash (v8), run_reviews by run (v6), consent_records
    # by user + token hash (v7), quiz_attempts by (user, skill) (v5).
    "CREATE INDEX IF NOT EXISTS idx_runs_user ON recommendation_runs (user_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_assessment_runs_user ON assessment_runs (user_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_plans_user ON plans (user_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_interview_sessions_user ON interview_sessions (user_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id, id)",
    # Institute public API keys (Phase 10): only the SHA-256 hash of a key
    # is stored; the raw key is shown once at creation (see
    # career_guidance/api_keys.py).
    """CREATE TABLE IF NOT EXISTS institute_api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        institute_id INTEGER NOT NULL,
        key_hash TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        revoked_at TEXT NOT NULL DEFAULT '',
        last_used_at TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_inst_api_keys_institute ON institute_api_keys (institute_id)",
]

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "baseline (runs, users, progress, feedback, overrides, audit)", _V1),
    (2, "journey, content, admin, gamification stores", _V2),
    (3, "billing: user plan/trial + payments ledger", _V3),
    (4, "phase 1: institute demo-request leads", _V4),
    (5, "phase 3: skill verification, public profiles, 90-day plans", _V5),
    (6, "phase 4: institutes, membership, invites, run reviews", _V6),
    (7, "phase 5: age declaration + parental consent records", _V7),
    (8, "phase 8: shareable report links (hashed tokens)", _V8),
    (9, "phase 9: subscriptions, coupons, referrals, report schedule", _V9),
    (10, "phase 10: per-user index review + institute public API keys", _V10),
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


_VERSION_TABLE = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
)


def applied_versions(path: str | Path) -> list[int]:
    """Return the migration versions already applied to ``path``."""
    from career_guidance import db as db_layer

    if db_layer.is_postgres_target(str(path)):
        return _applied_versions_postgres(str(path))
    if not Path(path).exists():
        return []
    with sqlite3.connect(str(path)) as conn:
        conn.execute(_VERSION_TABLE)
        return sorted(int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations"))


def migrate(path: str | Path) -> list[int]:
    """Apply pending migrations and return the versions applied by this call.

    ``path`` is a SQLite file path by default; a ``postgres://`` URL runs
    the same migration list through the dialect layer (Phase 6).
    """
    from career_guidance import db as db_layer

    if db_layer.is_postgres_target(str(path)):
        return _migrate_postgres(str(path))
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    done = applied_versions(path)
    applied: list[int] = []
    with sqlite3.connect(str(path)) as conn:
        conn.execute(_VERSION_TABLE)
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


# --- Postgres runner (Phase 6) ----------------------------------------------
# Same MIGRATIONS list, translated by career_guidance.db.translate_ddl.
# Idempotency on Postgres cannot rely on catching errors mid-transaction
# (an error aborts it), so ADD COLUMN statements are pre-checked against
# information_schema and CREATE statements carry IF NOT EXISTS already.


def _pg_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        (table,),
    ).fetchall()
    return {row["column_name"] for row in rows}


def _applied_versions_postgres(url: str) -> list[int]:
    from career_guidance import db as db_layer

    with db_layer.connect(url) as conn:
        conn.execute(_VERSION_TABLE)
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return sorted(int(r["version"]) for r in rows)


def _migrate_postgres(url: str) -> list[int]:
    from career_guidance import db as db_layer

    done = _applied_versions_postgres(url)
    applied: list[int] = []
    with db_layer.connect(url) as conn:
        for version, name, statements in MIGRATIONS:
            if version in done:
                continue
            with conn:  # one transaction per migration
                for statement in statements:
                    alter = db_layer.alter_add_column(statement)
                    if alter and alter[1] in _pg_columns(conn, alter[0]):
                        continue  # column already present — idempotent skip
                    translated = db_layer.translate_ddl(statement)
                    if translated is not None:
                        conn.execute(translated)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _now()),
                )
            applied.append(version)
            logger.info("Applied migration %s (%s) [postgres]", version, name)
    return applied
