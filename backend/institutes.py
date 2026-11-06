"""Phase 4 routes: institute portal, mounted under ``/api/v1/institutes``.

Role model (checked server-side on EVERY route):
- ``POST /`` — any signed-in user (self-serve) or a platform admin; the
  creator becomes the institute's ``institute_admin``. A signed-in user
  who already belongs to an institute gets 409 (one institute per user
  in v1).
- Invites / member removal / branding — ``institute_admin`` of *that*
  institute only.
- Member list, cohort, per-student detail, exports, review queue and run
  reviews — ``institute_admin`` or ``counsellor`` of *that* institute
  only. Students and other institutes get 403; anonymous gets 401 (from
  the ``current_user`` dependency). Cohort payloads are aggregate-first
  and never contain e-mail addresses.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from career_guidance.institutes import (
    MAX_CSV_BYTES,
    InstituteStore,
    cohort_csv,
    cohort_pdf,
    compute_cohort,
    compute_cohort_comparison,
    parse_invite_csv,
    report_schedule_payload,
)
from career_guidance.users import User

logger = logging.getLogger("career_guidance.institutes_api")

STAFF_ROLES = ("institute_admin", "counsellor")


class CreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(default="", max_length=80)
    logo_url: str = Field(default="", max_length=500)
    accent_color: str = Field(default="", max_length=7)


class BrandingBody(BaseModel):
    name: str = Field(default="", max_length=160)
    logo_url: str = Field(default="", max_length=500)
    accent_color: str = Field(default="", max_length=7)
    # Phase 9: report-schedule PREFERENCE (none|weekly|monthly). Records
    # the preference + a nominal next_run only — no scheduler sends
    # anything yet (see career_guidance.institutes.report_schedule_payload).
    report_schedule: str | None = None


class InviteMember(BaseModel):
    email: str
    name: str = ""
    role: str = "student"


class InviteBody(BaseModel):
    members: list[InviteMember] = Field(default_factory=list, max_length=500)
    emails: list[str] = Field(default_factory=list, max_length=500)


class ReviewBody(BaseModel):
    note: str = Field(default="", max_length=2000)
    approved: bool = True


def build_router(settings, current_user, users, db) -> APIRouter:
    router = APIRouter(prefix="/api/v1/institutes", tags=["institutes"])
    store = InstituteStore(settings.database_path)

    # Phase 5: institute membership is guardian/school-mediated, so cohort
    # AGGREGATES keep counting every student — but an unconsented minor
    # must not appear on the individual needs-attention list.
    from career_guidance.consent import ConsentStore, is_unconsented_minor

    consent_store = ConsentStore(settings.database_path)

    def _filter_attention(cohort: dict) -> dict:
        cohort = {**cohort}
        cohort["needs_attention"] = [
            entry
            for entry in cohort.get("needs_attention", [])
            if not is_unconsented_minor(users.get(entry["user_id"]), consent_store)
        ]
        return cohort

    # ------------------------------------------------------------- helpers
    def _institute_or_404(institute_id: int) -> dict:
        institute = store.get_institute(institute_id)
        if institute is None:
            raise HTTPException(404, "Institute not found.")
        return institute

    def _require(user: User, institute_id: int, roles: tuple[str, ...]) -> dict:
        """Membership gate: returns the membership or raises 403."""
        institute = _institute_or_404(institute_id)
        membership = store.membership_of(user.id)
        if (
            not membership
            or membership["institute_id"] != institute_id
            or membership["institute_role"] not in roles
        ):
            raise HTTPException(403, "Not a member of this institute with the required role.")
        return {**membership, "institute": institute}

    def _payload(institute: dict, user: User) -> dict:
        membership = store.membership_of(user.id)
        return {
            "institute": institute,
            "my_role": membership["institute_role"] if membership else "",
            "seat_usage": store.seat_usage(institute["id"]),
            "report_schedule": report_schedule_payload(institute),
        }

    def _cohort(institute_id: int) -> dict:
        members = store.members(institute_id)
        runs = db.list_runs(limit=5000)
        return _filter_attention(compute_cohort(members, runs))

    # --------------------------------------------------------------- mine
    @router.get("/mine")
    def mine(user: User = Depends(current_user)) -> dict:  # noqa: B008
        membership = store.membership_of(user.id)
        if not membership:
            return {"institute": None, "my_role": ""}
        return _payload(_institute_or_404(membership["institute_id"]), user)

    @router.post("/invites/claim")
    def claim(user: User = Depends(current_user)) -> dict:  # noqa: B008
        try:
            invite = store.claim_invites(user.id, user.email)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if invite is None:
            raise HTTPException(404, "No pending invite for your e-mail address.")
        users.audit(user.email, "institute:claim", str(invite["institute_id"]))
        return {"claimed": True, "institute_id": invite["institute_id"]}

    @router.get("/reviews/mine")
    def my_reviews(user: User = Depends(current_user)) -> dict:  # noqa: B008
        out = []
        for run in db.list_runs(limit=1000):
            if run.user_id != user.id:
                continue
            review = store.review_for_run(run.id)
            if review:
                out.append({"run_id": run.id, "counsellor_review": review})
        return {"reviews": out}

    # ------------------------------------------------------------- create
    @router.post("", status_code=201)
    @router.post("/", status_code=201)
    def create(body: CreateBody, user: User = Depends(current_user)) -> dict:  # noqa: B008
        if store.membership_of(user.id):
            raise HTTPException(409, "You already belong to an institute.")
        try:
            institute = store.create_institute(
                body.name, user.id, body.slug, body.logo_url, body.accent_color
            )
            store.set_membership(user.id, institute["id"], "institute_admin")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(user.email, "institute:create", institute["slug"])
        return _payload(institute, user)

    # ------------------------------------------------------------- detail
    @router.get("/{institute_id}")
    def detail(institute_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        institute = _institute_or_404(institute_id)
        membership = store.membership_of(user.id)
        if not user.is_admin and (not membership or membership["institute_id"] != institute_id):
            raise HTTPException(403, "Not a member of this institute.")
        return _payload(institute, user)

    @router.patch("/{institute_id}")
    def branding(
        institute_id: int,
        body: BrandingBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require(user, institute_id, ("institute_admin",))
        try:
            institute = store.update_branding(
                institute_id, body.name, body.logo_url, body.accent_color
            )
            if body.report_schedule is not None:
                institute = store.set_report_schedule(institute_id, body.report_schedule)
                users.audit(
                    user.email,
                    "institute:report-schedule",
                    f"{institute_id}:{body.report_schedule}",
                )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        users.audit(user.email, "institute:branding", str(institute_id))
        return _payload(institute, user)

    # ------------------------------------------------------------ members
    @router.get("/{institute_id}/members")
    def members(institute_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        _require(user, institute_id, STAFF_ROLES)
        return {
            "members": store.members(institute_id),
            "invites": store.list_invites(institute_id),
            "seat_usage": store.seat_usage(institute_id),
        }

    @router.delete("/{institute_id}/members/{member_id}")
    def remove_member(
        institute_id: int,
        member_id: str,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require(user, institute_id, ("institute_admin",))
        if member_id == user.id:
            raise HTTPException(409, "You cannot remove yourself.")
        target = store.membership_of(member_id)
        if not target or target["institute_id"] != institute_id:
            raise HTTPException(404, "Member not found in this institute.")
        store.clear_membership(member_id)
        users.audit(user.email, "institute:remove-member", member_id)
        return {"removed": True, "seat_usage": store.seat_usage(institute_id)}

    # ------------------------------------------------------------ invites
    @router.post("/{institute_id}/invites")
    def invite(
        institute_id: int,
        body: InviteBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require(user, institute_id, ("institute_admin",))
        rows = [m.model_dump() for m in body.members]
        rows += [{"email": e, "name": "", "role": "student"} for e in body.emails]
        if not rows:
            raise HTTPException(422, "No invite rows supplied.")
        if len(rows) > 500:
            raise HTTPException(422, "At most 500 invites per request.")
        report = store.process_invites(institute_id, rows, actor=user.id)
        users.audit(user.email, "institute:invite", f"{institute_id}:{len(rows)}")
        return report

    @router.post("/{institute_id}/invites/csv")
    async def invite_csv(
        institute_id: int,
        file: UploadFile = File(...),  # noqa: B008
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require(user, institute_id, ("institute_admin",))
        data = await file.read(MAX_CSV_BYTES + 1)
        try:
            rows, parse_errors = parse_invite_csv(data)
        except ValueError as error:
            # Whole-file problem → structured 422, never a 500.
            raise HTTPException(422, detail={"error": str(error), "row_errors": []}) from error
        report = store.process_invites(institute_id, rows, actor=user.id)
        results = sorted(
            report["results"] + [{**e, "status": "error"} for e in parse_errors],
            key=lambda r: r["row"],
        )
        users.audit(user.email, "institute:invite-csv", f"{institute_id}:{len(results)}")
        return {
            "results": results,
            "invited": report["invited"],
            "pending": report["pending"],
            "errors": report["errors"] + len(parse_errors),
        }

    # ------------------------------------------------------------- cohort
    @router.get("/{institute_id}/cohort")
    def cohort(
        institute_id: int,
        period: str = "",
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Cohort aggregates; Phase 9 adds term-over-term comparison.

        No ``period`` → the Phase 4 all-time cohort (unchanged).
        ``?period=current|previous`` → the cohort for that CALENDAR
        QUARTER plus a ``comparison`` block (both quarters + deltas).
        A period with no stored runs returns honest zeros/empty lists.
        Aggregates only — never e-mail addresses.
        """
        _require(user, institute_id, STAFF_ROLES)
        institute = _institute_or_404(institute_id)
        if not period:
            return {"cohort": _cohort(institute_id), "institute": institute}
        if period not in ("current", "previous"):
            raise HTTPException(422, "period must be 'current' or 'previous'.")
        members = store.members(institute_id)
        comparison = compute_cohort_comparison(members, db.list_runs(limit=5000))
        comparison["current"] = _filter_attention(comparison["current"])
        comparison["previous"] = _filter_attention(comparison["previous"])
        return {
            "cohort": comparison[period],
            "comparison": comparison,
            "institute": institute,
        }

    @router.get("/{institute_id}/students")
    def students(institute_id: int, user: User = Depends(current_user)) -> dict:  # noqa: B008
        _require(user, institute_id, STAFF_ROLES)
        members = store.members(institute_id)
        cohort = _filter_attention(compute_cohort(members, db.list_runs(limit=5000)))
        attention = {a["user_id"]: a for a in cohort["needs_attention"]}
        runs = db.list_runs(limit=5000)
        out = []
        for member in members:
            mine = [r for r in runs if r.user_id == member["user_id"]]
            latest = mine[0] if mine else None
            out.append(
                {
                    "user_id": member["user_id"],
                    "name": member["name"],
                    "institute_role": member["institute_role"],
                    "runs_count": len(mine),
                    "last_run_at": latest.created_at if latest else "",
                    "latest_top_career": (
                        latest.recommendations[0].title if latest and latest.recommendations else ""
                    ),
                    "needs_attention": member["user_id"] in attention,
                }
            )
        return {"students": out}

    @router.get("/{institute_id}/students/{student_id}/runs")
    def student_runs(
        institute_id: int,
        student_id: str,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        _require(user, institute_id, STAFF_ROLES)
        target = store.membership_of(student_id)
        if not target or target["institute_id"] != institute_id:
            raise HTTPException(404, "Student not found in this institute.")
        out = []
        for run in db.list_runs(limit=1000):
            if run.user_id != student_id:
                continue
            out.append(
                {
                    "id": run.id,
                    "created_at": run.created_at,
                    "top_career": run.recommendations[0].title if run.recommendations else "",
                    "top_match_percent": (
                        round(float(run.recommendations[0].match_score or 0) * 100, 1)
                        if run.recommendations
                        else None
                    ),
                    "missing_skills": [
                        s for rec in run.recommendations for s in (rec.missing_skills or [])
                    ],
                    "counsellor_review": store.review_for_run(run.id),
                }
            )
        return {"runs": out}

    # ------------------------------------------------------------ exports
    @router.get("/{institute_id}/cohort/report.csv")
    def cohort_csv_route(institute_id: int, user: User = Depends(current_user)):  # noqa: B008
        _require(user, institute_id, STAFF_ROLES)
        return PlainTextResponse(
            cohort_csv(_cohort(institute_id), _institute_or_404(institute_id)),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cohort-report.csv"},
        )

    @router.get("/{institute_id}/cohort/report.pdf")
    def cohort_pdf_route(institute_id: int, user: User = Depends(current_user)):  # noqa: B008
        _require(user, institute_id, STAFF_ROLES)
        pdf = cohort_pdf(_cohort(institute_id), _institute_or_404(institute_id))
        return Response(
            pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=cohort-report.pdf"},
        )

    # ------------------------------------------------------------- reviews
    @router.get("/{institute_id}/review-queue")
    def review_queue(
        institute_id: int,
        limit: int = 50,
        offset: int = 0,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Counsellor work queue (Phase 9 v2): UNREVIEWED runs of this
        institute's students only, OLDEST first, paginated with
        ``limit``/``offset``. Reviewing a run (the Phase 4 review
        endpoint below) removes it from this queue.
        """
        _require(user, institute_id, STAFF_ROLES)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        members = {m["user_id"]: m for m in store.members(institute_id)}
        student_ids = {uid for uid, m in members.items() if m["institute_role"] == "student"}
        runs = [r for r in db.list_runs(limit=5000) if r.user_id in student_ids]
        reviewed = store.reviewed_run_ids([r.id for r in runs])
        pending = sorted(
            (r for r in runs if r.id not in reviewed), key=lambda r: (r.created_at, r.id)
        )
        page = pending[offset : offset + limit]
        return {
            "queue": [
                {
                    "run_id": r.id,
                    "student_id": r.user_id,
                    "student_name": members[r.user_id]["name"],
                    "created_at": r.created_at,
                    "top_career": r.recommendations[0].title if r.recommendations else "",
                    "reviewed": False,
                }
                for r in page
            ],
            "total": len(pending),
            "limit": limit,
            "offset": offset,
        }

    @router.post("/{institute_id}/runs/{run_id}/review")
    def review_run(
        institute_id: int,
        run_id: int,
        body: ReviewBody,
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        membership = _require(user, institute_id, STAFF_ROLES)
        run = next((r for r in db.list_runs(limit=5000) if r.id == run_id), None)
        owner = store.membership_of(run.user_id) if run and run.user_id else None
        if run is None or not owner or owner["institute_id"] != institute_id:
            raise HTTPException(404, "Run not found for a student of this institute.")
        review = store.add_review(
            run_id, user.id, membership["institute_role"], body.note, body.approved
        )
        users.audit(user.email, "institute:run-review", str(run_id))
        return {"counsellor_review": review}

    return router
