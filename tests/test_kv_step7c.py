"""Kaam-Vaani Step 7C tests: the Postgres-compatible path.

The repo's DB layer already supports Postgres optionally (Phase 6
dialect layer); Step 7C VERIFIED it against a real local Postgres
16.2 and fixed the one thing that broke. These tests pin that
verification:

- a guard over the REAL migration DDL: no unquoted PostgreSQL
  reserved word may appear as a column/table name (the
  ``current_role`` regression — v2's profiles DDL failed on live
  Postgres with a syntax error until it was quoted);
- the quoted ``current_role`` form in the v2 DDL and in the
  profiles upsert SQL (quoted identifiers work identically in
  SQLite, so the shared SQL stays portable);
- every migration statement translates through ``translate_ddl``
  (no AUTOINCREMENT survives, no PRAGMA reaches Postgres);
- a LIVE Postgres test (skipped unless ``KV_TEST_POSTGRES_URL``
  points at a real server): migrations 1..14 apply in one call,
  the re-run is a no-op, and the KV stores (RagStore,
  EmployerStore, ConsentStore) round-trip. Run it before any
  cutover — see ``docs/RUNBOOK.md`` §3 for the local-server
  recipe (Postgres refuses to run as root; start it as an
  unprivileged user).
"""

import os
import re

import pytest

from career_guidance import db as db_layer
from career_guidance.migrations import LATEST_VERSION, MIGRATIONS

# PostgreSQL reserved words (key words that can never be used as
# unquoted identifiers). Source: PostgreSQL docs, Appendix C.
PG_RESERVED_WORDS = {
    "ALL",
    "ANALYSE",
    "ANALYZE",
    "AND",
    "ANY",
    "ARRAY",
    "AS",
    "ASC",
    "ASYMMETRIC",
    "AUTHORIZATION",
    "BINARY",
    "BOTH",
    "CASE",
    "CAST",
    "CHECK",
    "COLLATE",
    "COLUMN",
    "CONSTRAINT",
    "CREATE",
    "CROSS",
    "CURRENT_CATALOG",
    "CURRENT_DATE",
    "CURRENT_ROLE",
    "CURRENT_TIME",
    "CURRENT_TIMESTAMP",
    "CURRENT_USER",
    "DEFAULT",
    "DEFERRABLE",
    "DO",
    "ELSE",
    "END",
    "EXCEPT",
    "FALSE",
    "FETCH",
    "FOR",
    "FOREIGN",
    "FREEZE",
    "FROM",
    "FULL",
    "GRANT",
    "GROUP",
    "HAVING",
    "ILIKE",
    "IN",
    "INITIALLY",
    "INNER",
    "INTERSECT",
    "INTO",
    "IS",
    "ISNULL",
    "JOIN",
    "LATERAL",
    "LEADING",
    "LEFT",
    "LIKE",
    "LIMIT",
    "LOCALTIME",
    "LOCALTIMESTAMP",
    "NATURAL",
    "NOT",
    "NOTNULL",
    "NULL",
    "OFFSET",
    "ON",
    "ONLY",
    "OR",
    "ORDER",
    "OUTER",
    "OVERLAPS",
    "PLACING",
    "PRIMARY",
    "REFERENCES",
    "RETURNING",
    "RIGHT",
    "SELECT",
    "SESSION_USER",
    "SIMILAR",
    "SOME",
    "SYMMETRIC",
    "TABLE",
    "TABLESAMPLE",
    "THEN",
    "TO",
    "TRAILING",
    "TRUE",
    "UNION",
    "UNIQUE",
    "USER",
    "USING",
    "VARIADIC",
    "VERBOSE",
    "WHEN",
    "WHERE",
    "WINDOW",
    "WITH",
}

_COLUMN_DEF = re.compile(
    r"^\s{8,12}([a-z][a-z0-9_]*)\s+"
    r"(TEXT|INTEGER|REAL|BLOB|BOOLEAN|TIMESTAMP|NUMERIC|BIGINT|VARCHAR|CHAR)\b",
    re.MULTILINE,
)
_ADD_COLUMN = re.compile(r"ADD COLUMN\s+(?:IF NOT EXISTS\s+)?([a-z][a-z0-9_]*)", re.IGNORECASE)
_CREATE_TABLE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?([a-z][a-z0-9_]*)")


def _migration_identifiers() -> tuple[set[str], set[str]]:
    """(column names, table names) declared across all migrations,
    excluding quoted identifiers (a quoted name is safe)."""
    columns: set[str] = set()
    tables: set[str] = set()
    for _version, _name, statements in MIGRATIONS:
        for statement in statements:
            columns.update(m.group(1) for m in _COLUMN_DEF.finditer(statement))
            columns.update(m.lower() for m in _ADD_COLUMN.findall(statement))
            tables.update(_CREATE_TABLE.findall(statement))
    return columns, tables


