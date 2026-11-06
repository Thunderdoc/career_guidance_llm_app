"""Phase 7 route: POST /api/v1/chat — scoped chat over one stored run.

Access rules (server-side, re-checked on every call):
* signed-in caller: the run must be theirs (``user_id`` match) or an
  anonymous run (``user_id IS NULL`` — a guest run from their own guest
  session, Phase 1 semantics);
* guest caller (no session): only anonymous runs are visible;
* anyone else's run → 404 (never 403, so existence is not leaked).

Rate-limited per caller/IP. No streaming: the stack has no SSE pattern
anywhere (checked Phase 7), so the contract is plain JSON request/response.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.ratelimit import RateLimiter
from career_guidance.chat import answer_chat, build_context
from career_guidance.providers import ProviderFactory
from career_guidance.taxonomy import load_taxonomy
from career_guidance.users import User

logger = logging.getLogger("career_guidance.chat_api")

_chat_limiter = RateLimiter(max_calls=20, per_seconds=60)


class ChatBody(BaseModel):
    run_id: int
    message: str = Field(min_length=1, max_length=1000)


def build_router(settings, optional_user, db) -> APIRouter:
    """``optional_user(request) -> User | None`` (guest = None)."""
    router = APIRouter(prefix="/api/v1", tags=["chat"])
    plans = None
    try:
        from career_guidance.roadmap import Plan90Store

        plans = Plan90Store(settings.database_path)
    except Exception:  # noqa: BLE001 - plan context is additive only
        logger.warning("90-day plan store unavailable for chat", exc_info=True)

    @router.post("/chat")
    def chat(body: ChatBody, request: Request) -> dict:  # noqa: B008
        user: User | None = optional_user(request)
        key = f"chat:{user.id if user else (request.client.host if request.client else '?')}"
        if not _chat_limiter.allow(key):
            raise HTTPException(429, "Too many chat messages — please wait a minute.")
        run = next((r for r in db.list_runs(limit=1000) if r.id == body.run_id), None)
        if run is None:
            raise HTTPException(404, "Run not found.")
        if user is None:
            if run.user_id is not None:
                raise HTTPException(404, "Run not found.")
        elif run.user_id is not None and run.user_id != user.id:
            raise HTTPException(404, "Run not found.")

        plan = None
        if plans is not None and user is not None:
            try:
                latest = plans.latest(user.id)
                if latest and latest.get("run_id") == run.id:
                    plan = latest
            except Exception:  # noqa: BLE001 - plan context is additive only
                logger.warning("chat plan lookup failed", exc_info=True)

        context = build_context(
            run.profile,
            run.recommendations,
            taxonomy=load_taxonomy(),
            plan=plan,
            message=body.message,
        )
        completer = ProviderFactory.create_completer(settings)
        reply = answer_chat(body.message, context, completer)
        return {
            "run_id": run.id,
            "answer": reply.answer,
            "mode": reply.mode,
            "refused": reply.refused,
            "refusal_key": reply.refusal_key,
        }

    return router
