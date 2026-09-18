"""Account (``/me``) routes.

The admin console lives in :mod:`backend.admin_console`; this module only keeps
the endpoints that belong to the signed-in user's own account.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from career_guidance.storage import Database
from career_guidance.users import User, UserStore


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
    tool: str = ""


def build_me_router(store: UserStore, db: Database, current_user) -> APIRouter:
    me = APIRouter(prefix="/api/v1/me", tags=["account"])

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
                    "user_id": r.user_id,
                    "tool": r.profile.get("tool", "recommend"),
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
    def feedback(body: FeedbackBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        fid = store.add_feedback(
            body.rating,
            body.comment,
            user.id,
            body.run_id,
            body.career_title,
            tool=body.tool,
        )
        return {"id": fid}

    return me
