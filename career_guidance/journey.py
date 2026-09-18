"""Journey store: self-ratings, saved plans, learning progress, interview notes.

Everything a signed-in user accumulates between sessions lives here, so the
dashboard, the plan page and the admin console read from one place.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from career_guidance.migrations import migrate
from career_guidance.roadmap import Roadmap, generate
from career_guidance.skillgap import Readiness, evaluate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JourneyStore:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------- skill ratings
    def ratings(self, user_id: str, career_id: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT skill, rating FROM skill_ratings WHERE user_id = ? AND career_id = ?",
                (user_id, career_id),
            ).fetchall()
        return {row["skill"]: int(row["rating"]) for row in rows}

    def set_ratings(self, user_id: str, career_id: str, ratings: dict[str, int]) -> dict[str, int]:
        with self._connect() as conn:
            for skill, value in ratings.items():
                try:
                    rating = max(0, min(5, int(value)))
                except (TypeError, ValueError):
                    continue
                conn.execute(
                    "INSERT INTO skill_ratings (user_id, career_id, skill, rating, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, career_id, skill) DO UPDATE SET "
                    "rating=excluded.rating, updated_at=excluded.updated_at",
                    (user_id, career_id, skill.strip().lower(), rating, _now()),
                )
        return self.ratings(user_id, career_id)

    # ------------------------------------------------------------- plans
    def save_plan(
        self,
        user_id: str,
        career_id: str,
        readiness: Readiness,
        roadmap: Roadmap,
    ) -> dict:
        payload = roadmap.to_dict()
        ratings = self.ratings(user_id, career_id)
        payload["ratings"] = ratings
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO plans (user_id, career_id, created_at, hours_per_week, readiness, weeks, "  # noqa: E501
                "eta, plan_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    career_id,
                    _now(),
                    roadmap.hours_per_week,
                    round(readiness.readiness_weighted, 1),
                    roadmap.weeks,
                    roadmap.eta,
                    json.dumps(payload),
                ),
            )
            plan_id = int(cur.lastrowid or 0)
        payload["plan_id"] = plan_id
        payload["created_at"] = _now()
        return payload

    def latest_plan(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["plan_json"])
        payload.update(
            {
                "plan_id": row["id"],
                "created_at": row["created_at"],
                "hours_per_week": row["hours_per_week"],
                "readiness": row["readiness"],
                "weeks": row["weeks"],
                "eta": row["eta"],
            }
        )
        # merge per-item completion state
        done = self.done_items(user_id, row["id"])
        for item in payload.get("items", []):
            item["done"] = item["id"] in done
        return payload

    def plan_by_id(self, user_id: str, plan_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE id = ? AND user_id = ?", (plan_id, user_id)
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["plan_json"])
        payload.update(
            {
                "plan_id": row["id"],
                "created_at": row["created_at"],
                "hours_per_week": row["hours_per_week"],
                "readiness": row["readiness"],
                "weeks": row["weeks"],
                "eta": row["eta"],
            }
        )
        done = self.done_items(user_id, row["id"])
        for item in payload.get("items", []):
            item["done"] = item["id"] in done
        return payload

    def set_item_done(self, user_id: str, plan_id: int, item_id: str, done: bool) -> dict | None:
        plan = self.plan_by_id(user_id, plan_id)
        if plan is None:
            return None
        with self._connect() as conn:
            if done:
                conn.execute(
                    "INSERT INTO xp_events (user_id, kind, points, created_at, detail) "
                    "SELECT ?, 'plan_item', 15, ?, ? WHERE NOT EXISTS ("
                    "SELECT 1 FROM xp_events WHERE user_id = ? AND kind = 'plan_item' AND detail = ?)",  # noqa: E501
                    (user_id, _now(), item_id, user_id, f"plan:{plan_id}:{item_id}"),
                )
        for item in plan.get("items", []):
            if item["id"] == item_id:
                item["done"] = done
        return plan

    def done_items(self, user_id: str, plan_id: int) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT detail FROM xp_events WHERE user_id = ? AND kind = 'plan_item' "
                "AND detail LIKE ?",
                (user_id, f"plan:{plan_id}:%"),
            ).fetchall()
        return {row["detail"].split(":", 2)[2] for row in rows}

    def rebuild_plan(self, user_id: str, career_id: str, hours_per_week: int) -> dict:
        """Evaluate ratings → roadmap → persist (single source of truth for /plan)."""
        ratings = self.ratings(user_id, career_id)
        readiness = evaluate(career_id, ratings)
        roadmap = generate(readiness, hours_per_week=hours_per_week)
        return self.save_plan(user_id, career_id, readiness, roadmap)

    # --------------------------------------------------- learning progress
    def saved_resources(self, user_id: str) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT resource_id FROM saved_resources WHERE user_id = ? ORDER BY saved_at DESC",
                (user_id,),
            ).fetchall()
        return [int(r["resource_id"]) for r in rows]

    def toggle_saved(self, user_id: str, resource_id: int, saved: bool) -> bool:
        with self._connect() as conn:
            if saved:
                conn.execute(
                    "INSERT OR IGNORE INTO saved_resources (user_id, resource_id, saved_at) "
                    "VALUES (?, ?, ?)",
                    (user_id, resource_id, _now()),
                )
            else:
                conn.execute(
                    "DELETE FROM saved_resources WHERE user_id = ? AND resource_id = ?",
                    (user_id, resource_id),
                )
        return saved

    def done_resources(self, user_id: str) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT resource_id FROM resource_progress WHERE user_id = ? AND done = 1",
                (user_id,),
            ).fetchall()
        return [int(r["resource_id"]) for r in rows]

    def mark_resource(self, user_id: str, resource_id: int, done: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO resource_progress (user_id, resource_id, done, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, resource_id) DO UPDATE SET "
                "done=excluded.done, updated_at=excluded.updated_at",
                (user_id, resource_id, int(done), _now()),
            )

    # ------------------------------------------------------ interview notes
    def save_interview(self, user_id: str, career_id: str, seconds: int, notes: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO interview_sessions (user_id, career_id, created_at, seconds, notes_json) "  # noqa: E501
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, career_id, _now(), int(seconds), json.dumps(notes)),
            )
            return int(cur.lastrowid or 0)

    def interview_sessions(self, user_id: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM interview_sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "career_id": row["career_id"],
                "created_at": row["created_at"],
                "seconds": row["seconds"],
                "notes": json.loads(row["notes_json"] or "{}"),
            }
            for row in rows
        ]

    # ------------------------------------------------------------- purges
    def purge_user(self, user_id: str) -> None:
        """Delete every row that belongs to a user (GDPR-style delete)."""
        tables = [
            "plans",
            "skill_ratings",
            "targets",
            "saved_resources",
            "resource_progress",
            "interview_sessions",
            "xp_events",
            "badges",
            "profiles",
            "skill_progress",
            "assessment_runs",
        ]
        with self._connect() as conn:
            for table in tables:
                conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            conn.execute(
                "UPDATE recommendation_runs SET user_id = NULL WHERE user_id = ?", (user_id,)
            )
            conn.execute("UPDATE feedback SET user_id = NULL WHERE user_id = ?", (user_id,))

    def export_user(self, user_id: str) -> dict:
        """Everything we hold about a user, as JSON."""
        with self._connect() as conn:

            def rows(sql: str, params=()) -> list[dict]:
                return [dict(r) for r in conn.execute(sql, params)]

            return {
                "profile": rows("SELECT * FROM profiles WHERE user_id = ?", (user_id,)),
                "targets": rows("SELECT * FROM targets WHERE user_id = ?", (user_id,)),
                "ratings": rows("SELECT * FROM skill_ratings WHERE user_id = ?", (user_id,)),
                "plans": rows("SELECT * FROM plans WHERE user_id = ?", (user_id,)),
                "saved_resources": rows(
                    "SELECT * FROM saved_resources WHERE user_id = ?", (user_id,)
                ),
                "learning_progress": rows(
                    "SELECT * FROM resource_progress WHERE user_id = ?", (user_id,)
                ),
                "interview_sessions": rows(
                    "SELECT * FROM interview_sessions WHERE user_id = ?", (user_id,)
                ),
                "xp_events": rows("SELECT * FROM xp_events WHERE user_id = ?", (user_id,)),
                "badges": rows("SELECT * FROM badges WHERE user_id = ?", (user_id,)),
                "skill_progress": rows(
                    "SELECT * FROM skill_progress WHERE user_id = ?", (user_id,)
                ),
                "assessments": rows("SELECT * FROM assessment_runs WHERE user_id = ?", (user_id,)),
                "runs": rows("SELECT * FROM recommendation_runs WHERE user_id = ?", (user_id,)),
                "feedback": rows("SELECT * FROM feedback WHERE user_id = ?", (user_id,)),
            }
