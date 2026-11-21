"""Kaam-Vaani employer portal router (Stage 5).

Mounted under ``/api/v1/kv/*`` ONLY when the ``KV_EMPLOYERS`` flag is
on (see ``backend/main.py``). Covers F3: employer registration,
listing CRUD, verification states, the scam checker, the admin review
queue, and worker reports.

Verification model (see ``career_guidance.kaamvaani.employers``):
employers and listings each carry ``pending`` / ``verified`` /
``rejected`` / ``flagged``. Workers see **verified listings only**
(``GET /kv/listings``), and a listing can only be verified when its
employer is verified. Nothing auto-verifies — every verification is
a human admin decision (R5).

Phone verification: the client completes Firebase Phone Auth and
passes the ID token to ``POST /employers/mine/verify-phone``. The
token's e-mail must match the signed-in user (the phone credential
linked to their Firebase account) and it must carry a
``phone_number`` claim — Firebase did the OTP check; the backend
only stores the verified number (A12/A36). Until the owner enables
phone sign-in in the Firebase console this endpoint answers 503
(L38); verification meanwhile is email + admin review.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import Auth
from backend.kv_ratelimit import client_key, kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.cache import cached_completer
from career_guidance.kaamvaani.employers import (
    DEFAULT_RADIUS_KM,
    REPORT_REASONS,
    EmployerStore,
)
from career_guidance.kaamvaani.scam import check_listing
from career_guidance.kaamvaani.wages import load_wage_tables
from career_guidance.providers import ProviderFactory
from career_guidance.users import User

logger = logging.getLogger("career_guidance.kv_employers")


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class EmployerRegisterBody(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=120)
    contact_name: str = Field(default="", max_length=120)
    phone_e164: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=80)
    district: str = Field(default="", max_length=80)
    state: str = Field(default="Tamil Nadu", max_length=80)
    business_type: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)


class EmployerUpdateBody(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=120)
    contact_name: str | None = Field(default=None, max_length=120)
    phone_e164: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    business_type: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)


class PhoneVerifyBody(BaseModel):
    id_token: str = Field(..., min_length=10)


class ListingBody(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    role_category: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=5000)
    city: str = Field(default="", max_length=80)
    district: str = Field(default="", max_length=80)
    state: str = Field(default="Tamil Nadu", max_length=80)
    pay_monthly_min: int | None = Field(default=None, ge=0, le=10_000_000)
    pay_monthly_max: int | None = Field(default=None, ge=0, le=10_000_000)
    pay_text: str = Field(default="", max_length=200)
    work_type: str = Field(default="full-time", max_length=40)
    shift: str = Field(default="", max_length=80)
    openings: int = Field(default=1, ge=1, le=1000)
    requirements: str = Field(default="", max_length=3000)
    contact_info: str = Field(default="", max_length=1000)


class ListingUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    role_category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    pay_monthly_min: int | None = Field(default=None, ge=0, le=10_000_000)
    pay_monthly_max: int | None = Field(default=None, ge=0, le=10_000_000)
    pay_text: str | None = Field(default=None, max_length=200)
    work_type: str | None = Field(default=None, max_length=40)
    shift: str | None = Field(default=None, max_length=80)
    openings: int | None = Field(default=None, ge=1, le=1000)
    requirements: str | None = Field(default=None, max_length=3000)
    contact_info: str | None = Field(default=None, max_length=1000)


class ReportBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=40)
    details: str = Field(default="", max_length=2000)


class ReviewBody(BaseModel):
    approve: bool = True
    note: str = Field(default="", max_length=1000)


class EndorseBody(BaseModel):
    endorsed_by: str = Field(default="", max_length=120)
    endorsed_by_type: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=1000)


class ReportReviewBody(BaseModel):
    action: str = Field(..., min_length=1, max_length=20)  # uphold | dismiss
    note: str = Field(default="", max_length=1000)


def _pay_plausibility_status() -> dict:
    """Pay-plausibility capability for the status endpoint (L39,
    wired in Step 8A): the central-sphere wage tables, with their
    order reference. A missing or corrupt tables file degrades to
    "unavailable" instead of failing the status endpoint — the
    check itself still raises loudly when it runs."""
    try:
        tables = load_wage_tables()
    except (FileNotFoundError, ValueError):
        return {
            "status": "unavailable",
            "reason": "Wage tables could not be loaded.",
        }
    provenance = tables["provenance"]
    return {
        "status": "central_sphere",
        "employments": len(tables["employments"]),
        "order": provenance["order"],
        "effective_from": provenance["effective_from"],
        "reason": "Central-sphere rates only — TN state rates are absent (L18).",
    }


# Step 9.4 rate limits. Signed-in mutations share a generous
# 60/min per-user budget (stops scripts, not humans); the
# phone-verification endpoint is strict (5/hour/user — OTP
# endpoints are the abuse magnet); anonymous listing reports
# are 10/min per IP. Admin review endpoints are unmetered by
# design (admin-only, attributable, low volume).
_MUTATION_LIMITER = kv_limiter(max_calls=60, per_seconds=60)
_VERIFY_LIMITER = kv_limiter(max_calls=5, per_seconds=3600)
_REPORT_LIMITER = kv_limiter(max_calls=10, per_seconds=60)


def build_router(
    settings: Settings, current_user, admin_user, employer_user, auth: Auth
) -> APIRouter:
    """Return the employer-portal router. ``auth`` supplies the
    Firebase verifier (phone verification) and the user store
    (``auth.store``: role changes + audit log)."""
    router = APIRouter(prefix="/api/v1/kv", tags=["kaam-vaani-employers"])
    store = EmployerStore(settings.database_target)
    users = auth.store
    # The completer is wrapped in the shared LLM cache (Step 8.6): a
    # repeated listing text reuses the risk-score completion instead
    # of calling the provider again. No LLM configured → None.
    completer = cached_completer(settings)
    llm_name = ProviderFactory.selected_name(settings)

    def _employer_for(user: User):
        employer = store.get_employer_by_user(user.id)
        if employer is None:
            raise HTTPException(404, "No employer profile for this account.")
        return employer

    def _own_listing(employer_id: int, listing_id: int):
        """A listing belonging to this employer — 404 otherwise (never
        403: cross-employer ids must not be enumerable)."""
        listing = store.get_listing(listing_id)
        if listing is None or listing.employer_id != employer_id:
            raise HTTPException(404, "Listing not found.")
        return listing

    def _public_listing(listing) -> dict:
        """Worker-visible shape: the listing's public fields plus the
        employer's name and endorsement badge (no review internals)."""
        data = listing.public_dict()
        employer = store.get_employer(listing.employer_id)
        data["employer_name"] = employer.business_name if employer else ""
        data["employer_endorsed"] = bool(employer and employer.endorsed)
        data["employer_endorsed_by"] = employer.endorsed_by if employer else ""
        return data

    def _run_check(listing_dict: dict, employer, exclude_id: int | None = None):
        duplicate = store.find_duplicate(
            employer.id,
            listing_dict.get("title", ""),
            listing_dict.get("city", ""),
            listing_dict.get("description", ""),
            exclude_id,
        )
        return check_listing(
            listing_dict,
            employer.to_dict(),
            duplicate is not None,
            completer=completer,
        )

    # -------------------------------------------------------------- status

    @router.get("/employers/status")
    def status() -> dict:
        """Which employer-portal capabilities are live. ``phone_otp``
        is honest about the two-step dependency: Firebase configured
        (a project id exists) does NOT prove phone sign-in is enabled
        in the console — that is the owner's step (L38)."""
        return {
            "enabled": True,
            "phone_otp": {
                "firebase_configured": auth.firebase.enabled,
                "available": auth.firebase.enabled,
                "note": (
                    "Phone sign-in also needs the owner to enable it in the "
                    "Firebase console; until then verification is email + admin review."
                ),
            },
            "llm_risk_score": {
                "configured": completer is not None,
                "provider": llm_name,
            },
            "pay_plausibility": _pay_plausibility_status(),
        }

    # -------------------------------------------------- employer registration

    @router.post("/employers/register")
    def register(body: EmployerRegisterBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        """Register an employer profile for the signed-in account
        (status ``pending`` — admin review verifies it). Registration
        sets the account's role to ``employer`` (A35): verification
        gates listing visibility, not the role. Only plain ``user``
        accounts can register — admins and coordinators keep their
        role (one role per account, A10)."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        if user.role != "user":
            raise HTTPException(
                400,
                f"Only a worker account can register as an employer (this account is {user.role}).",
            )
        try:
            employer = store.create_employer(
                user.id,
                business_name=body.business_name,
                contact_name=body.contact_name,
                phone_e164=body.phone_e164,
                email=body.email or user.email,
                city=body.city,
                district=body.district,
                state=body.state,
                business_type=body.business_type,
                description=body.description,
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        users.set_role(user.id, "employer")
        users.audit(user.email, "kv:employer_register", f"employer:{employer.id}")
        return {"employer": employer.to_dict()}

    @router.get("/employers/mine")
    def mine(user: User = Depends(current_user)) -> dict:  # noqa: B008
        """The signed-in user's own employer profile, plus whether their
        phone is Firebase-verified (from the users table). Any signed-in
        user may call this — a user who has not registered yet gets 404,
        which the UI treats as "show the register form". (The employer
        role is required for ACTIONS — create/update/verify — not for
        reading your own profile; gating this on the role broke
        onboarding for fresh users, found by the Stage 5 live check.)"""
        employer = _employer_for(user)
        data = employer.to_dict()
        fresh = users.get(user.id)
        data["phone_verified"] = bool(fresh and fresh.phone_verified)
        data["phone_e164_user"] = fresh.phone_e164 if fresh else ""
        return {"employer": data}

    @router.put("/employers/mine")
    def update_mine(body: EmployerUpdateBody, user: User = Depends(employer_user)) -> dict:  # noqa: B008
        """Edit the employer's own profile. A verified employer that
        edits goes back to ``pending`` for re-review (A39)."""
        employer = _employer_for(user)
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            return {"employer": employer.to_dict()}
        updated = store.update_employer(employer.id, **updates)
        users.audit(user.email, "kv:employer_update", f"employer:{employer.id}")
        return {"employer": updated.to_dict()}

    @router.post("/employers/mine/verify-phone")
    def verify_phone(body: PhoneVerifyBody, user: User = Depends(employer_user)) -> dict:  # noqa: B008
        """Record a Firebase-verified phone number. The client passes
        the ID token from a Firebase Phone Auth sign-in; the token's
        e-mail must match the signed-in user (phone credential linked
        to their Firebase account) and it must carry a ``phone_number``
        claim. Firebase did the OTP check — the backend only stores
        the verified number (A12/A36). Phone verification alone does
        NOT verify the employer; admin review still decides that."""
        if not _VERIFY_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        if not auth.firebase.enabled:
            raise HTTPException(
                503,
                "Phone sign-in is not enabled (Firebase not configured, or the owner "
                "has not enabled phone sign-in in the Firebase console).",
            )
        try:
            claims = auth.firebase.verify(body.id_token)
        except ValueError as error:
            raise HTTPException(401, str(error)) from error
        email = (claims.get("email") or "").lower()
        if email != user.email.lower():
            raise HTTPException(
                400,
                "This token belongs to a different account — link the phone number "
                "to the Firebase account that matches this login first.",
            )
        # The e-mail match is only a claim match unless Firebase has
        # verified the address — require it (Google sign-in sets it;
        # email/password users verify via the sign-up e-mail).
        if not claims.get("email_verified"):
            raise HTTPException(
                400,
                "Verify your e-mail address with Firebase first — the phone "
                "number can only be linked to a verified account.",
            )
        phone = (claims.get("phone_number") or "").strip()
        if not phone:
            raise HTTPException(
                400,
                "This Firebase account has no verified phone number — "
                "complete phone sign-in first.",
            )
        try:
            updated_user = users.set_phone_verified(user.id, phone)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        employer = _employer_for(user)
        store.update_employer(employer.id, phone_e164=phone)
        users.audit(user.email, "kv:employer_phone_verified", f"employer:{employer.id}")
        return {"phone_e164": updated_user.phone_e164, "phone_verified": True}

    # ------------------------------------------------------------- listings

    @router.post("/employers/listings/check")
    def check_text(body: ListingBody, user: User = Depends(employer_user)) -> dict:  # noqa: B008
        """Preview the scam check on listing fields before submitting —
        stores nothing. The same check runs on create/edit."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        employer = _employer_for(user)
        check = _run_check(body.model_dump(), employer)
        return {"check": check.to_dict()}

    @router.post("/employers/listings")
    def create_listing(body: ListingBody, user: User = Depends(employer_user)) -> dict:  # noqa: B008
        """Create a listing (status ``pending``, or ``flagged`` when the
        scam check scores >= 70). A rejected employer cannot list."""
        if not _MUTATION_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        employer = _employer_for(user)
        check = _run_check(body.model_dump(), employer)
        try:
            listing = store.create_listing(
                employer.id,
                status=check.recommended_status,
                risk_score=check.score,
                risk_flags=[f.to_dict() for f in check.flags],
                **body.model_dump(),
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        users.audit(user.email, "kv:listing_create", f"listing:{listing.id}")
        return {"listing": listing.to_dict(), "check": check.to_dict()}

    @router.get("/employers/listings")
    def my_listings(
        status: str | None = None,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """The signed-in user's own listings (any status). Any signed-in
        user may call this; no profile yet → 404 (see ``mine``)."""
        employer = _employer_for(user)
        listings = store.list_listings(employer_id=employer.id, status=status)
        return {"listings": [item.to_dict() for item in listings]}

    @router.get("/employers/listings/{listing_id}")
    def my_listing(listing_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        employer = _employer_for(user)
        return {"listing": _own_listing(employer.id, listing_id).to_dict()}

    @router.put("/employers/listings/{listing_id}")
    def update_listing(
        listing_id: int,
        body: ListingUpdateBody,
        user: User = Depends(employer_user),  # noqa: B008
    ) -> dict:
        """Edit the employer's own listing. The scam check re-runs on
        the edited text; a verified listing goes back to ``pending``
        for re-review (A39), and a re-score >= 70 flags a pending
        listing. A rejected listing stays rejected until an admin
        re-reviews it."""
        employer = _employer_for(user)
        listing = _own_listing(employer.id, listing_id)
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if updates:
            listing = store.update_listing(listing_id, **updates)
        check = _run_check(listing.to_dict(), employer, exclude_id=listing_id)
        listing = store.set_listing_risk(
            listing_id, check.score, [f.to_dict() for f in check.flags]
        )
        if check.score >= 70 and listing.status == "pending":
            listing = store.set_listing_status(
                listing_id, "flagged", reviewer="system", note="Scam check on edit."
            )
        users.audit(user.email, "kv:listing_update", f"listing:{listing_id}")
        return {"listing": listing.to_dict(), "check": check.to_dict()}

    @router.delete("/employers/listings/{listing_id}")
    def delete_listing(listing_id: int, user: User = Depends(employer_user)) -> dict:  # noqa: B008
        """Withdraw the employer's own listing. Reports against it are
        kept as audit history."""
        employer = _employer_for(user)
        _own_listing(employer.id, listing_id)
        store.delete_listing(listing_id)
        users.audit(user.email, "kv:listing_delete", f"listing:{listing_id}")
        return {"deleted": listing_id}

    # ------------------------------------------- public listings (workers)

    @router.get("/listings")
    def public_listings(
        city: str | None = None,
        role_category: str | None = None,
        limit: int = 100,
        near_city: str | None = None,
        radius_km: float | None = None,
    ) -> dict:
        """Verified listings only — the worker-visible job board.
        ``is_sample`` on each item labels seeded demo data; the
        top-level ``sample_data`` flag says whether any sample rows
        are in this response at all. ``near_city`` replaces the
        exact-city filter with a radius search around that city's
        centre (Step 8.3; ``radius_km`` defaults to 25 km, max
        500). A radius search centred on a city with no
        coordinates is a 400 naming the mapped cities."""
        limit = max(1, min(limit, 100))
        try:
            listings = store.list_public_listings(
                city=city or None,
                role_category=role_category or None,
                limit=limit,
                near_city=near_city or None,
                radius_km=radius_km,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        items = [_public_listing(item) for item in listings]
        response = {
            "listings": items,
            "count": len(items),
            "sample_data": any(item["is_sample"] for item in items),
        }
        if near_city:
            response["near_city"] = near_city
            response["radius_km"] = DEFAULT_RADIUS_KM if radius_km is None else radius_km
        return response

    @router.get("/listings/{listing_id}")
    def public_listing(listing_id: int) -> dict:
        """One verified listing. Anything else 404s — an unverified
        listing must never leak through its id."""
        listing = store.get_listing(listing_id)
        if listing is None or listing.status != "verified":
            raise HTTPException(404, "Listing not found.")
        return {"listing": _public_listing(listing)}

    @router.post("/listings/{listing_id}/report")
    def report_listing(listing_id: int, body: ReportBody, request: Request) -> dict:
        """Worker report (guests allowed — the voice flow is
        guest-first). Three open reports auto-flag a verified listing
        (hidden from workers until an admin re-reviews it)."""
        if not _REPORT_LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        if body.reason not in REPORT_REASONS:
            raise HTTPException(400, f"Unknown report reason: {body.reason!r}")
        listing = store.get_listing(listing_id)
        if listing is None:
            raise HTTPException(404, "Listing not found.")
        reporter = auth.user_from(request)
        try:
            report, auto_flagged = store.report_listing(
                listing_id,
                body.reason,
                body.details,
                reporter_user_id=reporter.id if reporter else "",
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"report": report.to_dict(), "auto_flagged": auto_flagged}

    # ---------------------------------------------------- admin review queue

    @router.get("/admin/review-queue")
    def review_queue(user: User = Depends(admin_user)) -> dict:  # noqa: B008
        """Pending + flagged employers and listings, plus open reports
        — the admin review queue (reuses the Phase 3 verify review
        pattern: review decisions are audited)."""
        employers = store.list_employers(status="pending") + store.list_employers(status="flagged")
        listings = store.list_listings(status="pending") + store.list_listings(status="flagged")
        reports = store.list_reports(status="open")
        return {
            "counts": store.review_queue_counts(),
            "employers": [item.to_dict() for item in employers],
            "listings": [item.to_dict() for item in listings],
            "reports": [item.to_dict() for item in reports],
        }

    @router.post("/admin/employers/{employer_id}/review")
    def review_employer(
        employer_id: int,
        body: ReviewBody,
        reviewer: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        """Approve (→ verified) or reject an employer. Audited."""
        try:
            employer = store.set_employer_status(
                employer_id,
                "verified" if body.approve else "rejected",
                reviewer=reviewer.email,
                note=body.note,
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        users.audit(
            reviewer.email,
            "kv:employer_review",
            f"employer:{employer_id}:{'ok' if body.approve else 'no'}",
        )
        return {"employer": employer.to_dict()}

    @router.post("/admin/listings/{listing_id}/review")
    def review_listing(
        listing_id: int,
        body: ReviewBody,
        reviewer: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        """Approve (→ verified, worker-visible) or reject a listing.
        Approving requires a verified employer — 409 otherwise.
        Audited."""
        try:
            listing = store.set_listing_status(
                listing_id,
                "verified" if body.approve else "rejected",
                reviewer=reviewer.email,
                note=body.note,
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        users.audit(
            reviewer.email,
            "kv:listing_review",
            f"listing:{listing_id}:{'ok' if body.approve else 'no'}",
        )
        return {"listing": listing.to_dict()}

    @router.post("/admin/employers/{employer_id}/endorse")
    def endorse_employer(
        employer_id: int,
        body: EndorseBody,
        reviewer: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        """Record (or clear, with empty strings) the ITI /
        skilling-centre / panchayat endorsement badge. In Stage 5 an
        admin records it on the endorser's behalf; the coordinator
        console (Stage 8) takes this over. Audited."""
        try:
            employer = store.set_endorsement(
                employer_id, body.endorsed_by, body.endorsed_by_type, body.note
            )
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        users.audit(reviewer.email, "kv:employer_endorse", f"employer:{employer_id}")
        return {"employer": employer.to_dict()}

    @router.get("/admin/reports")
    def list_reports(
        status: str | None = None,
        user: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        """All worker reports (filter by status)."""
        reports = store.list_reports(status=status)
        return {"reports": [item.to_dict() for item in reports]}

    @router.post("/admin/reports/{report_id}/review")
    def review_report(
        report_id: int,
        body: ReportReviewBody,
        reviewer: User = Depends(admin_user),  # noqa: B008
    ) -> dict:
        """Uphold or dismiss a worker report. Upholding flags the
        listing (if it is still verified); dismissing closes the
        report with no listing change. Audited."""
        if body.action not in ("uphold", "dismiss"):
            raise HTTPException(400, "action must be 'uphold' or 'dismiss'.")
        try:
            report = store.set_report_status(
                report_id,
                "upheld" if body.action == "uphold" else "dismissed",
                reviewer=reviewer.email,
                note=body.note,
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        listing = store.get_listing(report.listing_id)
        if body.action == "uphold" and listing is not None and listing.status == "verified":
            listing = store.set_listing_status(
                listing.id, "flagged", reviewer=reviewer.email, note="Report upheld."
            )
        users.audit(reviewer.email, "kv:report_review", f"report:{report_id}:{body.action}")
        return {
            "report": report.to_dict(),
            "listing": listing.to_dict() if listing is not None else None,
        }

    return router
