"""Kaam-Vaani consent + employer matching router (Stage 6).

Mounted under ``/api/v1/kv/*`` ONLY when the ``KV_CONSENT`` flag is
on (see ``backend/main.py``). Covers F4/F5: the worker's shareable
profile, per-employer time-limited revocable consent, the
append-only consent audit log, employer candidate matching over
verified + consented candidates only, shortlists, contact requests,
and hire-outcome reporting with the 30/90-day retention metric.

Consent enforcement lives in the STORE (``career_guidance.kaamvaani.
consent``), not the UI: the candidate view queries active consents
first and filters every profile to its consented fields, so no
consent means no data even for a caller that bypasses the UI. This
router adds the HTTP layer: role checks, ownership checks (a 404,
never a 403, for another employer's listing — ids must not be
enumerable), and error mapping (ConsentNotFound → 404,
ConsentConflict → 409, ConsentValidationError → 400).

The consent audit log (``kv_consent_audit``) is the authoritative
record of consent events — grant/revoke/expiry/access — so these
endpoints do NOT double-log to the main ``audit_log``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth import Auth
from backend.kv_ratelimit import kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.consent import (
    CONSENT_DURATIONS_DAYS,
    CONSENT_FIELDS,
    DEFAULT_CONSENT_DAYS,
    FIELD_EXPLANATIONS,
    OUTCOMES,
    RETENTION_STATUSES,
    ConsentConflict,
    ConsentError,
    ConsentNotFound,
    ConsentStore,
    ConsentValidationError,
    consent_explanation,
    delete_all_kv_data,
)
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.users import User

logger = logging.getLogger("career_guidance.kv_consent")


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class WorkerProfileBody(BaseModel):
    skills: list[str] | str | None = None
    education: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    district: str = Field(default="", max_length=80)
    income_monthly: int | None = Field(default=None, ge=0, le=10_000_000)
    income_text: str = Field(default="", max_length=200)
    goal_type: str = Field(default="explore", max_length=40)
    interests: str = Field(default="", max_length=1000)
    language: str = Field(default="en", max_length=5)


class GrantBody(BaseModel):
    employer_id: int
    fields: list[str] | None = None  # None = all shareable fields
    duration_days: int = DEFAULT_CONSENT_DAYS
    listing_id: int | None = None


class CandidatesBody(BaseModel):
    listing_id: int
    city: str = Field(default="", max_length=80)
    limit: int = Field(default=20, ge=1, le=100)


class ShortlistBody(BaseModel):
    listing_id: int
    worker_user_id: str = Field(..., min_length=1, max_length=64)


class ContactRequestBody(BaseModel):
    listing_id: int
    worker_user_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(default="", max_length=1000)


class OutcomeBody(BaseModel):
    listing_id: int
    worker_user_id: str = Field(..., min_length=1, max_length=64)
    outcome: str = Field(..., min_length=1, max_length=20)
    note: str = Field(default="", max_length=1000)


class FollowupBody(BaseModel):
    day: int
    status: str = Field(..., min_length=1, max_length=20)


# Step 9.4: signed-in consent/matching mutations share a
# generous 60/min per-user budget (stops scripts, not humans).
_MUTATION_LIMITER = kv_limiter(max_calls=60, per_seconds=60)


def build_router(settings: Settings, current_user, employer_user, auth: Auth) -> APIRouter:
    """Return the consent router. ``auth`` supplies the user store
    (role checks + worker names for enriched views)."""
    router = APIRouter(prefix="/api/v1/kv", tags=["kaam-vaani-consent"])
    store = ConsentStore(settings.database_target)
    employers = EmployerStore(settings.database_target)
    users = auth.store

    def _consent_error(error: ConsentError) -> HTTPException:
        if isinstance(error, ConsentNotFound):
            return HTTPException(404, str(error))
        if isinstance(error, ConsentConflict):
            return HTTPException(409, str(error))
        if isinstance(error, ConsentValidationError):
            return HTTPException(400, str(error))
        return HTTPException(400, str(error))

    def _employer_for(user: User):
        employer = employers.get_employer_by_user(user.id)
        if employer is None:
            raise HTTPException(404, "No employer profile for this account.")
        return employer

    def _own_listing(employer_id: int, listing_id: int):
        """A listing belonging to this employer — 404 otherwise
        (never 403: cross-employer ids must not be enumerable)."""
        listing = employers.get_listing(listing_id)
        if listing is None or listing.employer_id != employer_id:
            raise HTTPException(404, "Listing not found.")
        return listing

    def _verified_own_listing(employer, listing_id: int):
        """An owned listing that is verified, from a verified
        employer — the gate for shortlist/contact (matching a
        candidate to a live job)."""
        if employer.status != "verified":
            raise HTTPException(409, "Employer matching needs a verified employer profile.")
        listing = _own_listing(employer.id, listing_id)
        if listing.status != "verified":
            raise HTTPException(409, "Employer matching needs a verified listing.")
        return listing

    def _enrich_consent(consent) -> dict:
        data = consent.to_dict()
        employer = employers.get_employer(consent.employer_id)
        data["employer_name"] = employer.business_name if employer else ""
        data["listing_title"] = ""
        if consent.listing_id is not None:
            listing = employers.get_listing(consent.listing_id)
            data["listing_title"] = listing.title if listing else ""
        return data

    def _enrich_contact_request(request) -> dict:
        data = request.to_dict()
        employer = employers.get_employer(request.employer_id)
        data["employer_name"] = employer.business_name if employer else ""
        listing = employers.get_listing(request.listing_id)
        data["listing_title"] = listing.title if listing else ""
        return data

    def _enrich_outcome(outcome) -> dict:
        data = outcome.to_dict()
        employer = employers.get_employer(outcome.employer_id)
        data["employer_name"] = employer.business_name if employer else ""
        listing = employers.get_listing(outcome.listing_id)
        data["listing_title"] = listing.title if listing else ""
        worker = users.get(outcome.worker_user_id)
        data["worker_name"] = worker.name if worker else ""
        return data

    def _enrich_candidate(candidate: dict) -> dict:
        """Add the worker's display name to a ranked candidate. The
        name comes from the account record, not the consented profile
        — a worker who never set a name shows as "" and the UI falls
        back to "Worker"."""
        worker = users.get(candidate["worker_user_id"])
        candidate["worker_name"] = worker.name if worker else ""
        return candidate

    # -------------------------------------------------------------- status

    @router.get("/consent/status")
    def status() -> dict:
        """What the consent system offers: the shareable fields with
        their plain-language explanations, the allowed durations,
        and the outcome vocabulary. The UI renders the grant screen
        from this — the field list is server-defined, never
        client-invented."""
        return {
            "enabled": True,
            "fields": [
                {"name": name, "explanation": FIELD_EXPLANATIONS[name]} for name in CONSENT_FIELDS
            ],
            "durations_days": list(CONSENT_DURATIONS_DAYS),
            "default_duration_days": DEFAULT_CONSENT_DAYS,
            "outcomes": list(OUTCOMES),
            "retention_statuses": list(RETENTION_STATUSES),
        }

    # ------------------------------------------------------- worker profile

    @router.get("/worker-profile")
    def get_worker_profile(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """The signed-in user's own shareable work profile (404 when
        they have not saved one yet — the UI treats that as 'show the
        form')."""
        profile = store.get_worker_profile(user.id)
        if profile is None:
            raise HTTPException(404, "No work profile saved yet.")
        return {"profile": profile.to_dict()}

    @router.put("/worker-profile")
    def save_worker_profile(
        body: WorkerProfileBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Create or replace the signed-in worker's shareable
        profile. Worker accounts only (one role per account, A10):
        an employer account cannot also hold a worker profile."""
        if user.role != "user":
            raise HTTPException(
                400,
                f"Only a worker account can save a work profile (this account is {user.role}).",
            )
        try:
            profile = store.save_worker_profile(
                user.id,
                skills=body.skills,
                education=body.education,
                city=body.city,
                district=body.district,
                income_monthly=body.income_monthly,
                income_text=body.income_text,
                goal_type=body.goal_type,
                interests=body.interests,
                language=body.language,
            )
        except ConsentError as error:
            raise _consent_error(error) from error
        return {"profile": profile.to_dict()}

    # -------------------------------------------------------------- consent

    @router.post("/consent/grant")
    def grant_consent(body: GrantBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Share the worker's profile with one employer. The grant
        stores the exact fields shared and the expiry; the response
        carries the plain-language explanation the worker agreed to.
        Granting to a not-yet-verified employer is allowed — the
        employer cannot SEE the profile until verified (matching
        gates on verification), so an early grant is harmless and
        lets the worker apply while review is pending."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        if user.role != "user":
            raise HTTPException(
                400,
                f"Only a worker account can share a profile (this account is {user.role}).",
            )
        employer = employers.get_employer(body.employer_id)
        if employer is None:
            raise HTTPException(404, "Employer not found.")
        if body.listing_id is not None:
            listing = employers.get_listing(body.listing_id)
            if listing is None or listing.employer_id != employer.id:
                raise HTTPException(404, "Listing not found.")
        try:
            consent = store.grant_consent(
                user.id,
                employer.id,
                body.fields,
                body.duration_days,
                listing_id=body.listing_id,
                actor=user.email,
            )
        except ConsentError as error:
            raise _consent_error(error) from error
        return {
            "consent": _enrich_consent(consent),
            "explanation": consent_explanation(
                employer.business_name, consent.fields, consent.duration_days
            ),
            "employer_name": employer.business_name,
        }

    @router.post("/consent/{consent_id}/revoke")
    def revoke_consent(consent_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Revoke the worker's own consent. Revocation is immediate:
        the employer sees nothing from the next call on."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        try:
            consent = store.revoke_consent(consent_id, user.id, actor=user.email)
        except ConsentError as error:
            raise _consent_error(error) from error
        return {"consent": _enrich_consent(consent)}

    @router.get("/consent/mine")
    def my_consents(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """The worker's own consents (all statuses), with the
        employer name and listing title for each."""
        consents = store.list_consents_for_worker(user.id)
        return {"consents": [_enrich_consent(c) for c in consents]}

    @router.get("/consent/audit")
    def my_audit(
        limit: int = Query(default=100, ge=1, le=200),
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """The worker's own sharing history: every grant, revoke,
        expiry and profile access, newest first."""
        events = store.list_audit(worker_user_id=user.id, limit=limit)
        return {"events": [e.to_dict() for e in events]}

    @router.get("/consent/contact-requests")
    def my_contact_requests(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Contact requests the worker has received, with the
        employer name and listing title for each."""
        requests = store.list_contact_requests(worker_user_id=user.id)
        return {"requests": [_enrich_contact_request(r) for r in requests]}

    # ------------------------------------------------------- employer matching

    @router.post("/employers/matching/candidates")
    def matching_candidates(
        body: CandidatesBody,
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """Ranked consented candidates for one of the employer's
        verified listings. Only workers with an ACTIVE consent to
        this employer appear, and each carries only their consented
        fields. Every returned candidate appends an ``accessed``
        audit event the worker can see."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        employer = _employer_for(user)
        _own_listing(employer.id, body.listing_id)
        try:
            result = store.rank_candidates_for_listing(
                body.listing_id, limit=body.limit, city=body.city or None
            )
        except ConsentError as error:
            raise _consent_error(error) from error
        result["candidates"] = [_enrich_candidate(c) for c in result["candidates"]]
        return result

    @router.get("/employers/matching/shortlist")
    def get_shortlist(
        listing_id: int = Query(...),
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """Shortlisted candidates for one listing, with each
        candidate's CURRENT consent state — a revoked consent shows
        a placeholder with no profile fields."""
        employer = _employer_for(user)
        _own_listing(employer.id, listing_id)
        view = store.shortlist_view(employer.id, listing_id)
        # Flatten the store's nested {"shortlist": {...}, ...} items
        # into one object per entry, with the worker's display name.
        flat = []
        for item in view:
            worker = users.get(item["shortlist"]["worker_user_id"])
            flat.append(
                {
                    **item["shortlist"],
                    "worker_name": worker.name if worker else "",
                    "consent_status": item["consent_status"],
                    "consent_expires_at": item["consent_expires_at"],
                    "profile": item["profile"],
                }
            )
        return {"shortlist": flat}

    @router.post("/employers/matching/shortlist")
    def add_shortlist(body: ShortlistBody, user: User = Depends(employer_user)) -> dict:  # noqa: B008
        """Shortlist a consented worker for a verified listing."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        employer = _employer_for(user)
        _verified_own_listing(employer, body.listing_id)
        try:
            entry = store.add_shortlist(employer.id, body.listing_id, body.worker_user_id)
        except ConsentError as error:
            raise _consent_error(error) from error
        return {"shortlist": entry.to_dict()}

    @router.delete("/employers/matching/shortlist")
    def remove_shortlist(
        listing_id: int = Query(...),
        worker_user_id: str = Query(...),
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """Remove a worker from a listing's shortlist."""
        employer = _employer_for(user)
        _own_listing(employer.id, listing_id)
        removed = store.remove_shortlist(employer.id, listing_id, worker_user_id)
        if not removed:
            raise HTTPException(404, "Shortlist entry not found.")
        return {"deleted": True}

    @router.post("/employers/matching/contact-request")
    def create_contact_request(
        body: ContactRequestBody,
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """Ask to contact a consented worker about a verified
        listing. The worker sees the request in My sharing; contact
        itself happens out of band via the consented contact
        details."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        employer = _employer_for(user)
        _verified_own_listing(employer, body.listing_id)
        try:
            request = store.create_contact_request(
                employer.id, body.listing_id, body.worker_user_id, body.message
            )
        except ConsentError as error:
            raise _consent_error(error) from error
        return {"request": _enrich_contact_request(request)}

    @router.get("/employers/matching/contact-requests")
    def employer_contact_requests(
        listing_id: int | None = Query(default=None),
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """Contact requests the employer has sent (optionally one
        listing)."""
        employer = _employer_for(user)
        if listing_id is not None:
            _own_listing(employer.id, listing_id)
        requests = store.list_contact_requests(employer_id=employer.id, listing_id=listing_id)
        return {"requests": [_enrich_contact_request(r) for r in requests]}

    @router.get("/employers/matching/audit")
    def employer_audit(
        limit: int = Query(default=100, ge=1, le=200),
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """The employer's own consent-audit trail: grants, revokes,
        expiries and accesses for their candidates."""
        employer = _employer_for(user)
        events = store.list_audit(employer_id=employer.id, limit=limit)
        return {"events": [e.to_dict() for e in events]}

    # ------------------------------------------------------------ hire outcomes

    @router.post("/hire-outcomes")
    def report_outcome(body: OutcomeBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Report a hire outcome. The reporter must be the employer
        who owns the listing, or the worker themselves. The store
        additionally requires a consent record between the worker
        and the employer (any status) — outcomes can be reported
        after a consent ends, but never about a stranger."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        listing = employers.get_listing(body.listing_id)
        if listing is None:
            raise HTTPException(404, "Listing not found.")
        employer = employers.get_employer(listing.employer_id)
        is_employer = employer is not None and employer.user_id == user.id
        is_worker = body.worker_user_id == user.id
        if not is_employer and not is_worker:
            raise HTTPException(403, "Only the employer or the worker can report this outcome.")
        try:
            outcome = store.report_outcome(
                listing.employer_id,
                listing.id,
                body.worker_user_id,
                body.outcome,
                user.id,
                "employer" if is_employer else "worker",
                body.note,
            )
        except ConsentError as error:
            raise _consent_error(error) from error
        return {"outcome": _enrich_outcome(outcome)}

    @router.post("/hire-outcomes/{outcome_id}/followup")
    def record_followup(
        outcome_id: int,
        body: FollowupBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Record a day-30 or day-90 retention follow-up on a hire.
        The reporter must be the employer who owns the listing, or
        the worker themselves."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        outcome = store.get_outcome(outcome_id)
        if outcome is None:
            raise HTTPException(404, "Hire outcome not found.")
        employer = employers.get_employer(outcome.employer_id)
        is_employer = employer is not None and employer.user_id == user.id
        is_worker = outcome.worker_user_id == user.id
        if not is_employer and not is_worker:
            raise HTTPException(403, "Only the employer or the worker can report a follow-up.")
        try:
            updated = store.record_followup(outcome_id, body.day, body.status)
        except ConsentError as error:
            raise _consent_error(error) from error
        return {"outcome": _enrich_outcome(updated)}

    @router.get("/employers/hire-outcomes")
    def employer_outcomes(
        listing_id: int | None = Query(default=None),
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """The employer's hire outcomes (optionally one listing),
        with per-outcome counts and the 30/90-day retention summary."""
        employer = _employer_for(user)
        if listing_id is not None:
            _own_listing(employer.id, listing_id)
        outcomes = store.list_outcomes(employer_id=employer.id, listing_id=listing_id)
        return {
            "outcomes": [_enrich_outcome(o) for o in outcomes],
            "counts": store.outcome_counts(employer.id, listing_id=listing_id),
            "retention": store.retention_summary(employer.id, listing_id=listing_id),
        }

    @router.get("/hire-outcomes/mine")
    def my_outcomes(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Hire outcomes reported about the signed-in worker."""
        outcomes = store.list_outcomes(worker_user_id=user.id)
        return {"outcomes": [_enrich_outcome(o) for o in outcomes]}

    @router.delete("/me/data")
    def delete_my_kv_data(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Erase the signed-in user's Kaam-Vaani data (Step 9.4,
        DPDP erasure). Deletes the worker profile, consents,
        shortlists and contact requests, plus the employer row and
        listings when the account is an employer. Hire outcomes
        are ANONYMISED, not deleted (aggregate retention stats
        stay valid); listing reports are KEPT (workers' safety
        records); the consent audit trail is NEVER touched
        (append-only, Stage 6 invariant). The response is the
        full summary — what was deleted, anonymised and retained.
        This deletes Kaam-Vaani data only; full account deletion
        (DELETE /api/v1/me) runs this first, then the base-app
        deletion. Irreversible."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        result = delete_all_kv_data(settings.database_target, user.id)
        return {
            **result,
            "retained": {
                "consent_audit_rows": "never deleted (append-only consent trail)",
                "listing_reports": "kept as safety records (no employer PII)",
            },
        }

    return router
