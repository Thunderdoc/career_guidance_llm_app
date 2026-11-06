"""Phase 3 routes: skill verification, public profiles, 90-day plans.

Mounted under ``/api/v1``:

- ``GET  /skills/verify/quizzes`` — quizzes that exist (metadata only)
- ``GET  /skills/verify/{skill}/quiz`` — start an attempt (no answer keys)
- ``POST /skills/verify/{skill}/submit`` — grade an attempt
- ``POST /skills/verify/{skill}/project`` — submit project evidence
- ``GET  /skills/verify/mine`` — my verification states
- ``POST /skills/verify/admin/review`` — admin-only project review
- ``GET  /p/{handle}`` — public profile (opt-in only, minors force-off)
- ``PUT  /me/public-profile`` — handle / opt-in / is_minor controls
- ``POST|GET /plan/90day``, ``PATCH /plan/90day/{id}/tasks``,
  ``GET /plan/90day/export.{md,ics}``

Everything except ``GET /p/{handle}`` requires a signed-in session; the
``current_user`` dependency answers 401 for anonymous callers.
"""

from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.ratelimit import RateLimiter
from career_guidance.roadmap import (
    Plan90Store,
    build_90_day_plan,
    current_week,
    plan_progress,
    to_ics_90,
    to_markdown_90,
)
from career_guidance.users import User
from career_guidance.verify import (
    CooldownActive,
    QuizUnavailable,
    VerificationStore,
    available_quizzes,
    grade_attempt,
    start_attempt,
)

logger = logging.getLogger("career_guidance.verify_api")

_quiz_start_limiter = RateLimiter(max_calls=10, per_seconds=3600)
_quiz_submit_limiter = RateLimiter(max_calls=20, per_seconds=3600)


class SubmitBody(BaseModel):
    attempt_token: str
    answers: dict[str, int]


