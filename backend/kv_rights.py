"""Kaam-Vaani rights/scam assistant router (Step 9.1).

Mounted under ``/api/v1/kv/rights/*`` ONLY when the ``KV_RAG`` flag
is on (see ``backend/main.py``) — the rights assistant is a
topic-restricted view of the same RAG, not a separate knowledge
base. Flag off means the route 404s as if it never existed.

Public (no session): the voice flow is guest-first, like ``/health``
and ``POST /recommend`` — a worker who may have been scammed must
not need an account to ask for help. The retriever is built lazily
from the DB on first use and rebuilt when the snapshot version in
the store changes, so a re-ingest takes effect without a restart.
This router builds its own retriever (like ``kv_rag`` does): two
~4 s first-request builds per process, once, at pilot scale.

Answers are grounded quotes with citations, or refusals; a scam
question also carries an ``escalation`` block of verified helpline
numbers (see ``career_guidance/kaamvaani/rights.py``) — never an
invented number.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.kv_ratelimit import client_key, kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.cache import ANSWER_CACHE_MAXSIZE, LruCache, cache_key
from career_guidance.kaamvaani.dense import DenseRetriever
from career_guidance.kaamvaani.rag import HybridRetriever, RagStore
from career_guidance.kaamvaani.rights import (
    RIGHTS_TOPICS,
    answer_rights_question,
    load_helplines,
)
from career_guidance.kaamvaani.trace import Trace, get_sink, hash_query

logger = logging.getLogger("career_guidance.kaamvaani.rights_router")


class RightsAskRequest(BaseModel):
    """A rights/scam question: one question, quoted answer or refusal."""

    question: str = Field(..., min_length=1, max_length=1000)


# Step 9.4: anonymous rights calls are 30/min per IP.
_LIMITER = kv_limiter(max_calls=30, per_seconds=60)


def build_router(settings: Settings) -> APIRouter:
    """Return the rights router over ``settings.database_target``."""
    router = APIRouter(prefix="/api/v1/kv/rights", tags=["kaam-vaani-rights"])
    store = RagStore(settings.database_target)
    cache: dict[str, object] = {"versions": None, "retriever": None}
    # Answer cache (Step 8.6 pattern): keyed by (snapshot versions,
    # kind, question), so a re-ingest can never serve a pre-ingest
    # answer. Values are deep-copied on read, so a caller mutating a
    # returned dict cannot poison the cache.
    answers = LruCache(maxsize=ANSWER_CACHE_MAXSIZE, deepcopy_values=True)
    sink = get_sink(settings)

    def retriever() -> HybridRetriever:
        versions = tuple(store.snapshot_versions())
        if cache["retriever"] is None or cache["versions"] != versions:
            chunks = store.all_chunks()
            dense = None
            if settings.kv_dense_model:
                try:
                    dense = DenseRetriever(chunks, settings.kv_dense_model)
                except RuntimeError as exc:
                    logger.warning("dense retrieval disabled: %s", exc)
            cache["retriever"] = HybridRetriever(chunks, dense=dense)
            cache["versions"] = versions
        return cache["retriever"]  # type: ignore[return-value]

    @router.get("/status")
    def status() -> dict:
        """What the rights assistant covers: chunk counts per rights
        topic, the verified helplines it may quote (numbers are
        public helplines), snapshot versions, and answer-cache
        stats."""
        by_topic = store.count_by_topic()
        helplines = load_helplines()
        return {
            "enabled": True,
            "topics": {topic: by_topic.get(topic, 0) for topic in RIGHTS_TOPICS},
            "chunks": sum(by_topic.get(topic, 0) for topic in RIGHTS_TOPICS),
            "helplines": [
                {"number": entry["number"], "name": entry["name"]} for entry in helplines
            ],
            "snapshot_versions": store.snapshot_versions(),
            "cache": answers.stats().to_dict(),
        }

    @router.post("/ask")
    def ask(request: Request, body: RightsAskRequest) -> dict:
        """A grounded rights/scam answer: a verbatim quote of the
        best rights-topic chunk with its citation, or a refusal
        (``refused: true`` with a reason) when nothing in the rights
        topics grounds it. A scam question also carries an
        ``escalation`` block of verified helpline numbers. Repeated
        identical questions are served from the answer cache (keyed
        by the snapshot versions, so a re-ingest invalidates). Every
        call is traced (Step 8.9): the response carries
        ``trace_id``; the trace records the translate / retrieve /
        verify stages with latencies, and never the question text."""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        trace = Trace("/api/v1/kv/rights/ask", query_hash=hash_query(body.question))
        versions = tuple(store.snapshot_versions())
        key = cache_key("rights-ask", versions, body.question)
        cached = answers.get(key)
        if cached is not None:
            trace.cache_hit = True
            sink.store(trace.finish(status="ok", outcome="cache_hit"))
            return {**cached, "trace_id": trace.trace_id}
        try:
            result = answer_rights_question(body.question, retriever(), trace=trace)
        except Exception:
            sink.store(trace.finish(status="error", outcome="error"))
            raise
        answers.put(key, result)
        outcome = "answered" if not result["refused"] else f"refused:{result['reason']}"
        sink.store(trace.finish(status="ok", outcome=outcome))
        return {**result, "trace_id": trace.trace_id}

    return router
