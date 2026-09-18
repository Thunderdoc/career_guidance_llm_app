"""Admin console API (S4) — every screen in ``/admin`` is backed by these routes.

Conventions
-----------
* every route requires an **admin** session (401 anonymous, 403 non-admin);
* every write records an ``audit_log`` row (actor, action, target, detail);
* payload shapes match ``frontend/lib/api.ts`` exactly — the console renders
  whatever the server returns, with no client-side mock data.
"""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from career_guidance import __version__, migrations, riasec
from career_guidance.analytics import summarize
from career_guidance.content_store import ContentStore
from career_guidance.explanations import get_explanations
from career_guidance.gamification import GamificationStore
from career_guidance.journey import JourneyStore
from career_guidance.profiles import ProfileStore
from career_guidance.settings_store import SettingsStore
from career_guidance.synonyms import SynonymStore, load_normalizer
from career_guidance.translations import locale_catalog
from career_guidance.users import User

_STARTED = time.time()
LINK_CHECK_TIMEOUT = 6
LINK_CHECK_LIMIT = 60
ENV_KEYS = (
    "APP_ENV",
    "LOG_LEVEL",
    "DATABASE_PATH",
    "PUBLIC_APP",
    "PUBLIC_URL",
    "SESSION_SECRET",
    "ADMIN_EMAILS",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "FIREBASE_PROJECT_ID",
    "NEXT_PUBLIC_FIREBASE_API_KEY",
    "OPENAI_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
)


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class RoleBody(BaseModel):
    role: str = Field(pattern="^(user|admin)$")


class DisabledBody(BaseModel):
    disabled: bool


class FlagBody(BaseModel):
    flagged: bool


class StatusBody(BaseModel):
    status: str = "new"
    note: str | None = None


class CareerPatchBody(BaseModel):
    hidden: bool | None = None
    salary_p25: int | None = None
    salary_p50: int | None = None
    salary_p75: int | None = None
    trend: str | None = None
    remote: bool | None = None
    indian_titles: str | None = None
    notes: str | None = None


class CustomCareerBody(BaseModel):
    id: str
    title: str
    description: str = ""
    job_zone: int = Field(default=3, ge=1, le=5)
    skills: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    technology: list[str] = Field(default_factory=list)


class SynonymBody(BaseModel):
    alias: str
    canonical: str
    locale: str = "en"


class MapBody(BaseModel):
    term: str
    canonical: str


class DismissBody(BaseModel):
    term: str


class ResourceBody(BaseModel):
    skill: str
    title: str
    url: str
    provider: str = ""
    level: str = "beginner"
    language: str = "en"
    free: bool = True
    duration_minutes: int = 0


class AssessmentItemBody(BaseModel):
    id: str
    dim: str
    text: str
    weight: float = 1.0
    active: bool = True


class WeightsBody(BaseModel):
    weights: dict[str, float]


class SettingsBody(BaseModel):
    values: dict


class TemplatesBody(BaseModel):
    locale: str = "en"
    templates: dict[str, str]


class InterviewTemplateBody(BaseModel):
    kind: str = "behavioural"
    template: str
    skill: str = ""
    career_id: str = ""


class AnnouncementBody(BaseModel):
    title: str
    body: str = ""
    level: str = "info"
    pinned: bool = False
    active: bool = True


