"""Account (``/me``) and admin (``/admin``) routes."""

from __future__ import annotations

import os
import platform
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from career_guidance import __version__
from career_guidance.analytics import summarize
from career_guidance.learning import all_skills, resources_for, set_overrides
from career_guidance.storage import Database
from career_guidance.taxonomy import load_taxonomy
from career_guidance.users import User, UserStore

_STARTED = time.time()


class ProgressBody(BaseModel):
    skill: str
    done: bool = True


class PrefsBody(BaseModel):
    prefs: dict


class FeedbackBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""
    run_id: int | None = None
    career_title: str = ""


class RoleBody(BaseModel):
    role: str = Field(pattern="^(user|admin)$")


class DisabledBody(BaseModel):
    disabled: bool


class StatusBody(BaseModel):
    status: str = Field(pattern="^(new|reviewed|resolved)$")


class ResourceItem(BaseModel):
    title: str
    url: str
    provider: str = ""
    free: bool = True


class ResourcesBody(BaseModel):
    resources: list[ResourceItem]


def build_routers(
    store: UserStore, db: Database, current_user, admin_user, optional_user
) -> tuple[APIRouter, APIRouter]:
    me = APIRouter(prefix="/api/v1/me", tags=["account"])
    admin = APIRouter(prefix="/api/v1/admin", tags=["admin"])

    # ------------------------------------------------------------------ me
    @me.get("/runs")
    def my_runs(user: User = Depends(current_user), limit: int = 50) -> dict:  # noqa: B008
        runs = [r for r in db.list_runs(limit=1000) if r.user_id == user.id][:limit]
        return {
            "runs": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "provider": r.provider,
                    "is_demo": r.is_demo,
                    "skills": str(r.profile.get("skills", ""))[:200],
                    "goals": str(r.profile.get("goals", "")),
                    "experience_level": r.profile.get("experience_level", ""),
                    "recommendations": [asdict(x) for x in r.recommendations],
                }
                for r in runs
            ]
        }

    @me.get("/progress")
    def my_progress(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"done": store.progress(user.id)}

    @me.post("/progress")
    def set_progress(body: ProgressBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        store.set_progress(user.id, body.skill, body.done)
        return {"done": store.progress(user.id)}

    @me.put("/prefs")
    def set_prefs(body: PrefsBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        store.set_prefs(user.id, body.prefs)
        return {"ok": True}

    @me.delete("")
    def delete_me(user: User = Depends(current_user)) -> dict:  # noqa: B008
        store.audit(user.email, "self-delete", user.id)
        store.delete_user(user.id)
        return {"deleted": True}

    @me.post("/feedback")
    def feedback(body: FeedbackBody, user: User | None = Depends(optional_user)) -> dict:  # noqa: B008
        fid = store.add_feedback(
            body.rating, body.comment, user.id if user else None, body.run_id, body.career_title
        )
        return {"id": fid}

    # --------------------------------------------------------------- admin
    @admin.get("/overview")
    def overview(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        runs = db.list_runs(limit=5000)
        s = summarize(runs) if runs else None
        return {
            "users": store.count_users(),
            "runs": {
                "total": len(runs),
                "ai": s.ai_runs if s else 0,
                "demo": s.demo_runs if s else 0,
                "per_day": s.runs_per_day[-30:] if s else [],
                "anonymous": sum(1 for r in runs if not r.user_id),
            },
            "top_careers": s.top_careers if s else [],
            "top_missing_skills": s.top_missing_skills if s else [],
            "feedback": store.feedback_stats(),
            "system": {
                "version": __version__,
                "python": platform.python_version(),
                "uptime_s": int(time.time() - _STARTED),
                "ai_mode": bool(os.getenv("OPENAI_API_KEY")),
                "occupations": len(load_taxonomy()),
                "overrides": len(store.resource_overrides()),
            },
        }

    @admin.get("/users")
    def users(q: str = "", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"users": store.list_users(q)}

    @admin.patch("/users/{user_id}/role")
    def set_role(user_id: str, body: RoleBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if user_id == actor.id and body.role != "admin":
            raise HTTPException(400, "You cannot demote yourself.")
        if not store.get(user_id):
            raise HTTPException(404, "User not found.")
        store.set_role(user_id, body.role)
        store.audit(actor.email, f"role:{body.role}", user_id)
        return {"ok": True}

    @admin.patch("/users/{user_id}/disabled")
    def set_disabled(
        user_id: str,
        body: DisabledBody,
        actor: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        if user_id == actor.id:
            raise HTTPException(400, "You cannot disable yourself.")
        store.set_disabled(user_id, body.disabled)
        store.audit(actor.email, "disable" if body.disabled else "enable", user_id)
        return {"ok": True}

    @admin.delete("/users/{user_id}")
    def delete_user(user_id: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        if user_id == actor.id:
            raise HTTPException(400, "You cannot delete yourself.")
        store.delete_user(user_id)
        store.audit(actor.email, "delete-user", user_id)
        return {"ok": True}

    @admin.get("/runs")
    def all_runs(limit: int = 100, _: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {
            "runs": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "provider": r.provider,
                    "user_id": r.user_id,
                    "skills": str(r.profile.get("skills", ""))[:120],
                    "titles": [x.title for x in r.recommendations],
                }
                for r in db.list_runs(limit=limit)
            ]
        }

    @admin.delete("/runs/{run_id}")
    def delete_run(run_id: int, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        db.delete_run(run_id)
        store.audit(actor.email, "delete-run", str(run_id))
        return {"ok": True}

    @admin.get("/feedback")
    def list_feedback(status: str | None = None, _: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"feedback": store.list_feedback(status)}

    @admin.patch("/feedback/{fid}")
    def feedback_status(fid: int, body: StatusBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        store.set_feedback_status(fid, body.status)
        store.audit(actor.email, f"feedback:{body.status}", str(fid))
        return {"ok": True}

    @admin.get("/resources")
    def list_resources(q: str = "", _: User = Depends(admin_user)) -> dict:  # noqa: B008
        overrides = store.resource_overrides()
        skills = sorted(set(all_skills()) | set(overrides))
        if q:
            skills = [s for s in skills if q.lower() in s]
        return {
            "skills": [
                {
                    "skill": s,
                    "overridden": s in overrides,
                    "resources": overrides.get(s) or [asdict(r) for r in resources_for(s, 5)],
                }
                for s in skills[:300]
            ]
        }

    @admin.put("/resources/{skill}")
    def put_resources(skill: str, body: ResourcesBody, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        store.set_resources(skill, [r.model_dump() for r in body.resources], actor.email)
        set_overrides(store.resource_overrides())
        store.audit(actor.email, "resources:set", skill)
        return {"ok": True}

    @admin.delete("/resources/{skill}")
    def reset_resources(skill: str, actor: User = Depends(admin_user)) -> dict:  # noqa: B008
        store.delete_resources(skill)
        set_overrides(store.resource_overrides())
        store.audit(actor.email, "resources:reset", skill)
        return {"ok": True}

    @admin.get("/audit")
    def audit(_: User = Depends(admin_user)) -> dict:  # noqa: B008
        return {"log": store.audit_log()}

    return me, admin
