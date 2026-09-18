"""Gamification: XP events, daily/weekly streaks and badges.

Rules are deliberately simple and explainable — every badge is earned by a
countable action, so a user can see exactly how to get it.

XP              action
--------------  ---------------------------------------------------------------
10              saved a recommendation run
20              completed the interest assessment
25              generated a roadmap
15              marked a roadmap item learned
10              marked a course done
30              résumé analysed
20              job-description fit run
25              interview practice session saved
5               feedback left
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from career_guidance.migrations import migrate

XP_RULES: dict[str, int] = {
    "run": 10,
    "assessment": 20,
    "plan": 25,
    "plan_item": 15,
    "course_done": 10,
    "resume": 30,
    "jobfit": 20,
    "interview": 25,
    "feedback": 5,
}

LEVELS: tuple[tuple[int, str], ...] = (
    (0, "Explorer"),
    (50, "Planner"),
    (150, "Builder"),
    (300, "Achiever"),
    (600, "Specialist"),
    (1000, "Mentor"),
)


@dataclass(frozen=True)
class Badge:
    id: str
    name: str
    description: str
    kind: str  # xp | count | streak | event
    threshold: int
    event: str = ""


BADGES: tuple[Badge, ...] = (
    Badge("first-run", "First run", "Get your first recommendations", "count", 1),
    Badge(
        "interest-explorer",
        "Interest explorer",
        "Complete the RIASEC interest test",
        "event",
        1,
        "assessment",
    ),  # noqa: E501
    Badge("first-plan", "First plan", "Generate your first learning roadmap", "event", 1, "plan"),
    Badge(
        "first-resume",
        "Résumé ready",
        "Analyse your résumé against a target career",
        "event",
        1,
        "resume",
    ),  # noqa: E501
    Badge(
        "first-interview",
        "Interview starter",
        "Save your first interview practice session",
        "event",
        1,
        "interview",
    ),  # noqa: E501
    Badge(
        "course-starter",
        "Course starter",
        "Mark your first course as done",
        "event",
        1,
        "course_done",
    ),
    Badge(
        "skills-10",
        "10 skills learned",
        "Mark 10 roadmap items or courses as learned",
        "count",
        10,
        "learned",
    ),  # noqa: E501
    Badge(
        "skills-25",
        "25 skills learned",
        "Mark 25 roadmap items or courses as learned",
        "count",
        25,
        "learned",
    ),  # noqa: E501
    Badge(
        "interview-ready",
        "Interview-ready",
        "Complete 10 interview practice sessions",
        "count",
        10,
        "interview",
    ),  # noqa: E501
    Badge("streak-3", "Three-day streak", "Practise three days in a row", "streak", 3),
    Badge("streak-7", "Week-long streak", "Practise seven days in a row", "streak", 7),
    Badge("xp-500", "500 XP", "Earn 500 XP", "xp", 500),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def level_for(xp: int) -> tuple[int, str]:
    level, name = 1, LEVELS[0][1]
    for index, (threshold, label) in enumerate(LEVELS, start=1):
        if xp >= threshold:
            level, name = index, label
    return level, name


def last_n_days(days: int = 30) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


class GamificationStore:
    """XP, streaks and badges for one database."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # -------------------------------------------------------------- events
    def award(self, user_id: str, kind: str, detail: str = "", points: int | None = None) -> int:
        """Record an event and return the points awarded."""
        value = XP_RULES.get(kind, 0) if points is None else int(points)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO xp_events (user_id, kind, points, created_at, detail) VALUES (?, ?, ?, ?, ?)",  # noqa: E501
                (user_id, kind, value, _now(), detail[:200]),
            )
        self.evaluate_badges(user_id)
        return value

    def xp(self, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(points), 0) AS xp FROM xp_events WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row["xp"])

    def daily_xp(self, user_id: str, days: int = 30) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT substr(created_at, 1, 10) AS day, SUM(points) AS points FROM xp_events "
                "WHERE user_id = ? GROUP BY day ORDER BY day",
                (user_id,),
            ).fetchall()
        by_day = {row["day"]: int(row["points"]) for row in rows}
        return [(day, by_day.get(day, 0)) for day in last_n_days(days)]

    def active_days(self, user_id: str, limit: int = 400) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(created_at, 1, 10) AS day FROM xp_events "
                "WHERE user_id = ? ORDER BY day DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [row["day"] for row in rows]

    def streak(self, user_id: str) -> dict:
        days = sorted(self.active_days(user_id))
        if not days:
            return {"current": 0, "longest": 0, "days": []}
        dates = [date.fromisoformat(day) for day in days]
        longest = current = 1
        for previous, day in zip(dates, dates[1:], strict=False):
            if (day - previous).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1
        today = date.today()
        tail_current = 0
        if dates[-1] in (today, today - timedelta(days=1)):
            tail_current = 1
            for previous, day in zip(reversed(dates[:-1]), reversed(dates), strict=False):
                if (day - previous).days == 1:
                    tail_current += 1
                else:
                    break
        return {
            "current": tail_current,
            "longest": max(longest, tail_current),
            "days": days[-60:],
        }

    def counts(self, user_id: str) -> dict[str, int]:
        with self._connect() as conn:

            def count(kind: str) -> int:
                row = conn.execute(
                    "SELECT COUNT(*) n FROM xp_events WHERE user_id = ? AND kind = ?",
                    (user_id, kind),
                ).fetchone()
                return int(row["n"])

            learned = count("plan_item") + count("course_done")
            return {
                "runs": count("run"),
                "assessments": count("assessment"),
                "plans": count("plan"),
                "plan_items": count("plan_item"),
                "courses": count("course_done"),
                "resumes": count("resume"),
                "jobfits": count("jobfit"),
                "interviews": count("interview"),
                "learned": learned,
            }

    # -------------------------------------------------------------- badges
    def badges(self, user_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT badge_id, earned_at FROM badges WHERE user_id = ? ORDER BY earned_at",
                (user_id,),
            ).fetchall()
        earned = {row["badge_id"]: row["earned_at"] for row in rows}
        return [
            {
                "id": badge.id,
                "name": badge.name,
                "description": badge.description,
                "earned_at": earned.get(badge.id, ""),
            }
            for badge in BADGES
        ]

    def evaluate_badges(self, user_id: str) -> list[str]:
        """Grant any badge whose rule is now satisfied; returns the new ids."""
        xp = self.xp(user_id)
        counts = self.counts(user_id)
        streak = self.streak(user_id)["longest"]
        have = {b["id"] for b in self.badges(user_id) if b["earned_at"]}
        earned: list[str] = []
        for badge in BADGES:
            if badge.id in have:
                continue
            if badge.kind == "xp" and xp >= badge.threshold:
                earned.append(badge.id)
            elif badge.kind == "count" and counts.get(badge.event, 0) >= badge.threshold:
                earned.append(badge.id)
            elif badge.kind == "event" and counts.get(badge.event, 0) >= badge.threshold:
                earned.append(badge.id)
            elif badge.kind == "streak" and streak >= badge.threshold:
                earned.append(badge.id)
        if earned:
            with self._connect() as conn:
                for badge_id in earned:
                    conn.execute(
                        "INSERT OR IGNORE INTO badges (user_id, badge_id, earned_at) VALUES (?, ?, ?)",  # noqa: E501
                        (user_id, badge_id, _now()),
                    )
        return earned

    # -------------------------------------------------------------- status
    def status(self, user_id: str) -> dict:
        xp = self.xp(user_id)
        level, name = level_for(xp)
        badges = self.badges(user_id)
        next_badge = next((b for b in badges if not b["earned_at"]), None)
        with self._connect() as conn:
            recent = [
                dict(row)
                for row in conn.execute(
                    "SELECT kind, points, created_at, detail FROM xp_events WHERE user_id = ? "
                    "ORDER BY id DESC LIMIT 10",
                    (user_id,),
                )
            ]
        return {
            "xp": xp,
            "level": level,
            "level_name": name,
            "next_level_xp": next((t for t, _ in LEVELS if t > xp), None),
            "streak": self.streak(user_id),
            "badges": [b for b in badges if b["earned_at"]],
            "all_badges": badges,
            "next_badge": next_badge,
            "recent": recent,
            "counts": self.counts(user_id),
            "source": "Source: your activity in this app (XP rules documented in career_guidance/gamification.py)",  # noqa: E501
        }
