"""Kaam-Vaani consent + employer matching store (Stage 6).

Tables live in the relational DB (migration v14: ``kv_worker_profiles``,
``kv_consents``, ``kv_consent_audit``, ``kv_shortlists``,
``kv_contact_requests``, ``kv_hire_outcomes``) and go through
``career_guidance.db.connect()`` like the employer store — no direct
``sqlite3`` — so the Postgres path works from day one. SQL uses ``?``
placeholders; inserts use ``RETURNING id`` on Postgres and ``lastrowid``
on SQLite (the ``storage.py`` pattern).

Consent model (F4 / execution prompt 6.2)
------------------------------------------
A worker shares their work profile with ONE employer at a time, for a
limited time, and can stop sharing at any time:

* **Per-employer**: a consent names one worker and one employer (plus
  the listing it was granted from, as context only — the grant is to
  the employer, not to the listing).
* **Explicit**: the grant stores the EXACT field list shared
  (``fields_shared``) and the plain-language explanation the worker
  saw is built from that same list (``consent_explanation``) — the
  explanation is a deterministic template, never LLM-paraphrased, so
  it cannot misstate which fields are shared.
* **Time-limited**: 7 / 30 / 90 days (default 30). Expiry is lazy:
  read paths flip overdue ``granted`` rows to ``expired`` and append
  an audit event (``expire_overdue_consents``).
* **Revocable**: the worker revokes at any time; revocation cuts
  access immediately (the candidate view re-checks consent on every
  call — there is no cached "allowed" state).
* **One active consent per (worker, employer)**: granting while one
  is active is a conflict — revoke first, then re-grant.

Audit log (execution prompt 6.2)
---------------------------------
``kv_consent_audit`` is **append-only by construction**: the only
audit write in this module is ``_append_audit`` (INSERT). There is
no update or delete code path for audit rows anywhere in this file,
and a test proves it (source grep + behaviour). Every grant, revoke,
expiry and profile access appends one event, so a worker can always
see who saw their profile and when.

Employer matching (F5 / execution prompt 6.3–6.4)
-------------------------------------------------
``rank_candidates_for_listing`` returns ONLY workers with an ACTIVE
consent to that employer, and ONLY the fields each worker consented
to share — enforced in the query layer (the consent filter runs
before any profile is loaded), not in the UI. The employer must be
verified and the listing verified; otherwise there is no matching
at all. Every returned candidate appends one ``accessed`` audit
event (the worker sees "Employer X viewed your profile").

The candidate score reuses the Stage 4 KV scorer's machinery
(``expand_competencies``, ``title_purity``, the income-fit shape)
rather than inventing a second scoring library:

* skill overlap 0.35 — IDF-free here: the listing's required skills
  (``extract_skills`` over title + role + requirements) against the
  worker's competencies; matched / required.
* title match 0.30 — the worker's skill phrases against the listing
  title (same stemmed phrase matcher as Stage 4).
* city 0.20 — same city 1.0, same district 0.5, else 0.0; 0.5 when
  either side has no city (unknown must not punish, but must not
  claim a local match either).
* income 0.15 — the worker's monthly need against the listing's pay
  ceiling: need <= max 1.0, need above max 0.4, missing data 1.0
  (the Stage 4 rule: no data never punishes a match).

Weights are a starting point measured on probe candidates (see the
Stage 6 tests); per-feature contributions are returned with every
candidate so the ranking is explainable. The scorer reads ONLY
skills, city, district and income from the worker and ONLY title,
role, requirements, city, district and pay from the listing — no
other worker attribute is an input, and a fairness test proves it.

Hire outcomes (execution prompt 6.5)
-------------------------------------
An employer or the worker reports the outcome of a match
(``hired`` / ``interviewed`` / ``not_hired``). Reporting requires a
consent RECORD (any status — granted, revoked or expired) between
the worker and the employer: outcomes can be reported after a
consent ends, but never about a stranger. Day-30 and day-90
follow-up statuses (``still_employed`` / ``left`` / ``unknown``)
feed the retention metric (``retention_summary``); a rate is
``null`` until at least one follow-up is reported — never 0% by
default, never invented.

Complexity (see ARCHITECTURE.md §7 for the full table)
------------------------------------------------------
* Consent check: O(1) — indexed lookup on (worker, employer).
* Lazy expiry: O(k) where k = overdue granted consents (usually 0).
* Candidate ranking: O(C × (R + S + T)) where C = consented
  candidates for the employer (bounded by the consent filter +
  limit), R = required skills, S = worker skills, T = title words.
  Profiles load in ONE query (``IN (...)``), not one per candidate.
* Audit append: O(1) per event; storage O(events); reads paginated.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from career_guidance import db as db_layer
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.kaamvaani.matching import (
    TITLE_FILLER,
    expand_competencies,
    phrase_variant_sets,
    title_purity,
    word_variants,
)
from career_guidance.kaamvaani.rag import tokenize
from career_guidance.synonyms import load_normalizer
from career_guidance.taxonomy import extract_skills

logger = logging.getLogger("career_guidance.kaamvaani.consent")

# --- Consent vocabulary ----------------------------------------------------- #

#: Fields a worker may share with an employer. The list is fixed and
#: validated server-side — the client can only pick a subset.
CONSENT_FIELDS: tuple[str, ...] = (
    "skills",
    "education",
    "city",
    "income",
    "goal",
    "interests",
    "contact",
)

#: Plain-language explanation of each shareable field (Class 6–8
#: English — the consent screen and the spoken explanation use these
#: exact words, so the worker hears what they are sharing).
FIELD_EXPLANATIONS: dict[str, str] = {
    "skills": "the work you can do (your skills)",
    "education": "your education (for example, 12th pass)",
    "city": "where you live (your city and district)",
    "income": "how much you need to earn each month",
    "goal": "what kind of work you want",
    "interests": "what you are interested in",
    "contact": "how to reach you (your email and verified phone number, if you have one)",
}

CONSENT_DURATIONS_DAYS: tuple[int, ...] = (7, 30, 90)
DEFAULT_CONSENT_DAYS = 30
CONSENT_STATUSES: tuple[str, ...] = ("granted", "revoked", "expired")
AUDIT_ACTIONS: tuple[str, ...] = ("granted", "revoked", "expired", "accessed")

#: Hire outcomes a match can end in.
OUTCOMES: tuple[str, ...] = ("hired", "interviewed", "not_hired")
#: Day-30 / day-90 retention statuses (empty string = not reported yet).
RETENTION_STATUSES: tuple[str, ...] = ("still_employed", "left", "unknown")

# --- Candidate scoring weights (starting point, measured on probes) -------- #
CANDIDATE_WEIGHT_SKILL = 0.35
CANDIDATE_WEIGHT_TITLE = 0.30
CANDIDATE_WEIGHT_CITY = 0.20
CANDIDATE_WEIGHT_INCOME = 0.15

# --- Errors ----------------------------------------------------------------- #


class ConsentError(ValueError):
    """Base class for consent-store errors (a ValueError, so callers
    can catch either). The router maps the subclasses to HTTP codes."""


class ConsentNotFound(ConsentError):
    """The named consent / profile / outcome does not exist (→ 404)."""


class ConsentConflict(ConsentError):
    """The request conflicts with current state — duplicate active
    consent, already revoked/expired, no worker profile yet (→ 409)."""


class ConsentValidationError(ConsentError):
    """The request body is invalid — unknown field, bad duration,
    bad outcome value (→ 400)."""


# --- Helpers ---------------------------------------------------------------- #


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


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def clean_worker_skills(value: list[str] | str | None) -> list[str]:
    """Normalise worker skills to a de-duplicated list of canonical
    names (lowercase, max 30). Each skill goes through
    ``extract_skills`` — the SAME canonicalisation the listing side
    uses — so a voice-confirmed skill ("electrical technician") and
    a listing requirement ("electrical") meet on one name. A skill
    the taxonomy does not know is kept verbatim, so a local trade
    term is never silently lost."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip().lower() for part in value.split(",")]
    else:
        items = [str(item).strip().lower() for item in value]
    out: list[str] = []
    for item in items:
        if not item or len(item) > 60:
            continue
        found = extract_skills(item)
        if found:
            out.extend(found)
        else:
            out.append(item)
    seen: dict[str, None] = {}
    for skill in out:
        seen.setdefault(skill, None)
    return list(seen)[:30]


