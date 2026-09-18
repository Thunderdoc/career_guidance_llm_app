"""SQLite persistence for recommendation history.

A single ``Database`` class encapsulates all storage access so the
application can later swap SQLite for another database (e.g. Postgres)
without changing the UI or core logic.
"""

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

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


class Database:
    """SQLite-backed storage for recommendation runs."""

    def __init__(self, path: str) -> None:
        self._path = path
        parent = Path(path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(recommendation_runs)")]
            if "user_id" not in cols:
                conn.execute("ALTER TABLE recommendation_runs ADD COLUMN user_id TEXT")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

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
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO recommendation_runs "
                "(created_at, provider, is_demo, profile_json, recommendations_json, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    created_at,
                    provider,
                    int(is_demo),
                    json.dumps(profile),
                    json.dumps([asdict(rec) for rec in recommendations]),
                    user_id,
                ),
            )
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
