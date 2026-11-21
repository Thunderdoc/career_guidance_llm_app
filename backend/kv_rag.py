"""Kaam-Vaani RAG router (Stage 2).

Mounted under ``/api/v1/kv/rag/*`` ONLY when the ``KV_RAG`` flag is on
(see ``backend/main.py``) — flag off means the route 404s as if it never
existed. Serves the Kaam-Vaani knowledge base (snapshot v2: 974 O*NET
occupation chunks + 66 India skilling/rights/scam chunks + 8
central-sphere minimum-wage chunks from Step 7B) with grounded,
cited answers and no LLM: the answer is a verbatim quote of the top
retrieved chunk, or a refusal when nothing grounds it.

Public (no session): the voice flow is guest-first, like ``/health`` and
``POST /recommend``. The retriever is built lazily from the DB on first
use and rebuilt when the snapshot version in the store changes, so a
re-ingest takes effect without a restart.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.kv_ratelimit import client_key, kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.cache import ANSWER_CACHE_MAXSIZE, LruCache, cache_key
from career_guidance.kaamvaani.dense import DenseRetriever
from career_guidance.kaamvaani.rag import (
    HybridRetriever,
    RagStore,
    answer_question,
)
from career_guidance.kaamvaani.trace import Trace, get_sink, hash_query

logger = logging.getLogger("career_guidance.kaamvaani.rag_router")


class SearchRequest(BaseModel):
    """A retrieval request (filters narrow before scoring)."""

    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=10)
    language: str | None = None
    topic: str | None = None
    state: str | None = None
    district: str | None = None


class AskRequest(BaseModel):
    """A grounded-answer request: one question, quoted answer or refusal."""

    question: str = Field(..., min_length=1, max_length=1000)


# Step 9.4: anonymous RAG calls are 30/min per IP (combined
# /search + /ask), the same budget as the base app's /recommend.
_LIMITER = kv_limiter(max_calls=30, per_seconds=60)


def build_router(settings: Settings) -> APIRouter:
    """Return the RAG router over ``settings.database_target``."""
    router = APIRouter(prefix="/api/v1/kv/rag", tags=["kaam-vaani-rag"])
    store = RagStore(settings.database_target)
    cache: dict[str, object] = {"versions": None, "retriever": None}
    # Answer/search cache (Step 8.6): keyed by (snapshot versions,
    # kind, query, top_k, filters), so a re-ingest can never serve a
    # pre-ingest answer — old entries become unreachable and age out
    # by LRU. Values are deep-copied on read (LruCache with
    # deepcopy_values=True), so a caller mutating a returned dict
    # cannot poison the cache.
    answers = LruCache(maxsize=ANSWER_CACHE_MAXSIZE, deepcopy_values=True)
    # Agent trace log (Step 8.9): the process-wide sink, shared with
    # the voice + matching routers and read by the admin endpoint.
    sink = get_sink(settings)

    def retriever() -> HybridRetriever:
        versions = tuple(store.snapshot_versions())
        if cache["retriever"] is None or cache["versions"] != versions:
            chunks = store.all_chunks()
            dense = None
            if settings.kv_dense_model:
                # Step 7A: fuse dense rankings when configured. Without
                # the packages the router stays hybrid-only (with a
                # warning), never faked — same rule as the voice
                # providers (Stage 3).
                try:
                    dense = DenseRetriever(chunks, settings.kv_dense_model)
                except RuntimeError as exc:
                    logger.warning("dense retrieval disabled: %s", exc)
            cache["retriever"] = HybridRetriever(chunks, dense=dense)
            cache["versions"] = versions
        return cache["retriever"]  # type: ignore[return-value]

    @router.get("/status")
    def status() -> dict:
        """What the knowledge base holds: chunk/topic counts, snapshot
        versions, and the distinct sources with their citations.
        ``cache`` reports the answer/search cache stats (hits, misses,
        hit rate) so the pilot can see whether repeated questions are
        being served from the cache."""
        return {
            "enabled": True,
            "chunks": store.count(),
            "by_topic": store.count_by_topic(),
            "snapshot_versions": store.snapshot_versions(),
            "sources": store.sources(),
            "cache": answers.stats().to_dict(),
        }

    @router.post("/search")
    def search(request: Request, body: SearchRequest) -> dict:
        """Top-``top_k`` chunks for ``query``, each with its citation.
        An empty store returns no hits (never an invented answer).
        Repeated identical searches are served from the answer cache
        (keyed by the snapshot versions, so a re-ingest invalidates).
        Every call is traced (Step 8.9): the response carries
        ``trace_id``; the trace itself holds counts and scores only,
        never the query text."""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        trace = Trace("/api/v1/kv/rag/search", query_hash=hash_query(body.query))
        versions = tuple(store.snapshot_versions())
        key = cache_key(
            "search",
            versions,
            body.query,
            body.top_k,
            body.language,
            body.topic,
            body.state,
            body.district,
        )
        cached = answers.get(key)
        if cached is not None:
            trace.cache_hit = True
            sink.store(trace.finish(status="ok", outcome="cache_hit"))
            return {**cached, "trace_id": trace.trace_id}
        try:
            with trace.span("retrieve") as span:
                hits = retriever().search(
                    body.query,
                    top_k=body.top_k,
                    language=body.language,
                    topic=body.topic,
                    state=body.state,
                    district=body.district,
                )
                span.detail["hits"] = len(hits)
                span.detail["top_score"] = round(hits[0].score, 4) if hits else 0.0
        except Exception:
            sink.store(trace.finish(status="error", outcome="error"))
            raise
        result = {"query": body.query, "hits": [h.to_dict() for h in hits]}
        answers.put(key, result)
        sink.store(trace.finish(status="ok", outcome="searched"))
        return {**result, "trace_id": trace.trace_id}

    @router.post("/ask")
    def ask(request: Request, body: AskRequest) -> dict:
        """A grounded answer: a verbatim quote of the best chunk with its
        citation, or a refusal (``refused: true`` with a reason) when the
        question is out of scope or nothing in the base grounds it.
        Repeated identical questions are served from the answer cache
        (keyed by the snapshot versions, so a re-ingest invalidates).
        Every call is traced (Step 8.9): the response carries
        ``trace_id``; the trace records the translate / retrieve /
        verify stages with latencies, and never the question text."""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        trace = Trace("/api/v1/kv/rag/ask", query_hash=hash_query(body.question))
        versions = tuple(store.snapshot_versions())
        key = cache_key("ask", versions, body.question)
        cached = answers.get(key)
        if cached is not None:
            trace.cache_hit = True
            sink.store(trace.finish(status="ok", outcome="cache_hit"))
            return {**cached, "trace_id": trace.trace_id}
        try:
            result = answer_question(body.question, retriever(), trace=trace)
        except Exception:
            sink.store(trace.finish(status="error", outcome="error"))
            raise
        answers.put(key, result)
        outcome = "answered" if not result["refused"] else f"refused:{result['reason']}"
        sink.store(trace.finish(status="ok", outcome=outcome))
        return {**result, "trace_id": trace.trace_id}

    return router
