"""Skill-gap engine: self-ratings → Strong / Weak / Missing → Readiness %.

The user self-rates each skill a target occupation requires on a 1–5 scale
(0 = "never used it"). Ratings are combined with the **importance** of the skill
inside the occupation (O*NET importance order, decayed by rank) so that
Readiness is importance-weighted:

    Readiness % = Σ(importance · level) / Σ(importance) · 100

with ``level`` = 1.0 for a strong skill (≥4), 0.5 for a weak one (2–3) and 0.0
for a missing one (0–1). Two numbers are reported: the raw percentage of skills
covered and the importance-weighted readiness that drives the roadmap.

Sources are always labelled — importance comes from the bundled O*NET catalog,
ratings come from the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from career_guidance.taxonomy import Occupation, Taxonomy, load_taxonomy

STRONG = "strong"
WEAK = "weak"
MISSING = "missing"

#: How much credit each status earns towards readiness.
STATUS_CREDIT = {STRONG: 1.0, WEAK: 0.5, MISSING: 0.0}

DEFAULT_STRONG_THRESHOLD = 4
DEFAULT_WEAK_THRESHOLD = 2
MAX_RATED_SKILLS = 18


def status_for(
    rating: int, strong: int = DEFAULT_STRONG_THRESHOLD, weak: int = DEFAULT_WEAK_THRESHOLD
) -> str:
    """Strong (≥4) / Weak (2–3) / Missing (0–1)."""
    if rating >= strong:
        return STRONG
    if rating >= weak:
        return WEAK
    return MISSING


def importance_weights(occupation: Occupation) -> list[tuple[str, float]]:
    """The occupation's core skills ordered by importance (rank-decayed 1.0 → 0.3)."""
    seen: dict[str, float] = {}
    total = len(occupation.skills) or 1
    for rank, name in enumerate(occupation.skills):
        weight = max(0.3, 1.0 - 0.7 * (rank / total))
        seen.setdefault(name, weight)
    for rank, name in enumerate(occupation.knowledge[:6]):
        weight = max(0.25, 0.8 - 0.6 * (rank / 6))
        seen.setdefault(name, weight)
    return list(seen.items())


def catalog_importance(occupation: Occupation) -> dict[str, float]:
    """1–10 importance score per skill (for the UI bars)."""
    weights = importance_weights(occupation)
    if not weights:
        return {}
    top = max(w for _, w in weights)
    return {name: round(w / top * 10, 1) for name, w in weights}


@dataclass
class SkillRating:
    skill: str
    importance: float
    rating: int
    status: str
    credit: float

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "importance": round(self.importance, 3),
            "importance_10": round(self.importance * 10, 1),
            "rating": self.rating,
            "status": self.status,
        }


@dataclass
class Readiness:
    """Readiness result for one occupation + one set of self-ratings."""

    occupation: Occupation
    ratings: list[SkillRating] = field(default_factory=list)
    readiness: float = 0.0
    readiness_weighted: float = 0.0

    @property
    def skills(self) -> list[SkillRating]:
        return self.ratings

    @property
    def strong(self) -> list[SkillRating]:
        return [r for r in self.ratings if r.status == STRONG]

    @property
    def weak(self) -> list[SkillRating]:
        return [r for r in self.ratings if r.status == WEAK]

    @property
    def missing(self) -> list[SkillRating]:
        return [r for r in self.ratings if r.status == MISSING]

    def radar(self, top: int = 8) -> list[dict]:
        """Radar dataset: the eight most important skills with rating + target."""
        ordered = sorted(self.ratings, key=lambda r: -r.importance)[:top]
        return [
            {
                "skill": r.skill,
                "rating": r.rating,
                "importance": round(r.importance * 10, 1),
                "status": r.status,
            }
            for r in ordered
        ]

    def next_gap(self) -> SkillRating | None:
        """The missing/weak skill with the highest importance."""
        candidates = [r for r in self.ratings if r.status != STRONG]
        return max(candidates, key=lambda r: r.importance) if candidates else None

    def to_dict(
        self,
        default_strong: int = DEFAULT_STRONG_THRESHOLD,
        default_weak: int = DEFAULT_WEAK_THRESHOLD,
    ) -> dict:
        return {
            "career_id": self.occupation.id,
            "title": self.occupation.title,
            "readiness": round(self.readiness, 1),
            "readiness_weighted": round(self.readiness_weighted, 1),
            "counts": {
                "strong": len(self.strong),
                "weak": len(self.weak),
                "missing": len(self.missing),
            },  # noqa: E501
            "skills": [r.to_dict() for r in self.ratings],
            "radar": self.radar(),
            "thresholds": {"strong": default_strong, "weak": default_weak},
            "source": "Source: O*NET skill importance (bundled catalog) × your 1–5 self-ratings",
        }


def evaluate(
    occupation_id: str,
    ratings: dict[str, int],
    taxonomy: Taxonomy | None = None,
    strong: int = DEFAULT_STRONG_THRESHOLD,
    weak: int = DEFAULT_WEAK_THRESHOLD,
    max_skills: int = MAX_RATED_SKILLS,
) -> Readiness:
    """Score ``ratings`` (skill → 1–5) against one occupation.

    Skills that were not rated count as **missing** so the readiness number is
    never optimistic: silence is not evidence of skill.
    """
    taxonomy = taxonomy or load_taxonomy()
    occupation = taxonomy.get(occupation_id)
    if occupation is None:
        raise KeyError(occupation_id)

    table = {k.strip().lower(): int(v) for k, v in (ratings or {}).items()}
    rated: list[SkillRating] = []
    for name, importance in importance_weights(occupation)[:max_skills]:
        rating = table.get(name.lower(), 0)
        rating = max(0, min(5, rating))
        status = status_for(rating, strong, weak)
        rated.append(
            SkillRating(
                skill=name,
                importance=importance,
                rating=rating,
                status=status,
                credit=STATUS_CREDIT[status],
            )
        )
    total_weight = sum(r.importance for r in rated) or 1.0
    weighted = sum(r.importance * r.credit for r in rated) / total_weight * 100
    plain = sum(r.credit for r in rated) / len(rated) * 100 if rated else 0.0
    return Readiness(
        occupation=occupation,
        ratings=rated,
        readiness=round(plain, 1),
        readiness_weighted=round(weighted, 1),
    )


def readiness_percent(readiness: Readiness) -> float:
    """Single number shown in the UI (importance-weighted, rounded)."""
    return round(readiness.readiness_weighted)