class ProjectBody(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    link: str = Field(max_length=500)
    description: str = Field(default="", max_length=1000)
    checklist: list[str] = Field(default_factory=list, max_length=12)


class ReviewBody(BaseModel):
    user_id: str
    skill: str
    approve: bool = True


class PublicProfileBody(BaseModel):
    handle: str = ""
    public_profile: bool = False
    is_minor: bool | None = None
    # Phase 5 (additive): preferred least-data declaration — when either
    # field is present it wins over the legacy is_minor checkbox.
    age_band: str | None = None
    birth_year: int | None = None


class Plan90Body(BaseModel):
    run_id: int | None = None
    hours_per_week: int | None = Field(default=None, ge=1, le=40)


class TaskBody(BaseModel):
    task_id: str
    done: bool = True


def _valid_project_link(link: str) -> bool:
    parsed = urlparse((link or "").strip())
    return parsed.scheme in ("http", "https") and "." in parsed.netloc


def build_router(settings, current_user, admin_user, users, db, secret: str) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["verify"])
    store = VerificationStore(settings.database_path)
    plans = Plan90Store(settings.database_path)

    # ---------------------------------------------------------- verification
    @router.get("/skills/verify/quizzes")
    def quizzes(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"quizzes": available_quizzes()}

    @router.get("/skills/verify/mine")
    def mine(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {
            "verifications": [v.to_dict() for v in store.list_for_user(user.id)],
            "quizzes": available_quizzes(),
        }

    @router.get("/skills/verify/{skill}/quiz")
    def quiz(skill: str, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not _quiz_start_limiter.allow(f"quiz-start:{user.id}"):
            raise HTTPException(429, "Too many quiz attempts — please try again later.")
        try:
            store.assert_can_attempt(user.id, skill.strip().lower())
        except CooldownActive as error:
            raise HTTPException(
                429,
                f"Retake cooldown: you can try this quiz again in "
                f"{error.retry_after_hours:.0f} hours.",
            ) from error
        try:
            return start_attempt(skill, secret)
        except QuizUnavailable as error:
            raise HTTPException(404, "No quiz available for this skill yet.") from error

    @router.post("/skills/verify/{skill}/submit")
    def submit(skill: str, body: SubmitBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not _quiz_submit_limiter.allow(f"quiz-submit:{user.id}"):
            raise HTTPException(429, "Too many quiz submissions — please try again later.")
        try:
            result = grade_attempt(body.attempt_token, body.answers, secret)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if result["skill"] != skill.strip().lower():
            raise HTTPException(400, "Attempt token does not match this skill.")
        verification = store.record_attempt(user.id, result["skill"], result)
        users.audit(user.email, "skill:quiz", f"{result['skill']}:{result['score_percent']}")
        return {"result": result, "verification": verification.to_dict()}

    @router.post("/skills/verify/{skill}/project")
    def project(skill: str, body: ProjectBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not _valid_project_link(body.link):
            raise HTTPException(422, "Project link must be a valid http(s) URL.")
        checklist = [str(item)[:120] for item in body.checklist if str(item).strip()]
        verification = store.submit_project(
            user.id,
            skill.strip().lower(),
            body.title.strip(),
            body.link.strip(),
            body.description.strip(),
            checklist,
        )
        users.audit(user.email, "skill:project", skill.strip().lower())
        return {"verification": verification.to_dict()}

    @router.post("/skills/verify/admin/review")
    def review(body: ReviewBody, reviewer: User = Depends(current_user)) -> dict:  # noqa: B008
        """Project review: platform admin, OR (Phase 4) an institute_admin /
        counsellor reviewing a student of their *own* institute."""
        allowed = reviewer.is_admin
        if not allowed:
            from career_guidance.institutes import InstituteStore

            institutes = InstituteStore(settings.database_path)
            mine = institutes.membership_of(reviewer.id)
            target = institutes.membership_of(body.user_id)
            allowed = bool(
                mine
                and target
                and mine["institute_id"] == target["institute_id"]
                and mine["institute_role"] in ("institute_admin", "counsellor")
                and target["institute_role"] == "student"
            )
        if not allowed:
            raise HTTPException(403, "Reviewer role required for this student.")
        try:
            verification = store.review_project(
                body.user_id, body.skill.strip().lower(), body.approve
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        users.audit(
            reviewer.email,
            "skill:review",
            f"{body.user_id}:{body.skill}:{'ok' if body.approve else 'no'}",
        )
        return {"verification": verification.to_dict()}

    # -------------------------------------------------------- public profile
    @router.put("/me/public-profile")
    def set_public_profile(body: PublicProfileBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if body.age_band is not None or body.birth_year is not None:
            current = users.get(user.id)
            try:
                users.set_age_declaration(
                    user.id,
                    body.age_band
                    if body.age_band is not None
                    else (current.age_band if current else ""),  # noqa: E501
                    body.birth_year
                    if body.birth_year is not None
                    else (current.birth_year if current else None),
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        elif body.is_minor is not None:
            users.set_minor(user.id, body.is_minor)
        try:
            updated = users.set_public_profile(user.id, body.handle, body.public_profile)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"user": updated.public()}

    @router.get("/p/{handle}")
    def public_profile(handle: str) -> dict:
        """Public, opt-in profile. Never exposes email/age/school/institute.

        A minor's profile is force-disabled even when they opted in (the
        full consent flow arrives in Phase 5; the rule ships now).
        """
        target = users.get_by_handle(handle)
        if target is None or not target.public_profile or target.is_minor:
            raise HTTPException(404, "Profile not found.")
        plan = plans.latest(target.id)
        summary = None
        if plan:
            done_ids = {
                t["id"] for w in plan.get("weeks", []) for t in w.get("tasks", []) if t.get("done")
            }
            week = current_week(plan)
            summary = {
                **plan_progress(plan, done_ids),
                "current_week": week["week"] if week else None,
                "total_weeks": plan.get("total_weeks", 13),
            }
        return {
            "handle": target.handle,
            "display_name": target.name or target.handle,
            "verified_skills": store.verified_skills(target.id),
            "projects": store.public_projects(target.id),
            "plan_progress": summary,
            "source": "Source: skills this user verified inside Career Guidance AI",
        }

    # -------------------------------------------------------------- 90-day plan
    def _priority_skills_for(
        user_id: str, run_id: int | None
    ) -> tuple[list[str], dict, int | None]:
        runs = [r for r in db.list_runs(limit=1000) if r.user_id == user_id]
        run = None
        if run_id is not None:
            run = next((r for r in runs if r.id == run_id), None)
            if run is None:
                raise HTTPException(404, "Run not found.")
        elif runs:
            run = runs[0]
        if run is None:
            return [], {}, None
        skills: list[str] = []
        for rec in run.recommendations:
            for skill in rec.missing_skills or []:
                if skill.lower() not in {s.lower() for s in skills}:
                    skills.append(skill)
        if not skills:
            raw = str(run.profile.get("skills", ""))
            skills = [s.strip() for s in raw.split(",") if s.strip()]
        constraints = run.profile.get("constraints") or {}
        return skills, constraints if isinstance(constraints, dict) else {}, run.id

    @router.post("/plan/90day")
    def create_plan90(body: Plan90Body, user: User = Depends(current_user)) -> dict:  # noqa: B008
        skills, constraints, run_id = _priority_skills_for(user.id, body.run_id)
        if not skills:
            raise HTTPException(
                422, "No recommendation run yet — get recommendations first, then build the plan."
            )
        if body.hours_per_week is not None:
            constraints = {**constraints, "hours_per_week": body.hours_per_week}
        plan = build_90_day_plan(skills, constraints, run_id=run_id)
        saved = plans.save(user.id, plan)
        users.audit(user.email, "plan90:create", str(run_id or ""))
        return {"plan": saved}

    @router.get("/plan/90day")
    def get_plan90(user: User = Depends(current_user)) -> dict:  # noqa: B008
        plan = plans.latest(user.id)
        if plan is None:
            return {"plan": None, "current_week": None, "progress": None}
        done_ids = {
            t["id"] for w in plan.get("weeks", []) for t in w.get("tasks", []) if t.get("done")
        }
        return {
            "plan": plan,
            "current_week": current_week(plan),
            "progress": plan_progress(plan, done_ids),
        }

    @router.patch("/plan/90day/{plan_id}/tasks")
    def mark_task(plan_id: int, body: TaskBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        plan = plans.mark_task(user.id, plan_id, body.task_id, body.done)
        if plan is None:
            raise HTTPException(404, "Plan or task not found.")
        done_ids = {
            t["id"] for w in plan.get("weeks", []) for t in w.get("tasks", []) if t.get("done")
        }
        return {
            "plan": plan,
            "current_week": current_week(plan),
            "progress": plan_progress(plan, done_ids),
        }

    @router.get("/plan/90day/export.{fmt}")
    def export_plan90(fmt: Literal["md", "ics"], user: User = Depends(current_user)):  # noqa: B008
        plan = plans.latest(user.id)
        if plan is None:
            raise HTTPException(404, "No 90-day plan yet.")
        if fmt == "md":
            return PlainTextResponse(
                to_markdown_90(plan),
                media_type="text/markdown",
                headers={"Content-Disposition": "attachment; filename=plan-90day.md"},
            )
        return Response(
            to_ics_90(plan),
            media_type="text/calendar",
            headers={"Content-Disposition": "attachment; filename=plan-90day.ics"},
        )

    return router
