"""User-journey endpoints (S3): onboarding, discover, plan, learn, résumé, …

Every route requires a session and returns numbers assembled by the pure
engines in ``career_guidance/`` — the same values the exports and the PDF
report contain.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from career_guidance import riasec
from career_guidance.content_store import ContentStore
from career_guidance.explanations import get_explanations
from career_guidance.gamification import GamificationStore
from career_guidance.interview import generate as generate_interview
from career_guidance.journey import JourneyStore
from career_guidance.market_seed import build_adapter
from career_guidance.profiles import ProfileStore
from career_guidance.reports import build_roadmap_pdf
from career_guidance.resume_score import score as score_resume
from career_guidance.roadmap import Roadmap, RoadmapItem, to_ics, to_json, to_markdown
from career_guidance.roadmap import generate as generate_roadmap
from career_guidance.settings_store import SettingsStore
from career_guidance.skillgap import evaluate
from career_guidance.suggestions2 import market_payload
from career_guidance.tasks import derive_tasks, education_path
from career_guidance.taxonomy import extract_skills
from career_guidance.transitions import find_path, transitions_into
from career_guidance.users import User

logger = logging.getLogger("career_guidance.journey")


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class ProfileBody(BaseModel):
    persona: str | None = None
    education: str | None = None
    current_role: str | None = None
    experience_level: str | None = None
    skills: list[str] | str | None = None
    goals: str | None = None
    interests: str | None = None
    hours_per_week: int | None = Field(default=None, ge=1, le=40)
    language: Literal["en", "ta", "hi"] | None = None
    country: Literal["in", "gb", "us"] | None = None
    onboarded: bool | None = None
    set_target: str | None = None


class DiscoverBody(BaseModel):
    answers: dict[str, int]


class RatingsBody(BaseModel):
    career_id: str
    ratings: dict[str, int]


class PlanBody(BaseModel):
    career_id: str
    hours_per_week: int | None = Field(default=None, ge=1, le=40)


class PlanItemBody(BaseModel):
    item_id: str
    done: bool = True


class TargetBody(BaseModel):
    career_id: str


class ResumeBody(BaseModel):
    resume_text: str = ""
    target_career_id: str | None = None
    skills: str = ""


class InterviewBody(BaseModel):
    career_id: str
    seconds: int = 0
    notes: dict[str, str] = Field(default_factory=dict)


class EventBody(BaseModel):
    kind: str
    detail: str = ""


class FeedbackBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""
    run_id: int | None = None
    career_title: str = ""
    tool: str = ""


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def build_router(settings, current_user, db, users) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["journey"])

    profiles = ProfileStore(settings.database_path)
    journey = JourneyStore(settings.database_path)
    gamification = GamificationStore(settings.database_path)
    content = ContentStore(settings.database_path)
    settings_store = SettingsStore(settings.database_path)
    explanations = get_explanations()
    market = build_adapter()

    def catalog():
        """Catalog with admin custom careers applied and hidden ids removed."""
        return content.catalog()

    def market_for(occupation):
        market.set_overrides(content.career_overrides())
        return market

    def resource_lookup(skill: str, limit: int = 2):
        found = content.resources_for_skill(skill, limit)
        if found:
            return found
        from career_guidance.learning import resources_for

        return resources_for(skill, limit)

    def _guard(module: str) -> None:
        if not settings_store.module_enabled(module):
            raise HTTPException(503, f"{module} is disabled by the administrator.")

    # ------------------------------------------------------------- profile
    @router.get("/profile")
    def get_profile(user: User = Depends(current_user)) -> dict:  # noqa: B008
        profile = profiles.get(user.id)
        return {"profile": profile.to_dict() if profile else None, "options": profiles.options()}

    @router.put("/profile")
    def save_profile(body: ProfileBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        payload = body.model_dump(exclude_none=True)
        target = payload.pop("set_target", None)
        profile = profiles.save(user.id, **payload)
        if target:
            try:
                profiles.set_target(user.id, target)
            except KeyError as error:
                raise HTTPException(404, "Unknown career id.") from error
        users.audit(user.email, "profile:update", ",".join(sorted(payload)))
        return {"profile": profile.to_dict()}

    @router.post("/onboarding")
    def onboarding(body: ProfileBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Wizard submit: saves the profile, marks it complete and sets a target."""
        payload = body.model_dump(exclude_none=True)
        target = payload.pop("set_target", None)
        payload["onboarded"] = True
        profile = profiles.save(user.id, **payload)
        target_payload = None
        if target:
            try:
                target_payload = profiles.set_target(user.id, target)
            except KeyError as error:
                raise HTTPException(404, "Unknown career id.") from error
        users.audit(user.email, "onboarding:complete", target or "")
        return {"profile": profile.to_dict(), "target": target_payload}

    # ------------------------------------------------------------ discover
    @router.get("/discover/items")
    def discover_items(locale: str = "en", user: User = Depends(current_user)) -> dict:  # noqa: B008
        _guard("discover")
        items = riasec.AssessmentStore(settings.database_path).merged_items(locale)
        return {
            "items": [
                {
                    "id": item.id,
                    "dim": item.dim,
                    "text": item.text,
                    "weight": item.weight,
                    "active": item.active,
                    "locale": item.locale,
                }
                for item in items
                if item.active
            ],
            "total": sum(1 for item in items if item.active),
            "scales": {
                "1": "Strongly disagree",
                "2": "Disagree",
                "3": "Neutral",
                "4": "Agree",
                "5": "Strongly agree",
            },
        }

    @router.post("/discover")
    def discover(body: DiscoverBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        _guard("discover")
        store = riasec.AssessmentStore(settings.database_path)
        items = store.merged_items("en")
        result = riasec.score(body.answers, items)
        history_id = store.save(user.id, body.answers, result)
        careers = riasec.top_careers(result["scores"], limit=15, taxonomy=catalog())
        gamification.award(user.id, "assessment", result["holland_code"])
        users.audit(user.email, "assessment:submit", result["holland_code"])
        for career in careers:
            career["why"] = explanations.render(
                "match.interests",
                locale="en",
                interest_top=career["top_interests"][0] if career["top_interests"] else "—",
                interest_pct=career["fit"],
            )
        return {**result, "history_id": history_id, "top_careers": careers}

    @router.get("/discover/history")
    def discover_history(user: User = Depends(current_user)) -> dict:  # noqa: B008
        store = riasec.AssessmentStore(settings.database_path)
        return {"runs": store.history(user.id)}

    @router.get("/assessment/history")
    def assessment_history(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Alias kept for the earlier single-page client."""
        return {"runs": riasec.AssessmentStore(settings.database_path).history(user.id)}

    # ---------------------------------------------------------------- plan
    @router.get("/plan/target")
    def get_target(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"target": profiles.target(user.id)}

    @router.post("/plan/target")
    def set_target(body: TargetBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        try:
            target = profiles.set_target(user.id, body.career_id)
        except KeyError as error:
            raise HTTPException(404, "Unknown career id.") from error
        users.audit(user.email, "target:set", body.career_id)
        return {"target": target}

    @router.get("/plan/readiness")
    def readiness(career_id: str, user: User = Depends(current_user)) -> dict:  # noqa: B008
        occupation = catalog().get(career_id)
        if occupation is None:
            raise HTTPException(404, "Unknown career id.")
        result = evaluate(career_id, journey.ratings(user.id, career_id), taxonomy=catalog())
        payload = result.to_dict()
        payload["template"] = _readiness_template(result, explanations)
        return payload

    @router.post("/plan/ratings")
    def save_ratings(body: RatingsBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if catalog().get(body.career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        journey.set_ratings(user.id, body.career_id, body.ratings)
        result = evaluate(
            body.career_id, journey.ratings(user.id, body.career_id), taxonomy=catalog()
        )
        payload = result.to_dict()
        payload["template"] = _readiness_template(result, explanations)
        return payload

    @router.post("/plan")
    def create_plan(body: PlanBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        _guard("plan")
        if catalog().get(body.career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        stored_profile = profiles.get(user.id)
        hours = body.hours_per_week or (stored_profile.hours_per_week if stored_profile else 6)
        result = evaluate(
            body.career_id, journey.ratings(user.id, body.career_id), taxonomy=catalog()
        )
        roadmap = generate_roadmap(
            result, hours_per_week=int(hours), resource_lookup=resource_lookup
        )
        plan = journey.save_plan(user.id, body.career_id, result, roadmap)
        plan["template"] = explanations.render(
            "roadmap.summary",
            locale="en",
            weeks=plan["weeks"],
            hours=plan["hours_per_week"],
            readiness_before=plan["readiness_before"],
            readiness_after=plan["readiness_after"],
            eta=plan["eta"],
        )
        gamification.award(user.id, "plan", body.career_id)
        users.audit(user.email, "plan:create", body.career_id)
        return {"plan": plan}

    @router.get("/plan")
    def latest_plan(user: User = Depends(current_user)) -> dict:  # noqa: B008
        plan = journey.latest_plan(user.id)
        ratings = journey.ratings(user.id, plan["career_id"]) if plan else {}
        return {"plan": plan, "ratings": ratings}

    @router.patch("/plan/{plan_id}/items")
    def mark_item(
        plan_id: int,
        body: PlanItemBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        plan = journey.plan_by_id(user.id, plan_id)
        if plan is None:
            raise HTTPException(404, "Plan not found.")
        if body.done:
            journey.set_item_done(user.id, plan_id, body.item_id, True)
            gamification.award(user.id, "plan_item", f"plan:{plan_id}:{body.item_id}")
        else:
            with journey._connect() as conn:  # noqa: SLF001 - same package
                conn.execute(
                    "DELETE FROM xp_events WHERE user_id = ? AND kind = 'plan_item' AND detail = ?",
                    (user.id, f"plan:{plan_id}:{body.item_id}"),
                )
        plan = journey.plan_by_id(user.id, plan_id)
        return {"plan": plan}

    @router.get("/plan/{plan_id}.{fmt}")
    def export_plan(
        plan_id: int,
        fmt: Literal["md", "json", "ics", "pdf"],
        user: User = Depends(current_user),  # noqa: B008
    ):  # noqa: E501
        stored = journey.plan_by_id(user.id, plan_id)
        if stored is None:
            raise HTTPException(404, "Plan not found.")
        headers = {"Content-Disposition": f"attachment; filename=roadmap-{plan_id}.{fmt}"}
        if fmt == "json":
            return PlainTextResponse(
                to_json(_roadmap_object(stored)), media_type="application/json", headers=headers
            )
        if fmt == "md":
            return PlainTextResponse(
                to_markdown(_roadmap_object(stored)), media_type="text/markdown", headers=headers
            )
        if fmt == "ics":
            return PlainTextResponse(
                to_ics(_roadmap_object(stored)), media_type="text/calendar", headers=headers
            )
        return Response(
            content=build_roadmap_pdf(stored), media_type="application/pdf", headers=headers
        )

    # --------------------------------------------------------------- learn
    @router.get("/learn")
    def learn_list(
        q: str = "",
        skill: str = "",
        language: str = "",
        provider: str = "",
        level: str = "",
        free: bool | None = None,
        limit: int = Query(default=60, ge=1, le=300),
        offset: int = 0,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _guard("learn")
        results = content.resources(
            q=q,
            skill=skill,
            language=language,
            provider=provider,
            level=level,
            free=free,
            limit=limit,
            offset=offset,
        )
        saved = set(journey.saved_resources(user.id))
        done = set(journey.done_resources(user.id))
        for row in results:
            row["saved"] = row["id"] in saved
            row["done"] = row["id"] in done
        total = len(
            content.resources(
                q=q,
                skill=skill,
                language=language,
                provider=provider,
                level=level,
                free=free,
                limit=100_000,
            )
        )
        return {"results": results, "total": total, "filters": content.filters()}

    @router.get("/learn/saved")
    def learn_saved(user: User = Depends(current_user)) -> dict:  # noqa: B008
        ids = journey.saved_resources(user.id)
        done = set(journey.done_resources(user.id))
        results = []
        for resource_id in ids:
            row = content.resource(resource_id)
            if row:
                row["saved"] = True
                row["done"] = row["id"] in done
                results.append(row)
        return {"results": results}

    @router.post("/learn/{resource_id}/save")
    def save_resource(resource_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if content.resource(resource_id) is None:
            raise HTTPException(404, "Resource not found.")
        journey.toggle_saved(user.id, resource_id, True)
        return {"saved": True}

    @router.delete("/learn/{resource_id}/save")
    def unsave_resource(resource_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        journey.toggle_saved(user.id, resource_id, False)
        return {"saved": False}

    @router.post("/learn/{resource_id}/done")
    def done_resource(
        resource_id: int,
        body: dict | None = None,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        if content.resource(resource_id) is None:
            raise HTTPException(404, "Resource not found.")
        done = bool((body or {}).get("done", True))
        journey.mark_resource(user.id, resource_id, done)
        if done:
            gamification.award(user.id, "course_done", f"resource:{resource_id}")
        return {"done": done, "xp": gamification.status(user.id)}

    # -------------------------------------------------------------- résumé
    @router.post("/resume/score")
    def resume_score(body: ResumeBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        _guard("resume")
        if body.target_career_id and catalog().get(body.target_career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        if len(body.resume_text.strip()) < 40:
            raise HTTPException(422, "Paste at least a few lines of your résumé.")
        result = score_resume(
            body.resume_text, body.target_career_id, extra_skills=body.skills, taxonomy=catalog()
        )
        payload = result.to_dict()
        payload["summary"] = explanations.render(
            "resume.headline",
            locale="en",
            score=payload["score"],
            grade=payload["grade"],
            title=(payload.get("target_career") or {}).get("title", "your target role"),
        )
        gamification.award(user.id, "resume", body.target_career_id or "no-target")
        return payload

    # ------------------------------------------------------------- compare
    @router.get("/compare")
    def compare(
        ids: str = Query(..., description="Comma-separated career ids (2–3)"),
        country: str = "in",
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _guard("compare")
        wanted = [i.strip() for i in ids.split(",") if i.strip()][:3]
        if len(wanted) < 2:
            raise HTTPException(422, "Provide at least two career ids.")
        taxonomy = catalog()
        adapter = market_for(None)
        careers = []
        for career_id in wanted:
            occupation = taxonomy.get(career_id)
            if occupation is None:
                raise HTTPException(404, f"Unknown career id: {career_id}")
            families = adapter.seed.family_for(occupation)
            careers.append(
                {
                    **_career_payload(occupation, adapter, country),
                    "family": families.id if families else "other",
                }
            )
        shared = set(careers[0]["skills"])
        for career in careers[1:]:
            shared &= set(career["skills"])
        unique = []
        for career in careers:
            others: set[str] = set()
            for other in careers:
                if other["id"] != career["id"]:
                    others |= set(other["skills"])
            unique.append(
                {
                    "id": career["id"],
                    "title": career["title"],
                    "skills": [s for s in career["skills"] if s not in others][:8],
                }
            )
        table = [
            {"label": "Job zone", "values": [c["job_zone"] for c in careers]},
            {
                "label": "Salary (p50)",
                "values": [c["market"]["salary_p50"] or "—" for c in careers],
            },
            {"label": "Demand", "values": [c["market"]["demand_label"] for c in careers]},
            {
                "label": "Remote-friendly",
                "values": ["Yes" if c["remote"] else "No" for c in careers],
            },
            {"label": "Core skills", "values": [len(c["skills"]) for c in careers]},
            {"label": "Tools", "values": [len(c["technology"]) for c in careers]},
            {"label": "Holland code", "values": [c["holland_code"] or "—" for c in careers]},
        ]
        return {
            "careers": careers,
            "shared_skills": sorted(shared)[:12],
            "unique_skills": unique,
            "table": table,
            "source": market.seed.label,
            "template": explanations.render(
                "compare.headline",
                locale="en",
                shared=", ".join(sorted(shared)[:5]) or "no shared core skills",
            ),
        }

    # --------------------------------------------------------- transitions
    @router.get("/transitions")
    def transitions(
        from_: str = Query(alias="from"),
        to: str = Query(...),
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _guard("transitions")
        try:
            path = find_path(from_, to, taxonomy=catalog())
        except KeyError as error:
            raise HTTPException(404, f"Unknown career id: {error.args[0]}") from error
        payload = path.to_dict()
        payload["template"] = (
            explanations.render(
                "transition.found",
                locale="en",
                hops=payload["hops"],
                from_title=payload["from"]["title"],
                to_title=payload["to"]["title"],
            )
            if payload["found"]
            else explanations.render("transition.missing", locale="en")
        )
        for hop in payload["path"]:
            hop["template"] = explanations.render(
                "transition.hop",
                locale="en",
                title=hop["title"],
                delta_count=len(hop.get("delta_skills", [])),
                delta=", ".join(hop.get("delta_skills", [])[:3]) or "none",
            )
        return payload

    # ----------------------------------------------------------- interview
    @router.get("/interview/questions")
    def interview_questions(
        career_id: str,
        seed: int = 42,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _guard("interview")
        if catalog().get(career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        extras = content.interview_templates()
        kit = generate_interview(
            career_id,
            seed=seed,
            extra_behavioural=[t["template"] for t in extras if t["kind"] == "behavioural"],
            extra_technical=[t["template"] for t in extras if t["kind"] == "technical"],
        )
        return kit.to_dict()

    @router.post("/interview/sessions")
    def save_interview(body: InterviewBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        session_id = journey.save_interview(user.id, body.career_id, body.seconds, body.notes)
        gamification.award(user.id, "interview", body.career_id)
        return {"id": session_id, "xp": gamification.status(user.id)}

    @router.get("/interview/sessions")
    def interview_sessions(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"sessions": journey.interview_sessions(user.id)}

    # -------------------------------------------------------------- careers
    @router.get("/careers")
    def careers_list(
        q: str = "",
        family: str = "",
        job_zone: int | None = None,
        min_salary: int | None = None,
        remote: bool | None = None,
        limit: int = Query(default=40, ge=1, le=200),
        offset: int = 0,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        taxonomy = catalog()
        adapter = market_for(None)
        rows = []
        family_ids: set[str] = set()
        for occupation in taxonomy.occupations:
            found = adapter.seed.family_for(occupation)
            if found:
                family_ids.add(found.id)
            if q and q.lower() not in occupation.title.lower():
                continue
            if job_zone and occupation.job_zone != job_zone:
                continue
            if family and (found.id if found else "other") != family:
                continue
            snapshot = adapter.snapshot(occupation, "in")
            if min_salary and (snapshot.salary_p50 or 0) < min_salary:
                continue
            is_remote = adapter.seed.remote_friendly(occupation)
            if remote is not None and is_remote != remote:
                continue
            rows.append(
                {
                    "id": occupation.id,
                    "title": occupation.title,
                    "job_zone": occupation.job_zone,
                    "salary_p50": snapshot.salary_p50,
                    "demand": adapter.seed.demand_label(occupation),
                    "remote": is_remote,
                    "family": found.id if found else "other",
                }
            )
        rows.sort(key=lambda r: (-(r["salary_p50"] or 0), r["title"]))
        return {
            "total": len(rows),
            "results": rows[offset : offset + limit],
            "families": sorted(family_ids | {"other"}),
            "source": market.seed.label,
        }

    # ------------------------------------------------------- gamification
    @router.get("/gamification")
    def gamification_status(user: User = Depends(current_user)) -> dict:  # noqa: B008
        _guard("gamification")
        return gamification.status(user.id)

    @router.post("/gamification/event")
    def gamification_event(body: EventBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        allowed = {
            "run",
            "assessment",
            "plan",
            "plan_item",
            "course_done",
            "resume",
            "jobfit",
            "interview",
            "feedback",
            "visit",
        }
        if body.kind not in allowed:
            raise HTTPException(422, "Unknown event kind.")
        gamification.award(
            user.id, body.kind, body.detail, points=0 if body.kind == "visit" else None
        )
        return gamification.status(user.id)

    # ------------------------------------------------------- announcements
    @router.get("/announcements")
    def announcements(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"announcements": settings_store.announcements()}

    # ------------------------------------------------------------ feedback
    @router.post("/feedback")
    def feedback(body: FeedbackBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        feedback_id = users.add_feedback(
            body.rating, body.comment, user.id, body.run_id, body.career_title, tool=body.tool
        )
        gamification.award(user.id, "feedback", f"feedback:{feedback_id}")
        return {"id": feedback_id}

    # ----------------------------------------------------------- dashboard
    @router.get("/me/dashboard")
    def dashboard(user: User = Depends(current_user)) -> dict:  # noqa: B008
        profile = profiles.get(user.id)
        target = profiles.target(user.id)
        readiness_payload = None
        plan_payload = None
        if target:
            readiness_payload = evaluate(
                target["career_id"],
                journey.ratings(user.id, target["career_id"]),
                taxonomy=catalog(),
            ).to_dict()
            readiness_payload["template"] = explanations.render(
                "readiness.summary",
                locale="en",
                readiness=readiness_payload["readiness_weighted"],
                title=readiness_payload["title"],
                strong=readiness_payload["counts"]["strong"],
                weak=readiness_payload["counts"]["weak"],
                missing=readiness_payload["counts"]["missing"],
            )
            candidate = journey.latest_plan(user.id)
            if candidate and candidate["career_id"] == target["career_id"]:
                plan_payload = candidate
        xp = gamification.status(user.id)
        runs = [r for r in db.list_runs(limit=200) if r.user_id == user.id][:6]
        return {
            "profile": profile.to_dict() if profile else None,
            "target": target,
            "readiness": readiness_payload,
            "roadmap": plan_payload,
            "xp": xp,
            "streak": xp["streak"],
            "recent_runs": [_run_payload(r) for r in runs],
            "announcements": settings_store.announcements(),
        }

    @router.get("/me/export")
    def export_me(user: User = Depends(current_user)) -> dict:  # noqa: B008
        import datetime as _dt

        payload = journey.export_user(user.id)
        payload["account"] = user.public()
        payload["exported_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        return payload

    # ------------------------------------------------------------- reports
    @router.get("/reports/career.pdf")
    def career_report(user: User = Depends(current_user)):  # noqa: B008
        from career_guidance.reports import build_report

        profile = profiles.get(user.id)
        target = profiles.target(user.id)
        assessment = riasec.AssessmentStore(settings.database_path).latest(user.id)
        readiness_payload = None
        roadmap = None
        if target:
            readiness_result = evaluate(
                target["career_id"],
                journey.ratings(user.id, target["career_id"]),
                taxonomy=catalog(),
            )
            readiness_payload = readiness_result.to_dict()
            roadmap = journey.latest_plan(user.id)
        matches = []
        latest_run = next((r for r in db.list_runs(limit=100) if r.user_id == user.id), None)
        if latest_run:
            for rec in latest_run.recommendations:
                matches.append(
                    {
                        "title": rec.title,
                        "match_percent": round(rec.match_score * 100, 1),
                        "readiness": readiness_payload["readiness_weighted"]
                        if readiness_payload
                        else 0,  # noqa: E501
                        "why": (rec.provenance or {}).get("why") or [rec.match_reason],
                        "missing_skills": rec.missing_skills,
                    }
                )
        pdf = build_report(
            {
                "user": {"name": user.name, "email": user.email},
                "profile": profile.to_dict() if profile else {},
                "assessment": assessment,
                "matches": matches,
                "readiness": readiness_payload,
                "roadmap": roadmap,
            }
        )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=career-guidance-report.pdf"},
        )

    return router


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _career_payload(occupation, adapter, country: str = "in") -> dict:
    """Career detail payload shared by /careers/{id}, /compare and the report."""
    payload = {
        **asdict(occupation),
        "technology": occupation.technology[:15],
        "market": market_payload(adapter, occupation, country),
        "market_us": market_payload(adapter, occupation, "us"),
        "related": [
            {"id": r.id, "title": r.title, "job_zone": r.job_zone}
            for r in (adapter_taxonomy().get(rid) for rid in occupation.related)
            if r
        ],
        "tasks": derive_tasks(occupation, limit=8),
        "education_path": education_path(occupation),
        "skill_importance": [
            {"skill": name, "importance": round(value * 10, 1), "raw": round(value, 3)}
            for name, value in _importance(occupation)
        ],
        "resources": [
            {
                "id": None,
                "skill": skill,
                "title": r.title,
                "url": r.url,
                "provider": r.provider,
                "free": r.free,
            }
            for skill in occupation.skills[:3]
            for r in _default_resources(skill, 1)
        ],
        "transitions_in": transitions_into(occupation.id, taxonomy=adapter_taxonomy(), limit=6),
        "family": (
            adapter.seed.family_for(occupation).id
            if adapter.seed.family_for(occupation)
            else "other"
        ),  # noqa: E501
        "remote": adapter.seed.remote_friendly(occupation),
        "indian_titles": adapter.seed.indian_titles(occupation),
        "detected_from_skills": extract_skills(occupation.title),
    }
    return payload


def adapter_taxonomy():
    from career_guidance.taxonomy import load_taxonomy

    return load_taxonomy()


def _default_resources(skill: str, limit: int):
    from career_guidance.learning import resources_for

    return resources_for(skill, limit)


def _importance(occupation) -> list[tuple[str, float]]:
    from career_guidance.skillgap import importance_weights

    return importance_weights(occupation)[:12]


def _readiness_template(readiness, explanations) -> str:
    gap = readiness.next_gap()
    if gap is None:
        return explanations.render(
            "readiness.summary",
            locale="en",
            readiness=round(readiness.readiness_weighted, 1),
            title=readiness.occupation.title,
            strong=len(readiness.strong),
            weak=len(readiness.weak),
            missing=len(readiness.missing),
        )
    return explanations.render(
        "readiness.next",
        locale="en",
        gap=gap.skill,
        importance=round(gap.importance * 100, 1),
    )


def _run_payload(run) -> dict:
    from dataclasses import asdict as _asdict

    return {
        "id": run.id,
        "created_at": run.created_at,
        "provider": run.provider,
        "is_demo": run.is_demo,
        "skills": str(run.profile.get("skills", ""))[:200],
        "goals": str(run.profile.get("goals", "")),
        "experience_level": run.profile.get("experience_level", ""),
        "recommendations": [
            {**_asdict(rec), "match_percent": round(rec.match_score * 100, 1)}
            for rec in run.recommendations  # noqa: E501
        ],
    }


def _roadmap_object(payload: dict) -> Roadmap:
    """Rebuild a :class:`Roadmap` from stored JSON so exports keep working."""
    from career_guidance.models import LearningResource

    items = [
        RoadmapItem(
            id=item["id"],
            week=item["week"],
            skill=item["skill"],
            title=item["title"],
            hours=item["hours"],
            status=item["status"],
            importance=item.get("importance", 5) / 10,
            prerequisite_of=item.get("prerequisite_of", []),
            resources=[
                LearningResource(
                    skill=r.get("skill", item["skill"]),
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    provider=r.get("provider", ""),
                    free=bool(r.get("free", True)),
                )
                for r in item.get("resources", [])
            ],
            milestone=item.get("milestone", ""),
        )
        for item in payload.get("items", [])
    ]
    return Roadmap(
        occupation_id=payload.get("career_id", ""),
        title=payload.get("title", ""),
        hours_per_week=int(payload.get("hours_per_week", 6)),
        weeks=int(payload.get("weeks", 0)),
        eta=payload.get("eta", ""),
        items=items,
        milestones=payload.get("milestones", []),
        readiness_before=payload.get("readiness_before", 0),
        readiness_after=payload.get("readiness_after", 0),
        source=payload.get("source", ""),
    )
