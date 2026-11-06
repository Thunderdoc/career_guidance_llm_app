"""Institute portal core (Phase 4).

Privacy rule (hard): cohort data is **aggregate by default**. The cohort
payload never contains e-mail addresses; individual-level detail lives
behind separate role-gated helpers/endpoints (institute_admin / counsellor
of the *same* institute only).

Membership: a user belongs to **at most one institute in v1** — enforced
in :meth:`InstituteStore.set_membership` and in the invite pipeline. The
global ``users.role`` system is untouched: ``admin`` stays platform admin,
institute roles live in ``users.institute_role``
(``institute_admin`` / ``counsellor`` / ``student``).

Seats: the Institute plan in ``career_guidance.billing.plans_payload``
carries no seat count today (its price itself is an env placeholder), so
new institutes get :data:`DEFAULT_SEAT_LIMIT` — a conservative default the
owner replaces via plan config, never an invented price/seat product.
Pending invites reserve a seat so an institute cannot over-invite and
then fail at activation time.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from career_guidance.migrations import migrate

#: Conservative default seat limit for a new institute. The Institute plan
#: definition (billing plans data) does not define seats yet — the owner
#: sets real limits via plan config; until then this constant applies.
DEFAULT_SEAT_LIMIT = 50

#: A student's latest top match below this percent counts as needing
#: attention (together with "no run in 30+ days").
NEEDS_ATTENTION_MATCH_PERCENT = 50.0
NEEDS_ATTENTION_DAYS = 30

#: Report-schedule preferences (Phase 9). A preference record only.
REPORT_SCHEDULES = ("none", "weekly", "monthly")

INSTITUTE_ROLES = ("institute_admin", "counsellor", "student")
INVITABLE_ROLES = ("student", "counsellor")
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 500
REVIEW_LABEL = "Reviewed by counsellor"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or "institute"


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value or "")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class InstituteStore:
    """SQLite store for institutes, membership, invites and run reviews."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------ institutes
    def create_institute(
        self,
        name: str,
        created_by: str,
        slug: str = "",
        logo_url: str = "",
        accent_color: str = "",
        seat_limit: int = DEFAULT_SEAT_LIMIT,
    ) -> dict:
        name = (name or "").strip()
        if len(name) < 2:
            raise ValueError("Institute name is required.")
        accent = (accent_color or "").strip()
        if accent and not _HEX_RE.match(accent):
            raise ValueError("Accent colour must be a hex value like #0f766e.")
        base = _slugify(slug or name)
        with self._connect() as conn:
            slug_final, n = base, 2
            while conn.execute("SELECT 1 FROM institutes WHERE slug=?", (slug_final,)).fetchone():
                slug_final, n = f"{base}-{n}", n + 1
            cur = conn.execute(
                "INSERT INTO institutes (name, slug, logo_url, accent_color, plan,"
                " seat_limit, created_by, created_at) VALUES (?,?,?,?,'institute',?,?,?)",
                (
                    name,
                    slug_final,
                    (logo_url or "").strip(),
                    accent,
                    seat_limit,
                    created_by,
                    _now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM institutes WHERE id=?", (int(cur.lastrowid or 0),)
            ).fetchone()
        return dict(row)

    def get_institute(self, institute_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM institutes WHERE id=?", (institute_id,)).fetchone()
        return dict(row) if row else None

    def set_report_schedule(self, institute_id: int, schedule: str) -> dict | None:
        """Set the report-schedule PREFERENCE (Phase 9 analytics v2).

        This records only what the institute asked for (none|weekly|
        monthly) plus when; ``report_schedule_payload`` derives the
        nominal next run. There is NO scheduler in the product yet —
        nothing is sent automatically (documented honestly in README).
        """
        if schedule not in REPORT_SCHEDULES:
            raise ValueError("Report schedule must be one of: none, weekly, monthly.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE institutes SET report_schedule=?, report_schedule_updated_at=? WHERE id=?",
                (schedule, _now(), institute_id),
            )
            row = conn.execute("SELECT * FROM institutes WHERE id=?", (institute_id,)).fetchone()
        return dict(row) if row else None

    def update_branding(
        self, institute_id: int, name: str = "", logo_url: str = "", accent_color: str = ""
    ) -> dict | None:
        accent = (accent_color or "").strip()
        if accent and not _HEX_RE.match(accent):
            raise ValueError("Accent colour must be a hex value like #0f766e.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE institutes SET name=COALESCE(NULLIF(?,''), name), logo_url=?,"
                " accent_color=? WHERE id=?",
                ((name or "").strip(), (logo_url or "").strip(), accent, institute_id),
            )
            row = conn.execute("SELECT * FROM institutes WHERE id=?", (institute_id,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------ membership
    def membership_of(self, user_id: str) -> dict | None:
        """{institute_id, institute_role} for a user, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT institute_id, institute_role FROM users WHERE id=?", (user_id,)
            ).fetchone()
        if not row or row["institute_id"] is None:
            return None
        return {"institute_id": int(row["institute_id"]), "institute_role": row["institute_role"]}

    def set_membership(self, user_id: str, institute_id: int, role: str) -> None:
        """Join an institute. Raises ValueError when already in another one."""
        if role not in INSTITUTE_ROLES:
            raise ValueError(f"Unknown institute role: {role}")
        current = self.membership_of(user_id)
        if current and current["institute_id"] != institute_id:
            raise ValueError("User already belongs to another institute.")
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET institute_id=?, institute_role=? WHERE id=?",
                (institute_id, role, user_id),
            )

    def clear_membership(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET institute_id=NULL, institute_role='' WHERE id=?", (user_id,)
            )

    def members(self, institute_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, email, name, institute_role, created_at FROM users"
                " WHERE institute_id=? ORDER BY institute_role, name",
                (institute_id,),
            ).fetchall()
        return [
            {
                "user_id": r["id"],
                "email": r["email"],
                "name": r["name"],
                "institute_role": r["institute_role"],
                "joined_at": r["created_at"],
            }
            for r in rows
        ]

    def member_count(self, institute_id: int) -> int:
        return len(self.members(institute_id))

    def user_by_email(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, email, name, institute_id, institute_role FROM users WHERE email=?",
                ((email or "").strip().lower(),),
            ).fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------------- invites
    def pending_invite_count(self, institute_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) n FROM institute_invites WHERE institute_id=? AND status='pending'",  # noqa: E501
                (institute_id,),
            ).fetchone()
        return int(row["n"])

    def seat_usage(self, institute_id: int) -> dict:
        institute = self.get_institute(institute_id) or {}
        used = self.member_count(institute_id)
        pending = self.pending_invite_count(institute_id)
        limit = int(institute.get("seat_limit") or DEFAULT_SEAT_LIMIT)
        return {
            "seat_limit": limit,
            "members": used,
            "pending_invites": pending,
            "seats_used": used + pending,
            "seats_available": max(0, limit - used - pending),
        }

    def _record_invite(
        self, conn, institute_id: int, email: str, name: str, role: str, actor: str, status: str
    ) -> None:
        conn.execute(
            "INSERT INTO institute_invites (institute_id, email, name, institute_role, status,"
            " created_by, created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(institute_id, email)"
            " DO UPDATE SET name=excluded.name, institute_role=excluded.institute_role,"
            " status=excluded.status",
            (institute_id, email, name, role, status, actor, _now()),
        )

    def process_invites(self, institute_id: int, rows: list[dict], actor: str = "") -> dict:
        """Validate + apply invite rows one by one; bad rows never abort.

        Each row: ``{email, name?, role?}``. Returns a per-row report:
        ``{row, email, status: invited|pending|error, error?}`` where row
        numbers are 1-based over the submitted list (CSV callers offset by
        their header). Existing users are activated immediately; unknown
        e-mails become pending invites that reserve a seat.
        """
        institute = self.get_institute(institute_id)
        if institute is None:
            raise ValueError("Institute not found.")
        results: list[dict] = []
        seen: set[str] = set()
        seats_available = self.seat_usage(institute_id)["seats_available"]
        with self._connect() as conn:
            for index, raw in enumerate(rows, start=1):
                email = str(raw.get("email") or "").strip().lower()
                name = str(raw.get("name") or "").strip()
                role = str(raw.get("role") or "student").strip().lower() or "student"
                entry: dict = {"row": int(raw.get("_line") or index), "email": email}
                error = None
                if not _EMAIL_RE.match(email):
                    error = "Invalid e-mail address."
                elif role not in INVITABLE_ROLES:
                    error = "Role must be student or counsellor."
                elif email in seen:
                    error = "Duplicate row in this import."
                elif conn.execute(
                    "SELECT 1 FROM users WHERE email=? AND institute_id=?", (email, institute_id)
                ).fetchone():
                    error = "Already a member of this institute."
                elif conn.execute(
                    "SELECT 1 FROM users WHERE email=? AND institute_id IS NOT NULL", (email,)
                ).fetchone():
                    error = "Already belongs to another institute."
                elif conn.execute(
                    "SELECT 1 FROM institute_invites WHERE institute_id=? AND email=?"
                    " AND status='pending'",
                    (institute_id, email),
                ).fetchone():
                    error = "Invite already pending for this e-mail."
                elif seats_available <= 0:
                    error = "Seat limit reached for this institute."
                seen.add(email)
                if error:
                    results.append({**entry, "status": "error", "error": error})
                    continue
                user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                if user:
                    conn.execute(
                        "UPDATE users SET institute_id=?, institute_role=? WHERE id=?",
                        (institute_id, role, user["id"]),
                    )
                    self._record_invite(conn, institute_id, email, name, role, actor, "accepted")
                    results.append({**entry, "status": "invited"})
                else:
                    self._record_invite(conn, institute_id, email, name, role, actor, "pending")
                    results.append({**entry, "status": "pending"})
                seats_available -= 1
        return {
            "results": results,
            "invited": sum(1 for r in results if r["status"] == "invited"),
            "pending": sum(1 for r in results if r["status"] == "pending"),
            "errors": sum(1 for r in results if r["status"] == "error"),
        }

    def list_invites(self, institute_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM institute_invites WHERE institute_id=? ORDER BY id",
                (institute_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def claim_invites(self, user_id: str, email: str) -> dict | None:
        """Activate a pending invite for a signed-in user (seat-checked)."""
        email = (email or "").strip().lower()
        with self._connect() as conn:
            invite = conn.execute(
                "SELECT * FROM institute_invites WHERE email=? AND status='pending'"
                " ORDER BY id LIMIT 1",
                (email,),
            ).fetchone()
        if invite is None:
            return None
        if self.membership_of(user_id):
            raise ValueError("You already belong to an institute.")
        usage = self.seat_usage(int(invite["institute_id"]))
        # The pending invite itself already reserves its seat.
        if usage["members"] >= usage["seat_limit"]:
            raise ValueError("Seat limit reached for this institute.")
        self.set_membership(user_id, int(invite["institute_id"]), invite["institute_role"])
        with self._connect() as conn:
            conn.execute(
                "UPDATE institute_invites SET status='accepted' WHERE id=?", (invite["id"],)
            )
        return dict(invite)

    # ---------------------------------------------------------- run reviews
    def add_review(
        self, run_id: int, reviewer_id: str, reviewer_role: str, note: str, approved: bool
    ) -> dict:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO run_reviews (run_id, reviewer_id, reviewer_role, note, approved,"
                " created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(run_id, reviewer_id) DO UPDATE"
                " SET note=excluded.note, approved=excluded.approved,"
                " reviewer_role=excluded.reviewer_role, created_at=excluded.created_at",
                (run_id, reviewer_id, reviewer_role, (note or "")[:2000], int(approved), _now()),
            )
            row = conn.execute(
                "SELECT * FROM run_reviews WHERE run_id=? AND reviewer_id=?",
                (run_id, reviewer_id),
            ).fetchone()
        return review_payload(dict(row))

    def review_for_run(self, run_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_reviews WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)
            ).fetchone()
        return review_payload(dict(row)) if row else None

    def reviewed_run_ids(self, run_ids: list[int]) -> set[int]:
        if not run_ids:
            return set()
        with self._connect() as conn:
            marks = ",".join("?" * len(run_ids))
            rows = conn.execute(
                f"SELECT DISTINCT run_id FROM run_reviews WHERE run_id IN ({marks})", run_ids
            ).fetchall()
        return {int(r["run_id"]) for r in rows}


def review_payload(row: dict) -> dict:
    """The student-facing review projection — human label, never 'AI'."""
    return {
        "reviewed": True,
        "label": REVIEW_LABEL,
        "note": row.get("note", ""),
        "approved": bool(row.get("approved")),
        "reviewer_role": row.get("reviewer_role", "counsellor"),
        "reviewed_at": row.get("created_at", ""),
    }


# --------------------------------------------------------------------------- #
# CSV invite parsing (pure — malformed input yields row errors, never raises) #
# --------------------------------------------------------------------------- #


def parse_invite_csv(data: bytes) -> tuple[list[dict], list[dict]]:
    """Parse invite CSV bytes into (rows, errors).

    Expected header: ``email`` (required), ``name`` and ``role`` optional.
    Row numbers in errors are real CSV line numbers (header = row 1).
    Raises ValueError only for whole-file problems (too large / too many
    rows / undecodable / missing email column) — the API maps that to 422.
    """
    if len(data) > MAX_CSV_BYTES:
        raise ValueError("CSV file exceeds the 5 MB limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV file must be UTF-8 text.") from error
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "email" not in [f.strip().lower() for f in reader.fieldnames]:
        raise ValueError("CSV must have an 'email' column.")
    fields = {f.strip().lower(): f for f in reader.fieldnames if f}
    raw_rows = list(reader)
    if len(raw_rows) > MAX_CSV_ROWS:
        raise ValueError(f"CSV has more than {MAX_CSV_ROWS} rows.")
    rows: list[dict] = []
    errors: list[dict] = []
    for offset, raw in enumerate(raw_rows):
        line = offset + 2  # header is line 1
        email = str(raw.get(fields["email"]) or "").strip()
        if not email and not any(str(v or "").strip() for v in raw.values()):
            continue  # blank line — not an error
        if not _EMAIL_RE.match(email.lower()):
            errors.append({"row": line, "email": email, "error": "Invalid e-mail address."})
            continue
        role = (
            str(raw.get(fields["role"]) or "student").strip().lower()
            if "role" in fields
            else "student"
        )
        if role not in INVITABLE_ROLES:
            errors.append(
                {"row": line, "email": email, "error": "Role must be student or counsellor."}
            )
            continue
        rows.append(
            {
                "email": email,
                "name": str(raw.get(fields["name"]) or "").strip() if "name" in fields else "",
                "role": role,
                "_line": line,
            }
        )
    return rows, errors


# --------------------------------------------------------------------------- #
# Cohort aggregation (pure over stored runs)                                   #
# --------------------------------------------------------------------------- #

_READINESS_BUCKETS = ("0-49", "50-69", "70-84", "85-100")


def _bucket(percent: float) -> str:
    if percent < 50:
        return "0-49"
    if percent < 70:
        return "50-69"
    if percent < 85:
        return "70-84"
    return "85-100"


def _top_match_percent(run) -> float | None:
    if not run.recommendations:
        return None
    score = float(run.recommendations[0].match_score or 0)
    # Stored scores are 0..1 in the v2 matcher; tolerate 0..100 rows.
    return round(score * 100, 1) if score <= 1 else round(score, 1)


def compute_cohort(members: list[dict], runs: list, now: datetime | None = None) -> dict:
    """Aggregate cohort payload from student members + their stored runs.

    Rules (documented for the report/API docs):
    - top careers / readiness use each run's **first** recommendation;
    - missing skills aggregate over **all** recommendations of all runs;
    - needs_attention: a student with no run in the last
      ``NEEDS_ATTENTION_DAYS`` days (or no run at all), or whose latest
      top match is below ``NEEDS_ATTENTION_MATCH_PERCENT``.
    The payload contains no e-mail addresses.
    """
    now = now or datetime.now(timezone.utc)
    students = [m for m in members if m.get("institute_role") == "student"]
    student_ids = {m["user_id"] for m in students}
    own_runs = [r for r in runs if r.user_id in student_ids]

    top_careers: Counter = Counter()
    missing: Counter = Counter()
    distribution: Counter = Counter({b: 0 for b in _READINESS_BUCKETS})
    for run in own_runs:
        if run.recommendations:
            top_careers[run.recommendations[0].title] += 1
            percent = _top_match_percent(run)
            if percent is not None:
                distribution[_bucket(percent)] += 1
        for rec in run.recommendations:
            for skill in rec.missing_skills or []:
                missing[skill.strip().lower()] += 1

    by_student: dict[str, list] = {}
    for run in own_runs:
        by_student.setdefault(run.user_id, []).append(run)
    attention: list[dict] = []
    for student in students:
        mine = sorted(by_student.get(student["user_id"], []), key=lambda r: r.id)
        latest = mine[-1] if mine else None
        reasons: list[str] = []
        last_at = latest.created_at if latest else ""
        percent = _top_match_percent(latest) if latest else None
        created = _parse_time(last_at) if latest else None
        if (
            latest is None
            or created is None
            or created < now - timedelta(days=NEEDS_ATTENTION_DAYS)
        ):
            reasons.append(f"no_run_in_{NEEDS_ATTENTION_DAYS}_days")
        if percent is not None and percent < NEEDS_ATTENTION_MATCH_PERCENT:
            reasons.append("low_top_match")
        if reasons:
            attention.append(
                {
                    "user_id": student["user_id"],
                    "name": student.get("name", ""),
                    "reasons": reasons,
                    "last_run_at": last_at,
                    "top_match_percent": percent,
                }
            )
    return {
        "member_count": len(members),
        "student_count": len(students),
        "runs_count": len(own_runs),
        "top_recommended_careers": [
            {"title": title, "count": count} for title, count in top_careers.most_common(10)
        ],
        "most_missing_skills": [
            {"skill": skill, "count": count} for skill, count in missing.most_common(10)
        ],
        "readiness_distribution": [
            {"bucket": bucket, "count": distribution[bucket]} for bucket in _READINESS_BUCKETS
        ],
        "needs_attention": attention,
    }


# --------------------------------------------------------------------------- #
# Term-over-term analytics (Phase 9)                                           #
# --------------------------------------------------------------------------- #
# A "term" is a CALENDAR QUARTER (Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep,
# Q4 = Oct–Dec, UTC). Term-over-term compares the current quarter against
# the immediately previous one, over REAL stored runs only: a period with
# no runs yields the honest zero/empty cohort, never fabricated numbers.


def quarter_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """[start, end) UTC bounds of the calendar quarter holding ``moment``."""
    start_month = 3 * ((moment.month - 1) // 3) + 1
    start = moment.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_month == 10:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start_month + 3)
    return start, end


def _quarter_label(start: datetime) -> str:
    return f"{start.year}-Q{(start.month - 1) // 3 + 1}"


def _runs_between(runs: list, start: datetime, end: datetime) -> list:
    out = []
    for run in runs:
        created = _parse_time(run.created_at or "")
        if created is not None and start <= created < end:
            out.append(run)
    return out


def _merged_counts(current: list[dict], previous: list[dict], key: str) -> list[dict]:
    cur = {item[key]: item["count"] for item in current}
    prev = {item[key]: item["count"] for item in previous}
    titles = sorted(set(cur) | set(prev), key=lambda t: (-cur.get(t, 0), t))
    return [
        {
            key: title,
            "current": cur.get(title, 0),
            "previous": prev.get(title, 0),
            "delta": cur.get(title, 0) - prev.get(title, 0),
        }
        for title in titles[:10]
    ]


def compute_cohort_comparison(members: list[dict], runs: list, now: datetime | None = None) -> dict:
    """Current-quarter vs previous-quarter cohorts + deltas.

    Both sides are plain :func:`compute_cohort` payloads over the runs
    stored inside each quarter (attention is evaluated as of each
    period's end). Deltas: ``runs_count`` (current − previous), the
    readiness distribution per bucket, and merged top-career /
    missing-skill counts. Membership counts are period-independent, so
    they are reported per side but not delta-ed.
    """
    now = now or datetime.now(timezone.utc)
    cur_start, cur_end = quarter_bounds(now)
    # The day before this quarter starts sits in the previous quarter.
    prev_start, prev_end = quarter_bounds(cur_start - timedelta(days=1))
    current = compute_cohort(members, _runs_between(runs, cur_start, cur_end), now=cur_end)
    previous = compute_cohort(members, _runs_between(runs, prev_start, prev_end), now=prev_end)
    cur_dist = {d["bucket"]: d["count"] for d in current["readiness_distribution"]}
    prev_dist = {d["bucket"]: d["count"] for d in previous["readiness_distribution"]}
    return {
        "term": {
            "kind": "calendar_quarter",
            "current": {
                "label": _quarter_label(cur_start),
                "start": cur_start.date().isoformat(),
                "end": (cur_end - timedelta(days=1)).date().isoformat(),
            },
            "previous": {
                "label": _quarter_label(prev_start),
                "start": prev_start.date().isoformat(),
                "end": (prev_end - timedelta(days=1)).date().isoformat(),
            },
        },
        "current": current,
        "previous": previous,
        "deltas": {
            "runs_count": current["runs_count"] - previous["runs_count"],
            "readiness_distribution": [
                {
                    "bucket": bucket,
                    "current": cur_dist.get(bucket, 0),
                    "previous": prev_dist.get(bucket, 0),
                    "delta": cur_dist.get(bucket, 0) - prev_dist.get(bucket, 0),
                }
                for bucket in _READINESS_BUCKETS
            ],
            "top_recommended_careers": _merged_counts(
                current["top_recommended_careers"], previous["top_recommended_careers"], "title"
            ),
            "most_missing_skills": _merged_counts(
                current["most_missing_skills"], previous["most_missing_skills"], "skill"
            ),
        },
    }


def _add_month(moment: datetime) -> datetime:
    if moment.month == 12:
        return moment.replace(year=moment.year + 1, month=1)
    return moment.replace(month=moment.month + 1)


def report_schedule_payload(institute: dict) -> dict:
    """{schedule, next_run} for an institute row.

    ``next_run`` is NOMINAL — derived from when the preference was last
    set (weekly → +7 days, monthly → +1 calendar month, none → None).
    No scheduler exists yet, so nothing is sent at that time; this is a
    preference record the owner/scheduler work will consume later.
    """
    schedule = institute.get("report_schedule") or "none"
    if schedule not in REPORT_SCHEDULES:
        schedule = "none"
    next_run = None
    updated = _parse_time(institute.get("report_schedule_updated_at") or "")
    if updated is not None:
        if schedule == "weekly":
            next_run = (updated + timedelta(days=7)).isoformat(timespec="seconds")
        elif schedule == "monthly":
            next_run = _add_month(updated).isoformat(timespec="seconds")
    return {"schedule": schedule, "next_run": next_run}


def cohort_csv(cohort: dict, institute: dict) -> str:
    """Aggregate-only CSV (no names, no e-mails, no per-student rows)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["institute", institute.get("name", "")])
    writer.writerow(["metric", "value"])
    writer.writerow(["member_count", cohort["member_count"]])
    writer.writerow(["student_count", cohort["student_count"]])
    writer.writerow(["runs_count", cohort["runs_count"]])
    writer.writerow(["needs_attention_count", len(cohort["needs_attention"])])
    writer.writerow([])
    writer.writerow(["top_recommended_career", "runs"])
    for item in cohort["top_recommended_careers"]:
        writer.writerow([item["title"], item["count"]])
    writer.writerow([])
    writer.writerow(["most_missing_skill", "runs"])
    for item in cohort["most_missing_skills"]:
        writer.writerow([item["skill"], item["count"]])
    writer.writerow([])
    writer.writerow(["readiness_bucket_percent", "runs"])
    for item in cohort["readiness_distribution"]:
        writer.writerow([item["bucket"], item["count"]])
    return out.getvalue()


def cohort_pdf(cohort: dict, institute: dict) -> bytes:
    """Branded cohort PDF via reportlab (same plumbing as reports.py)."""
    import io as _io

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    accent_hex = institute.get("accent_color") or "#0f766e"
    try:
        accent = colors.HexColor(accent_hex)
    except (ValueError, AttributeError):
        accent = colors.HexColor("#0f766e")
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], alignment=0)
    h2 = ParagraphStyle("h", parent=styles["Heading2"], textColor=accent)
    body = ParagraphStyle("b", parent=styles["Normal"], fontSize=10, leading=14)

    def esc(text: object) -> str:
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(rows: list[list[str]]) -> Table:
        t = Table(rows, hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 0), (-1, 0), accent),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    buffer = _io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="Cohort Report",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story = [Paragraph(f"{esc(institute.get('name', 'Institute'))} — Cohort Report", title)]
    if institute.get("logo_url"):
        story.append(Paragraph(f"Logo: {esc(institute['logo_url'])}", body))
    story.append(
        Paragraph(
            f"Members: {cohort['member_count']} · Students: {cohort['student_count']} · "
            f"Runs: {cohort['runs_count']} · Needs attention: {len(cohort['needs_attention'])}",
            body,
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Top recommended careers", h2))
    story.append(
        table(
            [["Career", "Runs"]]
            + [[esc(i["title"]), str(i["count"])] for i in cohort["top_recommended_careers"]]
            or [["Career", "Runs"], ["—", "0"]]
        )
    )
    story.append(Paragraph("Most missing skills", h2))
    story.append(
        table(
            [["Skill", "Runs"]]
            + [[esc(i["skill"]), str(i["count"])] for i in cohort["most_missing_skills"]]
            or [["Skill", "Runs"], ["—", "0"]]
        )
    )
    story.append(Paragraph("Readiness distribution (top match %)", h2))
    story.append(
        table(
            [["Bucket", "Runs"]]
            + [[i["bucket"], str(i["count"])] for i in cohort["readiness_distribution"]]
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph("Aggregate report only — no individual student data. Career Guidance AI.", body)  # noqa: E501
    )
    doc.build(story)
    return buffer.getvalue()


__all__ = [
    "DEFAULT_SEAT_LIMIT",
    "INSTITUTE_ROLES",
    "MAX_CSV_BYTES",
    "MAX_CSV_ROWS",
    "NEEDS_ATTENTION_DAYS",
    "NEEDS_ATTENTION_MATCH_PERCENT",
    "REPORT_SCHEDULES",
    "REVIEW_LABEL",
    "InstituteStore",
    "cohort_csv",
    "cohort_pdf",
    "compute_cohort",
    "compute_cohort_comparison",
    "parse_invite_csv",
    "quarter_bounds",
    "report_schedule_payload",
    "review_payload",
]
