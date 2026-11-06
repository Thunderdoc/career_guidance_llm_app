"""Central database dialect layer (Phase 6 — Postgres option).

One place owns every SQLite-vs-Postgres difference so no other module
scatters dialect checks:

* **Config selection** — :func:`resolve_database_config` picks the engine:
  ``DATABASE_URL`` wins when set (``postgres://`` / ``postgresql://`` →
  Postgres, ``sqlite:///`` → SQLite file), otherwise the historical
  ``DATABASE_PATH`` SQLite file (the default; every test runs on it).
* **Placeholder style** — SQLite uses ``?``, psycopg uses ``%s``;
  :func:`translate_placeholders` converts at the connection boundary.
* **Row factory** — both engines hand back name-addressable rows
  (``sqlite3.Row`` / psycopg ``dict_row``), so callers use ``row["col"]``
  and ``row.keys()`` identically.
* **DDL translation** — :func:`translate_ddl` rewrites the SQLite-flavoured
  migration DDL for Postgres (identity columns); migrations stay written
  once, in the SQLite dialect.

Scope (honest boundary): the dialect layer backs the core
``career_guidance.storage.Database`` and the migration runner. The
remaining per-feature stores still open the SQLite file directly — they
share the same portable SQL (``?`` placeholders, no SQLite-only functions)
and are migrated store-by-store behind this layer; see
``docs/DEPLOY.md`` § "Choosing Postgres" for the smoke procedure and the
current boundary. The Postgres password is never stored on the config
object's repr or logged — only in the raw DSN handed to psycopg.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg", "postgres+psycopg"}
SQLITE_SCHEMES = {"sqlite", "sqlite3"}


@dataclass(frozen=True)
class DatabaseConfig:
    """Resolved database target. ``dsn`` holds credentials — never log it."""

    dialect: str  # "sqlite" | "postgres"
    sqlite_path: str = "data/career_guidance.db"
    dsn: str = field(default="", repr=False)
    host: str = ""
    port: int = 5432
    dbname: str = ""
    user: str = ""

    @property
    def placeholder(self) -> str:
        return "%s" if self.dialect == "postgres" else "?"

    @property
    def is_postgres(self) -> bool:
        return self.dialect == "postgres"

    def safe_label(self) -> str:
        """Credential-free description safe for logs and docs."""
        if self.is_postgres:
            return f"postgres://{self.user}@{self.host}:{self.port}/{self.dbname}"
        return f"sqlite:///{self.sqlite_path}"


def _sqlite_path_from_url(parsed) -> str:
    # sqlite:////abs/path -> /abs/path; sqlite:///rel.db -> rel.db;
    # sqlite:///:memory: -> :memory:
    path = unquote(parsed.path)
    if parsed.netloc and parsed.netloc not in ("localhost",):
        path = f"//{parsed.netloc}{path}"
    if path.startswith("/") and not parsed.path.startswith("//"):
        path = path[1:] if len(path) > 1 and not path.startswith("//") else path
    # urlparse keeps a leading "/" for absolute paths in sqlite://// form:
    if parsed.path.startswith("//"):
        path = unquote(parsed.path[1:])
    return path or "data/career_guidance.db"


def parse_database_url(url: str) -> DatabaseConfig:
    """Parse a ``DATABASE_URL`` into a :class:`DatabaseConfig`.

    Raises ``ValueError`` for an unsupported scheme so a typo fails loudly
    at boot instead of silently falling back to a throwaway SQLite file.
    """
    url = (url or "").strip()
    if not url:
        return DatabaseConfig(dialect="sqlite")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme in POSTGRES_SCHEMES:
        return DatabaseConfig(
            dialect="postgres",
            dsn=url,
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            dbname=(parsed.path or "/").lstrip("/") or "postgres",
            user=unquote(parsed.username or ""),
        )
    if scheme in SQLITE_SCHEMES:
        return DatabaseConfig(dialect="sqlite", sqlite_path=_sqlite_path_from_url(parsed))
    if scheme == "" or (len(scheme) == 1 and os.name == "nt"):  # plain path / Windows drive
        return DatabaseConfig(dialect="sqlite", sqlite_path=url)
    if "://" not in url:  # plain filesystem path without a scheme
        return DatabaseConfig(dialect="sqlite", sqlite_path=url)
    raise ValueError(f"Unsupported DATABASE_URL scheme {scheme!r}; use postgres:// or sqlite:///")


def resolve_database_config(
    database_url: str | None = None,
    database_path: str | None = None,
    environ: dict | None = None,
) -> DatabaseConfig:
    """Pick the engine: explicit arg > ``DATABASE_URL`` > ``DATABASE_PATH``."""
    env = os.environ if environ is None else environ
    url = database_url if database_url is not None else env.get("DATABASE_URL", "")
    if url and url.strip():
        return parse_database_url(url)
    path = database_path
    if path is None:
        path = env.get("DATABASE_PATH", "data/career_guidance.db")
    return DatabaseConfig(dialect="sqlite", sqlite_path=path)


def is_postgres_target(target: str) -> bool:
    """True when a path-or-URL argument names a Postgres database."""
    if not target:
        return False
    return urlparse(str(target)).scheme.lower() in POSTGRES_SCHEMES


def translate_placeholders(sql: str, dialect: str) -> str:
    """Convert ``?`` placeholders for the target dialect.

    For Postgres, literal ``%`` characters in the SQL text are doubled
    first (psycopg escaping); this project's SQL keeps patterns in bound
    parameters, never inline, so the rewrite is safe.
    """
    if dialect != "postgres":
        return sql
    return sql.replace("%", "%%").replace("?", "%s")


def translate_ddl(sql: str) -> str | None:
    """Translate one SQLite migration statement for Postgres.

    Returns ``None`` for statements with no Postgres meaning (PRAGMAs).
    Only the constructs the migration history actually uses are rewritten:
    identity primary keys; everything else (TEXT/INTEGER/REAL columns,
    ``IF NOT EXISTS``, partial indexes) is already valid Postgres.
    """
    statement = sql.strip()
    if statement.upper().startswith("PRAGMA"):
        return None
    statement = statement.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
    )
    return statement


_ALTER_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?P<table>\w+)\s+ADD\s+COLUMN\s+(?P<column>\w+)", re.IGNORECASE
)


def alter_add_column(statement: str) -> tuple[str, str] | None:
    """(table, column) for an ``ALTER TABLE … ADD COLUMN`` statement."""
    match = _ALTER_ADD_COLUMN.search(statement)
    if not match:
        return None
    return match.group("table"), match.group("column")


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #


class _PgCursor:
    """Minimal DB-API cursor facade over a psycopg cursor (dict rows)."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor.fetchall())

    @property
    def lastrowid(self):  # psycopg has no lastrowid; callers use RETURNING
        return None

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


