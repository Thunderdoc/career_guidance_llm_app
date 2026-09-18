"""User profiles: onboarding answers, targets, preferences.

One row per user (``profiles``) so the wizard runs once and every screen can
prefill from it. Pure storage — no web framework — and versioned through
:mod:`career_guidance.migrations`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from career_guidance.migrations import migrate

PERSONAS = (
    "Student",
    "Fresher / first job",
    "Career switcher",
    "Returning to work",
    "Working professional",
)

EDUCATION_LEVELS = (
    "10th / SSLC",
    "12th / Higher secondary",
    "ITI / Diploma",
    "Bachelor's degree",
    "Master's degree / MBA",
    "PhD / Doctorate",
    "Other",
)

LANGUAGES = ("en", "ta", "hi")
HOURS_MIN, HOURS_MAX = 1, 40
GOALS_MAX = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Profile:
    user_id: str
    persona: str = ""
    education: str = ""
    current_role: str = ""
    experience_level: str = ""
    skills: list[str] = field(default_factory=list)
    goals: str = ""
    interests: str = ""
    hours_per_week: int = 6
    language: str = "en"
    country: str = "in"
    onboarded: bool = False
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_complete(self) -> bool:
        """Enough signal for recommendations to be meaningful."""
        return bool(self.persona and (self.skills or self.goals) and self.experience_level)


class ProfileStore:
    """Read/write user profiles and career targets."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------- profiles
    def get(self, user_id: str) -> Profile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> Profile:
        return Profile(
            user_id=row["user_id"],
            persona=row["persona"],
            education=row["education"],
            current_role=row["current_role"],
            experience_level=row["experience_level"],
            skills=json.loads(row["skills_json"] or "[]"),
            goals=row["goals"],
            interests=row["interests"],
            hours_per_week=int(row["hours_per_week"]),
            language=row["language"],
            country=row["country"],
            onboarded=bool(row["onboarded"]),
            updated_at=row["updated_at"],
        )

    def save(self, user_id: str, **fields) -> Profile:
        """Upsert the profile; only the provided fields change."""
        current = self.get(user_id) or Profile(user_id=user_id)
        data = current.to_dict()
        for key, value in fields.items():
            if value is None or key not in data:
                continue
            if key == "skills":
                data["skills"] = _clean_skills(value)
            elif key == "hours_per_week":
                data["hours_per_week"] = max(HOURS_MIN, min(HOURS_MAX, int(value)))
            elif key == "goals":
                data["goals"] = str(value)[:GOALS_MAX]
            elif key == "language":
                data["language"] = str(value) if value in LANGUAGES else "en"
            elif key == "onboarded":
                data["onboarded"] = bool(value)
            else:
                data[key] = str(value)
        data["user_id"] = user_id
        data["updated_at"] = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO profiles (user_id, persona, education, current_role, experience_level, "  # noqa: E501
                "skills_json, goals, interests, hours_per_week, language, country, onboarded, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) "
                "DO UPDATE SET persona=excluded.persona, education=excluded.education, "
                "current_role=excluded.current_role, experience_level=excluded.experience_level, "
                "skills_json=excluded.skills_json, goals=excluded.goals, interests=excluded.interests, "  # noqa: E501
                "hours_per_week=excluded.hours_per_week, language=excluded.language, "
                "country=excluded.country, onboarded=excluded.onboarded, updated_at=excluded.updated_at",  # noqa: E501
                (
                    user_id,
                    data["persona"],
                    data["education"],
                    data["current_role"],
                    data["experience_level"],
                    json.dumps(data["skills"]),
                    data["goals"],
                    data["interests"],
                    int(data["hours_per_week"]),
                    data["language"],
                    data["country"],
                    1 if data["onboarded"] else 0,
                    data["updated_at"],
                ),
            )
        return self.get(user_id)  # type: ignore[return-value]

    def delete(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))

    def options(self) -> dict:
        return {
            "personas": list(PERSONAS),
            "education_levels": list(EDUCATION_LEVELS),
            "experience_levels": list(EXPERIENCE_LEVELS),
            "hours_per_week_range": [HOURS_MIN, HOURS_MAX],
            "languages": list(LANGUAGES),
        }

    # -------------------------------------------------------------- targets
    def target(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM targets WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        from career_guidance.taxonomy import load_taxonomy

        occupation = load_taxonomy().get(row["career_id"])
        return {
            "career_id": row["career_id"],
            "title": occupation.title if occupation else row["career_id"],
            "set_at": row["set_at"],
        }

    def set_target(self, user_id: str, career_id: str) -> dict:
        from career_guidance.taxonomy import load_taxonomy

        occupation = load_taxonomy().get(career_id)
        if occupation is None:
            raise KeyError(career_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO targets (user_id, career_id, set_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET career_id=excluded.career_id, set_at=excluded.set_at",  # noqa: E501
                (user_id, career_id, _now()),
            )
        return {"career_id": career_id, "title": occupation.title, "set_at": _now()}

    def clear_target(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM targets WHERE user_id = ?", (user_id,))


# Imported late to avoid a cycle with profile.py at module import time.
from career_guidance.profile import EXPERIENCE_LEVELS  # noqa: E402


def _clean_skills(value) -> list[str]:
    if isinstance(value, str):
        from career_guidance.taxonomy import extract_skills

        return extract_skills(value)
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for term in value:
            text = str(term).strip().lower()
            if text and text not in out:
                out.append(text)
        return out[:60]
    return []
