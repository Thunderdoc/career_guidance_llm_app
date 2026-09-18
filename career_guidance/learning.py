"""Curated learning-resource lookup for skills."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.models import LearningResource
from career_guidance.taxonomy import DOMAIN_HINTS, normalize_skill

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "learning_resources.yaml"

# O*NET competency -> canonical skill key in the YAML (when names differ).
_COMPETENCY_ALIASES = {
    "programming": "programming",
    "mathematics": "mathematics",
    "writing": "writing",
    "speaking": "communication",
    "active listening": "communication",
    "english language": "english",
    "computers and electronics": "programming",
    "design": "user experience",
    "economics and accounting": "accounting",
    "sales and marketing": "marketing",
    "customer and personal service": "service orientation",
    "education and training": "teaching",
    "medicine and dentistry": "nursing",
    "engineering and technology": "mechanical engineering",
    "telecommunications": "networking",
    "public safety and security": "cybersecurity",
    "administration and management": "project management",
    "coordination": "project management",
    "time management": "project management",
    "troubleshooting": "testing",
    "judgment and decision making": "critical thinking",
    "learning strategies": "teaching",
    "monitoring": "quality control analysis",
    "operation monitoring": "quality control analysis",
    "systems evaluation": "systems analysis",
}


@lru_cache(maxsize=1)
def _load(path: str | None = None) -> dict[str, list[dict]]:
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k).lower(): v for k, v in data.items()}


def resources_for(skill: str, limit: int = 2) -> list[LearningResource]:
    """Return curated resources for a skill or O*NET competency name."""
    table = _load()
    key = skill.strip().lower()
    candidates = [key, normalize_skill(skill), _COMPETENCY_ALIASES.get(key, "")]
    # A concrete tool can fall back to the competencies it implies.
    for hint in DOMAIN_HINTS.get(normalize_skill(skill), ()):
        candidates.append(_COMPETENCY_ALIASES.get(hint.lower(), hint.lower()))
    seen: set[str] = set()
    out: list[LearningResource] = []
    for cand in candidates:
        if not cand or cand in seen or cand not in table:
            seen.add(cand)
            continue
        seen.add(cand)
        for item in table[cand]:
            out.append(
                LearningResource(
                    skill=skill,
                    title=str(item["title"]),
                    url=str(item["url"]),
                    provider=str(item.get("provider", "")),
                    free=bool(item.get("free", True)),
                )
            )
            if len(out) >= limit:
                return out
    return out


def resources_for_gaps(
    missing_skills: list[str], per_skill: int = 1, limit: int = 5
) -> list[LearningResource]:
    """Resources for a list of gaps, de-duplicated by URL."""
    out: list[LearningResource] = []
    seen: set[str] = set()
    for skill in missing_skills:
        for res in resources_for(skill, per_skill):
            if res.url in seen:
                continue
            seen.add(res.url)
            out.append(res)
            if len(out) >= limit:
                return out
    return out