class PostgresConnection:
    """sqlite3-shaped facade over a psycopg connection.

    Supports the subset of the sqlite3 API the core storage layer uses:
    ``execute`` (with ``?`` placeholders), ``executescript``, ``with conn``
    transaction blocks, and dict rows.
    """

    dialect = "postgres"

    def __init__(self, raw) -> None:
        self._raw = raw

    def execute(self, sql: str, params: tuple = ()) -> _PgCursor:
        cursor = self._raw.cursor()
        cursor.execute(translate_placeholders(sql, "postgres"), params or None)
        return _PgCursor(cursor)

    def executescript(self, script: str) -> None:
        cursor = self._raw.cursor()
        for chunk in script.split(";"):
            statement = chunk.strip()
            if not statement:
                continue
            translated = translate_ddl(statement)
            if translated is not None:
                cursor.execute(translated)

    def __enter__(self) -> PostgresConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        return False

    def close(self) -> None:
        self._raw.close()


def connect(target: str | DatabaseConfig):
    """Open a connection for a path, URL or resolved config.

    SQLite targets return a real ``sqlite3.Connection`` (row factory set);
    Postgres targets return a :class:`PostgresConnection`. ``psycopg`` is
    imported lazily so SQLite-only installs never need it.
    """
    config = (
        target
        if isinstance(target, DatabaseConfig)
        else resolve_database_config(
            database_url=str(target) if is_postgres_target(str(target)) else None,
            database_path=None if is_postgres_target(str(target)) else str(target),
        )
    )
    if config.is_postgres:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - exercised via message only
            raise RuntimeError(
                "DATABASE_URL selects Postgres but psycopg is not installed; "
                "install the optional extra: pip install -r requirements-postgres.txt"
            ) from error
        return PostgresConnection(psycopg.connect(config.dsn, row_factory=dict_row))
    if config.sqlite_path != ":memory:":
        parent = Path(config.sqlite_path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn
