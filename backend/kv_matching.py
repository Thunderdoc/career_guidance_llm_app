"""Kaam-Vaani matching router (Stage 4).

Mounted under ``/api/v1/kv/*`` ONLY when the ``KV_VOICE`` flag is on
(see ``backend/main.py``) — matching is part of the voice flow, so it
shares the voice flag; flag off means the routes 404 as if they never
existed. (The RAG course citations read the Stage 2 knowledge base
directly from the store — the ``KV_RAG`` flag gates the RAG *router*,
not the data — so citations work whenever the snapshot is loaded, and
are honestly empty when it is not.)

Endpoints
---------
* ``POST /matches`` — the client round-trips its session (state
  ``matches``, as returned by ``/kv/voice/confirm``) plus the
  user-confirmed profile; the server returns the Top-5 Kaam-Vaani
  matches (see ``career_guidance.kaamvaani.matching``) with score
  components, matched/missing skills and structured why-it-fits
  reasons. The session is returned unchanged — fetching matches does
  not advance the flow.
* ``POST /gap-learning`` — the client round-trips its session (state
  ``matches`` or ``gap_learning``) plus the profile and the
  occupation the user picked; the server validates the
  ``matches`` → ``gap_learning`` state-machine transition and returns
  the skill gap (through the shared ``skillgap`` engine), a free
  learning path (curated catalogue, every item sourced) and RAG
  course citations (SWAYAM/NPTEL/NSDC/PMKVY sources from the Stage 2
  knowledge base). Re-calling it from ``gap_learning`` for another
  occupation is legal — the user may open several matches.

Public (no session): the voice flow is guest-first, like ``/health``
and ``POST /recommend``. The server stores no session and no
transcript — the client holds the session in ``sessionStorage``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.kv_ratelimit import client_key, kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.matching import (
    KVScorer,
    course_citations_for,
    gap_for_match,
    learning_path_for,
)
from career_guidance.kaamvaani.profile import VoiceSession, transition
from career_guidance.kaamvaani.rag import HybridRetriever, RagStore
from career_guidance.kaamvaani.skillgraph import skill_plan_for
from career_guidance.kaamvaani.trace import Trace, get_sink, hash_query

logger = logging.getLogger("career_guidance.kv_matching")


class MatchesRequest(BaseModel):
    """A confirmed session (state ``matches``) + the confirmed profile
    to rank. ``top_k`` is 5 by default (the F2 Top-5)."""

    session: VoiceSession
    profile: VoiceProfile
    top_k: int = Field(5, ge=1, le=10)


class GapLearningRequest(BaseModel):
    """A session in ``matches`` (or already ``gap_learning``) + the
    profile + the occupation the user wants the gap/learning path for."""

    session: VoiceSession
    profile: VoiceProfile
    occupation_id: str = Field(..., min_length=1, max_length=32)


# Step 9.4: anonymous matching calls are 30/min per IP
# (combined /matches + /gap-learning).
_LIMITER = kv_limiter(max_calls=30, per_seconds=60)


def build_router(settings: Settings) -> APIRouter:
    """Return the matching router. ``settings`` selects the DB target
    (for RAG course citations) — the scorer itself needs no settings."""
    router = APIRouter(prefix="/api/v1/kv", tags=["kaam-vaani-matching"])
    scorer = KVScorer()
    store = RagStore(settings.database_target)
    cache: dict[str, object] = {"versions": None, "retriever": None}
    # Agent trace log (Step 8.9): the process-wide sink, shared with
    # the RAG + voice routers and read by the admin endpoint.
    sink = get_sink(settings)

    def retriever() -> HybridRetriever:
        versions = tuple(store.snapshot_versions())
        if cache["retriever"] is None or cache["versions"] != versions:
            cache["retriever"] = HybridRetriever(store.all_chunks())
            cache["versions"] = versions
        return cache["retriever"]  # type: ignore[return-value]

    @router.post("/matches")
    def matches(request: Request, body: MatchesRequest) -> dict:
        """Top-``top_k`` Kaam-Vaani matches for a confirmed profile.
        Only legal from the ``matches`` state — a session that has not
        confirmed its profile gets a 400, never matches for an
        unconfirmed profile. A successful call is traced (Step 8.9):
        the response carries ``trace_id``; the trace records the
        ranking counts and top score only, never the profile. (A 400
        is a client state error, not agent work — it is not traced.)"""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        if body.session.state != "matches":
            raise HTTPException(
                status_code=400,
                detail=f"matches is only legal from the matches state, not {body.session.state}",
            )
        # The profile identifies the request by its hash only — the
        # trace never carries profile content.
        trace = Trace(
            "/api/v1/kv/matches",
            query_hash=hash_query(body.profile.model_dump_json()),
        )
        try:
            with trace.span("match") as span:
                ranked, meta = scorer.rank(body.profile, top_k=body.top_k)
                span.detail["returned"] = len(ranked)
                span.detail["top_score"] = round(ranked[0].score, 4) if ranked else 0.0
                span.detail["target_zone"] = meta["target_zone"]
                span.detail["excluded_zone"] = meta["excluded_zone"]
        except Exception:
            sink.store(trace.finish(status="error", outcome="error"))
            raise
        sink.store(trace.finish(status="ok", outcome="matched"))
        return {
            "session": body.session.model_dump(mode="json"),
            "matches": [m.to_dict() for m in ranked],
            "target_zone": meta["target_zone"],
            "excluded_zone": meta["excluded_zone"],
            "trace_id": trace.trace_id,
        }

    @router.post("/gap-learning")
    def gap_learning(request: Request, body: GapLearningRequest) -> dict:
        """Gap + free learning path + RAG course citations for one
        occupation, and the server-validated ``matches`` →
        ``gap_learning`` transition. An unknown occupation is a 404; a
        session that has not reached matches is a 400."""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        session = body.session
        if session.state == "matches":
            try:
                session = transition(session, "to_gap_learning")
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        elif session.state != "gap_learning":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"gap-learning is only legal from matches or gap_learning, not {session.state}"
                ),
            )
        match = scorer.match_for(body.profile, body.occupation_id)
        if match is None:
            raise HTTPException(status_code=404, detail=f"unknown occupation: {body.occupation_id}")
        gap = gap_for_match(match, scorer.taxonomy)
        learning_path = learning_path_for(match.missing)
        # Ordered skill-gap plan (Step 8.2): cheapest path per gap
        # skill, topologically ordered, shared courses counted once,
        # uncovered gaps listed honestly. Held = the matched core
        # competencies + the profile's canonical skills (the latter
        # lets DOMAIN_HINTS compression recognise e.g. python as
        # covering the programming competency). Additive: the flat
        # learning_path stays as-is for existing clients.
        skill_plan = skill_plan_for(match.missing, match.matched + list(body.profile.skills))
        # Citations are enrichment on top of the gap + learning path:
        # when the RAG store is unavailable (no snapshot loaded, table
        # missing) the endpoint still returns the core payload with
        # empty citations — and says so in the logs — instead of 500ing
        # a user who only needs the gap.
        try:
            citations = course_citations_for(retriever(), match.occupation.title, match.missing)
        except Exception as error:  # noqa: BLE001 - citations are best-effort
            logger.warning("RAG course citations unavailable: %s", error)
            citations = []
        return {
            "session": session.model_dump(mode="json"),
            "next_state": session.state,
            "career_id": match.occupation.id,
            "title": match.occupation.title,
            "match_percent": match.match_percent,
            "gap": gap,
            "learning_path": learning_path,
            "skill_plan": skill_plan,
            "citations": citations,
        }

    return router
