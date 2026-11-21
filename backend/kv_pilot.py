"""Kaam-Vaani pilot/institute console (Step 9.2).

Pilot OPERATIONS supporting the AI's deployment — bulk worker
onboarding, employer verification and metrics — never a recruiter
portal (product direction, 21 Nov 2026). Coordinators and admins
only; workers and employers get 403. Mounted behind ``KV_PILOT``.

Every metric comes from stored rows (see ``pilot_metrics`` on the
two stores); voice-flow match views are not persisted and so are
not reported (L65).
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from backend.auth import Auth
from career_guidance.config import Settings
from career_guidance.kaamvaani.consent import ConsentStore
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.kaamvaani.pilot import MAX_BULK_ROWS, bulk_onboard
from career_guidance.users import User


class ReviewBody(BaseModel):
    approve: bool = True
    note: str = Field(default="", max_length=1000)


class EndorseBody(BaseModel):
    endorsed_by: str = Field(default="", max_length=120)
    endorsed_by_type: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=1000)


class ReportReviewBody(BaseModel):
    action: str = Field(default="uphold", max_length=20)
    note: str = Field(default="", max_length=1000)


class BulkWorkersBody(BaseModel):
    rows: list[dict] = Field(..., min_length=1, max_length=MAX_BULK_ROWS)


def build_router(settings: Settings, current_user, auth: Auth) -> APIRouter:
    """Return the pilot-console router. ``auth`` supplies the user
    store (role checks, worker names, phone lookup, audit log)."""
    router = APIRouter(prefix="/api/v1/kv/pilot", tags=["kaam-vaani-pilot"])
    consent = ConsentStore(settings.database_target)
    employers = EmployerStore(settings.database_target)
    users = auth.store

    def pilot_user(user: User = Depends(current_user)) -> User:  # noqa: B008
        """Coordinators run the pilot; admins oversee it. Everyone
        else gets 403."""
        if not (user.is_admin or user.is_coordinator):
            raise HTTPException(403, "Pilot console is for coordinators and admins.")
        return user

    @router.get("/status")
    def status(user: User = Depends(pilot_user)) -> dict:  # noqa: B008
        return {
            "enabled": True,
            "profiles": consent.count_worker_profiles(),
            "review_queue": employers.review_queue_counts(),
        }

    @router.get("/metrics")
    def metrics(user: User = Depends(pilot_user)) -> dict:  # noqa: B008
        """Pilot metrics, all from stored rows: profiles, consents,
        shortlists, contact requests, outcomes, 30/90-day retention,
        employers, listings and scam reports."""
        return {**consent.pilot_metrics(), **employers.pilot_metrics()}

    @router.get("/metrics.csv")
    def metrics_csv(user: User = Depends(pilot_user)):  # noqa: B008
        """The same metrics as CSV (metric,value rows) for a
        spreadsheet. Nested groups flatten with dots, e.g.
        ``consents.granted``; a retention rate with no follow-ups
        yet exports as an empty cell, never 0."""
        data = {**consent.pilot_metrics(), **employers.pilot_metrics()}
        rows: list[tuple[str, object]] = []

        def _flatten(prefix: str, value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    _flatten(f"{prefix}.{key}" if prefix else str(key), item)
            else:
                rows.append((prefix, "" if value is None else value))

        _flatten("", data)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=kaam-vaani-metrics.csv"},
        )

    def _enriched_roster(limit: int, offset: int) -> list[dict]:
        profiles = consent.list_worker_profiles(limit=limit, offset=offset)
        out = []
        for profile in profiles:
            data = profile.to_dict()
            worker = users.get(profile.user_id)
            data["worker_name"] = worker.name if worker else ""
            data["worker_email"] = worker.email if worker else ""
            out.append(data)
        return out

    @router.get("/workers")
    def list_workers(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        user: User = Depends(pilot_user),  # noqa: B008
    ) -> dict:
        """Worker roster, newest first, with names enriched from the
        accounts table. Sample workers are flagged ``is_sample``."""
        return {
            "workers": _enriched_roster(limit, offset),
            "counts": consent.count_worker_profiles(),
        }

    @router.get("/workers.csv")
    def workers_csv(user: User = Depends(pilot_user)):  # noqa: B008
        """The full roster as CSV (paged internally in 500s)."""
        columns = [
            "user_id",
            "worker_name",
            "worker_email",
            "skills",
            "education",
            "city",
            "district",
            "income_monthly",
            "goal_type",
            "language",
            "is_sample",
            "created_at",
        ]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        offset = 0
        while True:
            page = _enriched_roster(limit=500, offset=offset)
            if not page:
                break
            for worker in page:
                row = dict(worker)
                row["skills"] = "; ".join(worker.get("skills") or [])
                writer.writerow(row)
            offset += len(page)
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=kaam-vaani-workers.csv"},
        )

    @router.post("/workers/bulk")
    def bulk_workers(
        body: BulkWorkersBody,
        user: User = Depends(pilot_user),  # noqa: B008
    ) -> dict:
        """Onboard up to 100 workers at once. Each row needs a
        ``user_id`` or a ``phone`` (resolved against accounts) plus
        profile fields. Per-row results: a bad row fails with its
        reason and never fails the batch. Audited."""
        try:
            result = bulk_onboard(consent, users, body.rows)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(
            user.email,
            "kv:pilot_bulk_onboard",
            f"created:{result['created']} updated:{result['updated']} failed:{result['failed']}",
        )
        return result

    @router.get("/review-queue")
    def review_queue(user: User = Depends(pilot_user)) -> dict:  # noqa: B008
        """Pending + flagged employers and listings, plus open
        reports — the same queue the admin console shows, for the
        coordinators who work it."""
        pending_employers = employers.list_employers(status="pending") + employers.list_employers(
            status="flagged"
        )
        pending_listings = employers.list_listings(status="pending") + employers.list_listings(
            status="flagged"
        )
        reports = employers.list_reports(status="open")
        return {
            "counts": employers.review_queue_counts(),
            "employers": [item.to_dict() for item in pending_employers],
            "listings": [item.to_dict() for item in pending_listings],
            "reports": [item.to_dict() for item in reports],
        }

    @router.post("/employers/{employer_id}/review")
    def review_employer(
        employer_id: int,
        body: ReviewBody,
        reviewer: User = Depends(pilot_user),  # noqa: B008
    ) -> dict:
        """Approve (→ verified) or reject an employer. Audited."""
        try:
            employer = employers.set_employer_status(
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

    @router.post("/listings/{listing_id}/review")
    def review_listing(
        listing_id: int,
        body: ReviewBody,
        reviewer: User = Depends(pilot_user),  # noqa: B008
    ) -> dict:
        """Approve (→ verified, worker-visible) or reject a listing.
        Approving requires a verified employer — 409 otherwise.
        Audited."""
        try:
            listing = employers.set_listing_status(
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

    @router.post("/employers/{employer_id}/endorse")
    def endorse_employer(
        employer_id: int,
        body: EndorseBody,
        reviewer: User = Depends(pilot_user),  # noqa: B008
    ) -> dict:
        """Record (or clear, with empty strings) the ITI /
        skilling-centre / panchayat endorsement badge. The
        coordinator console takes this over from the admin console
        (Stage 5). Audited."""
        try:
            employer = employers.set_endorsement(
                employer_id, body.endorsed_by, body.endorsed_by_type, body.note
            )
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        users.audit(reviewer.email, "kv:employer_endorse", f"employer:{employer_id}")
        return {"employer": employer.to_dict()}

    @router.post("/reports/{report_id}/review")
    def review_report(
        report_id: int,
        body: ReportReviewBody,
        reviewer: User = Depends(pilot_user),  # noqa: B008
    ) -> dict:
        """Uphold or dismiss a worker report. Upholding flags the
        listing (if it is still verified); dismissing closes the
        report with no listing change. Audited."""
        if body.action not in ("uphold", "dismiss"):
            raise HTTPException(400, "action must be 'uphold' or 'dismiss'.")
        try:
            report = employers.set_report_status(
                report_id,
                "upheld" if body.action == "uphold" else "dismissed",
                reviewer=reviewer.email,
                note=body.note,
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        listing = employers.get_listing(report.listing_id)
        if body.action == "uphold" and listing is not None and listing.status == "verified":
            listing = employers.set_listing_status(
                listing.id, "flagged", reviewer=reviewer.email, note="Report upheld."
            )
        users.audit(reviewer.email, "kv:report_review", f"report:{report_id}:{body.action}")
        return {
            "report": report.to_dict(),
            "listing": listing.to_dict() if listing is not None else None,
        }

    return router
