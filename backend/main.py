"""FastAPI backend for Career Guidance AI v2.

Thin adapter over the UI-agnostic ``career_guidance`` package. Serves the
built Next.js front end from ``frontend/out`` when present.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.admin import build_me_router
from backend.admin_console import build_router as build_console_router
from backend.assessment import QUESTIONS, score_assessment
from backend.auth import Auth, load_auth_settings
from backend.auth import build_router as build_auth_router
from backend.journey import build_router as build_journey_router
from backend.ratelimit import RateLimiter
from career_guidance import __version__
from career_guidance.analytics import summarize
from career_guidance.config import configure_logging, load_settings
from career_guidance.learning import resources_for
from career_guidance.matching import get_matcher
from career_guidance.matching2 import DEFAULT_WEIGHTS
from career_guidance.models import InvalidInputError
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.resume import extract_resume_text
from career_guidance.storage import Database, runs_to_json, runs_to_markdown
from career_guidance.suggestions import format_recommendations_markdown, generate_recommendations
from career_guidance.taxonomy import extract_skills, load_taxonomy
from career_guidance.users import User, UserStore

load_dotenv()  # .env at repo root (ignored by git); real env vars take precedence
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
_auth_settings = load_auth_settings()
_users = UserStore(settings.database_path, _auth_settings.admin_emails)
_auth = Auth(_auth_settings, _users)
_auth_router, _current_user, _admin_user = build_auth_router(_auth)
_me_router = build_me_router(_users, _db, _current_user)
_journey_router = build_journey_router(settings, _current_user, _db, _users)
_admin_console_router = build_console_router(settings, _users, _db, _admin_user)
app.include_router(_auth_router)
app.include_router(_me_router)
app.include_router(_journey_router)
app.include_router(_admin_console_router)


# The product is private: every content endpoint requires a signed-in session.
# Only ``/health``, ``/meta``, ``/skills/suggest`` and ``/careers/search`` stay
# public (used by the sign-in screen and by uptime probes).
GUEST_ID = "guest"

_GUEST = User(
    id=GUEST_ID,
    email="guest@local",
    name="Guest",
    picture="",
    provider="guest",
    role="user",
    created_at="",
    last_login_at="",
)


def _optional_session(request: Request) -> User | None:
    return _auth.user_from(request)


def _session(request: Request) -> User:  # noqa: B008
    """Session-required dependency: 401 unless signed in.

    When the admin feature flag ``public_app`` (or env ``PUBLIC_APP=true``) is
    set, anonymous visitors are served as a stateless guest instead — the
    original open-mode behaviour, kept for local demos.
    """
    user = _auth.user_from(request)
    if user:
        return user
    if _public_app():
        return _GUEST
    raise HTTPException(401, "Sign in required.")


def _uid(user: User) -> str | None:
    """Owner id for stored rows: guests are stored as anonymous."""
    return None if user.id == GUEST_ID else user.id


@app.middleware("http")
async def _timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.0f}"
    return response


@app.on_event("startup")
def _warm() -> None:
    """Apply migrations and warm the cached catalog before the first request."""
    from career_guidance.content_store import ContentStore
    from career_guidance.migrations import LATEST_VERSION, migrate
    from career_guidance.settings_store import SettingsStore

    applied = migrate(settings.database_path)
    if applied:
        logger.info("Database migrated to v%s (applied %s)", LATEST_VERSION, applied)
    ContentStore(settings.database_path)  # creates admin content tables
    SettingsStore(settings.database_path)  # creates the settings table
    get_matcher()  # build the TF-IDF index once
    from career_guidance.learning import set_overrides

    set_overrides(_users.resource_overrides())
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


def _settings_store():
    from career_guidance.settings_store import SettingsStore

    return SettingsStore(settings.database_path)


def _content_store():
    from career_guidance.content_store import ContentStore

    return ContentStore(settings.database_path)


def _assessment_store():
    from career_guidance import riasec

    return riasec.AssessmentStore(settings.database_path)


def _gamification():
    from career_guidance.gamification import GamificationStore

    return GamificationStore(settings.database_path)


def _market_adapter():
    """Curated seeds + admin India overrides, live provider when configured."""
    from career_guidance.market_seed import load_seed
    from career_guidance.suggestions2 import market_payload  # noqa: F401

    store = _settings_store()
    overrides = store.get("market.live", None)
    if overrides:
        try:  # optional free API adapter (Adzuna) configured by admins
            from career_guidance.market import get_market_adapter
            from career_guidance.market_seed import SeedMarketAdapter

            seed = load_seed()
            adapter = SeedMarketAdapter(seed, live=get_market_adapter())
            adapter.set_overrides(_content_store().career_overrides())
            return adapter
        except Exception:  # noqa: BLE001 - fall back to curated seeds
            logger.warning("live market adapter unavailable", exc_info=True)
    from career_guidance.market_seed import build_adapter

    adapter = build_adapter()
    adapter.set_overrides(_content_store().career_overrides())
    return adapter


def _scoring_settings() -> dict:
    from career_guidance.matching2 import DEFAULT_WEIGHTS

    stored = _settings_store().scoring()
    return {
        "skills": float(stored.get("skills", DEFAULT_WEIGHTS["skills"])),
        "interests": float(stored.get("interests", DEFAULT_WEIGHTS["interests"])),
        "job_zone": float(stored.get("job_zone", DEFAULT_WEIGHTS["job_zone"])),
    }


def _locale_for(request: Request) -> str:
    """Locale for the explanation templates, from Accept-Language."""
    header = request.headers.get("accept-language", "")
    for candidate in (header[:2], header[3:5]):
        if candidate in ("en", "ta", "hi"):
            return candidate
    return "en"


def _public_app() -> bool:
    """True when anonymous visitors may use the app (default: private).

    Set ``PUBLIC_APP=true`` to re-open the product to anonymous visitors; the
    admin console feature flag of the same name wins when it is set.
    """
    try:
        from career_guidance.settings_store import SettingsStore

        overrides = SettingsStore(settings.database_path).overrides()
        if "flags.public_app" in overrides:  # an admin decided explicitly
            return bool(overrides["flags.public_app"])
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("PUBLIC_APP", "false").strip().lower() in {"1", "true", "yes", "on"}


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
        "auth": {"google": _auth_settings.google_enabled, "magic_link": True},
        "public_app": _public_app(),
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
def recommend(
    body: RecommendRequest,  # noqa: B008
    request: Request,
    user: User = Depends(_session),  # noqa: B008
) -> dict:
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

    # Interests: explicit quiz scores from the client, otherwise the most recent
    # stored assessment run for this user.
    interests = body.interests_profile
    if not interests:
        latest = _assessment_store().latest(user.id)
        interests = latest["scores"] if latest else None

    try:
        profile.validate()
    except InvalidInputError as error:
        raise HTTPException(422, str(error)) from error

    try:
        from career_guidance.suggestions2 import recommend_v2

        result = recommend_v2(
            profile,
            weights=_scoring_settings(),
            interests=interests,
            locale=_locale_for(request),
            taxonomy=_content_store().catalog(),
            db_path=settings.database_path,
            market=_market_adapter(),
        )
    except Exception:  # noqa: BLE001
        logger.exception("matcher v2 failed, falling back to the offline provider")
        from career_guidance.providers import get_provider

        try:
            fallback = generate_recommendations(profile, settings, get_provider(settings))
        except InvalidInputError as error:
            raise HTTPException(422, str(error)) from error
        result = {
            "provider": fallback.provider_name,
            "is_demo": fallback.is_demo,
            "used_fallback": True,
            "priority_skills": fallback.priority_skills,
            "detected_skills": extract_skills(body.skills),
            "unmatched_skills": [],
            "weights": DEFAULT_WEIGHTS,
            "recommendations": [
                {
                    **asdict(rec),
                    "match_percent": round(rec.match_score * 100, 1),
                    "readiness": round(rec.match_score * 100, 1),
                    "why": [rec.match_reason],
                    "score_parts": {"skills": rec.match_score, "interests": 0.0, "job_zone": 0.0},
                }
                for rec in fallback.recommendations
            ],
            "source": "Source: offline provider fallback (template explanations)",
        }

    run_id = None
    try:
        from career_guidance.models import CareerRecommendation

        stored = [CareerRecommendation.from_dict(rec) for rec in result["recommendations"]]
        readiness = stored[0].provenance.get("score_parts", {}).get("skills", 0) if stored else 0
        run_id = _db.save_run(
            {
                **profile.to_dict(),
                "tool": "recommend",
                "flagged": 0,
                "readiness": round(float(readiness) * 100, 1),
            },
            stored,
            result["provider"],
            result["is_demo"],
            _uid(user),
        )
        _settings_store().record_tool("recommend", user.id, f"run {run_id}")
    except Exception:  # noqa: BLE001
        logger.exception("persist failed")

    try:
        _gamification().award(user.id, "run", f"run:{run_id}")
    except Exception:  # noqa: BLE001 - gamification must never break a run
        logger.warning("gamification award failed", exc_info=True)

    return {
        "run_id": run_id,
        "provider": result["provider"],
        "is_demo": result["is_demo"],
        "used_fallback": result["used_fallback"],
        "priority_skills": result["priority_skills"],
        "detected_skills": result["detected_skills"],
        "unmatched_skills": result.get("unmatched_skills", []),
        "weights": result["weights"],
        "recommendations": result["recommendations"],
        "source": result.get("source", ""),
    }


@app.post("/api/v1/resume/extract")
async def resume_extract(
    file: UploadFile = File(...),  # noqa: B008
    _: User = Depends(_session),  # noqa: B008
) -> dict:
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
    tax = _content_store().catalog()
    return {
        "results": [
            {"id": o.id, "title": o.title, "job_zone": o.job_zone} for o in tax.search(q, limit)
        ]
    }


@app.get("/api/v1/careers/{career_id}")
def career_detail(
    career_id: str,  # noqa: B008
    country: str = "in",
    _: User = Depends(_session),  # noqa: B008
) -> dict:
    """One career with tasks, education path, market bands and transitions."""
    from backend.journey import career_extras

    taxonomy = _content_store().catalog()
    occupation = taxonomy.get(career_id)
    if not occupation:
        raise HTTPException(404, "Unknown occupation.")
    adapter = _market_adapter()
    payload = {
        "id": occupation.id,
        "title": occupation.title,
        "description": occupation.description,
        "job_zone": occupation.job_zone,
        "skills": occupation.skills,
        "knowledge": occupation.knowledge,
        "alt_titles": occupation.alt_titles,
        "holland_code": occupation.holland_code,
        "interests": occupation.interests,
        "market": asdict(adapter.snapshot(occupation, country)),
        "source": adapter.seed.label,
    }
    payload.update(career_extras(occupation, adapter, taxonomy))
    return payload


@app.get("/api/v1/assessment/questions")
def assessment_questions(_: User = Depends(_session)) -> dict:  # noqa: B008
    return {"questions": QUESTIONS}


@app.post("/api/v1/assessment")
def assessment(body: AssessmentRequest, _: User = Depends(_session)) -> dict:  # noqa: B008
    return score_assessment(body.answers)


@app.post("/api/v1/jobs/fit")
def job_fit(body: FitRequest, user: User = Depends(_session)) -> dict:  # noqa: B008
    """Rule-based JD fit: matched/missing keywords, readiness and free courses."""
    have = set(extract_skills(body.skills)) | set(extract_skills(body.resume_text))
    need = [s for s in extract_skills(body.job_description) if len(s) > 2][:30]
    matched = [s for s in need if s in have]
    missing = [s for s in need if s not in have]
    readiness = round(100 * len(matched) / len(need), 1) if need else 0
    breakdown = {
        "keyword_coverage": round(100 * len(matched) / len(need), 1) if need else 0,
        "resume_signal": round(100 * min(1.0, len(extract_skills(body.resume_text)) / 10), 1),
        "skills_box_signal": round(100 * min(1.0, len(have) / 12), 1),
    }
    try:
        _gamification().award(user.id, "jobfit", f"jd:{len(need)}")
    except Exception:  # noqa: BLE001
        logger.warning("gamification award failed", exc_info=True)
    return {
        "readiness": readiness,
        "matched": matched,
        "missing": missing,
        "keywords_to_add": missing[:10],
        "score_breakdown": breakdown,
        "resources": [asdict(r) for s in missing[:4] for r in resources_for(s, 1)],
        "source": "Source: O*NET skill extractor over your resume + the pasted job description",
    }


@app.get("/api/v1/history")
def history(user: User = Depends(_session), limit: int = 50) -> dict:  # noqa: B008
    uid = _uid(user)
    runs = [r for r in _db.list_runs(limit=1000) if r.user_id == uid][:limit]
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
def clear_history(user: User = Depends(_session)) -> dict:  # noqa: B008
    uid = _uid(user)
    for r in _db.list_runs(limit=5000):
        if r.user_id == uid:
            _db.delete_run(r.id)
    return {"cleared": True}


@app.get("/api/v1/analytics")
def analytics(user: User = Depends(_session)) -> dict:  # noqa: B008
    uid = _uid(user)
    runs = (
        _db.list_runs(limit=1000)
        if user.is_admin
        else [r for r in _db.list_runs(limit=1000) if r.user_id == uid]
    )
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
def export_run(run_id: int, fmt: Literal["md", "json"], user: User = Depends(_session)):  # noqa: B008
    run = next((r for r in _db.list_runs(limit=1000) if r.id == run_id), None)
    if not run or (run.user_id != _uid(user) and not user.is_admin):
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
def export_history(fmt: Literal["md", "json"], user: User = Depends(_session)):  # noqa: B008
    uid = _uid(user)
    runs = (
        _db.list_runs(limit=1000)
        if user.is_admin
        else [r for r in _db.list_runs(limit=1000) if r.user_id == uid]
    )
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
