"""Kaam-Vaani employer + listing store (Stage 5).

Tables live in the relational DB (migration v13: ``kv_employers``,
``kv_listings``, ``kv_listing_reports``) and go through
``career_guidance.db.connect()`` like the RAG store — no direct
``sqlite3`` — so the Postgres path works from day one. SQL uses ``?``
placeholders; inserts use ``RETURNING id`` on Postgres (psycopg has no
``lastrowid``) and ``lastrowid`` on SQLite (the ``storage.py`` pattern).

Verification states
-------------------
Employers and listings each carry a status: ``pending`` → ``verified``
| ``rejected`` | ``flagged``. Workers see **verified listings only**,
and a listing can only be verified when its employer is verified
(the router enforces that; this module enforces the state machines).

* An employer edits their own profile → back to ``pending`` for
  re-review (ASSUMPTIONS.md A39).
* A listing edit by its employer → back to ``pending`` for re-review.
* Three open worker reports auto-flag a listing (``REPORT_AUTO_FLAG``).

No auto-verify anywhere: every verification is a human admin decision
(R5 / LIMITATIONS.md L41). Seeded demo rows are marked ``is_sample``
and the API/UI always label them as sample data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from career_guidance import db as db_layer
from career_guidance.kaamvaani.dedup import DuplicateIndex, DuplicateMatch
from career_guidance.kaamvaani.geo import GeohashIndex, city_coords, mapped_cities

logger = logging.getLogger("career_guidance.kaamvaani.employers")

# Default radius (km) when a worker asks for jobs near a city
# without naming a distance, and the widest radius the API
# accepts (beyond 500 km a "near me" search over Tamil Nadu is
# meaningless — the whole state fits inside it).
DEFAULT_RADIUS_KM = 25.0
MAX_RADIUS_KM = 500.0

EMPLOYER_STATUSES: tuple[str, ...] = ("pending", "verified", "rejected", "flagged")
LISTING_STATUSES: tuple[str, ...] = ("pending", "verified", "rejected", "flagged")
REPORT_STATUSES: tuple[str, ...] = ("open", "upheld", "dismissed")
REPORT_REASONS: tuple[str, ...] = (
    "fake",
    "fee_demanded",
    "not_as_described",
    "unsafe",
    "other",
)

# Open reports that auto-flag a listing (verified → flagged). The flag
# only hides the listing from workers until an admin re-reviews it — it
# is not a verdict.
REPORT_AUTO_FLAG = 3

# Allowed status transitions (the state machines). "rejected → pending"
# is the re-apply path: an employer fixes the problem and asks again.
_EMPLOYER_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"verified", "rejected", "flagged"}),
    "verified": frozenset({"flagged", "rejected"}),
    "flagged": frozenset({"verified", "rejected", "pending"}),
    "rejected": frozenset({"pending"}),
}
_LISTING_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"verified", "rejected", "flagged"}),
    "verified": frozenset({"flagged", "rejected"}),
    "flagged": frozenset({"verified", "rejected", "pending"}),
    "rejected": frozenset({"pending"}),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_postgres(conn) -> bool:
    return getattr(conn, "dialect", "sqlite") == "postgres"


def _insert_id(conn, sql: str, params: tuple) -> int:
    """Insert one row and return its id, on either dialect."""
    if _is_postgres(conn):
        row = conn.execute(sql + " RETURNING id", params).fetchone()
        return int(row["id"])
    cursor = conn.execute(sql, params)
    return int(cursor.lastrowid or 0)


@dataclass
class Employer:
    """One registered employer (one row per user account)."""

    id: int
    user_id: str
    business_name: str
    contact_name: str
    phone_e164: str
    email: str
    city: str
    district: str
    state: str
    business_type: str
    description: str
    status: str
    endorsed_by: str = ""
    endorsed_by_type: str = ""
    endorsement_note: str = ""
    created_at: str = ""
    updated_at: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""

    @property
    def endorsed(self) -> bool:
        """The endorsement badge: an ITI / skilling-centre / panchayat
        endorser is recorded (F3)."""
        return bool(self.endorsed_by.strip())

    def to_dict(self) -> dict:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data["endorsed"] = self.endorsed
        return data


@dataclass
class Listing:
    """One job listing. ``is_sample`` marks seeded demo data."""

    id: int
    employer_id: int
    title: str
    role_category: str
    description: str
    city: str
    district: str
    state: str
    pay_monthly_min: int | None
    pay_monthly_max: int | None
    pay_text: str
    work_type: str
    shift: str
    openings: int
    requirements: str
    contact_info: str
    status: str
    risk_score: int = 0
    risk_flags: list = field(default_factory=list)
    is_sample: bool = False
    created_at: str = ""
    updated_at: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""

    def to_dict(self) -> dict:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data["risk_flags"] = list(self.risk_flags)
        return data

    def public_dict(self) -> dict:
        """What workers see: no review internals, no risk internals.
        The sample-data label stays — a worker must never mistake a
        seeded listing for a real job."""
        return {
            "id": self.id,
            "employer_id": self.employer_id,
            "title": self.title,
            "role_category": self.role_category,
            "description": self.description,
            "city": self.city,
            "district": self.district,
            "state": self.state,
            "pay_monthly_min": self.pay_monthly_min,
            "pay_monthly_max": self.pay_monthly_max,
            "pay_text": self.pay_text,
            "work_type": self.work_type,
            "shift": self.shift,
            "openings": self.openings,
            "requirements": self.requirements,
            "contact_info": self.contact_info,
            "is_sample": self.is_sample,
            "created_at": self.created_at,
        }


@dataclass
class ListingReport:
    """One worker report against a listing."""

    id: int
    listing_id: int
    reporter_user_id: str
    reason: str
    details: str
    status: str
    created_at: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


_EMPLOYER_COLUMNS = (
    "id",
    "user_id",
    "business_name",
    "contact_name",
    "phone_e164",
    "email",
    "city",
    "district",
    "state",
    "business_type",
    "description",
    "status",
    "endorsed_by",
    "endorsed_by_type",
    "endorsement_note",
    "created_at",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
    "review_note",
)

_LISTING_COLUMNS = (
    "id",
    "employer_id",
    "title",
    "role_category",
    "description",
    "city",
    "district",
    "state",
    "pay_monthly_min",
    "pay_monthly_max",
    "pay_text",
    "work_type",
    "shift",
    "openings",
    "requirements",
    "contact_info",
    "status",
    "risk_score",
    "risk_flags",
    "is_sample",
    "created_at",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
    "review_note",
)

_REPORT_COLUMNS = (
    "id",
    "listing_id",
    "reporter_user_id",
    "reason",
    "details",
    "status",
    "created_at",
    "reviewed_by",
    "reviewed_at",
    "review_note",
)


def _employer_from_row(row) -> Employer:
    return Employer(**{name: row[name] for name in _EMPLOYER_COLUMNS})


def _listing_from_row(row) -> Listing:
    data = {name: row[name] for name in _LISTING_COLUMNS}
    try:
        data["risk_flags"] = json.loads(data["risk_flags"] or "[]")
    except (ValueError, TypeError):
        data["risk_flags"] = []
    data["is_sample"] = bool(data["is_sample"])
    return Listing(**data)


def _report_from_row(row) -> ListingReport:
    return ListingReport(**{name: row[name] for name in _REPORT_COLUMNS})


class EmployerStore:
    """Employers, listings and listing reports (migration v13).
    ``target`` is the same path-or-URL the storage layer takes
    (``settings.database_target``)."""

    def __init__(self, target: str) -> None:
        self.target = target
        # Cached indexes over listings, built lazily and
        # invalidated by every listing write below (Step 8.3 geo
        # index over verified listings; Step 8.4 duplicate index
        # over all listings). Rebuilding per request would cost
        # more than the indexes save (the geo build is ~1 s at
        # 100k listings; see the benchmark in the plan doc).
        self._geo_index: GeohashIndex[int] | None = None
        self._dup_index: DuplicateIndex | None = None

    # ---------------------------------------------------------- employers

    def create_employer(
        self,
        user_id: str,
        business_name: str,
        contact_name: str = "",
        phone_e164: str = "",
        email: str = "",
        city: str = "",
        district: str = "",
        state: str = "Tamil Nadu",
        business_type: str = "",
        description: str = "",
    ) -> Employer:
        """Register an employer profile (status ``pending``). One
        profile per user — a second registration raises ValueError."""
        if self.get_employer_by_user(user_id) is not None:
            raise ValueError("This account already has an employer profile.")
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                employer_id = _insert_id(
                    conn,
                    "INSERT INTO kv_employers (user_id, business_name, contact_name,"
                    " phone_e164, email, city, district, state, business_type,"
                    " description, status, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        business_name.strip(),
                        contact_name.strip(),
                        phone_e164.strip(),
                        email.strip(),
                        city.strip(),
                        district.strip(),
                        state.strip() or "Tamil Nadu",
                        business_type.strip(),
                        description.strip(),
                        "pending",
                        now,
                        now,
                    ),
                )
            employer = self.get_employer(employer_id)
            assert employer is not None
            return employer
        finally:
            conn.close()

    def get_employer(self, employer_id: int) -> Employer | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute("SELECT * FROM kv_employers WHERE id = ?", (employer_id,)).fetchone()
            return _employer_from_row(row) if row is not None else None
        finally:
            conn.close()

    def get_employer_by_user(self, user_id: str) -> Employer | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_employers WHERE user_id = ?", (user_id,)
            ).fetchone()
            return _employer_from_row(row) if row is not None else None
        finally:
            conn.close()

    def delete_employer_data(self, user_id: str) -> tuple[dict[str, int], list[int]]:
        """Erase an employer's Kaam-Vaani data (Step 9.4, DPDP
        erasure). Deletes the employer row and all their listings
        (one employer per account), invalidating the cached
        listing indexes. Listing REPORTS about those listings are
        KEPT — they are workers' safety records naming no
        employer PII, and deleting them would destroy scam
        evidence. Consents TO the employer are the ConsentStore's
        job (``delete_employer_consents``) — this method returns
        the deleted employer ids alongside the counts so the
        caller can clean that side up."""
        employer = self.get_employer_by_user(user_id)
        if employer is None:
            return {"kv_employers": 0, "kv_listings": 0}, []
        conn = db_layer.connect(self.target)
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM kv_listings WHERE employer_id = ?", (employer.id,)
                )
                listings = cursor.rowcount or 0
                cursor = conn.execute("DELETE FROM kv_employers WHERE id = ?", (employer.id,))
                employers = cursor.rowcount or 0
        finally:
            conn.close()
        if listings:
            self._invalidate_listing_indexes()
        return (
            {"kv_employers": employers, "kv_listings": listings},
            [employer.id],
        )

    def list_employers(self, status: str | None = None, limit: int = 200) -> list[Employer]:
        conn = db_layer.connect(self.target)
        try:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM kv_employers ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kv_employers WHERE status = ?"
                    " ORDER BY created_at DESC, id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            return [_employer_from_row(row) for row in rows]
        finally:
            conn.close()

    def update_employer(self, employer_id: int, **fields) -> Employer:
        """Edit an employer's own profile. A verified employer that
        edits goes back to ``pending`` — the changed details need a
        fresh review (A39). ``status`` cannot be set this way (use
        ``set_employer_status``)."""
        allowed = {
            "business_name",
            "contact_name",
            "phone_e164",
            "email",
            "city",
            "district",
            "state",
            "business_type",
            "description",
        }
        updates = {k: str(v).strip() for k, v in fields.items() if k in allowed}
        employer = self.get_employer(employer_id)
        if employer is None:
            raise ValueError(f"Unknown employer: {employer_id}")
        if employer.status == "verified":
            updates["status"] = "pending"
            updates["review_note"] = "Profile edited — needs re-review."
        updates["updated_at"] = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                sets = ", ".join(f"{name} = ?" for name in updates)
                conn.execute(
                    f"UPDATE kv_employers SET {sets} WHERE id = ?",  # noqa: S608
                    (*updates.values(), employer_id),
                )
            updated = self.get_employer(employer_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    def set_employer_status(
        self, employer_id: int, status: str, reviewer: str = "", note: str = ""
    ) -> Employer:
        """Admin review transition. Raises ValueError on an illegal
        transition or an unknown status/employer."""
        if status not in EMPLOYER_STATUSES:
            raise ValueError(f"Unknown employer status: {status!r}")
        employer = self.get_employer(employer_id)
        if employer is None:
            raise ValueError(f"Unknown employer: {employer_id}")
        if status not in _EMPLOYER_TRANSITIONS[employer.status]:
            raise ValueError(
                f"Cannot move employer {employer_id} from {employer.status} to {status}"
            )
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "UPDATE kv_employers SET status = ?, updated_at = ?,"
                    " reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                    (status, _now_iso(), reviewer, _now_iso(), note, employer_id),
                )
            updated = self.get_employer(employer_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    def set_endorsement(
        self, employer_id: int, endorsed_by: str, endorsed_by_type: str, note: str = ""
    ) -> Employer:
        """Record (or clear, with empty strings) the endorsement badge.
        In Stage 5 an admin records it on the endorser's behalf; the
        coordinator console (Stage 8) takes this over."""
        employer = self.get_employer(employer_id)
        if employer is None:
            raise ValueError(f"Unknown employer: {employer_id}")
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "UPDATE kv_employers SET endorsed_by = ?, endorsed_by_type = ?,"
                    " endorsement_note = ?, updated_at = ? WHERE id = ?",
                    (
                        endorsed_by.strip(),
                        endorsed_by_type.strip(),
                        note.strip(),
                        _now_iso(),
                        employer_id,
                    ),
                )
            updated = self.get_employer(employer_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    def delete_employer(self, employer_id: int) -> bool:
        """Hard delete an employer row (the seed script's ``--force``
        path — the caller removes the employer's listings first).
        Returns False when the employer did not exist."""
        conn = db_layer.connect(self.target)
        try:
            with conn:
                cursor = conn.execute("DELETE FROM kv_employers WHERE id = ?", (employer_id,))
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ----------------------------------------------------------- listings

    def create_listing(
        self,
        employer_id: int,
        title: str,
        role_category: str = "",
        description: str = "",
        city: str = "",
        district: str = "",
        state: str = "Tamil Nadu",
        pay_monthly_min: int | None = None,
        pay_monthly_max: int | None = None,
        pay_text: str = "",
        work_type: str = "full-time",
        shift: str = "",
        openings: int = 1,
        requirements: str = "",
        contact_info: str = "",
        status: str = "pending",
        risk_score: int = 0,
        risk_flags: list | None = None,
        is_sample: bool = False,
    ) -> Listing:
        """Create a listing. The caller runs the scam check first and
        passes the resulting status/score/flags — the store does not
        score. A rejected employer cannot list (ValueError)."""
        employer = self.get_employer(employer_id)
        if employer is None:
            raise ValueError(f"Unknown employer: {employer_id}")
        if employer.status == "rejected":
            raise ValueError("A rejected employer cannot create listings.")
        if status not in LISTING_STATUSES:
            raise ValueError(f"Unknown listing status: {status!r}")
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                listing_id = _insert_id(
                    conn,
                    "INSERT INTO kv_listings (employer_id, title, role_category,"
                    " description, city, district, state, pay_monthly_min,"
                    " pay_monthly_max, pay_text, work_type, shift, openings,"
                    " requirements, contact_info, status, risk_score, risk_flags,"
                    " is_sample, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        employer_id,
                        title.strip(),
                        role_category.strip(),
                        description.strip(),
                        city.strip(),
                        district.strip(),
                        state.strip() or "Tamil Nadu",
                        pay_monthly_min,
                        pay_monthly_max,
                        pay_text.strip(),
                        work_type.strip() or "full-time",
                        shift.strip(),
                        max(1, int(openings)),
                        requirements.strip(),
                        contact_info.strip(),
                        status,
                        int(risk_score),
                        json.dumps(risk_flags or []),
                        1 if is_sample else 0,
                        now,
                        now,
                    ),
                )
            self._invalidate_listing_indexes()
            listing = self.get_listing(listing_id)
            assert listing is not None
            return listing
        finally:
            conn.close()

    def get_listing(self, listing_id: int) -> Listing | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute("SELECT * FROM kv_listings WHERE id = ?", (listing_id,)).fetchone()
            return _listing_from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_listings(
        self,
        employer_id: int | None = None,
        status: str | None = None,
        city: str | None = None,
        limit: int = 200,
    ) -> list[Listing]:
        """All listings matching the filters — for employers (own) and
        admins (any). Workers must use ``list_public_listings``."""
        clauses, params = [], []
        if employer_id is not None:
            clauses.append("employer_id = ?")
            params.append(employer_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if city:
            clauses.append("city = ?")
            params.append(city)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_listings{where}"  # noqa: S608
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_listing_from_row(row) for row in rows]
        finally:
            conn.close()

    def _invalidate_listing_indexes(self) -> None:
        self._geo_index = None
        self._dup_index = None

    def _geo_index_within(self, lat: float, lon: float, radius_km: float) -> set[int]:
        """Verified listing ids within the radius, via the cached index.

        Listings in cities with no coordinates are not in the index
        and never match a radius search (L57). A listing written
        concurrently on another thread may be missed by one
        in-flight query — the next query sees it (the cache is
        invalidated synchronously by every write on this store).
        """
        if self._geo_index is None:
            conn = db_layer.connect(self.target)
            try:
                rows = conn.execute(
                    "SELECT id, city FROM kv_listings WHERE status = 'verified'"
                ).fetchall()
            finally:
                conn.close()
            entries = []
            for row in rows:
                coords = city_coords(row["city"])
                if coords is not None:
                    entries.append((int(row["id"]), coords[0], coords[1]))
            self._geo_index = GeohashIndex(entries)
        return set(self._geo_index.within(lat, lon, radius_km))

    def list_public_listings(
        self,
        city: str | None = None,
        role_category: str | None = None,
        limit: int = 100,
        near_city: str | None = None,
        radius_km: float | None = None,
    ) -> list[Listing]:
        """What workers see: **verified listings only**, newest first.
        Pending / rejected / flagged listings never appear here.

        ``near_city`` replaces the exact-city filter with a radius
        search around that city's centre (``radius_km`` defaults to
        25 km). Raises ValueError when both ``city`` and
        ``near_city`` are given, when the radius is out of range,
        or when ``near_city`` has no coordinates — the router maps
        that to a 400 naming the mapped cities.
        """
        if city and near_city:
            raise ValueError("Use city or near_city, not both.")
        if radius_km is not None and near_city is None:
            raise ValueError("radius_km needs near_city.")
        if near_city is not None:
            radius = DEFAULT_RADIUS_KM if radius_km is None else float(radius_km)
            if not 0 < radius <= MAX_RADIUS_KM:
                raise ValueError(
                    f"radius_km must be between 0 and {MAX_RADIUS_KM:g}, got {radius_km}."
                )
            centre = city_coords(near_city)
            if centre is None:
                raise ValueError(
                    f"No coordinates for {near_city!r} — radius search is "
                    f"available for: {', '.join(mapped_cities())}."
                )
            nearby = self._geo_index_within(centre[0], centre[1], radius)
            clauses, params = ["status = 'verified'"], []
            if role_category:
                clauses.append("role_category = ?")
                params.append(role_category)
            conn = db_layer.connect(self.target)
            try:
                rows = conn.execute(
                    f"SELECT * FROM kv_listings WHERE {' AND '.join(clauses)}"  # noqa: S608
                    " ORDER BY created_at DESC, id DESC",
                    (*params,),
                ).fetchall()
                listings = [_listing_from_row(row) for row in rows]
            finally:
                conn.close()
            # Newest-first order is preserved (the rows arrive
            # ordered; the index only decides membership). The
            # limit applies after the radius filter, so a nearby
            # older listing is never crowded out by distant newer
            # ones — the SQL LIMIT must not run first.
            return [listing for listing in listings if listing.id in nearby][:limit]
        clauses, params = ["status = 'verified'"], []
        if city:
            clauses.append("city = ?")
            params.append(city)
        if role_category:
            clauses.append("role_category = ?")
            params.append(role_category)
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_listings WHERE {' AND '.join(clauses)}"  # noqa: S608
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_listing_from_row(row) for row in rows]
        finally:
            conn.close()

    def _dup_index_find(
        self,
        employer_id: int,
        title: str,
        description: str,
        city: str,
        exclude_id: int | None = None,
    ) -> DuplicateMatch | None:
        """Best duplicate for a candidate listing, via the cached
        index (Step 8.4). The index covers listings of every status
        — a repost of a pending listing is still a duplicate."""
        if self._dup_index is None:
            conn = db_layer.connect(self.target)
            try:
                rows = conn.execute(
                    "SELECT id, employer_id, title, description, city, created_at FROM kv_listings"
                ).fetchall()
            finally:
                conn.close()
            self._dup_index = DuplicateIndex(
                [
                    (
                        int(row["id"]),
                        int(row["employer_id"]),
                        row["title"],
                        row["description"],
                        row["city"],
                        row["created_at"],
                    )
                    for row in rows
                ]
            )
        return self._dup_index.find(employer_id, title, description, city, exclude_id)

    def find_duplicate(
        self,
        employer_id: int,
        title: str,
        city: str,
        description: str = "",
        exclude_id: int | None = None,
    ) -> Listing | None:
        """Near-duplicate detection (Step 8.4): same employer, same
        city — an exact fingerprint match (identical title +
        description + city) or a shingle-Jaccard near match at or
        above the tuned threshold. Returns the matched listing, if
        any. A reused title with a different description is NOT a
        duplicate (a genuinely new opening reusing a title must
        not be blocked) — that is the deliberate change from the
        Stage 5 title-only check (L42). Cross-employer duplicates
        stay an admin judgement, not an automatic block."""
        match = self._dup_index_find(employer_id, title, description, city, exclude_id)
        if match is None:
            return None
        return self.get_listing(match.listing_id)

    def update_listing(self, listing_id: int, **fields) -> Listing:
        """Edit a listing. A verified listing that is edited goes back
        to ``pending`` — the changed details need a fresh review (A39).
        ``status`` / ``risk_*`` cannot be set this way (use
        ``set_listing_status`` / the scam check on re-submit)."""
        allowed = {
            "title",
            "role_category",
            "description",
            "city",
            "district",
            "state",
            "pay_monthly_min",
            "pay_monthly_max",
            "pay_text",
            "work_type",
            "shift",
            "openings",
            "requirements",
            "contact_info",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        listing = self.get_listing(listing_id)
        if listing is None:
            raise ValueError(f"Unknown listing: {listing_id}")
        if listing.status == "verified":
            updates["status"] = "pending"
            updates["review_note"] = "Listing edited — needs re-review."
        updates["updated_at"] = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                sets = ", ".join(f"{name} = ?" for name in updates)
                conn.execute(
                    f"UPDATE kv_listings SET {sets} WHERE id = ?",  # noqa: S608
                    (*updates.values(), listing_id),
                )
            self._invalidate_listing_indexes()
            updated = self.get_listing(listing_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    def set_listing_risk(self, listing_id: int, risk_score: int, risk_flags: list) -> Listing:
        """Store a (re-)run of the scam check. Does not change status —
        the caller decides the status from the score."""
        listing = self.get_listing(listing_id)
        if listing is None:
            raise ValueError(f"Unknown listing: {listing_id}")
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "UPDATE kv_listings SET risk_score = ?, risk_flags = ?,"
                    " updated_at = ? WHERE id = ?",
                    (int(risk_score), json.dumps(risk_flags or []), _now_iso(), listing_id),
                )
            updated = self.get_listing(listing_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    def set_listing_status(
        self, listing_id: int, status: str, reviewer: str = "", note: str = ""
    ) -> Listing:
        """Admin review transition. Raises ValueError on an illegal
        transition or an unknown status/listing. Verifying a listing
        whose employer is not verified is rejected here too — the
        router checks first, this is the second line of defence."""
        if status not in LISTING_STATUSES:
            raise ValueError(f"Unknown listing status: {status!r}")
        listing = self.get_listing(listing_id)
        if listing is None:
            raise ValueError(f"Unknown listing: {listing_id}")
        if status not in _LISTING_TRANSITIONS[listing.status]:
            raise ValueError(f"Cannot move listing {listing_id} from {listing.status} to {status}")
        if status == "verified":
            employer = self.get_employer(listing.employer_id)
            if employer is None or employer.status != "verified":
                raise ValueError("A listing can only be verified when its employer is verified.")
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "UPDATE kv_listings SET status = ?, updated_at = ?,"
                    " reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                    (status, _now_iso(), reviewer, _now_iso(), note, listing_id),
                )
            self._invalidate_listing_indexes()
            updated = self.get_listing(listing_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    def delete_listing(self, listing_id: int) -> bool:
        """Hard delete (employer withdrawing their own listing, or an
        admin removing one). Reports against it are kept — they are
        audit history, not listing data."""
        conn = db_layer.connect(self.target)
        try:
            with conn:
                cursor = conn.execute("DELETE FROM kv_listings WHERE id = ?", (listing_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._invalidate_listing_indexes()
            return deleted
        finally:
            conn.close()

    def delete_sample_listings(self) -> int:
        """Remove all seeded sample listings (the seed script's
        ``--force`` path). Returns the number removed."""
        conn = db_layer.connect(self.target)
        try:
            with conn:
                cursor = conn.execute("DELETE FROM kv_listings WHERE is_sample = 1")
            removed = int(cursor.rowcount or 0)
            if removed:
                self._invalidate_listing_indexes()
            return removed
        finally:
            conn.close()

    def count_sample_listings(self) -> int:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM kv_listings WHERE is_sample = 1"
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    # ------------------------------------------------------------ reports

    def report_listing(
        self,
        listing_id: int,
        reason: str,
        details: str = "",
        reporter_user_id: str = "",
    ) -> tuple[ListingReport, bool]:
        """File a worker report. Returns ``(report, auto_flagged)`` —
        ``auto_flagged`` is True when this report pushed the listing to
        ``REPORT_AUTO_FLAG`` open reports and the listing was
        auto-flagged (verified → flagged only; other states stay)."""
        if reason not in REPORT_REASONS:
            raise ValueError(f"Unknown report reason: {reason!r}")
        if self.get_listing(listing_id) is None:
            raise ValueError(f"Unknown listing: {listing_id}")
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                report_id = _insert_id(
                    conn,
                    "INSERT INTO kv_listing_reports (listing_id, reporter_user_id,"
                    " reason, details, status, created_at) VALUES (?,?,?,?,?,?)",
                    (listing_id, reporter_user_id, reason, details.strip(), "open", now),
                )
            report = self.get_report(report_id)
            assert report is not None
        finally:
            conn.close()
        auto_flagged = False
        if self.count_open_reports(listing_id) >= REPORT_AUTO_FLAG:
            listing = self.get_listing(listing_id)
            if listing is not None and listing.status == "verified":
                self.set_listing_status(
                    listing_id,
                    "flagged",
                    reviewer="system",
                    note=f"Auto-flagged: {REPORT_AUTO_FLAG} open worker reports.",
                )
                auto_flagged = True
                logger.info(
                    "listing %s auto-flagged after %s open reports",
                    listing_id,
                    REPORT_AUTO_FLAG,
                )
        return report, auto_flagged

    def get_report(self, report_id: int) -> ListingReport | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_listing_reports WHERE id = ?", (report_id,)
            ).fetchone()
            return _report_from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_reports(
        self, status: str | None = None, listing_id: int | None = None, limit: int = 200
    ) -> list[ListingReport]:
        clauses, params = [], []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if listing_id is not None:
            clauses.append("listing_id = ?")
            params.append(listing_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_listing_reports{where}"  # noqa: S608
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_report_from_row(row) for row in rows]
        finally:
            conn.close()

    def count_open_reports(self, listing_id: int) -> int:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM kv_listing_reports"
                " WHERE listing_id = ? AND status = 'open'",
                (listing_id,),
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    def set_report_status(
        self, report_id: int, status: str, reviewer: str = "", note: str = ""
    ) -> ListingReport:
        """Admin review of a report: ``upheld`` or ``dismissed``.
        Only open reports can be reviewed."""
        if status not in ("upheld", "dismissed"):
            raise ValueError(f"Unknown report outcome: {status!r}")
        report = self.get_report(report_id)
        if report is None:
            raise ValueError(f"Unknown report: {report_id}")
        if report.status != "open":
            raise ValueError(f"Report {report_id} is already {report.status}.")
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "UPDATE kv_listing_reports SET status = ?, reviewed_by = ?,"
                    " reviewed_at = ?, review_note = ? WHERE id = ?",
                    (status, reviewer, _now_iso(), note, report_id),
                )
            updated = self.get_report(report_id)
            assert updated is not None
            return updated
        finally:
            conn.close()

    # ------------------------------------------------------------- counts

    def pilot_metrics(self) -> dict:
        """Global pilot-console metrics over the employer-side tables
        (Step 9.2). Full by-status breakdowns — the review queue
        counts are a subset of these. Every number comes from stored
        rows; nothing is estimated."""
        conn = db_layer.connect(self.target)
        try:

            def _by_status(table: str, known: tuple[str, ...]) -> dict[str, int]:
                counts = {name: 0 for name in known}
                rows = conn.execute(
                    f"SELECT status, COUNT(*) AS n FROM {table} GROUP BY status"  # noqa: S608 - table is internal
                ).fetchall()
                for row in rows:
                    counts[row["status"]] = int(row["n"])
                counts["total"] = sum(counts.values())
                return counts

            employers = _by_status("kv_employers", EMPLOYER_STATUSES)
            listings = _by_status("kv_listings", LISTING_STATUSES)
            reports = _by_status("kv_listing_reports", REPORT_STATUSES)
        finally:
            conn.close()
        return {
            "employers": employers,
            "listings": listings,
            "scam_reports": reports,
            "review_queue": self.review_queue_counts(),
        }

    def review_queue_counts(self) -> dict[str, int]:
        """Pending + flagged counts for the admin queue badge."""
        conn = db_layer.connect(self.target)
        try:

            def _count(table: str, statuses: tuple[str, ...]) -> int:
                placeholders = ",".join("?" for _ in statuses)
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608 - table is internal
                    f" WHERE status IN ({placeholders})",
                    statuses,
                ).fetchone()
                return int(row["n"])

            return {
                "employers_pending": _count("kv_employers", ("pending",)),
                "employers_flagged": _count("kv_employers", ("flagged",)),
                "listings_pending": _count("kv_listings", ("pending",)),
                "listings_flagged": _count("kv_listings", ("flagged",)),
                "reports_open": _count("kv_listing_reports", ("open",)),
            }
        finally:
            conn.close()
