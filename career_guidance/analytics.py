"""Analytics computed from stored recommendation runs.

All metrics are derived from real persisted data; nothing is fabricated.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from career_guidance.storage import StoredRun

_SPLIT = re.compile(r"[,;\n|]+")


@dataclass(frozen=True)
class AnalyticsSummary:
    """Aggregated metrics over stored recommendation runs."""

    total_runs: int
    ai_runs: int
    demo_runs: int
    top_careers: list[tuple[str, int]]
    top_missing_skills: list[tuple[str, int]]
    runs_per_day: list[tuple[str, int]]
    top_requested_skills: list[tuple[str, int]] = field(default_factory=list)


def summarize(runs: list[StoredRun], top_n: int = 10) -> AnalyticsSummary:
    """Aggregate stored runs into an analytics summary."""
    careers: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    per_day: Counter[str] = Counter()
    requested: Counter[str] = Counter()

    for run in runs:
        per_day[run.created_at[:10]] += 1
        for token in _SPLIT.split(str(run.profile.get("skills", "") or "")):
            cleaned = token.strip().lower()
            if len(cleaned) >= 2:
                requested[cleaned] += 1
        for rec in run.recommendations:
            careers[rec.title] += 1
            for skill in rec.missing_skills:
                missing[skill.strip().lower()] += 1

    demo_runs = sum(1 for run in runs if run.is_demo)
    return AnalyticsSummary(
        total_runs=len(runs),
        ai_runs=len(runs) - demo_runs,
        demo_runs=demo_runs,
        top_careers=careers.most_common(top_n),
        top_missing_skills=missing.most_common(top_n),
        runs_per_day=sorted(per_day.items()),
        top_requested_skills=requested.most_common(top_n),
    )
