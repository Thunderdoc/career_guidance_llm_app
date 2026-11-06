"""Roadmap generator: missing/weak skills → week-by-week plan + exports.

Ordering is **importance × prerequisite order**: a skill that other missing
skills depend on comes first, and inside the same prerequisite layer the more
important skill wins. Skills are packed into weeks given ``hours_per_week``
(default 6, configurable per profile), each week carrying the free resources
attached to its skill, plus milestones and an ETA date.

Exports: Markdown, JSON and iCalendar (``.ics``).
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from career_guidance.learning import resources_for
from career_guidance.migrations import migrate
from career_guidance.models import LearningResource
from career_guidance.skillgap import Readiness, SkillRating, evaluate

#: Coarse prerequisite layers — lower runs first. Anything unlisted is layer 2.
PREREQUISITE_LAYERS: dict[str, int] = {
    # foundations that everything else builds on
    "mathematics": 0,
    "statistics": 0,
    "english language": 0,
    "computers and electronics": 0,
    "reading comprehension": 0,
    "critical thinking": 0,
    "active learning": 0,
    "programming": 1,
    "spreadsheet software": 1,
    "sql": 1,
    "excel": 1,
    "accounting software": 1,
    "accounting": 1,
    "communication": 0,
    "writing": 0,
    "speaking": 0,
}

#: Practice-heavy skills need more hours per week than reading-heavy ones.
HOUR_MULTIPLIER: dict[str, float] = {
    "speaking": 0.5,
    "active listening": 0.5,
    "reading comprehension": 0.5,
    "writing": 0.75,
    "critical thinking": 0.5,
    "mathematics": 1.0,
}
DEFAULT_HOURS = 6
DEFAULT_MIN_WEEKS = 1
DEFAULT_MAX_WEEKS = 26


@dataclass
class RoadmapItem:
    id: str
    week: int
    skill: str
    title: str
    hours: float
    status: str  # missing | weak
    importance: float
    prerequisite_of: list[str] = field(default_factory=list)
    resources: list[LearningResource] = field(default_factory=list)
    milestone: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "week": self.week,
            "skill": self.skill,
            "title": self.title,
            "hours": self.hours,
            "status": self.status,
            "importance": round(self.importance * 10, 1),
            "prerequisite_of": self.prerequisite_of,
            "resources": [
                {
                    "id": getattr(r, "id", None),
                    "skill": r.skill,
                    "title": r.title,
                    "url": r.url,
                    "provider": r.provider,
                    "free": r.free,
                    "level": getattr(r, "level", "beginner"),
                    "language": getattr(r, "language", "en"),
                    "duration_minutes": getattr(r, "duration_minutes", 0),
                }
                for r in self.resources
            ],
            "milestone": self.milestone,
        }


@dataclass
class Roadmap:
    occupation_id: str
    title: str
    hours_per_week: int
    weeks: int
    eta: str
    items: list[RoadmapItem] = field(default_factory=list)
    milestones: list[dict] = field(default_factory=list)
    readiness_before: float = 0.0
    readiness_after: float = 0.0
    source: str = (
        "Source: O*NET skill importance × curated free-course catalogue, ordered by prerequisites"  # noqa: E501
    )

    def to_dict(self) -> dict:
        return {
            "career_id": self.occupation_id,
            "title": self.title,
            "hours_per_week": self.hours_per_week,
            "weeks": self.weeks,
            "eta": self.eta,
            "readiness_before": self.readiness_before,
            "readiness_after": self.readiness_after,
            "items": [i.to_dict() for i in self.items],
            "milestones": self.milestones,
            "missing_skills": [i.skill for i in self.items if i.status == "missing"],
            "weak_skills": [i.skill for i in self.items if i.status == "weak"],
            "source": self.source,
        }


def _layer(skill: str) -> int:
    return PREREQUISITE_LAYERS.get(skill.strip().lower(), 2)


def _hours_for(skill: str, importance: float) -> float:
    base = 4 + 6 * importance  # 4–10 h for a skill
    return round(base * HOUR_MULTIPLIER.get(skill.strip().lower(), 1.0), 1)


def order_gaps(ratings: list[SkillRating]) -> list[SkillRating]:
    """Missing/weak skills, prerequisite layer first, then importance."""
    gaps = [r for r in ratings if r.status != "strong"]
    return sorted(gaps, key=lambda r: (_layer(r.skill), -r.importance, r.skill))


def generate(
    readiness: Readiness,
    hours_per_week: int = DEFAULT_HOURS,
    start: date | None = None,
    min_weeks: int = DEFAULT_MIN_WEEKS,
    max_weeks: int = DEFAULT_MAX_WEEKS,
    resource_lookup=resources_for,
) -> Roadmap:
    """Build the week-by-week plan for an evaluated readiness result."""
    hours_per_week = max(1, min(60, int(hours_per_week or DEFAULT_HOURS)))
    start = start or date.today()
    gaps = order_gaps(readiness.ratings)

    items: list[RoadmapItem] = []
    remaining_gaps = {r.skill for r in gaps}
    # Skills are scheduled sequentially: each one consumes its learning hours and
    # the week follows from the cumulative hours, so a 9-hour skill in a 6 h/week
    # plan simply spans into the next week instead of pushing the whole plan to
    # the end.
    cumulative = 0.0
    for gap in gaps:
        cost = _hours_for(gap.skill, gap.importance)
        # Prerequisites block dependents: a skill in a later layer is "prerequisite of"
        # everything remaining in a later layer.
        dependents = [
            r.skill
            for r in gaps
            if r.skill != gap.skill
            and r.skill in remaining_gaps
            and _layer(r.skill) > _layer(gap.skill)
        ]
        resources = list(resource_lookup(gap.skill, 2))
        week = min(max_weeks, int(cumulative // hours_per_week) + 1)
        cumulative += cost
        items.append(
            RoadmapItem(
                id=f"{readiness.occupation.id}:{gap.skill.lower().replace(' ', '-')}",
                week=week,
                skill=gap.skill,
                title=f"Learn {gap.skill}",
                hours=cost,
                status=gap.status,
                importance=gap.importance,
                prerequisite_of=dependents[:3],
                resources=resources,
                milestone=f"Week {week}: {gap.skill} at a working level",
            )
        )
        remaining_gaps.discard(gap.skill)

    planned_weeks = max(1, math.ceil(cumulative / hours_per_week)) if items else min_weeks
    weeks = max(min_weeks, min(max_weeks, planned_weeks))
    if items and items[-1].week > weeks:  # keep the last item inside the horizon
        weeks = min(max_weeks, items[-1].week)
    eta = start + timedelta(days=7 * weeks)
    milestones = [{"week": i.week, "text": i.milestone} for i in items]
    # Projection model: one pass through the plan moves every planned skill up one
    # step (missing → practising 0.5 credit, weak → strong 1.0 credit), which is
    # deliberately conservative — the UI never promises 100% after one plan.
    planned = {g.skill for g in gaps}
    total_weight = sum(r.importance for r in readiness.ratings) or 1.0
    projected = 0.0
    for rating in readiness.ratings:
        credit = rating.credit
        if rating.skill in planned:
            credit = 1.0 if rating.status == "weak" else 0.5
        projected += rating.importance * credit
    projected = projected / total_weight * 100
    return Roadmap(
        occupation_id=readiness.occupation.id,
        title=readiness.occupation.title,
        hours_per_week=hours_per_week,
        weeks=weeks,
        eta=eta.isoformat(),
        items=items,
        milestones=milestones,
        readiness_before=round(readiness.readiness_weighted, 1),
        readiness_after=round(min(100.0, projected), 1),
    )


def plan_for(
    occupation_id: str,
    ratings: dict[str, int],
    hours_per_week: int = DEFAULT_HOURS,
    start: date | None = None,
) -> tuple[Readiness, Roadmap]:
    """Convenience: evaluate ratings and generate the roadmap in one call."""
    readiness = evaluate(occupation_id, ratings)
    return readiness, generate(readiness, hours_per_week, start)


# ---------------------------------------------------------------------------- #
# Exports                                                                      #
# ---------------------------------------------------------------------------- #


def to_markdown(roadmap: Roadmap) -> str:
    lines = [
        f"# Learning roadmap — {roadmap.title}",
        "",
        f"* {roadmap.hours_per_week} hours per week · {roadmap.weeks} weeks · ETA {roadmap.eta}",
        f"* Readiness {roadmap.readiness_before}% → {roadmap.readiness_after}% (projected)",
        f"* {roadmap.source}",
        "",
    ]
    current_week = None
    for item in roadmap.items:
        if item.week != current_week:
            current_week = item.week
            lines += ["", f"## Week {item.week}"]
        lines.append(f"- [ ] **{item.skill}** ({item.hours} h, {item.status})")
        for resource in item.resources:
            lines.append(f"  - [{resource.title}]({resource.url}) — {resource.provider}")
        if item.prerequisite_of:
            lines.append(f"  - Unlocks: {', '.join(item.prerequisite_of)}")
    lines += ["", "## Milestones", ""]
    lines += [f"- Week {m['week']}: {m['text']}" for m in roadmap.milestones]
    return "\n".join(lines)


def to_json(roadmap: Roadmap) -> str:
    import json

    return json.dumps(roadmap.to_dict(), indent=2)


def to_ics(roadmap: Roadmap, start: date | None = None) -> str:
    """RFC 5545 calendar with one weekly block per planned skill."""
    from datetime import datetime, timezone

    start = start or date.today()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Career Guidance AI//Roadmap//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:Roadmap — {roadmap.title}",
    ]
    for item in roadmap.items:
        day = start + timedelta(days=7 * (item.week - 1))
        end = day + timedelta(days=1)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{item.id}@career-guidance-ai",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:Week {item.week} — learn {item.skill} ({item.hours} h)",
            f"DESCRIPTION:{item.title}. {len(item.resources)} free resource(s) attached.",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------- #
# 90-day plan (Phase 3.3)                                                      #
# ---------------------------------------------------------------------------- #

TOTAL_WEEKS_90 = 13


def _constraint_hours(constraints) -> int:
    """hours_per_week from a constraints dict/object, defaulting to 6."""
    if constraints is None:
        return DEFAULT_HOURS
    value = (
        constraints.get("hours_per_week")
        if isinstance(constraints, dict)
        else getattr(constraints, "hours_per_week", None)
    )
    try:
        hours = int(value) if value else DEFAULT_HOURS
    except (TypeError, ValueError):
        hours = DEFAULT_HOURS
    return max(1, min(40, hours))


def _resource_dict(resource) -> dict:
    if isinstance(resource, dict):
        return {
            "title": str(resource.get("title", "")),
            "url": str(resource.get("url", "")),
            "provider": str(resource.get("provider", "")),
            "free": bool(resource.get("free", True)),
        }
    return {
        "title": resource.title,
        "url": resource.url,
        "provider": resource.provider,
        "free": bool(resource.free),
    }


def build_90_day_plan(
    priority_skills: list[str],
    constraints=None,
    *,
    run_id: int | None = None,
    start: date | None = None,
    resource_lookup=resources_for,
) -> dict:
    """A 13-week plan over the run's priority skills.

    Every task is drawn from the curated learning catalogue
    (``career_guidance.learning``) — never an invented URL. A skill with no
    catalogued resource gets an honestly empty task list plus a note.
    ``hours_per_week`` comes from the wizard constraints (default 6) and
    scales the number of tasks per week (1–3). Each week names the Phase-3
    verification quiz for its skill when one exists.
    """
    from career_guidance.verify import available_quizzes, quiz_skill_for

    start = start or date.today()
    hours = _constraint_hours(constraints)
    skills: list[str] = []
    for skill in priority_skills or []:
        name = str(skill).strip()
        if name and name.lower() not in {s.lower() for s in skills}:
            skills.append(name)
    quiz_titles = {q["skill"]: q["title"] for q in available_quizzes()}
    tasks_per_week = max(1, min(3, round(hours / 3)))
    weeks: list[dict] = []
    seen_counts: dict[str, int] = {}
    for index in range(TOTAL_WEEKS_90):
        if not skills:
            break
        skill = skills[index % len(skills)]
        occurrence = seen_counts.get(skill.lower(), 0)
        seen_counts[skill.lower()] = occurrence + 1
        resources = [_resource_dict(r) for r in resource_lookup(skill, 6)]
        tasks: list[dict] = []
        if resources:
            offset = (occurrence * tasks_per_week) % len(resources)
            chosen = [resources[(offset + j) % len(resources)] for j in range(tasks_per_week)]
            per_task = round(hours / len(chosen), 1)
            tasks = [
                {
                    "id": f"w{index + 1}-t{j + 1}",
                    "title": f"Work through: {res['title']}",
                    "skill": skill,
                    "hours": per_task,
                    "resource": res,
                    "done": False,
                }
                for j, res in enumerate(chosen)
            ]
        quiz_skill = quiz_skill_for(skill)
        weeks.append(
            {
                "week": index + 1,
                "skill": skill,
                "theme": f"Build {skill}",
                "hours": hours,
                "tasks": tasks,
                "note": ("" if tasks else "No curated resource is catalogued for this skill yet."),
                "verification_check": (
                    f"Verification check: take the “{quiz_titles[quiz_skill]}” quiz "
                    "from your account to verify this skill."
                    if quiz_skill
                    else ""
                ),
            }
        )
    return {
        "kind": "90-day",
        "run_id": run_id,
        "start_date": start.isoformat(),
        "total_weeks": TOTAL_WEEKS_90,
        "hours_per_week": hours,
        "priority_skills": skills,
        "weeks": weeks,
        "tasks_total": sum(len(w["tasks"]) for w in weeks),
        "source": (
            "Source: your recommendation run's priority skills + the curated "
            "free-course catalogue (data/learning_resources.yaml)"
        ),
    }


def current_week(plan: dict, today: date | None = None) -> dict | None:
    """The plan week that contains ``today`` (None when the plan is empty)."""
    weeks = plan.get("weeks") or []
    if not weeks:
        return None
    try:
        start = date.fromisoformat(str(plan.get("start_date", "")))
    except ValueError:
        start = date.today()
    elapsed = max(0, ((today or date.today()) - start).days // 7)
    return weeks[min(elapsed, len(weeks) - 1)]


def plan_progress(plan: dict, done_task_ids: set[str]) -> dict:
    """Progress summary over a stored 90-day plan."""
    total = sum(len(w["tasks"]) for w in plan.get("weeks", []))
    done = sum(1 for w in plan.get("weeks", []) for t in w["tasks"] if t["id"] in done_task_ids)
    return {
        "tasks_total": total,
        "tasks_done": done,
        "percent": round(100.0 * done / total, 1) if total else 0.0,
    }


def to_markdown_90(plan: dict) -> str:
    lines = [
        "# 90-day plan",
        "",
        f"* {plan.get('hours_per_week', DEFAULT_HOURS)} hours per week · "
        f"{plan.get('total_weeks', TOTAL_WEEKS_90)} weeks · starts {plan.get('start_date', '')}",
        f"* Priority skills: {', '.join(plan.get('priority_skills', [])) or '—'}",
        f"* {plan.get('source', '')}",
        "",
    ]
    for week in plan.get("weeks", []):
        lines += ["", f"## Week {week['week']} — {week['skill']}"]
        for task in week["tasks"]:
            res = task["resource"]
            lines.append(
                f"- [ ] **{task['title']}** ({task['hours']} h) — [{res['provider']}]({res['url']})"
            )
        if week.get("note"):
            lines.append(f"- _{week['note']}_")
        if week.get("verification_check"):
            lines.append(f"- {week['verification_check']}")
    return "\n".join(lines)


def to_ics_90(plan: dict) -> str:
    """RFC 5545 calendar with one event per plan week."""
    from datetime import datetime, timezone

    try:
        start = date.fromisoformat(str(plan.get("start_date", "")))
    except ValueError:
        start = date.today()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Career Guidance AI//Plan90//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:90-day plan",
    ]
    for week in plan.get("weeks", []):
        day = start + timedelta(days=7 * (int(week["week"]) - 1))
        end = day + timedelta(days=1)
        task_titles = "; ".join(t["title"] for t in week["tasks"]) or week.get("note", "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:plan90-w{week['week']}@career-guidance-ai",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:90-day plan week {week['week']} — {week['skill']} ({week['hours']} h)",
            f"DESCRIPTION:{task_titles}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


class Plan90Store:
    """Persistence for 90-day plans (table from migration v5)."""

    def __init__(self, path) -> None:
        self._path = str(path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, user_id: str, plan: dict) -> dict:
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO plans_90day (user_id, run_id, created_at, hours_per_week, plan_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    user_id,
                    plan.get("run_id"),
                    created,
                    int(plan.get("hours_per_week", DEFAULT_HOURS)),
                    json.dumps(plan),
                ),
            )
            plan_id = int(cur.lastrowid or 0)
        return {**plan, "plan_id": plan_id, "created_at": created}

    def latest(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plans_90day WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        plan = json.loads(row["plan_json"])
        plan["plan_id"] = row["id"]
        plan["created_at"] = row["created_at"]
        return plan

    def mark_task(self, user_id: str, plan_id: int, task_id: str, done: bool) -> dict | None:
        """Toggle a task's done flag inside the stored plan JSON."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plans_90day WHERE id = ? AND user_id = ?", (plan_id, user_id)
            ).fetchone()
            if row is None:
                return None
            plan = json.loads(row["plan_json"])
            found = False
            for week in plan.get("weeks", []):
                for task in week.get("tasks", []):
                    if task["id"] == task_id:
                        task["done"] = bool(done)
                        found = True
            if not found:
                return None
            conn.execute(
                "UPDATE plans_90day SET plan_json = ? WHERE id = ?",
                (json.dumps(plan), plan_id),
            )
        plan["plan_id"] = row["id"]
        plan["created_at"] = row["created_at"]
        return plan
