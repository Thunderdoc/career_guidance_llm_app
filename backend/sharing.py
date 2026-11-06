"""Phase 8 routes: shareable report links.

Mounted under ``/api/v1``:

- ``POST   /runs/{run_id}/share`` — mint a link (owner only). Body:
  ``{expiry_days}`` (default 7, max 30). The raw token is returned **once**,
  in this response only; at rest only its SHA-256 hash exists.
- ``GET    /runs/{run_id}/shares`` — the owner's links for a run (metadata
  only — ids, expiry, status; never tokens or hashes), for the revoke UI.
- ``DELETE /runs/{run_id}/share/{token_id}`` — revoke a link (owner only,
  idempotent). A revoked/expired link's public URL then answers 410.
- ``GET    /shared/{token}`` — PUBLIC, rate-limited, no session: the
  share-safe report view built by
  :func:`career_guidance.sharing.build_shared_report` (allowlist only —
  no name/e-mail/handle, no constraints, no raw profile, no institute or
  counsellor data). Unknown token → 404, revoked/expired → 410.

Ownership (re-checked server-side on every mutating call):
- a signed-in user's run: only that user (any other caller, signed-in or
  not, gets 403; an unknown run id gets 404);
- an anonymous run (``user_id IS NULL``): only a guest caller — the guest
  session that created it. Anonymous runs belong to no account (the same
  rule as history/exports since Phase 1), so signing in does not adopt
  them; a signed-in caller gets 403 for an anonymous run.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.ratelimit import RateLimiter
from career_guidance.sharing import GUEST_CREATOR, ShareStore, build_shared_report
from career_guidance.users import User

logger = logging.getLogger("career_guidance.sharing_api")

_create_limiter = RateLimiter(max_calls=10, per_seconds=3600)
_public_limiter = RateLimiter(max_calls=60, per_seconds=60)


class ShareCreateBody(BaseModel):
    expiry_days: int | None = Field(default=None, ge=1, le=30)


def build_router(settings, optional_user, db) -> APIRouter:
    """``optional_user(request) -> User | None`` (guest = None)."""
    router = APIRouter(prefix="/api/v1", tags=["sharing"])
    store = ShareStore(settings.database_path)

    def _find_run(run_id: int):
        return next((r for r in db.list_runs(limit=1000) if r.id == run_id), None)

    def _owned_run(run_id: int, user: User | None):
        run = _find_run(run_id)
        if run is None:
            raise HTTPException(404, "Run not found.")
        if run.user_id is not None:
            if user is None or user.id != run.user_id:
                raise HTTPException(403, "Only the report owner can manage share links.")
        elif user is not None:
            raise HTTPException(
                403,
                "This anonymous report's share links are managed from the "
                "guest session that created it.",
            )
        return run

    @router.post("/runs/{run_id}/share", status_code=201)
    def create_share(run_id: int, body: ShareCreateBody, request: Request) -> dict:  # noqa: B008
        user: User | None = optional_user(request)
        run = _owned_run(run_id, user)
        key = f"share-create:{user.id if user else 'guest'}"
        if not _create_limiter.allow(key):
            raise HTTPException(429, "Too many share links created — please try again later.")
        record, raw_token = store.create(
            run.id, user.id if user else GUEST_CREATOR, body.expiry_days
        )
        return {
            **record.public(),
            "token": raw_token,
            "share_path": f"/shared/{raw_token}",
            "note": "Copy this link now — for privacy it cannot be shown again. "
            "Revoke it and create a new one at any time.",
        }

    @router.get("/runs/{run_id}/shares")
    def list_shares(run_id: int, request: Request) -> dict:
        user: User | None = optional_user(request)
        run = _owned_run(run_id, user)
        return {"shares": [r.public() for r in store.list_for_run(run.id)]}

    @router.delete("/runs/{run_id}/share/{token_id}")
    def revoke_share(run_id: int, token_id: int, request: Request) -> dict:
        user: User | None = optional_user(request)
        run = _owned_run(run_id, user)
        record = store.get(token_id)
        if record is None or record.run_id != run.id:
            raise HTTPException(404, "Share link not found.")
        revoked = store.revoke(token_id)
        return {"share": revoked.public() if revoked else record.public(), "revoked": True}

    @router.get("/shared/{token}")
    def shared_report(token: str, request: Request) -> dict:
        client = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else "?"
        ).split(",")[0]
        if not _public_limiter.allow(f"shared:{client}"):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        record = store.by_token(token)
        if record is None:
            raise HTTPException(404, "This share link is not valid.")
        if record.revoked:
            raise HTTPException(410, "This share link has been revoked.")
        if record.expired:
            raise HTTPException(410, "This share link has expired.")
        run = _find_run(record.run_id)
        if run is None:  # the owner deleted the run/history after sharing
            raise HTTPException(404, "This share link is not valid.")
        payload = build_shared_report(run)
        payload["expires_at"] = record.expires_at
        payload["shared"] = True
        return payload

    return router
