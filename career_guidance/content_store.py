"""Admin-editable content: career overrides, custom careers, learning resources.

The bundled catalog (``data/catalog/occupations.json``) and the curated course
list (``data/learning_resources.yaml``) are read-only defaults. Everything an
admin changes — India salary overrides, Indian job titles, hidden or custom
careers, courses, interview templates — lives in SQLite so the catalog can be
edited without a redeploy.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from career_guidance.migrations import migrate
from career_guidance.models import LearningResource
from career_guidance.taxonomy import Occupation, load_taxonomy

RESOURCE_LEVELS = ("beginner", "intermediate", "advanced")
RESOURCE_LANGUAGES = ("en", "ta", "hi")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ContentStore:
    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------- career overrides
    def career_overrides(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM career_overrides").fetchall()
        return {row["career_id"]: dict(row) for row in rows}

    def hidden_ids(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT career_id FROM career_overrides WHERE hidden = 1"
            ).fetchall()
        return {row["career_id"] for row in rows}

    def update_career(self, career_id: str, **fields) -> None:
        allowed = {
            "hidden",
            "salary_p25",
            "salary_p50",
            "salary_p75",
            "trend",
            "remote",
            "indian_titles",
            "notes",
        }
        data = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not data:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO career_overrides (career_id, updated_at) VALUES (?, ?)",
                (career_id, _now()),
            )
            sets = ", ".join(f"{key} = ?" for key in data)
            values = [int(v) if isinstance(v, bool) else v for v in data.values()]
            conn.execute(
                f"UPDATE career_overrides SET {sets}, updated_at = ? WHERE career_id = ?",
                [*values, _now(), career_id],
            )

    def add_custom_career(
        self,
        career_id: str,
        title: str,
        description: str = "",
        job_zone: int = 3,
        skills: list[str] | None = None,
        knowledge: list[str] | None = None,
        technology: list[str] | None = None,
        holland_code: str = "",
        interests: dict | None = None,
        actor: str = "",
    ) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO custom_careers (id, title, description, job_zone, skills_json, "
                "knowledge_json, technology_json, alt_titles_json, holland_code, interests_json, "
                "related_json, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, '[]', ?, ?)",  # noqa: E501
                (
                    career_id,
                    title,
                    description,
                    int(job_zone),
                    json.dumps(skills or []),
                    json.dumps(knowledge or []),
                    json.dumps(technology or []),
                    holland_code,
                    json.dumps(interests or {}),
                    _now(),
                    actor,
                ),
            )
        return career_id

    def delete_custom_career(self, career_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_careers WHERE id = ?", (career_id,))

    def custom_careers(self) -> list[Occupation]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM custom_careers ORDER BY title").fetchall()
        return [
            Occupation(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                job_zone=int(row["job_zone"]),
                skills=json.loads(row["skills_json"] or "[]"),
                knowledge=json.loads(row["knowledge_json"] or "[]"),
                technology=json.loads(row["technology_json"] or "[]"),
                alt_titles=json.loads(row["alt_titles_json"] or "[]"),
                holland_code=row["holland_code"],
                interests=json.loads(row["interests_json"] or "{}"),
            )
            for row in rows
        ]

    def catalog(self):
        """Taxonomy with custom careers included and hidden ones removed."""
        base = load_taxonomy()
        custom = self.custom_careers()
        hidden = self.hidden_ids()
        if not custom and not hidden:
            return base
        from career_guidance.taxonomy import Taxonomy

        occupations = [o for o in base.occupations if o.id not in hidden]
        occupations.extend(custom)
        return Taxonomy(occupations)

    def import_careers_csv(self, csv_text: str) -> tuple[int, int]:
        """Bulk import: id,title,description,job_zone,skills,knowledge,technology."""
        reader = csv.DictReader(io.StringIO(csv_text))
        imported = skipped = 0
        for row in reader:
            career_id = (row.get("id") or "").strip()
            title = (row.get("title") or "").strip()
            if not career_id or not title:
                skipped += 1
                continue
            try:
                self.add_custom_career(
                    career_id,
                    title,
                    (row.get("description") or "")[:2000],
                    int(row.get("job_zone") or 3),
                    skills=[s.strip() for s in (row.get("skills") or "").split("|") if s.strip()],
                    knowledge=[
                        s.strip() for s in (row.get("knowledge") or "").split("|") if s.strip()
                    ],
                    technology=[
                        s.strip() for s in (row.get("technology") or "").split("|") if s.strip()
                    ],  # noqa: E501
                )
                imported += 1
            except sqlite3.IntegrityError:
                skipped += 1
        return imported, skipped

    def export_careers_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "title", "job_zone", "salary_p25", "salary_p50", "salary_p75", "trend", "remote"]
        )  # noqa: E501
        overrides = self.career_overrides()
        for occupation in self.catalog().occupations:
            row = overrides.get(occupation.id, {})
            writer.writerow(
                [
                    occupation.id,
                    occupation.title,
                    occupation.job_zone,
                    row.get("salary_p25", ""),
                    row.get("salary_p50", ""),
                    row.get("salary_p75", ""),
                    row.get("trend", ""),
                    row.get("remote", ""),
                ]
            )
        return buffer.getvalue()

    # --------------------------------------------------- learning resources
    def seed_resources(self, resources: dict[str, list[dict]]) -> int:
        """Migrate the curated YAML into the DB on first run (idempotent)."""
        inserted = 0
        with self._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) n FROM resources").fetchone()["n"]
            if existing:
                return 0
            for skill, items in resources.items():
                for item in items:
                    conn.execute(
                        "INSERT OR IGNORE INTO resources (skill, title, url, provider, level, "
                        "language, free, duration_minutes, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                        (
                            skill,
                            item.get("title", ""),
                            item.get("url", ""),
                            item.get("provider", ""),
                            item.get("level", "beginner"),
                            item.get("language", "en"),
                            1 if item.get("free", True) else 0,
                            int(item.get("duration_minutes", 0)),
                            _now(),
                        ),
                    )
                    inserted += 1
        return inserted

    def resources(
        self,
        q: str = "",
        skill: str = "",
        language: str = "",
        provider: str = "",
        level: str = "",
        free: bool | None = None,
        limit: int = 200,
        offset: int = 0,
        include_dead: bool = False,
    ) -> list[dict]:
        sql = "SELECT * FROM resources WHERE 1=1"
        params: list = []
        if q:
            sql += " AND (title LIKE ? OR skill LIKE ? OR provider LIKE ?)"
            params += [f"%{q}%"] * 3
        if skill:
            sql += " AND skill = ?"
            params.append(skill)
        if language:
            sql += " AND language = ?"
            params.append(language)
        if provider:
            sql += " AND provider LIKE ?"
            params.append(f"%{provider}%")
        if level:
            sql += " AND level = ?"
            params.append(level)
        if free is not None:
            sql += " AND free = ?"
            params.append(1 if free else 0)
        if not include_dead:
            sql += " AND status != 'dead'"
        sql += " ORDER BY uses DESC, skill, title LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._resource_dict(row) for row in rows]

    @staticmethod
    def _resource_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "skill": row["skill"],
            "title": row["title"],
            "url": row["url"],
            "provider": row["provider"],
            "level": row["level"],
            "language": row["language"],
            "free": bool(row["free"]),
            "duration_minutes": int(row["duration_minutes"]),
            "status": row["status"],
            "last_checked": row["last_checked"],
            "uses": int(row["uses"]),
        }

    def resource(self, resource_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        return self._resource_dict(row) if row else None

    def filters(self) -> dict:
        with self._connect() as conn:
            skills = [
                r["skill"]
                for r in conn.execute("SELECT DISTINCT skill FROM resources ORDER BY skill")
            ]  # noqa: E501
            providers = [
                r["provider"]
                for r in conn.execute(
                    "SELECT DISTINCT provider FROM resources WHERE provider != '' ORDER BY provider"
                )
            ]  # noqa: E501
            languages = [
                r["language"]
                for r in conn.execute("SELECT DISTINCT language FROM resources ORDER BY language")
            ]  # noqa: E501
            levels = [
                r["level"]
                for r in conn.execute("SELECT DISTINCT level FROM resources ORDER BY level")
            ]  # noqa: E501
        return {"skills": skills, "providers": providers, "languages": languages, "levels": levels}

    def upsert_resource(
        self, payload: dict, resource_id: int | None = None, actor: str = ""
    ) -> int:
        fields = {
            "skill": str(payload.get("skill", "")).strip(),
            "title": str(payload.get("title", "")).strip(),
            "url": str(payload.get("url", "")).strip(),
            "provider": str(payload.get("provider", "")).strip(),
            "level": payload.get("level", "beginner")
            if payload.get("level") in RESOURCE_LEVELS
            else "beginner",  # noqa: E501
            "language": payload.get("language", "en")
            if payload.get("language") in RESOURCE_LANGUAGES
            else "en",  # noqa: E501
            "free": 1 if payload.get("free", True) else 0,
            "duration_minutes": int(payload.get("duration_minutes", 0) or 0),
        }
        if not fields["skill"] or not fields["title"] or not fields["url"]:
            raise ValueError("skill, title and url are required")
        with self._connect() as conn:
            if resource_id is None:
                cur = conn.execute(
                    "INSERT INTO resources (skill, title, url, provider, level, language, free, "
                    "duration_minutes, status, created_at, updated_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                    (*fields.values(), _now(), actor),
                )
                return int(cur.lastrowid or 0)
            conn.execute(
                "UPDATE resources SET skill=?, title=?, url=?, provider=?, level=?, language=?, "
                "free=?, duration_minutes=?, updated_by=? WHERE id=?",
                (*fields.values(), actor, resource_id),
            )
            return resource_id

    def delete_resource(self, resource_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))

    def bump_uses(self, resource_ids: list[int]) -> None:
        if not resource_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE resources SET uses = uses + 1 WHERE id = ?", [(i,) for i in resource_ids]
            )

    def mark_link_status(self, resource_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE resources SET status = ?, last_checked = ? WHERE id = ?",
                (status, _now(), resource_id),
            )

    def resources_for_skill(self, skill: str, limit: int = 2) -> list[LearningResource]:
        """DB-first lookup used by the roadmap (YAML stays as the fallback)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM resources WHERE skill = ? AND status != 'dead' ORDER BY uses DESC, id "  # noqa: E501
                "LIMIT ?",
                (skill.strip().lower(), limit),
            ).fetchall()
        if rows:
            self.bump_uses([int(r["id"]) for r in rows])
        return [
            LearningResource(
                skill=row["skill"],
                title=row["title"],
                url=row["url"],
                provider=row["provider"],
                free=bool(row["free"]),
            )
            for row in rows
        ]

    def export_resources_yaml(self) -> str:
        import yaml

        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM resources ORDER BY skill, title").fetchall()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["skill"], []).append(
                {
                    "title": row["title"],
                    "url": row["url"],
                    "provider": row["provider"],
                    "level": row["level"],
                    "language": row["language"],
                    "free": bool(row["free"]),
                    "duration_minutes": int(row["duration_minutes"]),
                }
            )
        header = (
            "# Exported from the Career Guidance AI admin console "
            f"({_now()}). The YAML in data/learning_resources.yaml is the seed;\n"
            "# this export is the current database state.\n"
        )
        return header + yaml.safe_dump(grouped, allow_unicode=True, sort_keys=True)

    # ------------------------------------------------- interview templates
    def interview_templates(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM interview_templates"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY kind, id"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql)]

    def add_interview_template(
        self, kind: str, template: str, skill: str = "", career_id: str = ""
    ) -> int:  # noqa: E501
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO interview_templates (kind, template, skill, career_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    kind if kind in {"behavioural", "technical"} else "behavioural",
                    template,
                    skill,
                    career_id,
                    _now(),
                ),  # noqa: E501
            )
            return int(cur.lastrowid or 0)

    def delete_interview_template(self, template_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM interview_templates WHERE id = ?", (template_id,))

    # --------------------------------------------------------- chat: unused
    @staticmethod
    def as_learning_resource(row: dict) -> dict:
        return asdict(
            LearningResource(
                skill=row["skill"],
                title=row["title"],
                url=row["url"],
                provider=row["provider"],
                free=row["free"],
            )
        )
