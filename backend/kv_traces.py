"""Kaam-Vaani agent trace admin router (Step 8.9).

Mounted under ``/api/v1/kv/traces/*`` ONLY when a trace producer is
on (``KV_RAG`` or ``KV_VOICE`` — see ``backend/main.py``). Both
endpoints are ADMIN-ONLY (the ``admin_user`` dependency): traces
hold no PII by construction, but they are still operational data
and do not belong in a public feed.

Endpoints
---------
* ``GET /api/v1/kv/traces?limit=50`` — the most recent traces,
  newest first (``limit`` clamped to 1..200).
* ``GET /api/v1/kv/traces/{trace_id}`` — one trace by its id, or
  404 when the id is unknown (or has aged out of the ring).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from career_guidance.config import Settings
from career_guidance.kaamvaani.trace import get_sink
from career_guidance.users import User


def build_router(settings: Settings, admin_user) -> APIRouter:
    """Return the traces router. ``admin_user`` is the FastAPI
    dependency that admits admins only (from ``backend.auth``)."""
    router = APIRouter(prefix="/api/v1/kv/traces", tags=["kaam-vaani-traces"])
    sink = get_sink(settings)

    @router.get("")
    def list_traces(limit: int = 50, user: User = Depends(admin_user)) -> dict:  # noqa: B008
        """The most recent traces, newest first."""
        limit = max(1, min(200, limit))
        traces = sink.recent(limit)
        return {"traces": traces, "count": len(traces)}

    @router.get("/{trace_id}")
    def get_trace(trace_id: str, user: User = Depends(admin_user)) -> dict:  # noqa: B008
        """One trace by id, or 404 when unknown / aged out."""
        record = sink.get(trace_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"unknown trace: {trace_id}")
        return record

    return router
