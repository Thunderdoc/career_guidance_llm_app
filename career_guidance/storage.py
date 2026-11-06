"""Persistence for recommendation history.

A single ``Database`` class encapsulates all storage access. The engine
is chosen by :mod:`career_guidance.db` (Phase 6): a filesystem path (or
``DATABASE_PATH``) keeps the default SQLite behaviour; a ``postgres://``
``DATABASE_URL`` selects Postgres through the same class — placeholder
style and row factory differences live in that layer, not here.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from career_guidance import db as db_layer
from career_guidance.models import CareerRecommendation

logger = logging.getLogger("career_guidance.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    is_demo INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at
    ON recommendation_runs (created_at);
"""


@dataclass(frozen=True)
class StoredRun:
    """A persisted recommendation run."""

    id: int
    created_at: str
    provider: str
    is_demo: bool
    profile: dict
    recommendations: list[CareerRecommendation]
    user_id: str | None = None
    flagged: bool = False


class Database:
    """Storage for recommendation runs (SQLite by default, Postgres option)."""

    def __init__(self, path: str) -> None:
        # ``path`` is a filesystem path or a DATABASE_URL (career_guidance.db).
        self._path = path
        self._config = db_layer.resolve_database_config(
            database_url=path if db_layer.is_postgres_target(path) else None,
            database_path=None if db_layer.is_postgres_target(path) else path,
        )
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            if "user_id" not in self._column_names(conn, "recommendation_runs"):
                conn.execute("ALTER TABLE recommendation_runs ADD COLUMN user_id TEXT")

    @property
    def dialect(self) -> str:
        return self._config.dialect

    def _connect(self):
        return db_layer.connect(self._config)

    def _column_names(self, conn, table: str) -> set[str]:
        if self._config.is_postgres:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                (table,),
            ).fetchall()
            return {row["column_name"] for row in rows}
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    def ping(self) -> bool:
        """Readiness probe: True when a trivial query succeeds."""
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:  # noqa: BLE001 - a probe reports, never raises
            return False

    def save_run(
        self,
        profile: dict,
        recommendations: list[CareerRecommendation],
        provider: str,
        is_demo: bool,
        user_id: str | None = None,
    ) -> int:
        """Persist a recommendation run and return its row id."""
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        params = (
            created_at,
            provider,
            int(is_demo),
            json.dumps(profile),
            json.dumps([asdict(rec) for rec in recommendations]),
            user_id,
        )
        sql = (
            "INSERT INTO recommendation_runs "
            "(created_at, provider, is_demo, profile_json, recommendations_json, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        with self._connect() as conn:
            if self._config.is_postgres:  # psycopg has no lastrowid
                row = conn.execute(sql + " RETURNING id", params).fetchone()
                return int(row["id"] or 0)
            cursor = conn.execute(sql, params)
            return int(cursor.lastrowid or 0)

    def list_runs(self, limit: int = 100) -> list[StoredRun]:
        """Return the most recent runs, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recommendation_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        runs = []
        for row in rows:
            try:
                runs.append(
                    StoredRun(
                        id=row["id"],
                        created_at=row["created_at"],
                        provider=row["provider"],
                        is_demo=bool(row["is_demo"]),
                        flagged=bool(row["flagged"]) if "flagged" in row.keys() else False,
                        profile=json.loads(row["profile_json"]),
                        recommendations=[
                            CareerRecommendation.from_dict(item)
                            for item in json.loads(row["recommendations_json"])
                        ],
                        user_id=row["user_id"],
                    )
                )
            except (json.JSONDecodeError, TypeError):
                logger.warning("Skipping corrupt history row id=%s", row["id"])
        return runs

    def count_runs(self) -> int:
        """Return the total number of stored runs."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM recommendation_runs").fetchone()
        return int(row["n"])

    def delete_run(self, run_id: int) -> None:
        """Delete a single run."""
        with self._connect() as conn:
            conn.execute("DELETE FROM recommendation_runs WHERE id = ?", (run_id,))

    def clear(self) -> None:
        """Delete all stored runs."""
        with self._connect() as conn:
            conn.execute("DELETE FROM recommendation_runs")


def runs_to_json(runs: list[StoredRun]) -> str:
    """Export stored runs as pretty-printed JSON."""
    return json.dumps(
        [
            {
                "id": run.id,
                "created_at": run.created_at,
                "provider": run.provider,
                "is_demo": run.is_demo,
                "profile": run.profile,
                "recommendations": [asdict(rec) for rec in run.recommendations],
            }
            for run in runs
        ],
        indent=2,
    )


def runs_to_markdown(runs: list[StoredRun]) -> str:
    """Export stored runs as a Markdown document."""
    if not runs:
        return "No history yet."
    blocks = []
    for run in runs:
        titles = ", ".join(rec.title for rec in run.recommendations)
        skills = str(run.profile.get("skills", ""))[:200]
        blocks.append(
            f"## Run #{run.id} · {run.created_at} · {run.provider}\n\n"
            f"> Skills: {skills}\n\n"
            f"Recommended: {titles}"
        )
    return "\n\n".join(blocks)
