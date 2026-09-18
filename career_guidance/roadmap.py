"""Roadmap generator: missing/weak skills → week-by-week plan + exports.

Ordering is **importance × prerequisite order**: a skill that other missing
skills depend on comes first, and inside the same prerequisite layer the more
important skill wins. Skills are packed into weeks given ``hours_per_week``
(default 6, configurable per profile), each week carrying the free resources
attached to its skill, plus milestones and an ETA date.

Exports: Markdown, JSON and iCalendar (``.ics``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from career_guidance.learning import resources_for
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