def consent_explanation(employer_name: str, fields: list[str], duration_days: int) -> str:
    """The plain-language consent text the worker sees (and hears)
    before granting. Deterministic template — it must state EXACTLY
    which fields are shared, so it is never LLM-paraphrased: a
    generative paraphrase could misstate the field list."""
    shared = [FIELD_EXPLANATIONS[f] for f in fields if f in FIELD_EXPLANATIONS]
    not_shared = [FIELD_EXPLANATIONS[f] for f in CONSENT_FIELDS if f not in fields]
    lines = [
        f"You are sharing your work profile with {employer_name} for {duration_days} days.",
        "They will see: " + "; ".join(shared) + ".",
    ]
    if not_shared:
        lines.append("They will NOT see: " + "; ".join(not_shared) + ".")
    lines.append(
        "You can stop sharing at any time — open My sharing and tap Revoke. "
        "After that, they cannot see your profile."
    )
    return " ".join(lines)


# --- Dataclasses ------------------------------------------------------------ #


@dataclass
class WorkerProfile:
    """The server-side shareable copy of a worker's profile: what the
    voice flow confirmed (or what the worker typed in the form),
    stored so consent has something to share. The voice session
    itself is never stored server-side (A24) — only this explicit
    save. ``is_sample`` marks seeded demo data."""

    user_id: str
    skills: list[str] = field(default_factory=list)
    education: str = ""
    city: str = ""
    district: str = ""
    income_monthly: int | None = None
    income_text: str = ""
    goal_type: str = "explore"
    interests: str = ""
    language: str = "en"
    is_sample: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Consent:
    """One per-employer consent grant."""

    id: int
    worker_user_id: str
    employer_id: int
    listing_id: int | None
    fields: list[str] = field(default_factory=list)
    status: str = "granted"
    duration_days: int = DEFAULT_CONSENT_DAYS
    granted_at: str = ""
    expires_at: str = ""
    revoked_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_expired(self) -> bool:
        expires = _parse_iso(self.expires_at)
        if expires is None:
            return False
        return datetime.now(timezone.utc) >= expires

    @property
    def is_active(self) -> bool:
        """Granted AND unexpired — the only state that allows access."""
        return self.status == "granted" and not self.is_expired

    def to_dict(self) -> dict:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data["active"] = self.is_active
        return data


@dataclass
class ConsentAuditEvent:
    """One append-only audit event. There is no code path that
    updates or deletes these rows."""

    id: int
    consent_id: int
    worker_user_id: str
    employer_id: int
    action: str
    actor: str = ""
    detail: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class ShortlistEntry:
    """An employer shortlisting a worker for a listing. Requires an
    active consent at add time; the entry survives a later revoke,
    but the profile then shows as consent-revoked (no fields)."""

    id: int
    employer_id: int
    listing_id: int
    worker_user_id: str
    created_at: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class ContactRequest:
    """An employer asking to contact a worker about a listing. The
    worker sees it in My sharing; contact itself happens out of band
    via the consented contact details. This record is the audit
    trail. No worker response flow in Stage 6 (Stage 8 console)."""

    id: int
    employer_id: int
    listing_id: int
    worker_user_id: str
    message: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class HireOutcome:
    """A reported hire outcome, plus day-30 / day-90 follow-up
    statuses that feed the retention metric. Latest report wins
    for display (list methods order newest first)."""

    id: int
    employer_id: int
    listing_id: int
    worker_user_id: str
    outcome: str
    reported_by_user_id: str = ""
    reporter_role: str = ""
    note: str = ""
    day30_status: str = ""
    day30_reported_at: str = ""
    day90_status: str = ""
    day90_reported_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class CandidateMatch:
    """One ranked candidate for an employer: the filtered profile
    (only consented fields), the score with per-feature
    contributions (explainable), and the skill gap."""

    worker_user_id: str
    profile: dict
    score: float
    components: dict[str, float] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    reasons: list[dict] = field(default_factory=list)
    consent_id: int = 0
    consent_expires_at: str = ""
    shortlisted: bool = False
    is_sample: bool = False

    @property
    def match_percent(self) -> float:
        return round(self.score * 100, 1)

    def to_dict(self) -> dict:
        return {
            "worker_user_id": self.worker_user_id,
            "profile": self.profile,
            "score": round(self.score, 4),
            "match_percent": self.match_percent,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "reasons": self.reasons,
            "consent_id": self.consent_id,
            "consent_expires_at": self.consent_expires_at,
            "shortlisted": self.shortlisted,
            "is_sample": self.is_sample,
        }


# --- Row parsers ------------------------------------------------------------ #


