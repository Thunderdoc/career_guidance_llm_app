"""User-journey endpoints (S3): profile, discover, plan, learn, résumé, …

Every route is a thin adapter over the pure engines in ``career_guidance``:
the same numbers therefore appear in the UI, in the exports and in the admin
console, and each payload carries the source label the front end renders.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from career_guidance import riasec
from career_guidance.content_store import ContentStore
from career_guidance.explanations import get_explanations
from career_guidance.gamification import XP_RULES, GamificationStore
from career_guidance.interview import generate as generate_interview
from career_guidance.journey import JourneyStore
from career_guidance.keywords import ranked_technology
from career_guidance.ladder import build as build_ladder
from career_guidance.learning import resources_for
from career_guidance.market_seed import build_adapter
from career_guidance.pathway import build_pathway, read_resume_signals
from career_guidance.profile import EXPERIENCE_LEVELS
from career_guidance.profiles import EDUCATION_LEVELS, PERSONAS, ProfileStore
from career_guidance.reports import build_report
from career_guidance.resume_score import score as score_resume
from career_guidance.roadmap import Roadmap, to_ics, to_json, to_markdown
from career_guidance.roadmap import generate as generate_roadmap
from career_guidance.settings_store import SettingsStore
from career_guidance.skillgap import catalog_importance, evaluate
from career_guidance.tasks import derive_tasks, education_path
from career_guidance.taxonomy import extract_skills
from career_guidance.transitions import delta_skills, find_path, transitions_into
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
    hours_per_week: int | None = None
    language: str | None = None
    country: str | None = None
    onboarded: bool | None = None
    set_target: str | None = None


class RatingsBody(BaseModel):
    career_id: str
    ratings: dict[str, int]

    def clean(self) -> dict[str, int]:
        return {k.strip().lower(): int(v) for k, v in self.ratings.items() if str(k).strip()}


class PlanBody(BaseModel):
    career_id: str
    hours_per_week: int | None = Field(default=None, ge=1, le=40)


class TargetBody(BaseModel):
    career_id: str


class ItemBody(BaseModel):
    item_id: str
    done: bool = True


class ResourceBody(BaseModel):
    resource_id: int


class ResumeBody(BaseModel):
    resume_text: str = ""
    target_career_id: str | None = None
    skills: str = ""


class InterviewBody(BaseModel):
    career_id: str
    seed: int = 42
    seconds: int = 0
    notes: dict[str, str] = Field(default_factory=dict)


class EventBody(BaseModel):
    kind: Literal[
        "run",
        "assessment",
        "plan",
        "plan_item",
        "course_done",
        "resume",
        "jobfit",
        "interview",
        "visit",
    ] = "visit"
    detail: str = ""


class PathwayBody(BaseModel):
    career_id: str
    resume_text: str = ""
    education: str = ""
    experience_level: str = ""
    hours_per_week: int | None = None
    current_role: str = ""
    ratings: dict[str, int] | None = None
    use_profile: bool = True


class FeedbackBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = ""
    run_id: int | None = None
    career_title: str = ""
    tool: str = ""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _iso_week_label(start: date, week: int) -> str:
    """Human label for a roadmap week (“Week 3 · 21 Sep”)."""
    day = start + timedelta(days=7 * (week - 1))
    return f"Week {week} · {day.strftime('%d %b')}"


def _roadmap_payload(plan: dict, start: date) -> dict:
    payload = dict(plan)
    payload["items"] = [
        {**item, "week_label": _iso_week_label(start, int(item.get("week", 1)))}
        for item in plan.get("items", [])
    ]
    return payload


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def build_router(settings, current_user, db, users) -> APIRouter:
    """Journey routes for the signed-in user (session enforced by FastAPI)."""
    router = APIRouter(prefix="/api/v1", tags=["journey"])

    profiles = ProfileStore(settings.database_path)
    journey = JourneyStore(settings.database_path)
    gamification = GamificationStore(settings.database_path)
    content = ContentStore(settings.database_path)
    settings_store = SettingsStore(settings.database_path)
    assessments = riasec.AssessmentStore(settings.database_path)
    explanations = get_explanations()

    def taxonomy():
        return content.catalog()

    def market():
        adapter = build_adapter()
        adapter.set_overrides(content.career_overrides())
        return adapter

    def locale_of(request_language: str = "") -> str:
        return request_language if request_language in ("en", "ta", "hi") else "en"

    # ---------------------------------------------------------------- profile
    @router.get("/profile")
    def get_profile(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {
            "profile": (profiles.get(user.id) or None) and profiles.get(user.id).to_dict(),
            "target": profiles.target(user.id),
            "options": {
                "personas": list(PERSONAS),
                "education_levels": list(EDUCATION_LEVELS),
                "experience_levels": list(EXPERIENCE_LEVELS),
                "hours_per_week_range": [1, 40],
                "languages": ["en", "ta", "hi"],
                "countries": ["in", "us", "gb"],
            },
        }

    @router.put("/profile")
    @router.post("/profile")
    def save_profile(body: ProfileBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        payload = body.model_dump(exclude_none=True)
        target = payload.pop("set_target", None)
        if payload.get("hours_per_week") is not None:
            # The UI uses a 1–40 h/week slider; clamp instead of rejecting so a
            # hand-typed 60 h becomes the documented maximum.
            payload["hours_per_week"] = max(1, min(40, int(payload["hours_per_week"])))
        if "experience_level" in payload and payload["experience_level"] not in EXPERIENCE_LEVELS:
            raise HTTPException(422, "Unknown experience level.")
        if "persona" in payload and payload["persona"] not in PERSONAS:
            raise HTTPException(422, "Unknown persona.")
        profile = profiles.save(user.id, **payload)
        if target:
            try:
                profiles.set_target(user.id, target)
            except KeyError as error:
                raise HTTPException(404, "Unknown career id.") from error
        users.audit(user.email, "profile:update", profile.persona or "profile")
        return {"profile": profile.to_dict()}

    @router.post("/onboarding")
    def onboarding(body: ProfileBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Final wizard step: save the answers and mark onboarding complete."""
        if body.onboarded is None:
            body.onboarded = True
        saved = save_profile(body, user)
        saved["target"] = profiles.target(user.id)
        return saved

    # --------------------------------------------------------------- discover
    @router.get("/discover/items")
    def discover_items(locale: str = "en", user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not settings_store.module_enabled("discover"):
            raise HTTPException(503, "The interest test is disabled by the administrator.")
        items = assessments.merged_items(locale)
        return {
            "items": [item.as_question() for item in items if item.active],
            "total": sum(1 for item in items if item.active),
            "locale": locale,
            "source": (
                "Source: 36-item RIASEC inventory "
                "(6 statements per dimension), bundled with the app"
            ),
        }

    @router.post("/discover")
    def discover(body: dict, locale: str = "en", user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not settings_store.module_enabled("discover"):
            raise HTTPException(503, "The interest test is disabled by the administrator.")
        answers = {
            str(k): int(v) for k, v in (body.get("answers") or {}).items() if str(v).isdigit()
        }
        if len(answers) < 12:
            raise HTTPException(422, "Answer at least 12 statements.")
        items = assessments.merged_items(locale)
        result = riasec.score(answers, items, locale=locale)
        run_id = assessments.save(user.id, answers, result)
        careers = riasec.top_careers(result["scores"], limit=15, taxonomy=taxonomy())
        leads = result["profile"][0]
        for career in careers:
            career["why"] = explanations.render(
                "match.interests",
                locale=locale,
                interest_top=leads["name"],
                interest_pct=round(career.get("fit", 0)),
            )
        gamification.award(user.id, "assessment", f"holland:{result['holland_code']}")
        users.audit(user.email, "assessment:submit", result["holland_code"])
        return {
            **result,
            "history_id": run_id,
            "top_careers": careers,
            "explanation": explanations.render(
                "match.interests",
                locale=locale,
                interest_top=result["profile"][0]["name"],
                interest_pct=round(result["profile"][0]["score"] / 7 * 100),
            ),
            "source": "Source: RIASEC scoring (1–5 → 1–7) over the bundled 36-item inventory",
        }

    @router.get("/discover/history")
    @router.get("/assessment/history")
    def discover_history(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"runs": assessments.history(user.id, limit=20)}

    # ---------------------------------------------------------------- careers
    @router.get("/careers")
    def careers(
        q: str = "",
        family: str = "",
        zone: int | None = None,
        holland: str = "",
        country: str = "in",
        limit: int = 24,
        offset: int = 0,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Browse the catalogue with a market snapshot on every card."""
        catalog = taxonomy()
        adapter = market()
        needle = q.strip().lower()
        want_holland = holland.strip().upper()
        rows = []
        for occupation in catalog.occupations:
            if needle and needle not in occupation.title.lower():
                continue
            if zone is not None and occupation.job_zone != zone:
                continue
            if want_holland and not (occupation.holland_code or "").startswith(want_holland):
                continue
            item_family = adapter.seed.family_for(occupation)
            if family and (item_family.id if item_family else "other") != family:
                continue
            rows.append((occupation, item_family))
        rows.sort(key=lambda pair: (pair[0].job_zone, pair[0].title))
        page = rows[offset : offset + max(1, min(limit, 60))]
        results = []
        for occupation, item_family in page:
            snapshot = adapter.snapshot(occupation, country)
            results.append(
                {
                    "id": occupation.id,
                    "title": occupation.title,
                    "family": item_family.id if item_family else "other",
                    "family_label": item_family.label if item_family else "Other",
                    "job_zone": occupation.job_zone,
                    "holland_code": occupation.holland_code,
                    "salary_p50": snapshot.salary_p50,
                    "salary_p25": snapshot.salary_p25,
                    "salary_p75": snapshot.salary_p75,
                    "currency": snapshot.currency,
                    "currency_symbol": "₹" if snapshot.currency == "INR" else "$",
                    "demand_label": adapter.seed.demand_label(occupation),
                    "trend": adapter.seed.trend(occupation),
                    "remote": adapter.seed.remote_friendly(occupation),
                    "indian_titles": adapter.seed.indian_titles(occupation),
                    "top_skills": occupation.skills[:4],
                    "technology": ranked_technology(occupation, limit=4),
                }
            )
        families = []
        seen = set()
        for occupation in catalog.occupations:
            item_family = adapter.seed.family_for(occupation)
            key = item_family.id if item_family else "other"
            if key in seen:
                continue
            seen.add(key)
            families.append({"id": key, "label": item_family.label if item_family else "Other"})
        families.sort(key=lambda f: f["label"])
        return {
            "results": results,
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "filters": {"families": families, "zones": [1, 2, 3, 4, 5]},
            "source": adapter.seed.label + "; 974-career catalogue bundled with the app",
        }

    # ------------------------------------------------------------------- plan
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
        if taxonomy().get(career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        result = evaluate(career_id, journey.ratings(user.id, career_id), taxonomy=taxonomy())
        payload = result.to_dict()
        payload["template"] = explanations.render(
            "readiness.summary",
            readiness=payload["readiness_weighted"],
            title=result.occupation.title,
            strong=payload["counts"]["strong"],
            weak=payload["counts"]["weak"],
            missing=payload["counts"]["missing"],
        )
        return payload

    @router.post("/plan/ratings")
    def save_ratings(body: RatingsBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if taxonomy().get(body.career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        ratings = journey.set_ratings(user.id, body.career_id, body.clean())
        result = evaluate(body.career_id, ratings, taxonomy=taxonomy())
        payload = result.to_dict()
        payload["template"] = explanations.render(
            "readiness.summary",
            readiness=payload["readiness_weighted"],
            title=result.occupation.title,
            strong=payload["counts"]["strong"],
            weak=payload["counts"]["weak"],
            missing=payload["counts"]["missing"],
        )
        gap = result.next_gap()
        payload["next_step"] = (
            explanations.render(
                "readiness.next", gap=gap.skill, importance=round(gap.importance * 100)
            )
            if gap
            else ""
        )
        return payload

    @router.post("/plan")
    def create_plan(body: PlanBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not settings_store.module_enabled("plan"):
            raise HTTPException(503, "Roadmaps are disabled by the administrator.")
        occupation = taxonomy().get(body.career_id)
        if occupation is None:
            raise HTTPException(404, "Unknown career id.")
        profile = profiles.get(user.id)
        hours = body.hours_per_week or (profile.hours_per_week if profile else 6)
        ratings = journey.ratings(user.id, body.career_id)
        result = evaluate(body.career_id, ratings, taxonomy=taxonomy())
        roadmap = generate_roadmap(
            result,
            hours_per_week=int(hours),
            resource_lookup=_resource_lookup(content, body.career_id),
        )
        plan = journey.save_plan(user.id, body.career_id, result, roadmap)
        profiles.set_target(user.id, body.career_id)
        gamification.award(user.id, "plan", body.career_id)
        users.audit(user.email, "plan:create", body.career_id)
        payload = _roadmap_payload(plan, date.today())
        payload["ratings"] = ratings
        return {"plan": payload}

    @router.get("/plan")
    def latest_plan(user: User = Depends(current_user)) -> dict:  # noqa: B008
        plan = journey.latest_plan(user.id)
        if plan is None:
            return {"plan": None, "ratings": {}, "target": profiles.target(user.id)}
        payload = _roadmap_payload(plan, date.today())
        payload["ratings"] = journey.ratings(user.id, plan["career_id"])
        return {"plan": payload, "ratings": payload["ratings"], "target": profiles.target(user.id)}

    @router.patch("/plan/{plan_id}/items")
    def mark_item(plan_id: int, body: ItemBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        plan = journey.set_item_done(user.id, plan_id, body.item_id, body.done)
        if plan is None:
            raise HTTPException(404, "Plan not found.")
        payload = _roadmap_payload(plan, date.today())
        payload["ratings"] = journey.ratings(user.id, plan["career_id"])
        return {"plan": payload, "xp": gamification.status(user.id)}

    @router.get("/plan/{plan_id}.{fmt}")
    def export_plan(
        plan_id: int,
        fmt: Literal["md", "json", "ics", "pdf"],
        user: User = Depends(current_user),  # noqa: B008
    ):
        plan = journey.plan_by_id(user.id, plan_id)
        if plan is None:
            raise HTTPException(404, "Plan not found.")
        roadmap = _roadmap_object(plan)
        if fmt == "md":
            return PlainTextResponse(
                to_markdown(roadmap),
                media_type="text/markdown",
                headers={"Content-Disposition": f"attachment; filename=roadmap-{plan_id}.md"},
            )
        if fmt == "json":
            return PlainTextResponse(
                to_json(roadmap),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=roadmap-{plan_id}.json"},
            )
        if fmt == "ics":
            return Response(
                to_ics(roadmap),
                media_type="text/calendar",
                headers={"Content-Disposition": f"attachment; filename=roadmap-{plan_id}.ics"},
            )
        pdf = build_report({"user": {"email": user.email}, "roadmap": plan})
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=roadmap-{plan_id}.pdf"},
        )

    # ------------------------------------------------------------------ learn
    @router.get("/learn")
    def learn(
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
        if not settings_store.module_enabled("learn"):
            raise HTTPException(503, "The learning hub is disabled by the administrator.")
        rows = content.resources(
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
        for row in rows:
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
                limit=1000,
            )  # noqa: E501
        )
        return {
            "results": rows,
            "total": total,
            "filters": content.filters(),
            "source": (
                "Source: curated free-course catalogue (data/learning_resources.yaml + admin edits)"
            ),
        }

    @router.get("/learn/saved")
    def saved(user: User = Depends(current_user)) -> dict:  # noqa: B008
        rows = [content.resource(i) for i in journey.saved_resources(user.id)]
        done = set(journey.done_resources(user.id))
        results = [row for row in rows if row]
        for row in results:
            row["saved"] = True
            row["done"] = row["id"] in done
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
    def mark_resource(
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

    # ----------------------------------------------------------------- résumé
    @router.post("/resume/score")
    def resume(body: ResumeBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not settings_store.module_enabled("resume"):
            raise HTTPException(503, "Résumé analysis is disabled by the administrator.")
        if len(body.resume_text.strip()) < 40:
            raise HTTPException(422, "Paste at least a few lines of your résumé.")
        if body.target_career_id and taxonomy().get(body.target_career_id) is None:
            raise HTTPException(404, "Unknown career id.")
        result = score_resume(
            body.resume_text, body.target_career_id, extra_skills=body.skills, taxonomy=taxonomy()
        )
        payload = result.to_dict()
        payload["summary"] = explanations.render(
            "resume.headline",
            score=payload["score"],
            grade=payload["grade"],
            title=(payload.get("target_career") or {}).get("title") or "your target career",
        )
        if payload.get("keyword_coverage", {}).get("missing"):
            payload["next_step"] = explanations.render(
                "resume.coverage",
                percent=payload["keyword_coverage"]["percent"],
                missing_count=len(payload["keyword_coverage"]["missing"]),
                gap=payload["keyword_coverage"]["missing"][0],
            )
        gamification.award(user.id, "resume", body.target_career_id or "no-target")
        users.audit(user.email, "resume:score", str(payload["score"]))
        return payload

    # ------------------------------------------------------- pathway & ladder
    @router.get("/pathway/signals")
    def pathway_signals(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Prefill the pathway form from the saved profile."""
        profile = profiles.get(user.id)
        target = profiles.target(user.id)
        return {
            "profile": profile.to_dict() if profile else None,
            "target": target,
            "education_levels": list(EDUCATION_LEVELS),
            "experience_levels": list(EXPERIENCE_LEVELS),
            "source": "Source: your saved profile in this app",
        }

    @router.post("/pathway")
    def pathway(body: PathwayBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """“I want to become X — do I qualify, and what exactly do I do next?”"""
        if not settings_store.module_enabled("plan"):
            raise HTTPException(503, "Roadmaps are disabled by the administrator.")
        catalog = taxonomy()
        occupation = catalog.get(body.career_id)
        if occupation is None:
            raise HTTPException(404, "Unknown career id.")
        profile = profiles.get(user.id)
        education = body.education or (profile.education if profile else "") or ""
        experience = body.experience_level or (profile.experience_level if profile else "") or ""
        if experience and experience not in EXPERIENCE_LEVELS:
            raise HTTPException(422, "Unknown experience level.")
        hours = body.hours_per_week or (profile.hours_per_week if profile else 6) or 6
        ratings = (
            body.ratings if body.ratings is not None else journey.ratings(user.id, body.career_id)
        )
        signals = read_resume_signals(body.resume_text) if body.resume_text else None
        if signals and not education:
            education = signals["education"]
        if signals and not experience:
            experience = signals["experience_level"]
        if not education and body.use_profile:
            education = "Bachelor's degree"
        company = market()
        payload = build_pathway(
            occupation,
            taxonomy=catalog,
            ratings=ratings,
            resume_text=body.resume_text,
            education=education,
            experience_level=experience,
            current_role=body.current_role,
            hours_per_week=int(hours),
            market=company,
            resource_lookup=_resource_lookup(content, body.career_id),
        )
        payload["signals"] = signals
        payload["resume_text_used"] = bool(body.resume_text.strip())
        payload["hours_per_week"] = int(hours)
        return payload

    @router.get("/ladder")
    def ladder(
        career_id: str = "",
        hours_per_week: int = 6,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Entry points, lateral moves and steps up from a role (or your target)."""
        catalog = taxonomy()
        target = profiles.target(user.id)
        resolved = career_id or (target["career_id"] if target else "")
        if not resolved:
            raise HTTPException(422, "Set a target career first, or pass career_id.")
        occupation = catalog.get(resolved)
        if occupation is None:
            raise HTTPException(404, "Unknown career id.")
        profile = profiles.get(user.id)
        payload = build_ladder(
            occupation,
            catalog,
            ratings=journey.ratings(user.id, resolved),
            resume_text="",
            hours_per_week=max(1, min(40, int(hours_per_week))),
            market=market(),
            limit=6,
        )
        payload["profile_used"] = profile.to_dict() if profile else None
        return payload

    # -------------------------------------------------------------- compare
    @router.get("/compare")
    def compare(
        ids: str = Query(..., description="Comma-separated career ids (2–3)"),
        country: str = "in",
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        if not settings_store.module_enabled("compare"):
            raise HTTPException(503, "Comparison is disabled by the administrator.")
        wanted = [i.strip() for i in ids.split(",") if i.strip()][:3]
        if len(wanted) < 2:
            raise HTTPException(422, "Provide at least two career ids.")
        catalog = taxonomy()
        adapter = market()
        careers = []
        for career_id in wanted:
            occupation = catalog.get(career_id)
            if occupation is None:
                raise HTTPException(404, f"Unknown career id: {career_id}")
            careers.append(
                {
                    "id": occupation.id,
                    "title": occupation.title,
                    "description": occupation.description,
                    "job_zone": occupation.job_zone,
                    "skills": occupation.skills,
                    "knowledge": occupation.knowledge,
                    "technology": ranked_technology(occupation, limit=12),
                    "holland_code": occupation.holland_code,
                    "interests": occupation.interests,
                    "alt_titles": occupation.alt_titles,
                    "related": occupation.related,
                    "hot_technology": occupation.hot_technology,
                    "market": asdict(adapter.snapshot(occupation, country)),
                    "market_us": asdict(adapter.snapshot(occupation, "us")),
                    "remote": adapter.seed.remote_friendly(occupation),
                    "salary_band_in": adapter.seed.band(occupation, "in"),
                    "demand_label": adapter.seed.demand_label(occupation),
                    "family": (
                        adapter.seed.family_for(occupation).id
                        if adapter.seed.family_for(occupation)
                        else "other"
                    ),  # noqa: E501
                    "tasks": derive_tasks(occupation, limit=5),
                    "education_path": education_path(occupation),
                    "resources": [
                        asdict(r)
                        for skill in occupation.skills[:3]
                        for r in resources_for(skill, 1)
                    ],
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
                "label": f"Salary p50 ({country.upper()})",
                "values": [c["market"]["salary_p50"] for c in careers],
            },  # noqa: E501
            {"label": "Demand", "values": [c["demand_label"] for c in careers]},
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
            "template": explanations.render(
                "compare.headline", shared=", ".join(sorted(shared)[:4]) or "no shared core skill"
            ),
            "source": adapter.seed.label,
        }

    # ---------------------------------------------------------- transitions
    @router.get("/transitions")
    def transitions(
        from_id: str = Query(..., alias="from"),
        to_id: str = Query(..., alias="to"),
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        if not settings_store.module_enabled("transitions"):
            raise HTTPException(503, "Transition paths are disabled by the administrator.")
        catalog = taxonomy()
        for career_id in (from_id, to_id):
            if catalog.get(career_id) is None:
                raise HTTPException(404, f"Unknown career id: {career_id}")
        path = find_path(from_id, to_id, taxonomy=catalog)
        payload = path.to_dict()
        payload["template"] = (
            explanations.render(
                "transition.found",
                hops=payload["hops"],
                from_title=payload["from"]["title"],
                to_title=payload["to"]["title"],
            )
            if payload["found"]
            else explanations.render("transition.missing")
        )
        payload["source"] = payload.get("note", "Source: O*NET related-occupations graph")
        return payload

    # ------------------------------------------------------------ interview
    @router.get("/interview/questions")
    def interview(
        career_id: str,
        seed: int = 42,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        if not settings_store.module_enabled("interview"):
            raise HTTPException(503, "Interview practice is disabled by the administrator.")
        if taxonomy().get(career_id) is None:
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
    def save_session(body: InterviewBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        session_id = journey.save_interview(user.id, body.career_id, body.seconds, body.notes)
        gamification.award(user.id, "interview", body.career_id)
        return {"id": session_id, "xp": gamification.status(user.id)}

    @router.get("/interview/sessions")
    def sessions(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {"sessions": journey.interview_sessions(user.id)}

    # --------------------------------------------------------- gamification
    @router.get("/gamification")
    def xp(user: User = Depends(current_user)) -> dict:  # noqa: B008
        if not settings_store.module_enabled("gamification"):
            raise HTTPException(503, "Gamification is disabled by the administrator.")
        payload = gamification.status(user.id)
        payload["rules"] = XP_RULES
        return payload

    @router.post("/gamification/event")
    def xp_event(body: EventBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        gamification.award(user.id, body.kind, body.detail)
        return gamification.status(user.id)

    # ------------------------------------------------------- announcements
    @router.get("/announcements")
    def announcements(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return {
            "announcements": settings_store.announcements(active_only=True),
            "source": "Source: admin announcements",
        }

    # ------------------------------------------------------------ feedback
    @router.post("/feedback")
    def feedback(body: FeedbackBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        feedback_id = users.add_feedback(
            body.rating, body.comment, user.id, body.run_id, body.career_title
        )
        if body.tool:
            with users._connect() as conn:  # noqa: SLF001 - same package write
                conn.execute("UPDATE feedback SET tool = ? WHERE id = ?", (body.tool, feedback_id))
        gamification.award(user.id, "feedback", f"feedback:{feedback_id}")
        return {"id": feedback_id}

    # ------------------------------------------------------------ dashboard
    @router.get("/me/dashboard")
    def dashboard(user: User = Depends(current_user)) -> dict:  # noqa: B008
        profile = profiles.get(user.id)
        target = profiles.target(user.id)
        readiness_payload = None
        roadmap = None
        if target:
            ratings = journey.ratings(user.id, target["career_id"])
            result = evaluate(target["career_id"], ratings, taxonomy=taxonomy())
            readiness_payload = result.to_dict()
            readiness_payload["template"] = explanations.render(
                "readiness.summary",
                readiness=readiness_payload["readiness_weighted"],
                title=result.occupation.title,
                strong=readiness_payload["counts"]["strong"],
                weak=readiness_payload["counts"]["weak"],
                missing=readiness_payload["counts"]["missing"],
            )
            plan = journey.latest_plan(user.id)
            if plan and plan["career_id"] == target["career_id"]:
                roadmap = _roadmap_payload(plan, date.today())
        runs = [r for r in db.list_runs(limit=200) if r.user_id == user.id][:6]
        xp_payload = gamification.status(user.id)
        announcements_payload = settings_store.announcements(active_only=True)
        return {
            "profile": profile.to_dict() if profile else None,
            "target": target,
            "readiness": readiness_payload,
            "roadmap": roadmap,
            "xp": xp_payload,
            "streak": xp_payload["streak"],
            "recent_runs": [
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "provider": r.provider,
                    "is_demo": r.is_demo,
                    "tool": r.profile.get("tool", "recommend"),
                    "skills": str(r.profile.get("skills", ""))[:160],
                    "goals": str(r.profile.get("goals", "")),
                    "experience_level": r.profile.get("experience_level", ""),
                    "recommendations": [
                        {**asdict(rec), "match_percent": round(rec.match_score * 100, 1)}
                        for rec in r.recommendations
                    ],
                }
                for r in runs
            ],
            "assessments": assessments.history(user.id, limit=3),
            "announcements": announcements_payload,
            "source": "Source: your saved runs, self-ratings and activity in this app",
        }

    @router.get("/me/export")
    def export_me(user: User = Depends(current_user)) -> dict:  # noqa: B008
        payload = journey.export_user(user.id)
        profile = profiles.get(user.id)
        payload["profile"] = (
            profile.to_dict()
            if profile
            else {
                "user_id": user.id,
                "email": user.email,
                "onboarded": False,
                "skills": [],
                "note": "onboarding not completed yet",
            }
        )
        payload["account"] = user.public()
        payload["exported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload["note"] = "Complete copy of your data in this app (JSON)."
        return payload

    @router.get("/reports/career.pdf")
    @router.get("/me/report.pdf")
    def report(user: User = Depends(current_user)) -> Response:  # noqa: B008
        profile = profiles.get(user.id)
        target = profiles.target(user.id)
        readiness_payload = None
        roadmap = None
        if target:
            result = evaluate(
                target["career_id"],
                journey.ratings(user.id, target["career_id"]),
                taxonomy=taxonomy(),
            )  # noqa: E501
            readiness_payload = result.to_dict()
            roadmap = journey.latest_plan(user.id)
        matches = []
        runs = [r for r in db.list_runs(limit=50) if r.user_id == user.id]
        if runs:
            for rec in runs[0].recommendations[:5]:
                matches.append(
                    {
                        "title": rec.title,
                        "match_percent": round(rec.match_score * 100, 1),
                        "readiness": readiness_payload["readiness_weighted"]
                        if readiness_payload
                        else 0,
                        "why": (rec.provenance or {}).get("why") or [rec.match_reason],
                        "missing_skills": rec.missing_skills,
                    }
                )
        pdf = build_report(
            {
                "user": {"name": user.name, "email": user.email},
                "profile": profile.to_dict() if profile else {},
                "assessment": assessments.latest(user.id),
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

    @router.get("/me/activity")
    def activity(days: int = 30, user: User = Depends(current_user)) -> dict:  # noqa: B008
        daily = gamification.daily_xp(user.id, days=min(max(days, 7), 120))
        return {
            "daily": daily,
            "streak": gamification.streak(user.id),
            "levels": [
                {"level": i + 1, "name": name, "xp": xp} for i, (xp, name) in enumerate(_levels())
            ],
            "source": "Source: your XP events in this app",
        }

    return router


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _levels():
    from career_guidance.gamification import LEVELS

    return LEVELS


def _resource_lookup(content: ContentStore, career_id: str):
    """Roadmap resource lookup: admin DB rows first, curated YAML as fallback."""

    def lookup(skill: str, limit: int = 2):
        found = content.resources_for_skill(skill, limit)
        if found:
            return found
        return resources_for(skill, limit)

    return lookup


def _roadmap_object(plan: dict) -> Roadmap:
    """Rebuild a Roadmap object from the stored JSON for exports."""
    from career_guidance.models import LearningResource
    from career_guidance.roadmap import RoadmapItem

    items = [
        RoadmapItem(
            id=item["id"],
            week=int(item["week"]),
            skill=item["skill"],
            title=item["title"],
            hours=float(item["hours"]),
            status=item.get("status", "missing"),
            importance=float(item.get("importance", 5)) / 10,
            prerequisite_of=list(item.get("prerequisite_of", [])),
            resources=[
                LearningResource(
                    skill=resource.get("skill", item["skill"]),
                    title=resource.get("title", ""),
                    url=resource.get("url", ""),
                    provider=resource.get("provider", ""),
                    free=bool(resource.get("free", True)),
                )
                for resource in item.get("resources", [])
            ],
            milestone=item.get("milestone", ""),
        )
        for item in plan.get("items", [])
    ]
    return Roadmap(
        occupation_id=plan["career_id"],
        title=plan["title"],
        hours_per_week=int(plan["hours_per_week"]),
        weeks=int(plan["weeks"]),
        eta=plan["eta"],
        items=items,
        milestones=list(plan.get("milestones", [])),
        readiness_before=float(plan.get("readiness_before", 0)),
        readiness_after=float(plan.get("readiness_after", 0)),
        source=plan.get("source", ""),
    )


def related_rungs(occupation, catalog, market=None, limit: int = 6) -> list[dict]:
    """Who can move *into* this role: explicit related roles, else family peers.

    ``transitions_into`` only sees roles that list this one as ``related``; for
    most occupations that list is short. Falling back to “same family, lower or
    equal job zone, highest skill overlap” keeps the career page useful.
    """
    related = []
    for rid in occupation.related:
        occ = catalog.get(rid)
        if occ is not None:
            related.append(occ)
    if len(related) < 3 and market is not None:
        family = market.seed.family_for(occupation)
        for occ in catalog.occupations:
            if occ.id == occupation.id or occ.job_zone > occupation.job_zone:
                continue
            if family is not None and market.seed.family_for(occ) is not family:
                continue
            related.append(occ)
    seen: set[str] = set()
    out: list[dict] = []
    for occ in related:
        if occ.id in seen:
            continue
        seen.add(occ.id)
        delta, shared = delta_skills(occ, occupation, limit=4)
        out.append(
            {
                "id": occ.id,
                "title": occ.title,
                "job_zone": occ.job_zone,
                "delta_skills": delta,
                "shared_skills": shared,
                "source": "Source: shared-skill delta over the bundled catalogue",
            }
        )
        if len(out) >= limit:
            break
    return out


def ladder_summary(occupation, catalog, market=None) -> dict:
    """Small ladder block for the career page (entry / across / up)."""
    payload = build_ladder(occupation, catalog, market=market, limit=4)
    return {
        "entry_points": payload["entry_points"],
        "step_across": payload["step_across"],
        "step_up": payload["step_up"],
        "source": payload["source"],
    }


def career_extras(occupation, adapter, catalog) -> dict:
    """Career-page extras used by ``GET /api/v1/careers/{id}`` in main.py."""
    related = [catalog.get(rid) for rid in occupation.related]
    return {
        "technology": ranked_technology(occupation, limit=15),
        "hot_technology": ranked_technology(occupation, limit=6),
        "detected_from_skills": extract_skills(occupation.title),
        "tasks": derive_tasks(occupation, limit=8),
        "education_path": education_path(occupation),
        "skill_importance": [
            {"skill": skill, "importance": round(value, 3), "importance_10": round(value * 10, 1)}
            for skill, value in catalog_importance(occupation).items()
        ],
        "market_us": asdict(adapter.snapshot(occupation, "us")),
        "salary_band_in": adapter.seed.band(occupation, "in"),
        "demand_label": adapter.seed.demand_label(occupation),
        "remote": adapter.seed.remote_friendly(occupation),
        "family": (
            adapter.seed.family_for(occupation).id
            if adapter.seed.family_for(occupation)
            else "other"
        ),  # noqa: E501
        "indian_titles": adapter.seed.indian_titles(occupation),
        "transitions_in": transitions_into(occupation.id, taxonomy=catalog, limit=6)
        or related_rungs(occupation, catalog, market=adapter),
        "ladder": ladder_summary(occupation, catalog, market=adapter),
        "related": [{"id": r.id, "title": r.title, "job_zone": r.job_zone} for r in related if r],
        "source": adapter.seed.label,
    }
