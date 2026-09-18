"""FastAPI backend for Career Guidance AI v2.

Thin adapter over the UI-agnostic ``career_guidance`` package. Serves the
built Next.js front end from ``frontend/out`` when present.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.assessment import QUESTIONS, score_assessment
from backend.ratelimit import RateLimiter
from career_guidance import __version__
from career_guidance.analytics import summarize
from career_guidance.config import configure_logging, load_settings
from career_guidance.learning import resources_for
from career_guidance.market import get_market_adapter
from career_guidance.matching import get_matcher
from career_guidance.models import InvalidInputError
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.resume import extract_resume_text
from career_guidance.storage import Database, runs_to_json, runs_to_markdown
from career_guidance.suggestions import format_recommendations_markdown, generate_recommendations
from career_guidance.taxonomy import extract_skills, load_taxonomy

settings = load_settings()
logger = configure_logging(settings)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI(
    title="Career Guidance AI API",
    version=__version__,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # front end is same-origin in prod; permissive for dev previews
    allow_methods=["*"],
    allow_headers=["*"],
)
_limiter = RateLimiter(max_calls=30, per_seconds=60)
_db = Database(settings.database_path)


@app.middleware("http")
async def _timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.0f}"
    return response


@app.on_event("startup")
def _warm() -> None:
    get_matcher()  # build TF-IDF index once
    logger.info("Taxonomy engine ready (%d occupations)", len(load_taxonomy()))


# ----------------------------------------------------------------------------- #
# Schemas
# ----------------------------------------------------------------------------- #


class RecommendRequest(BaseModel):
    skills: str = ""
    interests: str = ""
    education: str = ""
    experience_level: str = EXPERIENCE_LEVELS[0]
    goals: str = ""
    resume_text: str = ""
    interests_profile: dict[str, float] | None = Field(
        default=None, description="RIASEC scores from /assessment"
    )
    country: Literal["in", "gb", "us"] = "in"


class AssessmentRequest(BaseModel):
    answers: dict[str, int] = Field(description="question id -> 1..5 agreement")


class FitRequest(BaseModel):
    skills: str
    resume_text: str = ""
    job_description: str


def _client(request: Request) -> str:
    return request.headers.get(
        "x-forwarded-for", request.client.host if request.client else "?"
    ).split(",")[0]


def _rec_dict(rec) -> dict:
    return asdict(rec)


# ----------------------------------------------------------------------------- #
# Routes
# ----------------------------------------------------------------------------- #


@app.get("/api/v1/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ai_mode": bool(settings.openai_api_key),
        "occupations": len(load_taxonomy()),
    }


@app.get("/api/v1/meta")
def meta() -> dict:
    return {
        "experience_levels": list(EXPERIENCE_LEVELS),
        "ai_mode": bool(settings.openai_api_key),
        "occupations": len(load_taxonomy()),
        "version": __version__,
    }


@app.post("/api/v1/recommend")
def recommend(body: RecommendRequest, request: Request) -> dict:
    if not _limiter.allow(_client(request)):
        raise HTTPException(429, "Too many requests — please wait a minute.")
    if body.experience_level not in EXPERIENCE_LEVELS:
        raise HTTPException(422, "Unknown experience level.")
    profile = CareerProfile(
        skills=body.skills,
        interests=body.interests,
        education=body.education,
        experience_level=body.experience_level,
        goals=body.goals,
        resume_text=body.resume_text,
    )
    try:
        from career_guidance.providers import get_provider

        provider = get_provider(settings)
        if body.interests_profile and hasattr(provider, "interests"):
            provider.interests = body.interests_profile
        result = generate_recommendations(profile, settings, provider)
    except InvalidInputError as error:
        raise HTTPException(422, str(error)) from error
    except Exception:  # noqa: BLE001
        logger.exception("recommendation failed")
        raise HTTPException(500, "Something went wrong generating recommendations.") from None

    run_id = None
    try:
        run_id = _db.save_run(
            profile.to_dict(), result.recommendations, result.provider_name, result.is_demo
        )
    except Exception:  # noqa: BLE001
        logger.exception("persist failed")

    return {
        "run_id": run_id,
        "provider": result.provider_name,
        "is_demo": result.is_demo,
        "used_fallback": result.used_fallback,
        "priority_skills": result.priority_skills,
        "detected_skills": extract_skills(body.skills)
        + [s for s in extract_skills(body.resume_text) if s not in extract_skills(body.skills)],
        "recommendations": [_rec_dict(r) for r in result.recommendations],
    }


@app.post("/api/v1/resume/extract")
async def resume_extract(file: UploadFile = File(...)) -> dict:  # noqa: B008
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Resume exceeds 5 MB.")
    try:
        text = extract_resume_text(file.filename or "resume.txt", data)
    except InvalidInputError as error:
        raise HTTPException(422, str(error)) from error
    return {"characters": len(text), "text": text, "skills": extract_skills(text)}


@app.get("/api/v1/skills/suggest")
def skills_suggest(q: str = "", limit: int = 8) -> dict:
    q = q.strip().lower()
    if len(q) < 2:
        return {"suggestions": []}
    from career_guidance.taxonomy import SKILL_SYNONYMS

    pool = list(SKILL_SYNONYMS)
    starts = [s for s in pool if s.startswith(q)]
    contains = [s for s in pool if q in s and s not in starts]
    syn = [
        c
        for c, syns in SKILL_SYNONYMS.items()
        if any(x.startswith(q) for x in syns) and c not in starts + contains
    ]
    return {"suggestions": (starts + contains + syn)[:limit]}


@app.get("/api/v1/careers/search")
def careers_search(q: str, limit: int = 10) -> dict:
    tax = load_taxonomy()
    return {
        "results": [
            {"id": o.id, "title": o.title, "job_zone": o.job_zone} for o in tax.search(q, limit)
        ]
    }


@app.get("/api/v1/careers/{career_id}")
def career_detail(career_id: str, country: str = "in") -> dict:
    occ = load_taxonomy().get(career_id)
    if not occ:
        raise HTTPException(404, "Unknown occupation.")
    related = [load_taxonomy().get(r) for r in occ.related]
    return {
        **asdict(occ),
        "technology": occ.technology[:15],
        "market": asdict(get_market_adapter().snapshot(occ, country)),
        "related": [{"id": r.id, "title": r.title, "job_zone": r.job_zone} for r in related if r],
        "resources": [asdict(x) for s in occ.skills[:3] for x in resources_for(s, 1)],
    }


@app.get("/api/v1/assessment/questions")
def assessment_questions() -> dict:
    return {"questions": QUESTIONS}


@app.post("/api/v1/assessment")
def assessment(body: AssessmentRequest) -> dict:
    return score_assessment(body.answers)


@app.post("/api/v1/jobs/fit")
def job_fit(body: FitRequest) -> dict:
    have = set(extract_skills(body.skills)) | set(extract_skills(body.resume_text))
    need = extract_skills(body.job_description)
    need = [s for s in need if len(s) > 2][:25]
    matched = [s for s in need if s in have]
    missing = [s for s in need if s not in have]
    readiness = round(100 * len(matched) / len(need)) if need else 0
    return {
        "readiness": readiness,
        "matched": matched,
        "missing": missing,
        "resources": [asdict(r) for s in missing[:4] for r in resources_for(s, 1)],
    }


@app.get("/api/v1/history")
def history(limit: int = 50) -> dict:
    runs = _db.list_runs(limit=limit)
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
                "recommendations": [_rec_dict(x) for x in r.recommendations],
            }
            for r in runs
        ]
    }


@app.delete("/api/v1/history")
def clear_history() -> dict:
    _db.clear()
    return {"cleared": True}


@app.get("/api/v1/analytics")
def analytics() -> dict:
    runs = _db.list_runs(limit=1000)
    if not runs:
        return {"total_runs": 0}
    s = summarize(runs)
    return {
        "total_runs": s.total_runs,
        "ai_runs": s.ai_runs,
        "demo_runs": s.demo_runs,
        "top_careers": s.top_careers,
        "top_missing_skills": s.top_missing_skills,
        "runs_per_day": s.runs_per_day,
    }


@app.get("/api/v1/export/{run_id}.{fmt}")
def export_run(run_id: int, fmt: Literal["md", "json"]):
    run = next((r for r in _db.list_runs(limit=1000) if r.id == run_id), None)
    if not run:
        raise HTTPException(404, "Run not found.")
    if fmt == "json":
        return PlainTextResponse(
            runs_to_json([run]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=career-run-{run_id}.json"},
        )
    return PlainTextResponse(
        format_recommendations_markdown(run.recommendations),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=career-run-{run_id}.md"},
    )


@app.get("/api/v1/export/history.{fmt}")
def export_history(fmt: Literal["md", "json"]):
    runs = _db.list_runs(limit=1000)
    body = runs_to_json(runs) if fmt == "json" else runs_to_markdown(runs)
    return PlainTextResponse(
        body, media_type="application/json" if fmt == "json" else "text/markdown"
    )


# ----------------------------------------------------------------------------- #
# Static front end (production)
# ----------------------------------------------------------------------------- #

_STATIC = Path(__file__).resolve().parent.parent / "frontend" / "out"
if _STATIC.exists():
    app.mount("/_next", StaticFiles(directory=_STATIC / "_next"), name="next-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = _STATIC / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        html = _STATIC / f"{path}.html" if path else _STATIC / "index.html"
        if html.is_file():
            return FileResponse(html)
        return FileResponse(_STATIC / "index.html")