def _profile_from_row(row) -> WorkerProfile:
    try:
        skills = json.loads(row["skills_json"] or "[]")
    except (ValueError, TypeError):
        skills = []
    return WorkerProfile(
        user_id=row["user_id"],
        skills=[str(s) for s in skills] if isinstance(skills, list) else [],
        education=row["education"] or "",
        city=row["city"] or "",
        district=row["district"] or "",
        income_monthly=row["income_monthly"],
        income_text=row["income_text"] or "",
        goal_type=row["goal_type"] or "explore",
        interests=row["interests"] or "",
        language=row["language"] or "en",
        is_sample=bool(row["is_sample"]),
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _consent_from_row(row) -> Consent:
    try:
        fields = json.loads(row["fields_json"] or "[]")
    except (ValueError, TypeError):
        fields = []
    return Consent(
        id=int(row["id"]),
        worker_user_id=row["worker_user_id"],
        employer_id=int(row["employer_id"]),
        listing_id=row["listing_id"],
        fields=[str(f) for f in fields] if isinstance(fields, list) else [],
        status=row["status"] or "granted",
        duration_days=int(row["duration_days"] or DEFAULT_CONSENT_DAYS),
        granted_at=row["granted_at"] or "",
        expires_at=row["expires_at"] or "",
        revoked_at=row["revoked_at"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _audit_from_row(row) -> ConsentAuditEvent:
    try:
        detail = json.loads(row["detail"] or "{}")
    except (ValueError, TypeError):
        detail = {}
    return ConsentAuditEvent(
        id=int(row["id"]),
        consent_id=int(row["consent_id"]),
        worker_user_id=row["worker_user_id"],
        employer_id=int(row["employer_id"]),
        action=row["action"] or "",
        actor=row["actor"] or "",
        detail=detail if isinstance(detail, dict) else {},
        created_at=row["created_at"] or "",
    )


def _shortlist_from_row(row) -> ShortlistEntry:
    return ShortlistEntry(
        id=int(row["id"]),
        employer_id=int(row["employer_id"]),
        listing_id=int(row["listing_id"]),
        worker_user_id=row["worker_user_id"],
        created_at=row["created_at"] or "",
    )


def _contact_request_from_row(row) -> ContactRequest:
    return ContactRequest(
        id=int(row["id"]),
        employer_id=int(row["employer_id"]),
        listing_id=int(row["listing_id"]),
        worker_user_id=row["worker_user_id"],
        message=row["message"] or "",
        created_at=row["created_at"] or "",
    )


def _outcome_from_row(row) -> HireOutcome:
    return HireOutcome(
        id=int(row["id"]),
        employer_id=int(row["employer_id"]),
        listing_id=int(row["listing_id"]),
        worker_user_id=row["worker_user_id"],
        outcome=row["outcome"] or "",
        reported_by_user_id=row["reported_by_user_id"] or "",
        reporter_role=row["reporter_role"] or "",
        note=row["note"] or "",
        day30_status=row["day30_status"] or "",
        day30_reported_at=row["day30_reported_at"] or "",
        day90_status=row["day90_status"] or "",
        day90_reported_at=row["day90_reported_at"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# --- Field filtering -------------------------------------------------------- #


def filter_profile(profile: WorkerProfile, fields: list[str], contact: dict | None = None) -> dict:
    """The employer-visible shape of a worker profile: ONLY the
    consented fields, nothing else. ``worker_user_id`` and
    ``is_sample`` are always present (the join key and the sample
    label are not personal data). Unknown field names are ignored —
    the filter is allow-list, never block-list."""
    wanted = set(fields)
    out: dict = {
        "worker_user_id": profile.user_id,
        "is_sample": profile.is_sample,
        "fields_shared": [f for f in CONSENT_FIELDS if f in wanted],
    }
    if "skills" in wanted:
        out["skills"] = list(profile.skills)
    if "education" in wanted:
        out["education"] = profile.education
    if "city" in wanted:
        out["city"] = profile.city
        out["district"] = profile.district
    if "income" in wanted:
        out["income_monthly"] = profile.income_monthly
        out["income_text"] = profile.income_text
    if "goal" in wanted:
        out["goal_type"] = profile.goal_type
    if "interests" in wanted:
        out["interests"] = profile.interests
    if "contact" in wanted:
        out["contact"] = dict(contact) if contact else {}
    return out


# --- Candidate scoring ------------------------------------------------------ #


def required_skills_for_listing(listing) -> list[str]:
    """The skills a listing asks for: canonical skills extracted
    from its title + role category + requirements text."""
    text = " ".join([listing.title or "", listing.role_category or "", listing.requirements or ""])
    return extract_skills(text)


def score_candidate(worker: WorkerProfile, listing) -> CandidateMatch:
    """Score one worker for one listing. The score reuses the Stage 4
    KV scorer's machinery (competency expansion, stemmed title
    phrases, the income-fit shape) and reads ONLY the worker's
    skills, city, district and income, and ONLY the listing's title,
    role, requirements, city, district and pay. Per-feature
    contributions are returned so the ranking is explainable."""
    required = required_skills_for_listing(listing)
    required_comp = expand_competencies(required)
    worker_comp = expand_competencies(worker.skills)
    matched = sorted(required_comp & worker_comp)
    missing = sorted(required_comp - worker_comp)
    skill = len(matched) / len(required_comp) if required_comp else 0.0

    phrases: list[list[set[str]]] = []
    normalizer = load_normalizer()
    for skill_name in worker.skills:
        phrases.append(phrase_variant_sets(skill_name))
        for word in tokenize(skill_name):
            if word not in TITLE_FILLER and not any(c.isdigit() for c in word):
                phrases.append([word_variants(word)])
        # Aliases as full phrases only — their single words lie
        # ("garment construction" is a fashion-design alias, not a
        # construction trade). Same rule as Stage 4's phrases_for.
        for alias in normalizer.aliases_for(skill_name):
            phrases.append(phrase_variant_sets(alias))
    title = title_purity(listing.title or "", [p for p in phrases if p])

    if worker.city and listing.city:
        if worker.city.strip().lower() == listing.city.strip().lower():
            city = 1.0
        elif (
            worker.district
            and listing.district
            and worker.district.strip().lower() == listing.district.strip().lower()
        ):
            city = 0.5
        else:
            city = 0.0
    else:
        city = 0.5

    if worker.income_monthly is None or listing.pay_monthly_max is None:
        income = 1.0
    elif worker.income_monthly <= listing.pay_monthly_max:
        income = 1.0
    else:
        income = 0.4

    score = (
        CANDIDATE_WEIGHT_SKILL * skill
        + CANDIDATE_WEIGHT_TITLE * title
        + CANDIDATE_WEIGHT_CITY * city
        + CANDIDATE_WEIGHT_INCOME * income
    )
    components = {"skill": skill, "title": title, "city": city, "income": income}
    reasons: list[dict] = []
    if matched:
        reasons.append({"kind": "skill", "skills": matched})
    if title > 0:
        reasons.append({"kind": "title"})
    if city >= 1.0:
        reasons.append({"kind": "city", "city": listing.city})
    elif city >= 0.5 and worker.city and listing.city:
        reasons.append({"kind": "district", "district": listing.district})
    if income >= 1.0 and worker.income_monthly is not None and listing.pay_monthly_max is not None:
        reasons.append({"kind": "income"})
    if not required_comp:
        reasons.append({"kind": "no_requirements"})
    return CandidateMatch(
        worker_user_id=worker.user_id,
        profile={},
        score=score,
        components=components,
        matched_skills=matched,
        missing_skills=missing,
        reasons=reasons,
        is_sample=worker.is_sample,
    )


# --- Store ------------------------------------------------------------------ #


class ConsentStore:
    """Worker profiles, consents, the append-only audit log,
    shortlists, contact requests and hire outcomes (migration v14).
    ``target`` is the same path-or-URL the storage layer takes
    (``settings.database_target``)."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.employers = EmployerStore(target)

    # ---------------------------------------------------------- worker profile

    def save_worker_profile(
        self,
        user_id: str,
        *,
        skills: list[str] | str | None = None,
        education: str = "",
        city: str = "",
        district: str = "",
        income_monthly: int | None = None,
        income_text: str = "",
        goal_type: str = "explore",
        interests: str = "",
        language: str = "en",
        is_sample: bool = False,
    ) -> WorkerProfile:
        """Create or replace the worker's shareable profile. Skills
        are cleaned to canonical names; income must be non-negative.
        One row per worker — a second save replaces the first."""
        if income_monthly is not None and (income_monthly < 0 or income_monthly > 10_000_000):
            raise ConsentValidationError("Monthly income need must be between 0 and 1,00,00,000.")
        language = language if language in ("en", "hi", "ta") else "en"
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO kv_worker_profiles (user_id, skills_json, education, city,"
                    " district, income_monthly, income_text, goal_type, interests, language,"
                    " is_sample, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(user_id) DO UPDATE SET skills_json=excluded.skills_json,"
                    " education=excluded.education, city=excluded.city,"
                    " district=excluded.district, income_monthly=excluded.income_monthly,"
                    " income_text=excluded.income_text, goal_type=excluded.goal_type,"
                    " interests=excluded.interests, language=excluded.language,"
                    " is_sample=excluded.is_sample, updated_at=excluded.updated_at",
                    (
                        user_id,
                        json.dumps(clean_worker_skills(skills)),
                        education.strip()[:120],
                        city.strip()[:80],
                        district.strip()[:80],
                        income_monthly,
                        income_text.strip()[:200],
                        goal_type.strip()[:40] or "explore",
                        interests.strip()[:1000],
                        language,
                        1 if is_sample else 0,
                        now,
                        now,
                    ),
                )
        finally:
            conn.close()
        profile = self.get_worker_profile(user_id)
        assert profile is not None
        return profile

    def get_worker_profile(self, user_id: str) -> WorkerProfile | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_worker_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            return _profile_from_row(row) if row is not None else None
        finally:
            conn.close()

    def get_worker_profiles(self, user_ids: list[str]) -> dict[str, WorkerProfile]:
        """Load several worker profiles in ONE query (the matcher
        path) — never one query per candidate."""
        if not user_ids:
            return {}
        placeholders = ",".join("?" for _ in user_ids)
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_worker_profiles WHERE user_id IN ({placeholders})",
                tuple(user_ids),
            ).fetchall()
            return {row["user_id"]: _profile_from_row(row) for row in rows}
        finally:
            conn.close()

    def list_worker_profiles(self, limit: int = 100, offset: int = 0) -> list[WorkerProfile]:
        """All worker profiles, newest first — the pilot console roster
        (Step 9.2). ``limit`` is capped at 500; the roster export uses
        the same method in pages."""
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT * FROM kv_worker_profiles"
                " ORDER BY created_at DESC, user_id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [_profile_from_row(row) for row in rows]
        finally:
            conn.close()

    def count_worker_profiles(self) -> dict[str, int]:
        """Profile counts for the pilot metrics: total + sample."""
        conn = db_layer.connect(self.target)
        try:
            total = conn.execute("SELECT COUNT(*) AS n FROM kv_worker_profiles").fetchone()["n"]
            sample = conn.execute(
                "SELECT COUNT(*) AS n FROM kv_worker_profiles WHERE is_sample = 1"
            ).fetchone()["n"]
            return {"total": int(total), "sample": int(sample)}
        finally:
            conn.close()

    def delete_worker_profile(self, user_id: str) -> bool:
        """Delete a worker's profile (account deletion / erasure).
        Consents naming the worker are left in place — the audit
        trail must survive — but without a profile there is nothing
        left to share, so matching returns nothing for them."""
        conn = db_layer.connect(self.target)
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM kv_worker_profiles WHERE user_id = ?", (user_id,)
                )
                return (cursor.rowcount or 0) > 0
        finally:
            conn.close()

    def delete_worker_data(self, user_id: str) -> dict[str, int]:
        """Erase a worker's Kaam-Vaani data (Step 9.4, DPDP erasure).

        Deletes: the worker profile, every consent naming the
        worker (all statuses — a dead grant is still the worker's
        data), shortlists and contact requests naming the worker.
        Anonymises: hire outcomes about the worker — the row stays
        (aggregate retention stats must stay valid) but the worker
        link becomes a one-way tombstone
        ``deleted-{sha256(user_id)[:12]}`` (unique per worker, so
        the (listing, worker) dedup still holds; unlinkable once
        the account row is gone), the reporter link is cleared
        when the worker reported it, and the worker's note is
        cleared. NEVER touched: ``kv_consent_audit`` — the
        append-only consent trail (Stage 6 invariant). Its rows
        hold only user-id tokens (random, unlinkable after the
        account row is gone) plus employer ids/emails as actor;
        retention is a policy matter (COMPLIANCE.md §4), not a
        delete path. Returns per-table counts."""
        tombstone = f"deleted-{hashlib.sha256(user_id.encode()).hexdigest()[:12]}"
        conn = db_layer.connect(self.target)
        try:
            with conn:
                counts: dict[str, int] = {}
                # Fixed literal statements; every value is a bound
                # parameter (the 12 f-string SQL sites elsewhere in
                # this module interpolate only fixed clause
                # fragments — see SECURITY.md — and this method
                # adds none).
                cursor = conn.execute(
                    "DELETE FROM kv_worker_profiles WHERE user_id = ?", (user_id,)
                )
                counts["kv_worker_profiles"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "DELETE FROM kv_consents WHERE worker_user_id = ?", (user_id,)
                )
                counts["kv_consents"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "DELETE FROM kv_shortlists WHERE worker_user_id = ?", (user_id,)
                )
                counts["kv_shortlists"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "DELETE FROM kv_contact_requests WHERE worker_user_id = ?",
                    (user_id,),
                )
                counts["kv_contact_requests"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "UPDATE kv_hire_outcomes SET worker_user_id = ?,"
                    " reported_by_user_id = CASE WHEN reported_by_user_id = ?"
                    " THEN '' ELSE reported_by_user_id END,"
                    " note = CASE WHEN reported_by_user_id = ? THEN '' ELSE note END"
                    " WHERE worker_user_id = ?",
                    (tombstone, user_id, user_id, user_id),
                )
                counts["kv_hire_outcomes_anonymised"] = cursor.rowcount or 0
                return counts
        finally:
            conn.close()

    def delete_employer_consents(
        self, employer_ids: list[int], employer_user_id: str
    ) -> dict[str, int]:
        """Clean up the consent side when an employer is deleted
        (Step 9.4): consents TO the employer (dead grants),
        shortlists and contact requests for the employer's
        listings. Hire outcomes about the employer's listings
        STAY (aggregate stats + the worker's hiring record), but
        the employer's reporter link and note are cleared where
        the employer reported them. The audit trail is never
        touched (append-only). Returns per-table counts."""
        if not employer_ids:
            return {
                "kv_consents": 0,
                "kv_shortlists": 0,
                "kv_contact_requests": 0,
                "kv_hire_outcomes_reporter_cleared": 0,
            }
        # Placeholders only — the ids are bound values, never
        # interpolated.
        placeholders = "(" + ",".join("?" for _ in employer_ids) + ")"
        conn = db_layer.connect(self.target)
        try:
            with conn:
                counts: dict[str, int] = {}
                cursor = conn.execute(
                    "DELETE FROM kv_consents WHERE employer_id IN " + placeholders,
                    tuple(employer_ids),
                )
                counts["kv_consents"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "DELETE FROM kv_shortlists WHERE employer_id IN " + placeholders,
                    tuple(employer_ids),
                )
                counts["kv_shortlists"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "DELETE FROM kv_contact_requests WHERE employer_id IN " + placeholders,
                    tuple(employer_ids),
                )
                counts["kv_contact_requests"] = cursor.rowcount or 0
                cursor = conn.execute(
                    "UPDATE kv_hire_outcomes SET reported_by_user_id = '',"
                    " note = '' WHERE employer_id IN "
                    + placeholders
                    + " AND reported_by_user_id = ?",
                    (*employer_ids, employer_user_id),
                )
                counts["kv_hire_outcomes_reporter_cleared"] = cursor.rowcount or 0
                return counts
        finally:
            conn.close()

    def contact_for(self, user_id: str) -> dict:
        """The worker's contact details as the employer may see them:
        e-mail always (it is the account identity); the phone number
        ONLY when Firebase-verified — an unverified number is
        unconfirmed and is never shared."""
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT email, phone_e164, phone_verified_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"email": "", "phone_e164": "", "phone_verified": False}
        verified = bool(row["phone_e164"] and row["phone_verified_at"])
        return {
            "email": row["email"] or "",
            "phone_e164": row["phone_e164"] if verified else "",
            "phone_verified": verified,
        }

    # --------------------------------------------------------------- consent

    def _append_audit(
        self,
        conn,
        consent_id: int,
        worker_user_id: str,
        employer_id: int,
        action: str,
        actor: str,
        detail: dict,
    ) -> None:
        """The ONLY audit write in this module: an INSERT. There is
        deliberately no update or delete for ``kv_consent_audit`` —
        the log is append-only (execution prompt 6.2)."""
        conn.execute(
            "INSERT INTO kv_consent_audit (consent_id, worker_user_id, employer_id,"
            " action, actor, detail, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                consent_id,
                worker_user_id,
                employer_id,
                action,
                actor or "",
                json.dumps(detail),
                _now_iso(),
            ),
        )

    def expire_overdue_consents(self) -> list[int]:
        """Flip overdue ``granted`` consents to ``expired`` and audit
        each flip (actor ``system``). Lazy expiry: read paths call
        this first, so no caller can ever see a stale granted consent.
        Returns the expired consent ids."""
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT * FROM kv_consents WHERE status = 'granted' AND expires_at <= ?",
                (now,),
            ).fetchall()
            if not rows:
                return []
            with conn:
                expired: list[int] = []
                for row in rows:
                    consent = _consent_from_row(row)
                    conn.execute(
                        "UPDATE kv_consents SET status='expired', updated_at=? WHERE id=?",
                        (now, consent.id),
                    )
                    self._append_audit(
                        conn,
                        consent.id,
                        consent.worker_user_id,
                        consent.employer_id,
                        "expired",
                        "system",
                        {"reason": "expiry", "expires_at": consent.expires_at},
                    )
                    expired.append(consent.id)
                return expired
        finally:
            conn.close()

    def grant_consent(
        self,
        worker_user_id: str,
        employer_id: int,
        fields: list[str] | None,
        duration_days: int = DEFAULT_CONSENT_DAYS,
        listing_id: int | None = None,
        actor: str = "",
    ) -> Consent:
        """Grant a consent: the worker shares ``fields`` of their
        profile with ``employer_id`` for ``duration_days``. Requires
        a saved worker profile (there must be something to share)
        and no already-active consent to the same employer. The
        employer/listing existence checks live in the router (404s);
        this method enforces the consent rules."""
        wanted = list(dict.fromkeys(fields if fields is not None else list(CONSENT_FIELDS)))
        if not wanted:
            raise ConsentValidationError("Choose at least one field to share.")
        unknown = [f for f in wanted if f not in CONSENT_FIELDS]
        if unknown:
            raise ConsentValidationError(f"Unknown shareable field(s): {', '.join(unknown)}.")
        if duration_days not in CONSENT_DURATIONS_DAYS:
            raise ConsentValidationError(
                f"Consent lasts {', '.join(str(d) for d in CONSENT_DURATIONS_DAYS)} days — "
                f"not {duration_days}."
            )
        if self.get_worker_profile(worker_user_id) is None:
            raise ConsentConflict("Save your work profile first — there is nothing to share yet.")
        self.expire_overdue_consents()
        if self.has_active_consent(worker_user_id, employer_id) is not None:
            raise ConsentConflict(
                "You are already sharing with this employer — revoke the current consent first."
            )
        now = datetime.now(timezone.utc)
        granted_at = now.isoformat(timespec="seconds")
        expires_at = (now + timedelta(days=duration_days)).isoformat(timespec="seconds")
        conn = db_layer.connect(self.target)
        try:
            with conn:
                consent_id = _insert_id(
                    conn,
                    "INSERT INTO kv_consents (worker_user_id, employer_id, listing_id,"
                    " fields_json, status, duration_days, granted_at, expires_at,"
                    " revoked_at, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        worker_user_id,
                        employer_id,
                        listing_id,
                        json.dumps(wanted),
                        "granted",
                        duration_days,
                        granted_at,
                        expires_at,
                        "",
                        granted_at,
                        granted_at,
                    ),
                )
                self._append_audit(
                    conn,
                    consent_id,
                    worker_user_id,
                    employer_id,
                    "granted",
                    actor,
                    {"fields": wanted, "duration_days": duration_days, "listing_id": listing_id},
                )
        finally:
            conn.close()
        consent = self.get_consent(consent_id)
        assert consent is not None
        return consent

    def revoke_consent(self, consent_id: int, worker_user_id: str, actor: str = "") -> Consent:
        """Revoke the worker's own consent. Revocation is immediate
        and final — a revoked consent cannot be un-revoked; the
        worker grants a fresh one instead."""
        self.expire_overdue_consents()
        consent = self.get_consent(consent_id)
        if consent is None:
            raise ConsentNotFound("Consent not found.")
        if consent.worker_user_id != worker_user_id:
            raise ConsentNotFound("Consent not found.")
        if consent.status == "revoked":
            raise ConsentConflict("This consent is already revoked.")
        if consent.status == "expired":
            raise ConsentConflict("This consent has already expired.")
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    "UPDATE kv_consents SET status='revoked', revoked_at=?,"
                    " updated_at=? WHERE id=?",
                    (now, now, consent_id),
                )
                self._append_audit(
                    conn,
                    consent_id,
                    consent.worker_user_id,
                    consent.employer_id,
                    "revoked",
                    actor,
                    {"revoked_at": now},
                )
        finally:
            conn.close()
        revoked = self.get_consent(consent_id)
        assert revoked is not None
        return revoked

    def get_consent(self, consent_id: int) -> Consent | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute("SELECT * FROM kv_consents WHERE id = ?", (consent_id,)).fetchone()
            return _consent_from_row(row) if row is not None else None
        finally:
            conn.close()

    def has_active_consent(self, worker_user_id: str, employer_id: int) -> Consent | None:
        """The worker's ACTIVE consent to this employer, if any —
        the access gate every employer read goes through. O(1) on
        the (worker, employer) index."""
        self.expire_overdue_consents()
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_consents WHERE worker_user_id = ? AND employer_id = ?"
                " AND status = 'granted' ORDER BY granted_at DESC, id DESC LIMIT 1",
                (worker_user_id, employer_id),
            ).fetchone()
            return _consent_from_row(row) if row is not None else None
        finally:
            conn.close()

    def has_consent_record(self, worker_user_id: str, employer_id: int) -> bool:
        """Any consent record at all (granted, revoked or expired) —
        the hire-outcome rule: outcomes may be reported after a
        consent ends, but never about a stranger."""
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT id FROM kv_consents WHERE worker_user_id = ? AND employer_id = ? LIMIT 1",
                (worker_user_id, employer_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def list_consents_for_worker(self, worker_user_id: str, limit: int = 100) -> list[Consent]:
        self.expire_overdue_consents()
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT * FROM kv_consents WHERE worker_user_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (worker_user_id, limit),
            ).fetchall()
            return [_consent_from_row(row) for row in rows]
        finally:
            conn.close()

    def list_consents_for_employer(self, employer_id: int, limit: int = 100) -> list[Consent]:
        self.expire_overdue_consents()
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT * FROM kv_consents WHERE employer_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (employer_id, limit),
            ).fetchall()
            return [_consent_from_row(row) for row in rows]
        finally:
            conn.close()

    def list_audit(
        self,
        *,
        worker_user_id: str | None = None,
        employer_id: int | None = None,
        consent_id: int | None = None,
        limit: int = 100,
    ) -> list[ConsentAuditEvent]:
        """Audit events, scoped to one worker, one employer, or one
        consent. Newest first, paginated by ``limit``."""
        clauses, params = [], []
        if worker_user_id is not None:
            clauses.append("worker_user_id = ?")
            params.append(worker_user_id)
        if employer_id is not None:
            clauses.append("employer_id = ?")
            params.append(employer_id)
        if consent_id is not None:
            clauses.append("consent_id = ?")
            params.append(consent_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_consent_audit{where}"  # noqa: S608
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_audit_from_row(row) for row in rows]
        finally:
            conn.close()

    # ------------------------------------------------------- employer matching

    def rank_candidates_for_listing(
        self,
        listing_id: int,
        *,
        limit: int = 20,
        city: str | None = None,
    ) -> dict:
        """Rank consented candidates for a verified listing. The
        employer must be verified and the listing verified — enforced
        here, not just in the UI. Only workers with an ACTIVE consent
        to this employer are considered, and each candidate carries
        ONLY their consented fields. Every returned candidate appends
        one ``accessed`` audit event. Raises ConsentNotFound for a
        missing listing and ConsentConflict for an unverified
        employer/listing."""
        listing = self.employers.get_listing(listing_id)
        if listing is None:
            raise ConsentNotFound("Listing not found.")
        employer = self.employers.get_employer(listing.employer_id)
        if employer is None:
            raise ConsentNotFound("Listing not found.")
        if employer.status != "verified":
            raise ConsentConflict("Employer matching needs a verified employer profile.")
        if listing.status != "verified":
            raise ConsentConflict("Employer matching needs a verified listing.")
        self.expire_overdue_consents()
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT * FROM kv_consents WHERE employer_id = ? AND status = 'granted'",
                (employer.id,),
            ).fetchall()
            consents = [_consent_from_row(row) for row in rows]
        finally:
            conn.close()
        active = {c.worker_user_id: c for c in consents if c.is_active}
        profiles = self.get_worker_profiles(list(active))
        shortlisted = {
            entry.worker_user_id
            for entry in self.list_shortlists(employer.id, listing_id=listing_id)
        }
        ranked: list[CandidateMatch] = []
        for worker_user_id, consent in active.items():
            profile = profiles.get(worker_user_id)
            if profile is None:
                continue
            if city and profile.city.strip().lower() != city.strip().lower():
                continue
            match = score_candidate(profile, listing)
            contact = self.contact_for(worker_user_id) if "contact" in consent.fields else None
            match.profile = filter_profile(profile, consent.fields, contact)
            match.consent_id = consent.id
            match.consent_expires_at = consent.expires_at
            match.shortlisted = worker_user_id in shortlisted
            ranked.append(match)
        ranked.sort(key=lambda m: (-m.score, m.worker_user_id))
        ranked = ranked[: max(1, min(limit, 100))]
        # One audit event per returned candidate — the worker sees
        # exactly who viewed their profile, and when.
        conn = db_layer.connect(self.target)
        try:
            with conn:
                for match in ranked:
                    consent = active[match.worker_user_id]
                    self._append_audit(
                        conn,
                        consent.id,
                        match.worker_user_id,
                        employer.id,
                        "accessed",
                        employer.email or f"employer:{employer.id}",
                        {
                            "listing_id": listing_id,
                            "fields_returned": match.profile.get("fields_shared", []),
                        },
                    )
        finally:
            conn.close()
        return {
            "listing": listing.to_dict(),
            "candidates": [m.to_dict() for m in ranked],
            "count": len(ranked),
            "sample_data": any(m.is_sample for m in ranked),
        }

    # --------------------------------------------------------------- shortlist

    def get_shortlist(
        self, employer_id: int, listing_id: int, worker_user_id: str
    ) -> ShortlistEntry | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_shortlists WHERE employer_id = ? AND listing_id = ?"
                " AND worker_user_id = ?",
                (employer_id, listing_id, worker_user_id),
            ).fetchone()
            return _shortlist_from_row(row) if row is not None else None
        finally:
            conn.close()

    def add_shortlist(
        self, employer_id: int, listing_id: int, worker_user_id: str
    ) -> ShortlistEntry:
        """Shortlist a worker for a listing. Requires an ACTIVE
        consent at shortlist time — an employer cannot bookmark a
        worker who never shared with them."""
        if self.has_active_consent(worker_user_id, employer_id) is None:
            raise ConsentConflict(
                "This worker has not shared their profile with you — shortlisting needs consent."
            )
        if self.get_shortlist(employer_id, listing_id, worker_user_id) is not None:
            raise ConsentConflict("This worker is already shortlisted for this job.")
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                entry_id = _insert_id(
                    conn,
                    "INSERT INTO kv_shortlists (employer_id, listing_id, worker_user_id,"
                    " created_at) VALUES (?,?,?,?)",
                    (employer_id, listing_id, worker_user_id, now),
                )
        finally:
            conn.close()
        entry = self.get_shortlist(employer_id, listing_id, worker_user_id)
        assert entry is not None and entry.id == entry_id
        return entry

    def remove_shortlist(self, employer_id: int, listing_id: int, worker_user_id: str) -> bool:
        conn = db_layer.connect(self.target)
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM kv_shortlists WHERE employer_id = ? AND listing_id = ?"
                    " AND worker_user_id = ?",
                    (employer_id, listing_id, worker_user_id),
                )
                return (cursor.rowcount or 0) > 0
        finally:
            conn.close()

    def list_shortlists(
        self, employer_id: int, listing_id: int | None = None
    ) -> list[ShortlistEntry]:
        conn = db_layer.connect(self.target)
        try:
            if listing_id is None:
                rows = conn.execute(
                    "SELECT * FROM kv_shortlists WHERE employer_id = ?"
                    " ORDER BY created_at DESC, id DESC",
                    (employer_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kv_shortlists WHERE employer_id = ? AND listing_id = ?"
                    " ORDER BY created_at DESC, id DESC",
                    (employer_id, listing_id),
                ).fetchall()
            return [_shortlist_from_row(row) for row in rows]
        finally:
            conn.close()

    def shortlist_view(self, employer_id: int, listing_id: int) -> list[dict]:
        """Shortlisted candidates with their CURRENT consent state:
        an active consent shows the filtered profile; a revoked or
        expired consent shows a placeholder with no fields (the entry
        survives, the data does not)."""
        entries = self.list_shortlists(employer_id, listing_id=listing_id)
        profiles = self.get_worker_profiles([e.worker_user_id for e in entries])
        out: list[dict] = []
        for entry in entries:
            consent = self.has_active_consent(entry.worker_user_id, employer_id)
            profile = profiles.get(entry.worker_user_id)
            if consent is not None and profile is not None:
                contact = (
                    self.contact_for(entry.worker_user_id) if "contact" in consent.fields else None
                )
                out.append(
                    {
                        "shortlist": entry.to_dict(),
                        "consent_status": "granted",
                        "consent_expires_at": consent.expires_at,
                        "profile": filter_profile(profile, consent.fields, contact),
                    }
                )
            else:
                past = [
                    c
                    for c in self.list_consents_for_worker(entry.worker_user_id)
                    if c.employer_id == employer_id
                ]
                status = past[0].status if past else "none"
                out.append(
                    {
                        "shortlist": entry.to_dict(),
                        "consent_status": status,
                        "consent_expires_at": past[0].expires_at if past else "",
                        "profile": None,
                    }
                )
        return out

    # --------------------------------------------------------- contact requests

    def create_contact_request(
        self,
        employer_id: int,
        listing_id: int,
        worker_user_id: str,
        message: str = "",
    ) -> ContactRequest:
        """Ask to contact a worker about a listing. Requires an
        ACTIVE consent — an employer cannot reach out to a worker who
        never shared with them."""
        if self.has_active_consent(worker_user_id, employer_id) is None:
            raise ConsentConflict(
                "This worker has not shared their profile with you — contact needs consent."
            )
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                request_id = _insert_id(
                    conn,
                    "INSERT INTO kv_contact_requests (employer_id, listing_id, worker_user_id,"
                    " message, created_at) VALUES (?,?,?,?,?)",
                    (employer_id, listing_id, worker_user_id, message.strip()[:1000], now),
                )
        finally:
            conn.close()
        created = self.get_contact_request(request_id)
        assert created is not None
        return created

    def get_contact_request(self, request_id: int) -> ContactRequest | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_contact_requests WHERE id = ?", (request_id,)
            ).fetchone()
            return _contact_request_from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_contact_requests(
        self,
        *,
        employer_id: int | None = None,
        worker_user_id: str | None = None,
        listing_id: int | None = None,
        limit: int = 100,
    ) -> list[ContactRequest]:
        clauses, params = [], []
        if employer_id is not None:
            clauses.append("employer_id = ?")
            params.append(employer_id)
        if worker_user_id is not None:
            clauses.append("worker_user_id = ?")
            params.append(worker_user_id)
        if listing_id is not None:
            clauses.append("listing_id = ?")
            params.append(listing_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_contact_requests{where}"  # noqa: S608
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_contact_request_from_row(row) for row in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------ hire outcomes

    def report_outcome(
        self,
        employer_id: int,
        listing_id: int,
        worker_user_id: str,
        outcome: str,
        reported_by_user_id: str,
        reporter_role: str,
        note: str = "",
    ) -> HireOutcome:
        """Report a hire outcome. Requires a consent RECORD (any
        status) between the worker and the employer — outcomes may be
        reported after a consent ends, but never about a stranger.
        The caller-identity check (the reporter is the employer or
        the worker themselves) lives in the router."""
        if outcome not in OUTCOMES:
            raise ConsentValidationError(
                f"Outcome must be one of {', '.join(OUTCOMES)} — not {outcome!r}."
            )
        if reporter_role not in ("employer", "worker"):
            raise ConsentValidationError("Reporter role must be 'employer' or 'worker'.")
        if not self.has_consent_record(worker_user_id, employer_id):
            raise ConsentConflict(
                "No consent record exists between this worker and employer — "
                "outcomes can only be reported for workers who shared their profile."
            )
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                outcome_id = _insert_id(
                    conn,
                    "INSERT INTO kv_hire_outcomes (employer_id, listing_id, worker_user_id,"
                    " outcome, reported_by_user_id, reporter_role, note, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        employer_id,
                        listing_id,
                        worker_user_id,
                        outcome,
                        reported_by_user_id,
                        reporter_role,
                        note.strip()[:1000],
                        now,
                        now,
                    ),
                )
        finally:
            conn.close()
        created = self.get_outcome(outcome_id)
        assert created is not None
        return created

    def get_outcome(self, outcome_id: int) -> HireOutcome | None:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT * FROM kv_hire_outcomes WHERE id = ?", (outcome_id,)
            ).fetchone()
            return _outcome_from_row(row) if row is not None else None
        finally:
            conn.close()

    def record_followup(self, outcome_id: int, day: int, status: str) -> HireOutcome:
        """Record a day-30 or day-90 retention follow-up on a HIRE.
        Follow-ups only make sense for hires — an interviewed or
        not-hired outcome has no job to retain."""
        if day not in (30, 90):
            raise ConsentValidationError("Follow-up day must be 30 or 90.")
        if status not in RETENTION_STATUSES:
            raise ConsentValidationError(
                f"Retention status must be one of {', '.join(RETENTION_STATUSES)}."
            )
        outcome = self.get_outcome(outcome_id)
        if outcome is None:
            raise ConsentNotFound("Hire outcome not found.")
        if outcome.outcome != "hired":
            raise ConsentConflict("Retention follow-ups apply to hires only.")
        column = f"day{day}_status"
        stamp = f"day{day}_reported_at"
        now = _now_iso()
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute(
                    f"UPDATE kv_hire_outcomes SET {column}=?, {stamp}=?, updated_at=? WHERE id=?",
                    (status, now, now, outcome_id),
                )
        finally:
            conn.close()
        updated = self.get_outcome(outcome_id)
        assert updated is not None
        return updated

    def list_outcomes(
        self,
        *,
        employer_id: int | None = None,
        worker_user_id: str | None = None,
        listing_id: int | None = None,
        limit: int = 100,
    ) -> list[HireOutcome]:
        """Outcomes, newest first (latest report wins for display)."""
        clauses, params = [], []
        if employer_id is not None:
            clauses.append("employer_id = ?")
            params.append(employer_id)
        if worker_user_id is not None:
            clauses.append("worker_user_id = ?")
            params.append(worker_user_id)
        if listing_id is not None:
            clauses.append("listing_id = ?")
            params.append(listing_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                f"SELECT * FROM kv_hire_outcomes{where}"  # noqa: S608
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [_outcome_from_row(row) for row in rows]
        finally:
            conn.close()

    def outcome_counts(self, employer_id: int | None = None, listing_id: int | None = None) -> dict:
        """Per-outcome counts for an employer (optionally one
        listing) — or, with ``employer_id=None`` (Step 9.2 pilot
        metrics), across all employers. Counts the latest report
        per (listing, worker) only — a re-report replaces the
        earlier one. Loads at most 1000 outcome rows; beyond that
        the counts silently cap (pilot scale is far below it)."""
        outcomes = self.list_outcomes(employer_id=employer_id, listing_id=listing_id, limit=1000)
        latest: dict[tuple[int, str], str] = {}
        for outcome in outcomes:
            key = (outcome.listing_id, outcome.worker_user_id)
            if key not in latest:
                latest[key] = outcome.outcome
        counts = {name: 0 for name in OUTCOMES}
        for outcome in latest.values():
            counts[outcome] = counts.get(outcome, 0) + 1
        counts["total"] = len(latest)
        return counts

    def retention_summary(
        self, employer_id: int | None = None, listing_id: int | None = None
    ) -> dict:
        """The 30/90-day retention metric: among HIRES with a
        follow-up reported, the share still employed. A rate is
        ``None`` until at least one follow-up is reported — never
        0% by default, never invented. Day-90 is the 3-month
        retention the master prompt measures (F5). With
        ``employer_id=None`` (Step 9.2 pilot metrics) the summary
        covers all employers. Same 1000-row load cap as
        ``outcome_counts``."""
        outcomes = self.list_outcomes(employer_id=employer_id, listing_id=listing_id, limit=1000)
        latest: dict[tuple[int, str], HireOutcome] = {}
        for outcome in outcomes:
            key = (outcome.listing_id, outcome.worker_user_id)
            if key not in latest:
                latest[key] = outcome
        hires = [o for o in latest.values() if o.outcome == "hired"]
        summary: dict = {"hired": len(hires)}
        for day in (30, 90):
            column = f"day{day}_status"
            reported = [o for o in hires if getattr(o, column)]
            still = [o for o in reported if getattr(o, column) == "still_employed"]
            rate = round(len(still) / len(reported), 4) if reported else None
            summary[f"day{day}"] = {
                "reported": len(reported),
                "still_employed": len(still),
                "left": len([o for o in reported if getattr(o, column) == "left"]),
                "unknown": len([o for o in reported if getattr(o, column) == "unknown"]),
                "rate": rate,
            }
        return summary

    def pilot_metrics(self) -> dict:
        """Global pilot-console metrics over the consent-side tables
        (Step 9.2). Every number comes from stored rows — nothing is
        estimated. Voice-flow match VIEWS are not persisted, so they
        are not in this metric set (L65); the stored match funnel is
        shortlists + contact requests. Outcome/retention reuse the
        latest-per-(listing, worker) dedup of ``outcome_counts`` /
        ``retention_summary`` with their 1000-row load cap."""
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

            consents = _by_status("kv_consents", CONSENT_STATUSES)
            shortlists = conn.execute("SELECT COUNT(*) AS n FROM kv_shortlists").fetchone()["n"]
            contacts = conn.execute("SELECT COUNT(*) AS n FROM kv_contact_requests").fetchone()["n"]
        finally:
            conn.close()
        return {
            "profiles": self.count_worker_profiles(),
            "consents": consents,
            "shortlists": {"total": int(shortlists)},
            "contact_requests": {"total": int(contacts)},
            "outcomes": self.outcome_counts(),
            "retention": self.retention_summary(),
        }

    # ------------------------------------------------------------ seed cleanup

    def count_sample_workers(self) -> int:
        """How many seeded sample worker profiles exist — the seed
        script's idempotency check."""
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM kv_worker_profiles WHERE is_sample = 1"
            ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    def delete_sample_data(self) -> dict:
        """Remove seeded sample worker profiles and every consent,
        shortlist, contact request and outcome naming a sample worker
        — the re-seed path (``--force``). Audit rows are NOT deleted:
        the audit log is append-only (execution prompt 6.2), so
        events from a previous seed run stay as history, scoped to
        the same sample worker ids. There is no other delete path
        for audit rows anywhere in this module."""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT user_id FROM kv_worker_profiles WHERE is_sample = 1"
            ).fetchall()
            sample_workers = [row["user_id"] for row in rows]
            if not sample_workers:
                return {"sample_workers": 0}
            placeholders = ",".join("?" for _ in sample_workers)
            removed: dict[str, int] = {}
            with conn:
                for table, column in (
                    ("kv_shortlists", "worker_user_id"),
                    ("kv_contact_requests", "worker_user_id"),
                    ("kv_hire_outcomes", "worker_user_id"),
                    ("kv_consents", "worker_user_id"),
                ):
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE {column} IN ({placeholders})",
                        tuple(sample_workers),
                    )
                    removed[table] = cursor.rowcount or 0
                cursor = conn.execute("DELETE FROM kv_worker_profiles WHERE is_sample = 1")
                removed["kv_worker_profiles"] = cursor.rowcount or 0
            removed["sample_workers"] = len(sample_workers)
            return removed
        finally:
            conn.close()


# --- Erasure (Step 9.4) ---------------------------------------------------- #


def delete_all_kv_data(target: str, user_id: str) -> dict[str, dict[str, int]]:
    """Erase ALL of one user's Kaam-Vaani data (worker side +
    employer side). The single erasure entry point, used by
    DELETE /api/v1/kv/me/data, account self-delete and the admin
    user delete. Returns the aggregated counts in the same
    ``deleted`` / ``anonymised`` shape the endpoint returns."""
    store = ConsentStore(target)
    worker_counts = store.delete_worker_data(user_id)
    employer_counts, employer_ids = EmployerStore(target).delete_employer_data(user_id)
    consent_counts = store.delete_employer_consents(employer_ids, user_id)
    return {
        "deleted": {
            "worker_profiles": worker_counts["kv_worker_profiles"],
            "consents": worker_counts["kv_consents"] + consent_counts["kv_consents"],
            "shortlists": worker_counts["kv_shortlists"] + consent_counts["kv_shortlists"],
            "contact_requests": worker_counts["kv_contact_requests"]
            + consent_counts["kv_contact_requests"],
            "employers": employer_counts["kv_employers"],
            "listings": employer_counts["kv_listings"],
        },
        "anonymised": {
            "hire_outcomes": worker_counts["kv_hire_outcomes_anonymised"],
            "hire_outcome_reporter_links": consent_counts["kv_hire_outcomes_reporter_cleared"],
        },
    }
