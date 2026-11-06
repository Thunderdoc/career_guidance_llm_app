"""Phase 10: institute public API (API-key auth, aggregates only).

Two surfaces:

- **Key management** (session auth): ``POST/GET/DELETE
  /api/v1/institutes/{institute_id}/api-keys`` — the institute's own
  ``institute_admin`` or a platform admin. The raw key is returned once,
  in the create response only; listings carry metadata only.
- **Public reads** (``X-API-Key`` header ONLY, no session):
  ``GET /api/v1/public/institutes/{slug}/cohort`` and ``…/top-careers``.
  The key must belong to the institute named by ``{slug}`` — a valid key
  presented against another institute's slug answers 404 (the key does
  not authenticate for that institute, and its existence is not leaked).
  Payloads are built from the Phase 4 cohort aggregates with the
  individual needs-attention list reduced to a count: no e-mails, no
  names, no user ids, ever. Rate limit: 30 requests/minute per key —
  stricter than the session cohort routes (which carry no per-route
  limit beyond the global middleware).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from backend.ratelimit import RateLimiter
from career_guidance.api_keys import InstituteApiKeyStore
from career_guidance.institutes import InstituteStore, compute_cohort
from career_guidance.users import User

logger = logging.getLogger("career_guidance.public_api")

_public_limiter = RateLimiter(max_calls=30, per_seconds=60)


class CreateKeyBody(BaseModel):
    label: str = Field(default="", max_length=120)


def _aggregate_cohort(store: InstituteStore, db, institute_id: int) -> dict:
    """Phase 4 cohort aggregates with individual data stripped.

    ``compute_cohort`` never includes e-mails, but its needs-attention
    list carries names/user ids — for the public API that list is
    reduced to a bare count before anything leaves the process.
    """
    full = compute_cohort(store.members(institute_id), db.list_runs(limit=5000))
    cohort = {k: v for k, v in full.items() if k != "needs_attention"}
    cohort["needs_attention_count"] = len(full["needs_attention"])
    return cohort


def build_router(settings, current_user, users, db) -> APIRouter:
    router = APIRouter(tags=["public-api"])
    store = InstituteStore(settings.database_path)
    keys = InstituteApiKeyStore(settings.database_path)

    # ------------------------------------------------------- key admin
    def _require_key_admin(user: User, institute_id: int) -> dict:
        institute = store.get_institute(institute_id)
        if institute is None:
            raise HTTPException(404, "Institute not found.")
        if user.is_admin:
            return institute
        membership = store.membership_of(user.id)
        if (
            not membership
            or membership["institute_id"] != institute_id
            or membership["institute_role"] != "institute_admin"
        ):
            raise HTTPException(403, "Only the institute admin may manage API keys.")
        return institute

    @router.post("/api/v1/institutes/{institute_id}/api-keys", status_code=201)
    def create_key(
        institute_id: int,
        body: CreateKeyBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require_key_admin(user, institute_id)
        created = keys.create_key(institute_id, body.label, user.id)
        users.audit(user.email, "institute:api-key-create", f"{institute_id}:{created['id']}")
        return created

    @router.get("/api/v1/institutes/{institute_id}/api-keys")
    def list_keys(institute_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        _require_key_admin(user, institute_id)
        return {"api_keys": keys.list_keys(institute_id)}

    @router.delete("/api/v1/institutes/{institute_id}/api-keys/{key_id}")
    def revoke_key(
        institute_id: int,
        key_id: int,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require_key_admin(user, institute_id)
        if not keys.revoke_key(institute_id, key_id):
            raise HTTPException(404, "Active API key not found.")
        users.audit(user.email, "institute:api-key-revoke", f"{institute_id}:{key_id}")
        return {"revoked": True}

    # ------------------------------------------------------ public read
    def _key_for_slug(slug: str, raw_key: str | None) -> tuple[dict, dict]:
        key = keys.authenticate(raw_key)
        if key is None:
            raise HTTPException(401, "Missing or invalid API key.")
        institute = store.get_institute(key["institute_id"])
        if institute is None or institute["slug"] != slug:
            raise HTTPException(404, "Institute not found.")
        return key, institute

    def _rate_limit(key: dict) -> None:
        if not _public_limiter.allow(f"pubkey:{key['id']}"):
            raise HTTPException(429, "Too many requests — please wait a minute.")

    @router.get("/api/v1/public/institutes/{slug}/cohort")
    def public_cohort(
        slug: str,
        request: Request,
        x_api_key: str | None = Header(default=None),  # noqa: B008
    ) -> dict:
        key, institute = _key_for_slug(slug, x_api_key)
        _rate_limit(key)
        return {
            "institute": {"name": institute["name"], "slug": institute["slug"]},
            "cohort": _aggregate_cohort(store, db, institute["id"]),
        }

    @router.get("/api/v1/public/institutes/{slug}/top-careers")
    def public_top_careers(
        slug: str,
        request: Request,
        x_api_key: str | None = Header(default=None),  # noqa: B008
    ) -> dict:
        key, institute = _key_for_slug(slug, x_api_key)
        _rate_limit(key)
        cohort = _aggregate_cohort(store, db, institute["id"])
        return {
            "institute": {"name": institute["name"], "slug": institute["slug"]},
            "top_careers": cohort["top_recommended_careers"],
        }

    return router
