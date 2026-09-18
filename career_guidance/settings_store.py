"""Application settings, scoring weights, feature flags, announcements.

Everything here is **admin editable at runtime** and stored in ``app_settings``
so tuning the matcher or flipping a module on/off needs no redeploy. Values fall
back to the defaults declared in :data:`DEFAULTS`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from career_guidance.migrations import migrate

# Keys are dotted so the console can group them. ``None`` means "unset".
DEFAULTS: dict[str, Any] = {
    # matcher v2 weights (must sum to ~1.0)
    "scoring.w_skills": 0.55,
    "scoring.w_interests": 0.30,
    "scoring.w_job_zone": 0.15,
    "scoring.threshold_strong": 4,  # self-rating >= strong
    "scoring.threshold_weak": 2,  # self-rating >= weak
    "scoring.readiness_target": 80,  # % readiness considered "ready"
    # feature flags
    "flags.maintenance_mode": False,
    "flags.public_app": False,
    "flags.module.discover": True,
    "flags.module.plan": True,
    "flags.module.learn": True,
    "flags.module.resume": True,
    "flags.module.jobfit": True,
    "flags.module.interview": True,
    "flags.module.compare": True,
    "flags.module.transitions": True,
    "flags.module.reports": True,
    "flags.module.gamification": True,
    "flags.demo_mode": False,
    "flags.ai_enabled": False,  # no LLM keys in production; admin may flip
    # roadmap defaults
    "roadmap.default_hours_per_week": 6,
    "roadmap.min_weeks": 1,
    "roadmap.max_weeks": 26,
    # market seed provenance label
    "market.seed_label": "Source: curated, updated 2026-09",
    "market.live_provider": "",  # e.g. "adzuna" when a free key is configured
}

_MUTABLE_PREFIXES = ("scoring.", "flags.", "roadmap.", "market.", "templates.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SettingsStore:
    """Key/value store for runtime-tunable application settings."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ #
    def overrides(self) -> dict[str, Any]:
        """Only the values an admin has explicitly set."""
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                out[row["key"]] = row["value"]
        return out

    def all(self) -> dict[str, Any]:
        """Defaults merged with admin overrides."""
        return {**DEFAULTS, **self.overrides()}

    def get(self, key: str, default: Any = None) -> Any:
        return self.all().get(key, default if default is not None else DEFAULTS.get(key))

    def set_many(self, values: dict[str, Any], actor: str = "admin") -> dict[str, Any]:
        """Persist settings; unknown keys are rejected (422-worthy client error)."""
        unknown = [k for k in values if not k.startswith(_MUTABLE_PREFIXES)]
        if unknown:
            raise KeyError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
        # Mirror the short feature-flag spelling onto the canonical module key so
        # both the old and new admin screens switch the same module.
        for key, value in list(values.items()):
            if key.startswith("flags.") and not key.startswith("flags.module."):
                module = key[len("flags.") :]
                canonical = f"flags.module.{module}"
                if canonical in DEFAULTS and canonical not in values:
                    values[canonical] = value
        with self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO app_settings (key, value, updated_at, updated_by) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                    "value=excluded.value, updated_at=excluded.updated_at, "
                    "updated_by=excluded.updated_by",
                    (key, json.dumps(value), _now(), actor),
                )
        return self.all()

    def reset(self, keys: list[str] | None = None, actor: str = "admin") -> dict[str, Any]:
        with self._connect() as conn:
            if keys:
                conn.executemany("DELETE FROM app_settings WHERE key = ?", [(k,) for k in keys])
            else:
                conn.execute("DELETE FROM app_settings")
        return self.all()

    # ------------------------------------------------------------------ #
    def scoring(self) -> dict[str, Any]:
        """Matcher weights, normalised to sum to 1.0."""
        values = self.all()
        weights = {
            "skills": float(values["scoring.w_skills"]),
            "interests": float(values["scoring.w_interests"]),
            "job_zone": float(values["scoring.w_job_zone"]),
        }
        total = sum(weights.values()) or 1.0
        return {k: round(v / total, 4) for k, v in weights.items()}

    def template_overrides(self) -> dict[str, dict[str, str]]:
        """Admin edits to the explanation templates, keyed by locale."""
        raw = self.get("templates.overrides", {}) or {}
        return {
            str(locale): {str(k): str(v) for k, v in (values or {}).items()}
            for locale, values in raw.items()
        }  # noqa: E501

    def feature_flags(self) -> dict[str, Any]:
        return {k[len("flags.") :]: v for k, v in self.all().items() if k.startswith("flags.")}

    def set_feature_flag(self, name: str, value: Any, actor: str = "admin") -> dict[str, Any]:
        return self.set_many({f"flags.{name}": value}, actor).get(f"flags.{name}", value)

    def module_enabled(self, module: str) -> bool:
        """Feature flag for a screen.

        The console may write either ``flags.module.x`` (canonical) or the short
        ``flags.x``; both are honoured so a toggle in Settings never silently
        does nothing.
        """
        overrides = self.overrides()
        for key in (f"flags.module.{module}", f"flags.{module}"):
            if key in overrides:
                return bool(overrides[key])
        return bool(DEFAULTS.get(f"flags.module.{module}", True))

    # ------------------------------------------------------------------ #
    def record_event(self, kind: str, detail: str = "") -> None:
        """System events: cold starts, maintenance toggles, import jobs."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO system_events (created_at, kind, detail) VALUES (?, ?, ?)",
                (_now(), kind, detail[:500]),
            )

    def record_error(self, path: str, detail: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO error_events (created_at, path, detail) VALUES (?, ?, ?)",
                (_now(), path[:200], detail[:1000]),
            )

    def record_tool(self, tool: str, user_id: str | None, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tool_events (created_at, user_id, tool, detail) VALUES (?, ?, ?, ?)",
                (_now(), user_id, tool[:60], detail[:300]),
            )

    def events(self, kind: str, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM system_events WHERE kind = ? ORDER BY id DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        """Aggregate counters used by the admin overview."""
        week_ago = (datetime.now(timezone.utc).replace(microsecond=0)).isoformat()[:10]
        with self._connect() as conn:

            def count(sql: str, params: tuple = ()) -> int:
                return int(conn.execute(sql, params).fetchone()[0])

            return {
                "tools": count("SELECT COUNT(*) FROM tool_events"),
                "tools_7d": count(
                    "SELECT COUNT(*) FROM tool_events WHERE substr(created_at, 1, 10) >= date(?, '-7 day')",  # noqa: E501
                    (week_ago,),
                ),
                "errors": count("SELECT COUNT(*) FROM error_events"),
                "cold_starts": count("SELECT COUNT(*) FROM system_events WHERE kind = 'startup'"),
            }

    def tool_usage(self, limit: int = 20) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tool, COUNT(*) n FROM tool_events GROUP BY tool ORDER BY n DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(r["tool"], int(r["n"])) for r in rows]

    # ------------------------------------------------------------------ #
    def announcements(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM announcements"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY pinned DESC, id DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def add_announcement(
        self, title: str, body: str, level: str = "info", pinned: bool = False, actor: str = ""
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO announcements (title, body, level, active, pinned, created_at, "
                "created_by) VALUES (?, ?, ?, 1, ?, ?, ?)",
                (title, body, level, int(pinned), _now(), actor),
            )
            return int(cur.lastrowid or 0)

    def update_announcement(self, aid: int, **fields: Any) -> None:
        allowed = {"title", "body", "level", "active", "pinned"}
        sets, values = [], []
        for key, value in fields.items():
            if key in allowed and value is not None:
                sets.append(f"{key} = ?")
                values.append(int(value) if isinstance(value, bool) else value)
        if not sets:
            return
        values.append(aid)
        with self._connect() as conn:
            conn.execute(f"UPDATE announcements SET {', '.join(sets)} WHERE id = ?", values)

    def delete_announcement(self, aid: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM announcements WHERE id = ?", (aid,))

    # ------------------------------------------------------------------ #
    def jobs(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(r)
                for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
            ]

    def start_job(self, kind: str, detail: str = "") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (kind, status, created_at, detail) VALUES (?, 'running', ?, ?)",
                (kind, _now(), detail[:300]),
            )
            return int(cur.lastrowid or 0)

    def finish_job(self, job_id: int, status: str = "done", detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, detail = ? WHERE id = ?",
                (status, _now(), detail[:300], job_id),
            )
