"""Phase 5 routes: age declaration + parental consent.

Mounted under ``/api/v1``:

- ``PUT  /me/age-declaration`` — least-data declaration (band + optional
  birth year); derives ``is_minor``. Session required.
- ``POST /me/consent/request`` — a minor asks a guardian to consent.
  Session required; 422 for adults / invalid guardian e-mail.
- ``GET  /me/consent`` — my declaration + consent status + restrictions.
- ``POST /me/consent/revoke`` — revoke my current grant/request.
- ``GET  /consent/confirm/{token}`` — PUBLIC, token-secured guardian
  decision (``?decision=grant|deny|revoke``). The guardian may not have
  an account, so no session is involved; the unguessable token (stored
  hashed, 72 h expiry) is the credential. Unknown token → 404, expired
  → 410, already decided → 409.

Everything else answers 401 anonymously via the ``current_user``
dependency.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.ratelimit import RateLimiter
from career_guidance.consent import (
    NOTICE_VERSION,
    ConsentStore,
    ManualEmailConsentProvider,
    restrictions_for,
)
from career_guidance.users import User

logger = logging.getLogger("career_guidance.consent_api")

_request_limiter = RateLimiter(max_calls=5, per_seconds=3600)
_confirm_limiter = RateLimiter(max_calls=30, per_seconds=3600)


class AgeDeclarationBody(BaseModel):
    age_band: str = ""
    birth_year: int | None = None


class ConsentRequestBody(BaseModel):
    guardian_email: str = Field(min_length=3, max_length=320)


def build_router(settings, current_user, users, public_url: str = "") -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["consent"])
    store = ConsentStore(settings.database_path)
    provider = ManualEmailConsentProvider(store, base_url=public_url)

    def _status_payload(user: User) -> dict:
        fresh = users.get(user.id) or user
        record = store.latest(user.id)
        return {
            "user_id": user.id,
            "is_minor": bool(fresh.is_minor),
            "age_band": fresh.age_band,
            "birth_year": fresh.birth_year,
            "notice_version": NOTICE_VERSION,
            "effective_status": record.effective_status if record else "none",
            "consent": record.public(include_email=True) if record else None,
            "restrictions": restrictions_for(fresh, store),
        }

    # ---------------------------------------------------------- declaration
    @router.put("/me/age-declaration")
    def age_declaration(body: AgeDeclarationBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        try:
            updated = users.set_age_declaration(user.id, body.age_band, body.birth_year)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(user.email, "privacy:age-declaration", updated.age_band or "year-only")
        return {"user": updated.public(), "privacy": _status_payload(updated)}

    # -------------------------------------------------------------- consent
    @router.get("/me/consent")
    def my_consent(user: User = Depends(current_user)) -> dict:  # noqa: B008
        return _status_payload(user)

    @router.post("/me/consent/request")
    def request_consent(body: ConsentRequestBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        fresh = users.get(user.id) or user
        if not fresh.is_minor:
            raise HTTPException(422, "Parental consent is only needed for under-18 accounts.")
        if not _request_limiter.allow(f"consent-request:{user.id}"):
            raise HTTPException(429, "Too many consent requests — please try again later.")
        if store.effective_status(user.id) == "granted":
            raise HTTPException(409, "Consent is already granted for this account.")
        try:
            payload = provider.request_consent(
                {"id": user.id, "email": user.email}, body.guardian_email
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(user.email, "privacy:consent-request", store.latest(user.id).status)  # type: ignore[union-attr]
        return {"consent": payload, "privacy": _status_payload(user)}

    @router.post("/me/consent/revoke")
    def revoke_consent(user: User = Depends(current_user)) -> dict:  # noqa: B008
        record = store.revoke(user.id)
        if record is None:
            raise HTTPException(404, "No consent record to revoke.")
        users.audit(user.email, "privacy:consent-revoke", record.status)
        return {"consent": record.public(include_email=True), "privacy": _status_payload(user)}

    # ------------------------------------------------- guardian (public)
    @router.get("/consent/confirm/{token}")
    def confirm(
        token: str,
        request: Request,
        decision: Literal["grant", "deny", "revoke"] = Query(default="grant"),
    ) -> dict:
        client = request.headers.get("x-forwarded-for", "?")
        if not _confirm_limiter.allow(f"consent-confirm:{client}"):
            raise HTTPException(429, "Too many attempts — please try again later.")
        try:
            if decision == "revoke":
                record = store.revoke_by_token(token)
            else:
                record = provider.confirm(token, granted=decision == "grant")
        except ValueError as error:
            message = str(error)
            if message == "unknown_token":
                raise HTTPException(404, "This consent link is not valid.") from error
            if message == "expired_token":
                raise HTTPException(
                    410, "This consent link has expired — ask for a new one."
                ) from error
            if message == "already_decided":
                raise HTTPException(409, "This consent request was already decided.") from error
            raise HTTPException(400, message) from error
        return {
            "status": record.effective_status,
            "notice_version": record.notice_version,
            "decided_at": record.decided_at,
        }

    return router