def test_no_unquoted_reserved_word_identifiers_in_migrations():
    """Step 7C regression guard: v2's unquoted ``current_role``
    column failed on live Postgres (``CURRENT_ROLE`` is reserved)
    while SQLite accepted it silently. Any future migration that
    introduces an unquoted reserved word must fail HERE, not at
    cutover time."""
    columns, tables = _migration_identifiers()
    assert len(columns) > 100  # the scan sees the real DDL, not nothing
    assert len(tables) > 10
    bad_columns = sorted(c for c in columns if c.upper() in PG_RESERVED_WORDS)
    bad_tables = sorted(t for t in tables if t.upper() in PG_RESERVED_WORDS)
    assert bad_columns == []
    assert bad_tables == []


def test_current_role_is_quoted_in_v2_ddl():
    """The fix itself: v2's profiles DDL quotes ``current_role``
    (Postgres needs the quotes; SQLite accepts them identically)."""
    v2 = next(statements for v, _n, statements in MIGRATIONS if v == 2)
    profiles_ddl = next(s for s in v2 if "CREATE TABLE IF NOT EXISTS profiles" in s)
    assert '"current_role" TEXT NOT NULL' in profiles_ddl
    assert "\n        current_role TEXT" not in profiles_ddl


def test_current_role_is_quoted_in_profiles_upsert():
    """The upsert SQL quotes the column on both sides of the
    conflict clause (``excluded."current_role"``) — unquoted, the
    same syntax error would surface on the first profile save
    after cutover."""
    import career_guidance.profiles as profiles_mod

    source = open(profiles_mod.__file__, encoding="utf-8").read()
    assert '"current_role"' in source
    assert 'excluded."current_role"' in source


def test_all_migration_ddl_translates_for_postgres():
    """Every migration statement passes through ``translate_ddl``
    (the Postgres path): no AUTOINCREMENT survives, no PRAGMA
    reaches Postgres, and the translated v2 profiles DDL keeps
    the quoted column."""
    translated_all = []
    for _version, _name, statements in MIGRATIONS:
        for statement in statements:
            translated = db_layer.translate_ddl(statement)
            if translated is not None:
                translated_all.append(translated)
    assert translated_all  # the scan ran over real statements
    joined = "\n".join(translated_all)
    assert "AUTOINCREMENT" not in joined
    assert "PRAGMA" not in joined
    assert '"current_role" TEXT NOT NULL' in joined
    assert "GENERATED BY DEFAULT AS IDENTITY" in joined


# --------------------------------------------------------------------------- #
# Live Postgres (skipped unless KV_TEST_POSTGRES_URL is set)
# --------------------------------------------------------------------------- #
PG_URL = os.environ.get("KV_TEST_POSTGRES_URL", "")


@pytest.mark.skipif(not PG_URL, reason="KV_TEST_POSTGRES_URL not set")
def test_live_postgres_migrations_and_kv_stores():
    """The 7C live verification, committed as a runnable check:
    migrations 1..14 apply on a REAL Postgres, the re-run is a
    no-op, and the KV stores round-trip. Needs an EMPTY database
    (the test drops nothing — point it at a scratch DB)."""
    pytest.importorskip("psycopg")
    from career_guidance.kaamvaani.consent import ConsentStore
    from career_guidance.kaamvaani.employers import EmployerStore
    from career_guidance.kaamvaani.rag import Chunk, RagStore
    from career_guidance.migrations import applied_versions, migrate

    applied = migrate(PG_URL)
    assert applied == list(range(1, LATEST_VERSION + 1))
    assert applied_versions(PG_URL) == list(range(1, LATEST_VERSION + 1))
    assert migrate(PG_URL) == []

    store = RagStore(PG_URL)
    chunk = Chunk(
        source_id="test:7c",
        source_url="https://example.test/7c",
        source_title="7C smoke chunk",
        source_date="2026-11-21",
        licence="test",
        language="en",
        topic="wages",
        state="",
        district="",
        chunk_index=0,
        text="smoke test chunk",
        snapshot_version="v2-test",
    )
    assert store.replace_snapshot([chunk], "v2-test") == 1
    assert [c.source_id for c in store.all_chunks()] == ["test:7c"]

    employers = EmployerStore(PG_URL)
    employer = employers.create_employer("7c-owner", "7C Test Works", city="Madurai")
    assert employer.id > 0  # RETURNING id on Postgres
    listing = employers.create_listing(employer.id, "Electrician helper", city="Madurai")
    assert listing.id > 0
    assert employers.list_public_listings() == []  # pending: hidden

    consents = ConsentStore(PG_URL)
    consents.save_worker_profile("7c-worker", skills=["electrical"], city="Madurai")
    consent = consents.grant_consent("7c-worker", employer.id, ["skills", "city"])
    assert consent.id > 0
    assert consents.has_active_consent("7c-worker", employer.id) is not None
    audit = consents.list_audit(worker_user_id="7c-worker")
    assert len(audit) == 1 and audit[0].action == "granted"