class ResourceListBody(BaseModel):
    resources: list[dict]


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def build_router(settings, users, db, admin_user) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

    content = ContentStore(settings.database_path)
    settings_store = SettingsStore(settings.database_path)
    gamification = GamificationStore(settings.database_path)
    profiles = ProfileStore(settings.database_path)
    journey = JourneyStore(settings.database_path)
    synonym_store = SynonymStore(settings.database_path)
    explanations = get_explanations()
    db_path = Path(settings.database_path)

    def catalog():
        return content.catalog()

    def seed_resources_if_needed() -> None:
        from career_guidance.learning import load_resources_yaml

        content.seed_resources(load_resources_yaml())

    seed_resources_if_needed()

    # ------------------------------------------------------------ overview
    @router.get("/overview")
    def overview(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        runs = db.list_runs(limit=5000)
        stats = summarize(runs) if runs else None
        counts = users.count_users()
        feedback = users.feedback_stats()
        error_events = settings_store.events("error", limit=10)
        cold_starts = settings_store.events("cold_start", limit=200)
        return {
            "users": counts,
            "runs": {
                "total": len(runs),
                "ai": stats.ai_runs if stats else 0,
                "offline": (stats.demo_runs if stats else 0),
                "demo": stats.demo_runs if stats else 0,
                "anonymous": sum(1 for r in runs if not r.user_id),
                "per_day": stats.runs_per_day[-30:] if stats else [],
            },
            "tools": settings_store.tool_usage(limit=20),
            "top_careers": stats.top_careers if stats else [],
            "top_requested_skills": stats.top_skills if stats else [],
            "top_missing_skills": stats.top_missing_skills if stats else [],
            "averages": {
                "match": round(
                    sum(rec.match_score * 100 for run in runs for rec in run.recommendations)
                    / max(1, sum(len(run.recommendations) for run in runs)),
                    1,
                ),
                "readiness": round(
                    sum(float(run.profile.get("readiness", 0) or 0) for run in runs)
                    / max(1, len(runs)),
                    1,
                ),
            },
            "feedback": feedback,
            "errors": {
                "count": len(settings_store.events("error", limit=1000)),
                "cold_starts": len(cold_starts),
                "recent": error_events,
            },
            "system": {
                "version": __version__,
                "python": platform.python_version(),
                "uptime_s": int(time.time() - _STARTED),
                "ai_mode": bool(os.getenv("OPENAI_API_KEY")),
                "occupations": len(catalog()),
                "overrides": len(content.career_overrides()),
                "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
                "disk_free_bytes": shutil.disk_usage(
                    db_path.parent if db_path.parent.exists() else Path(".")
                ).free,  # noqa: E501
                "firebase": bool(os.getenv("FIREBASE_PROJECT_ID")),
                "smtp": bool(os.getenv("SMTP_HOST")),
            },
        }

    # --------------------------------------------------------------- users
    @router.get("/users")
    def list_users(
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = 0,
        _: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        rows = users.list_users(q)
        runs = db.list_runs(limit=5000)
        per_user: dict[str, int] = {}
        for run in runs:
            if run.user_id:
                per_user[run.user_id] = per_user.get(run.user_id, 0) + 1
        for row in rows:
            row["runs"] = per_user.get(row["id"], 0)
        reverse = order != "asc"
        key = (
            sort
            if sort in {"email", "created_at", "last_login_at", "role", "runs"}
            else "created_at"
        )
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=reverse)
        return {"users": rows[offset : offset + limit], "total": len(rows)}

    @router.get("/users.csv")
    def users_csv(_: User = Depends(admin_user)):  # noqa: B008
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "email", "name", "provider", "role", "created_at", "last_login_at", "disabled"]
        )  # noqa: E501
        for row in users.list_users():
            writer.writerow(
                [
                    row["id"],
                    row["email"],
                    row["name"],
                    row["provider"],
                    row["role"],
                    row["created_at"],
                    row["last_login_at"],
                    row["disabled"],
                ]
            )
        return PlainTextResponse(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users.csv"},
        )

    @router.get("/users/{user_id}")
    def user_detail(user_id: str, _: User = Depends(admin_user)) -> dict:  # noqa: B008
        user = users.get(user_id)
        if user is None:
            raise HTTPException(404, "User not found.")
        runs = [r for r in db.list_runs(limit=2000) if r.user_id == user_id]
        profile = profiles.get(user_id)  # noqa: E501
        return {
            "user": {**user.public(), "runs": len(runs)},
            "runs": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "provider": r.provider,
                    "is_demo": r.is_demo,
                    "user_id": r.user_id,
                    "skills": str(r.profile.get("skills", ""))[:120],
                    "goals": str(r.profile.get("goals", "")),
                    "experience_level": r.profile.get("experience_level", ""),
                    "job_zone_fit": float(r.profile.get("job_zone_fit", 0) or 0),
                    "titles": [x.title for x in r.recommendations],
                    "flagged": bool(r.profile.get("flagged", 0)),
                    "profile": r.profile,
                    "tool": r.profile.get("tool", "recommend"),
                    "email": user.email,
                    "recommendations": [asdict(x) for x in r.recommendations],
                }
                for r in runs[:50]
            ],
            "dashboard": {
                "profile": profile.to_dict() if profile else None,
                "target": profiles.target(user_id),
                "readiness": None,
                "xp": gamification.status(user_id),
                "plan": journey.latest_plan(user_id),
                "assessments": riasec.AssessmentStore(settings.database_path).history(
                    user_id, limit=5
                ),
            },
        }

    @router.patch("/users/{user_id}/role")
    def set_role(user_id: str, body: RoleBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if user_id == actor.id and body.role != "admin":
            raise HTTPException(400, "You cannot demote yourself.")
        if users.get(user_id) is None:
            raise HTTPException(404, "User not found.")
        users.set_role(user_id, body.role)
        users.audit(actor.email, f"role:{body.role}", user_id)
        return {"ok": True}

    @router.patch("/users/{user_id}/disabled")
    def set_disabled(user_id: str, body: DisabledBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if user_id == actor.id:
            raise HTTPException(400, "You cannot disable yourself.")
        if users.get(user_id) is None:
            raise HTTPException(404, "User not found.")
        users.set_disabled(user_id, body.disabled)
        users.audit(actor.email, "disable" if body.disabled else "enable", user_id)
        return {"ok": True}

    @router.delete("/users/{user_id}")
    def delete_user(user_id: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if user_id == actor.id:
            raise HTTPException(400, "You cannot delete yourself.")
        if users.get(user_id) is None:
            raise HTTPException(404, "User not found.")
        users.delete_user(user_id)
        journey.purge_user(user_id)
        profiles.delete(user_id)
        users.audit(actor.email, "delete-user", user_id)
        return {"ok": True, "deleted": True}

    # ---------------------------------------------------------------- runs
    @router.get("/runs")
    def list_runs(
        tool: str = "",
        flagged: bool | None = None,
        q: str = "",
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = 0,
        _: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        rows = db.list_runs(limit=5000)
        emails = {u["id"]: u["email"] for u in users.list_users()}
        payload = []
        for run in rows:
            body = _run_row(run, emails)
            if tool and body["tool"] != tool:
                continue
            if flagged is not None and body["flagged"] != flagged:
                continue
            if q and q.lower() not in json.dumps(body, default=str).lower():
                continue
            payload.append(body)
        return {"runs": payload[offset : offset + limit], "total": len(payload)}

    @router.get("/runs.{fmt}")
    def export_runs(fmt: str, actor: User = Depends(admin_user)):  # noqa: B008
        rows = db.list_runs(limit=5000)
        if fmt == "json":
            body = json.dumps(
                [
                    {
                        "id": r.id,
                        "created_at": r.created_at,
                        "provider": r.provider,
                        "user_id": r.user_id,
                        "profile": r.profile,
                        "recommendations": [asdict(x) for x in r.recommendations],
                    }
                    for r in rows
                ],
                indent=2,
            )
            return PlainTextResponse(
                body,
                media_type="application/json",
                headers={"Content-Disposition": "attachment; filename=runs.json"},
            )
        if fmt != "csv":
            raise HTTPException(404, "Unknown export format.")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "created_at", "provider", "is_demo", "user_id", "tool", "skills", "top_title"]
        )  # noqa: E501
        for run in rows:
            writer.writerow(
                [
                    run.id,
                    run.created_at,
                    run.provider,
                    int(run.is_demo),
                    run.user_id or "",
                    run.profile.get("tool", "recommend"),
                    str(run.profile.get("skills", ""))[:200],
                    run.recommendations[0].title if run.recommendations else "",
                ]
            )
        users.audit(actor.email, "runs:export", "csv")
        return PlainTextResponse(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=runs.csv"},
        )

    @router.patch("/runs/{run_id}/flag")
    def flag_run(run_id: int, body: FlagBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        run = next((r for r in db.list_runs(limit=5000) if r.id == run_id), None)
        if run is None:
            raise HTTPException(404, "Run not found.")
        with db._connect() as conn:  # noqa: SLF001 - admin-only write
            conn.execute(
                "UPDATE recommendation_runs SET flagged = ? WHERE id = ?",
                (1 if body.flagged else 0, run_id),
            )
        users.audit(actor.email, "run:flag" if body.flagged else "run:unflag", str(run_id))
        return {"ok": True, "flagged": body.flagged}

    @router.delete("/runs/{run_id}")
    def delete_run(run_id: int, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        db.delete_run(run_id)
        users.audit(actor.email, "delete-run", str(run_id))
        return {"ok": True}

    # ------------------------------------------------------------- careers
    @router.get("/careers")
    def list_careers(
        q: str = "",
        family: str = "",
        job_zone: int | None = None,
        limit: int = Query(default=50, ge=1, le=300),
        offset: int = 0,
        _: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        taxonomy = catalog()
        overrides = content.career_overrides()
        custom_ids = {o.id for o in content.custom_careers()}
        from career_guidance.market_seed import build_adapter

        adapter = build_adapter()
        rows = []
        for occupation in taxonomy.occupations:
            override = overrides.get(occupation.id, {})
            found = adapter.seed.family_for(occupation)
            occupation_family = found.id if found else "other"
            if q and q.lower() not in occupation.title.lower():
                continue
            if family and occupation_family != family:
                continue
            if job_zone and occupation.job_zone != job_zone:
                continue
            snapshot = adapter.snapshot(occupation, "in")
            rows.append(
                {
                    "id": occupation.id,
                    "title": occupation.title,
                    "job_zone": occupation.job_zone,
                    "hidden": bool(override.get("hidden")),
                    "custom": occupation.id in custom_ids,
                    "family": occupation_family,
                    "salary_p25": snapshot.salary_p25,
                    "salary_p50": snapshot.salary_p50,
                    "salary_p75": snapshot.salary_p75,
                    "trend": override.get("trend") or adapter.seed.trend(occupation),
                    "remote": adapter.seed.remote_friendly(occupation),
                    "indian_titles": override.get("indian_titles", "")
                    or ", ".join(adapter.seed.indian_titles(occupation)),
                    "source": snapshot.source,
                }
            )
        rows.sort(key=lambda r: r["title"])
        return {"careers": rows[offset : offset + limit], "total": len(rows)}

    @router.patch("/careers/{career_id}")
    def patch_career(
        career_id: str,
        body: CareerPatchBody,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        if catalog().get(career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        content.update_career(career_id, **body.model_dump(exclude_none=True))
        users.audit(actor.email, "career:update", career_id)
        return {"ok": True}

    @router.post("/careers")
    def create_career(body: CustomCareerBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if catalog().get(body.id) is not None:
            raise HTTPException(409, "That career id already exists.")
        content.add_custom_career(
            body.id,
            body.title,
            body.description,
            body.job_zone,
            body.skills,
            body.knowledge,
            body.technology,
            actor=actor.email,
        )
        users.audit(actor.email, "career:create", body.id)
        return {"id": body.id}

    @router.delete("/careers/{career_id}")
    def delete_career(career_id: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        content.delete_custom_career(career_id)
        users.audit(actor.email, "career:delete", career_id)
        return {"ok": True}

    @router.post("/careers/import")
    async def import_careers(
        file: UploadFile | None = File(default=None),  # noqa: B008
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        if file is None:
            raise HTTPException(422, "Attach a CSV file.")
        raw = (await file.read()).decode("utf-8", errors="replace")
        imported, skipped = content.import_careers_csv(raw)
        users.audit(actor.email, "career:import", f"{imported} imported, {skipped} skipped")
        return {"imported": imported, "skipped": skipped}

    @router.get("/careers.csv")
    def export_careers(actor: User = Depends(admin_user)):  # noqa: B008
        users.audit(actor.email, "career:export", "csv")
        return PlainTextResponse(
            content.export_careers_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=careers.csv"},
        )

    # ------------------------------------------------------------ synonyms
    @router.get("/synonyms")
    def list_synonyms(q: str = "", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        normalizer = load_normalizer()
        rows = []
        for alias in sorted(normalizer.known_aliases()):
            canonical = normalizer.normalize(alias) or ""
            if q and q.lower() not in alias.lower() and q.lower() not in canonical.lower():
                continue
            rows.append(
                {"alias": alias, "canonical": canonical, "locale": "file", "source": "file"}
            )
        for row in synonym_store.all(q):
            rows = [r for r in rows if r["alias"] != row["alias"]]
            rows.append(row)
        return {"synonyms": rows[:500]}

    @router.post("/synonyms")
    def add_synonym(body: SynonymBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if not body.alias.strip() or not body.canonical.strip():
            raise HTTPException(422, "alias and canonical are required.")
        synonym_store.upsert(
            body.alias.strip().lower(), body.canonical.strip(), body.locale, actor.email
        )  # noqa: E501
        users.audit(actor.email, "synonym:add", body.alias)
        return {"ok": True}

    @router.delete("/synonyms/{alias}")
    def delete_synonym(alias: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        synonym_store.delete(alias.lower())
        users.audit(actor.email, "synonym:delete", alias)
        return {"ok": True}

    @router.get("/unmatched")
    def unmatched(limit: int = 100, _: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"unmatched": synonym_store.unmatched(limit=limit), "stats": synonym_store.stats()}

    @router.post("/unmatched/map")
    def map_unmatched(body: MapBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        synonym_store.upsert(body.term.strip().lower(), body.canonical.strip(), actor=actor.email)
        synonym_store.map_unmatched(body.term, body.canonical, actor.email)
        users.audit(actor.email, "unmatched:map", f"{body.term} → {body.canonical}")
        return {"ok": True}

    @router.post("/unmatched/dismiss")
    def dismiss_unmatched(body: DismissBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        synonym_store.dismiss_unmatched(body.term)
        users.audit(actor.email, "unmatched:dismiss", body.term)
        return {"ok": True}

    # ------------------------------------------------------- resources CRUD
    @router.get("/resources")
    def list_resources(q: str = "", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        rows = content.resources(q=q, limit=500, include_dead=True)
        for row in rows:
            row["overridden"] = False
        return {"resources": rows}

    @router.post("/resources")
    def create_resource(body: ResourceBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        try:
            resource_id = content.upsert_resource(body.model_dump(), actor=actor.email)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(actor.email, "resource:create", str(resource_id))
        return {"id": resource_id}

    @router.put("/resources/{resource_id}")
    def update_resource(
        resource_id: int,
        body: ResourceBody,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        if content.resource(resource_id) is None:
            raise HTTPException(404, "Resource not found.")
        try:
            content.upsert_resource(body.model_dump(), resource_id=resource_id, actor=actor.email)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(actor.email, "resource:update", str(resource_id))
        return {"id": resource_id}

    @router.delete("/resources/{resource_id}")
    def delete_resource(resource_id: int, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if content.resource(resource_id) is None:
            raise HTTPException(404, "Resource not found.")
        content.delete_resource(resource_id)
        users.audit(actor.email, "resource:delete", str(resource_id))
        return {"ok": True}

    @router.post("/resources/check")
    def check_links(actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        job_id = settings_store.start_job("link-check", "resources")
        rows = content.resources(limit=LINK_CHECK_LIMIT, include_dead=True)
        checked = dead = unknown = 0
        for row in rows:
            status = _head_status(row["url"])
            checked += 1
            if status == "dead":
                dead += 1
                content.mark_link_status(row["id"], "dead")
            elif status == "unknown":
                unknown += 1
                content.mark_link_status(row["id"], "unknown")
            else:
                content.mark_link_status(row["id"], "active")
        settings_store.finish_job(
            job_id, "done", f"checked {checked}, dead {dead}, unknown {unknown}"
        )
        users.audit(actor.email, "resource:check", f"{checked} urls, {dead} dead")
        return {"job_id": job_id, "checked": checked, "dead": dead, "unknown": unknown}

    @router.get("/resources.yaml")
    def export_resources(actor: User = Depends(admin_user)):  # noqa: B008
        users.audit(actor.email, "resource:export", "yaml")
        return PlainTextResponse(
            content.export_resources_yaml(),
            media_type="application/x-yaml",
            headers={"Content-Disposition": "attachment; filename=resources.yaml"},
        )

    # --------------------------------------------------- legacy overrides UI
    @router.get("/resource-overrides")
    def list_resource_overrides(q: str = "", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        overrides = users.resource_overrides()
        from career_guidance.learning import all_skills, resources_for

        skills = sorted(set(all_skills()) | set(overrides))
        if q:
            skills = [s for s in skills if q.lower() in s]
        return {
            "skills": [
                {
                    "skill": skill,
                    "overridden": skill in overrides,
                    "resources": overrides.get(skill)
                    or [asdict(r) for r in resources_for(skill, 5)],
                }
                for skill in skills[:300]
            ]
        }

    @router.put("/resource-overrides/{skill}")
    def put_resource_overrides(
        skill: str,
        body: ResourceListBody,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        from career_guidance.learning import set_overrides

        users.set_resources(skill, body.resources, actor.email)
        set_overrides(users.resource_overrides())
        users.audit(actor.email, "resources:set", skill)
        return {"ok": True}

    @router.delete("/resource-overrides/{skill}")
    def reset_resource_overrides(skill: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        from career_guidance.learning import set_overrides

        users.delete_resources(skill)
        set_overrides(users.resource_overrides())
        users.audit(actor.email, "resources:reset", skill)
        return {"ok": True}

    # --------------------------------------------------- assessment items
    @router.get("/assessment-items")
    def list_assessment_items(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        store = riasec.AssessmentStore(settings.database_path)
        overrides = {row["id"] for row in store.item_overrides()}
        items = []
        for item in store.merged_items("en"):
            items.append(
                {
                    "id": item.id,
                    "dim": item.dim,
                    "text": item.text,
                    "weight": item.weight,
                    "active": item.active,
                    "locale": "en",
                    "overridden": item.id in overrides,
                }
            )
        return {"items": items}

    @router.post("/assessment-items")
    def upsert_assessment_item(
        body: AssessmentItemBody,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        if body.dim.upper() not in riasec.DIMENSION_NAMES:
            raise HTTPException(422, "dim must be one of R, I, A, S, E, C.")
        riasec.AssessmentStore(settings.database_path).upsert_item(
            body.id, body.dim, body.text, body.weight, body.active
        )
        users.audit(actor.email, "assessment-item:upsert", body.id)
        return {"ok": True}

    @router.delete("/assessment-items/{item_id}")
    def delete_assessment_item(item_id: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        riasec.AssessmentStore(settings.database_path).delete_item(item_id)
        users.audit(actor.email, "assessment-item:delete", item_id)
        return {"ok": True}

    # ---------------------------------------------------- weights/settings
    @router.get("/weights")
    def get_weights(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        weights = settings_store.scoring()
        return {
            "weights": {
                "skills": float(weights.get("skills", 0.55)),
                "interests": float(weights.get("interests", 0.30)),
                "job_zone": float(weights.get("job_zone", 0.15)),
            }
        }

    @router.put("/weights")
    def set_weights(body: WeightsBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        values = {
            k: max(0.0, float(v))
            for k, v in body.weights.items()
            if k in {"skills", "interests", "job_zone"}
        }  # noqa: E501
        if not values:
            raise HTTPException(422, "Provide at least one weight (skills, interests, job_zone).")
        if len(values) == 3 and sum(values.values()) <= 0:
            raise HTTPException(422, "Weights cannot all be zero.")
        settings_store.set_many(
            {
                "scoring.w_skills": values.get("skills", settings_store.scoring()["skills"]),
                "scoring.w_interests": values.get(
                    "interests", settings_store.scoring()["interests"]
                ),
                "scoring.w_job_zone": values.get("job_zone", settings_store.scoring()["job_zone"]),
            },
            actor=actor.email,
        )
        users.audit(actor.email, "settings:weights", json.dumps(values))
        return {"weights": settings_store.scoring()}

    @router.get("/settings")
    def get_settings(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"settings": settings_store.all(), "flags": settings_store.feature_flags()}

    @router.put("/settings")
    def set_settings(body: SettingsBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        try:
            updated = settings_store.set_many(body.values, actor=actor.email)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(actor.email, "settings:update", ",".join(sorted(body.values)))
        return {"settings": updated, "flags": settings_store.feature_flags()}

    # ------------------------------------------------------------ templates
    @router.get("/templates")
    def get_templates(locale: str = "en", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        overrides = settings_store.template_overrides()
        templates = explanations.locale_templates(locale)
        templates.update(overrides.get(locale, {}))
        rendered = explanations.preview(locale)
        rendered.update({k: v for k, v in overrides.get(locale, {}).items()})
        return {
            "locale": locale,
            "templates": templates,
            "rendered": rendered,
            "locales": list(explanations.locales),
            "source": explanations.source(),
        }

    @router.put("/templates")
    def set_templates(body: TemplatesBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if body.locale not in explanations.locales:
            raise HTTPException(422, "Unsupported locale.")
        known = set(explanations.keys(body.locale))
        unknown = [k for k in body.templates if k not in known]
        if unknown:
            raise HTTPException(422, f"Unknown template keys: {', '.join(unknown[:5])}")
        overrides = settings_store.template_overrides()
        overrides[body.locale] = {**overrides.get(body.locale, {}), **body.templates}
        settings_store.set_many({"templates.overrides": overrides}, actor=actor.email)
        explanations.set_overrides(overrides)
        users.audit(actor.email, "templates:update", f"{body.locale} ({len(body.templates)} keys)")
        return {"ok": True, "templates": overrides[body.locale]}

    # --------------------------------------------------- interview templates
    @router.get("/interview-templates")
    def list_interview_templates(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"templates": content.interview_templates(active_only=False)}

    @router.post("/interview-templates")
    def add_interview_template(
        body: InterviewTemplateBody,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        if len(body.template.strip()) < 10:
            raise HTTPException(422, "Template is too short.")
        template_id = content.add_interview_template(
            body.kind, body.template.strip(), body.skill, body.career_id
        )
        users.audit(actor.email, "interview-template:add", str(template_id))
        return {"id": template_id}

    @router.delete("/interview-templates/{template_id}")
    def delete_interview_template(template_id: int, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        content.delete_interview_template(template_id)
        users.audit(actor.email, "interview-template:delete", str(template_id))
        return {"ok": True}

    # ------------------------------------------------------------- feedback
    @router.get("/feedback")
    def list_feedback(
        status: str | None = None,
        rating: int | None = None,
        tool: str = "",
        _: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        rows = users.list_feedback(status)
        if rating:
            rows = [r for r in rows if int(r.get("rating", 0)) == rating]
        if tool:
            rows = [r for r in rows if r.get("tool") == tool]
        return {"feedback": rows, "stats": users.feedback_stats()}

    @router.patch("/feedback/{fid}")
    def update_feedback(fid: int, body: StatusBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if body.status not in {"new", "seen", "resolved"}:
            raise HTTPException(422, "status must be new, seen or resolved.")
        users.set_feedback_status(fid, body.status)
        if body.note is not None:
            with users._connect() as conn:  # noqa: SLF001 - admin-only write
                conn.execute(
                    "UPDATE feedback SET note = ?, reviewed_at = ? WHERE id = ?",
                    (
                        body.note[:2000],
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        fid,
                    ),
                )
        users.audit(actor.email, f"feedback:{body.status}", str(fid))
        return {"ok": True}

    # -------------------------------------------------------- announcements
    @router.get("/announcements")
    def list_announcements(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"announcements": settings_store.announcements(active_only=False)}

    @router.post("/announcements")
    def add_announcement(body: AnnouncementBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if len(body.title.strip()) < 3:
            raise HTTPException(422, "Title is too short.")
        announcement_id = settings_store.add_announcement(
            body.title.strip(), body.body, body.level, body.pinned, actor.email
        )
        users.audit(actor.email, "announcement:add", str(announcement_id))
        return {"id": announcement_id}

    @router.patch("/announcements/{announcement_id}")
    def update_announcement(
        announcement_id: int,
        body: dict,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        allowed = {
            k: v for k, v in body.items() if k in {"title", "body", "level", "pinned", "active"}
        }
        if not allowed:
            raise HTTPException(422, "Nothing to update.")
        settings_store.update_announcement(announcement_id, **allowed)
        users.audit(actor.email, "announcement:update", str(announcement_id))
        return {"ok": True}

    @router.delete("/announcements/{announcement_id}")
    def delete_announcement(announcement_id: int, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        settings_store.delete_announcement(announcement_id)
        users.audit(actor.email, "announcement:delete", str(announcement_id))
        return {"ok": True}

    # ------------------------------------------------------------- system
    @router.get("/system")
    def system(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        applied = _applied_map(db_path)
        usage = shutil.disk_usage(db_path.parent if db_path.parent.exists() else Path("."))
        return {
            "health": {
                "status": "ok",
                "db": "ok" if db_path.exists() else "missing",
                "firebase": "configured" if os.getenv("FIREBASE_PROJECT_ID") else "not configured",
                "smtp": "configured" if os.getenv("SMTP_HOST") else "not configured",
                "ai": "on" if os.getenv("OPENAI_API_KEY") else "off (offline templates)",
                "public_app": os.getenv("PUBLIC_APP", "true"),
            },
            "env": [{"name": key, "value": _mask(key, os.getenv(key, ""))} for key in ENV_KEYS],
            "disk": {
                "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
                "free_bytes": usage.free,
                "total_bytes": usage.total,
            },
            "jobs": settings_store.jobs(),
            "migrations": [
                {"version": version, "name": name, "applied_at": applied.get(version, "")}
                for version, name, _ in migrations.MIGRATIONS
            ],
            "translations": locale_catalog(),
            "counts": settings_store.counts(),
        }

    @router.get("/backup.db")
    def backup(actor: User = Depends(admin_user)):  # noqa: B008
        if not db_path.exists():
            raise HTTPException(404, "Database file not found.")
        users.audit(actor.email, "system:backup", db_path.name)
        target = db_path.parent / f"backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
        shutil.copy2(db_path, target)
        return FileResponse(target, media_type="application/octet-stream", filename=target.name)

    @router.post("/restore")
    async def restore(
        file: UploadFile = File(...),  # noqa: B008
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        raw = await file.read()
        if len(raw) < 100 or not raw.startswith(b"SQLite format 3"):
            raise HTTPException(422, "That does not look like a SQLite database.")
        staging = db_path.parent / "restore-staging.db"
        staging.write_bytes(raw)
        try:
            with sqlite3.connect(staging) as conn:
                tables = {
                    r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            if "recommendation_runs" not in tables and "users" not in tables:
                raise HTTPException(422, "Backup does not contain this app's tables.")
            applied = migrations.migrate(staging)
            shutil.copy2(db_path, db_path.parent / "backup-before-restore.db")
            shutil.copy2(staging, db_path)
        finally:
            staging.unlink(missing_ok=True)
        users.audit(actor.email, "system:restore", str(len(raw)))
        return {"restored": True, "migrations": applied}

    @router.post("/cache/clear")
    def clear_cache(actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        cleared = _clear_caches()
        settings_store.record_event("cache_clear", f"{cleared} caches")
        users.audit(actor.email, "system:cache-clear", str(cleared))
        return {"cleared": True, "caches": cleared}

    # -------------------------------------------------------------- audit
    @router.get("/audit")
    def audit(limit: int = 200, action: str = "", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        log = users.audit_log(limit=limit)
        if action:
            log = [row for row in log if action in row.get("action", "")]
        return {"log": log}

    return router


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mask(key: str, value: str) -> str:
    if not value:
        return ""
    if any(token in key for token in ("SECRET", "KEY", "PASSWORD", "TOKEN")):
        return f"••••{value[-4:]}" if len(value) > 4 else "••••"
    return value


def _applied_map(path: Path) -> dict[int, str]:
    try:
        with sqlite3.connect(path) as conn:
            return {
                int(row[0]): str(row[2])
                for row in conn.execute("SELECT version, name, applied_at FROM schema_migrations")
            }
    except sqlite3.Error:
        return {}


def _run_row(run, emails: dict[str, str]) -> dict:
    profile = run.profile or {}
    return {
        "id": run.id,
        "created_at": run.created_at,
        "provider": run.provider,
        "is_demo": run.is_demo,
        "flagged": bool(profile.get("flagged", 0)),
        "user_id": run.user_id,
        "email": emails.get(run.user_id or "", None),
        "tool": profile.get("tool", "recommend"),
        "skills": str(profile.get("skills", ""))[:200],
        "goals": str(profile.get("goals", "")),
        "experience_level": profile.get("experience_level", ""),
        "job_zone_fit": float(profile.get("job_zone_fit", 0) or 0),
        "titles": [x.title for x in run.recommendations],
        "profile": profile,
        "recommendations": [asdict(x) for x in run.recommendations],
    }


def _head_status(url: str) -> str:
    """ok | dead | unknown — never marks a link dead on a transient error."""
    if not url.startswith(("http://", "https://")):
        return "unknown"
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": "career-guidance-link-check"}
    )  # noqa: E501
    try:
        with urllib.request.urlopen(request, timeout=LINK_CHECK_TIMEOUT) as response:  # noqa: S310
            return "ok" if response.status < 400 else "dead"
    except urllib.error.HTTPError as error:
        return "dead" if error.code in {404, 410} else "unknown"
    except Exception:  # noqa: BLE001 - offline sandbox, DNS failure, TLS errors
        return "unknown"


def _clear_caches() -> int:
    from career_guidance import market_seed, matching, riasec, taxonomy

    cleared = 0
    for func in (
        getattr(taxonomy.load_taxonomy, "cache_clear", None),
        getattr(matching.get_matcher, "cache_clear", None),
        getattr(market_seed.load_seed, "cache_clear", None),
        getattr(riasec.load_items, "cache_clear", None),
    ):
        if func:
            func()
            cleared += 1
    from career_guidance.learning import clear_cache as learning_clear

    if learning_clear():
        cleared += 1
    return cleared
