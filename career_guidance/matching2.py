"""Matcher v2 — explainable, weight-blended ranking.

    score = w1 · IDF-skill-overlap  +  w2 · cosine(user RIASEC, career interests)
                                +  w3 · job-zone fit

* **w1 skills** – the existing hybrid overlap (competency × IDF, technology × IDF,
  coverage, TF-IDF semantics, title intent). It is the base score produced by
  :class:`career_guidance.matching.Matcher`, which already contains the zone
  penalty; we re-apply the zone as its own weighted term so that its influence is
  explicit and tunable.
* **w2 interests** – cosine between the user's RIASEC vector (1–7, from the
  36-item assessment) and the O*NET interest profile stored per occupation.
* **w3 job zone** – distance between the occupation's job zone and the zone the
  user's education/experience points at.

Weights default to 0.55 / 0.30 / 0.15 and are read from the settings table
(admin console → Scoring settings). When a signal is absent (no interests yet,
no education given) its weight is redistributed proportionally, so a skills-only
query still ranks by skills and an interest-only query still ranks by interests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from career_guidance.matching import _ZONE_FOR_LEVEL, Match, Matcher, get_matcher
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.taxonomy import Occupation, Taxonomy

DEFAULT_WEIGHTS = {"skills": 0.55, "interests": 0.30, "job_zone": 0.15}

#: Weight given to the job-zone term when only one signal is available.
ZONE_TIEBREAK = 0.05

ZONE_LABELS = {
    1: "little or no preparation needed",
    2: "some preparation needed",
    3: "medium preparation needed",
    4: "a Bachelor's degree or similar",
    5: "extensive preparation (postgraduate)",
}

#: Education keywords → job zone the user's background points at.
EDUCATION_ZONE_HINTS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("phd", "ph.d", "doctorate", "md", "postdoc"), 4.8),
    (
        (
            "mba",
            "m.tech",
            "mtech",
            "m.sc",
            "msc",
            "masters",
            "master",
            "pg",
            "post graduate",
            "postgraduate",
        ),
        4.4,
    ),  # noqa: E501
    (
        (
            "b.tech",
            "btech",
            "be ",
            "b.e",
            "bachelor",
            "b.sc",
            "bsc",
            "b.com",
            "bcom",
            "bca",
            "graduate",
            "degree",
            "bba",
            "ba ",
        ),
        4.0,
    ),  # noqa: E501
    (
        (
            "diploma",
            "polytechnic",
            "iti",
            "12th",
            "higher secondary",
            "intermediate",
            "hsc",
            "plus two",
        ),
        3.2,
    ),  # noqa: E501
    (("10th", "sslc", "matric", "school"), 2.2),
)


@dataclass
class RankedMatch:
    """One career candidate with every component of its score exposed."""

    match: Match
    score: float
    skills_score: float
    interest_fit: float
    zone_fit: float
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def occupation(self) -> Occupation:
        return self.match.occupation

    @property
    def match_percent(self) -> float:
        return round(max(0.0, min(1.0, self.score)) * 100, 1)

    @property
    def active_weight_total(self) -> float:
        return sum(self.weights.values()) or 1.0


def education_zone(education: str, experience_level: str = EXPERIENCE_LEVELS[0]) -> float:
    """Job zone the user's education + experience points at (1.0–5.0)."""
    text = f" {(education or '').lower()} "
    zone: float | None = None
    for keywords, value in EDUCATION_ZONE_HINTS:
        if any(k in text for k in keywords):
            zone = value
            break
    level_zone = _ZONE_FOR_LEVEL.get(experience_level, 3.0)
    if zone is None:
        return level_zone
    # Experience nudges the estimate but never overrides a stated degree.
    return round(0.75 * zone + 0.25 * level_zone, 2)


def zone_fit(occupation_zone: int, target_zone: float) -> float:
    """0.65–1.0 fit score for a job zone, same curve the base matcher uses."""
    return max(0.65, 1.0 - 0.09 * abs(occupation_zone - target_zone))


def interests_profile(
    scores: dict[str, float] | None, taxonomy: Taxonomy
) -> dict[str, float] | None:
    """Map an assessment result (1–7) onto the O*NET interest axes."""
    if not scores:
        return None
    out = {k.upper(): float(v) for k, v in scores.items() if isinstance(v, (int, float))}
    return out or None


def _cosine_positive(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity rescaled to 0–1 (O*NET interests are all positive)."""
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if not na or not nb:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


class MatcherV2:
    """Blends the base matcher with interests and job-zone fit."""

    def __init__(self, base: Matcher | None = None, weights: dict[str, float] | None = None):
        self.base = base or get_matcher()
        self.taxonomy = self.base.taxonomy
        self.weights = self._normalise(weights or DEFAULT_WEIGHTS)

    @staticmethod
    def _normalise(weights: dict[str, float]) -> dict[str, float]:
        clean = {
            key: max(0.0, float(weights.get(key, DEFAULT_WEIGHTS[key])))
            for key in ("skills", "interests", "job_zone")
        }
        total = sum(clean.values())
        if total <= 0:
            return dict(DEFAULT_WEIGHTS)
        return {k: round(v / total, 4) for k, v in clean.items()}

    # ------------------------------------------------------------------ #
    def active_weights(self, has_skills: bool, has_interests: bool) -> dict[str, float]:
        """Weights that apply to the signals the user actually provided.

        With both signals we use the configured weights verbatim. With only one,
        that signal takes over and the job zone is demoted to a **tiebreaker**
        (``ZONE_TIEBREAK``): interest-only lists are dominated by interest fit
        rather than by seniority brackets, and skills-only lists keep the zone
        penalty that is already inside the base score.
        """
        if has_skills and has_interests:
            active = dict(self.weights)
        elif has_skills:
            active = {"skills": 1.0, "interests": 0.0, "job_zone": ZONE_TIEBREAK}
        elif has_interests:
            active = {"skills": 0.0, "interests": 1.0, "job_zone": ZONE_TIEBREAK}
        else:
            return dict(self.weights)
        total = sum(active.values()) or 1.0
        return {k: round(v / total, 4) for k, v in active.items()}

    def rank(
        self,
        profile: CareerProfile,
        top_k: int = 5,
        interests: dict[str, float] | None = None,
        exclude_ids: set[str] | None = None,
        weights: dict[str, float] | None = None,
    ) -> list[RankedMatch]:
        weights = self._normalise(weights or self.weights)
        user_interests = interests_profile(interests, self.taxonomy)
        user_terms = self.base.user_terms(profile)
        target_zone = education_zone(profile.education, profile.experience_level)
        active = self.active_weights(bool(user_terms) or bool(profile.goals), bool(user_interests))

        # Ask the base matcher for the whole ranked field (it applies the
        # competency/technology/semantics/title-intent blend and dedupes families).
        base_matches = self.base.rank(
            profile, top_k=len(self.taxonomy.occupations), interests=None, exclude_ids=exclude_ids
        )

        ranked: list[RankedMatch] = []
        for match in base_matches:
            occ = match.occupation
            skills_score = max(0.0, min(1.0, match.score))
            interest = (
                _cosine_positive(user_interests, occ.interests)
                if user_interests and occ.interests
                else 0.0
            )
            fit = zone_fit(occ.job_zone, target_zone)
            score = (
                active["skills"] * skills_score
                + active["interests"] * interest
                + active["job_zone"] * fit
            )
            if not user_terms and not user_interests and not profile.goals.strip():
                score = 0.0
            ranked.append(
                RankedMatch(
                    match=match,
                    score=score,
                    skills_score=skills_score,
                    interest_fit=interest,
                    zone_fit=fit,
                    weights=active,
                )
            )
        ranked.sort(key=lambda r: (-r.score, -r.skills_score, r.occupation.title))
        return ranked[:top_k]


def why_sentences(ranked: RankedMatch) -> list[dict[str, object]]:
    """Structured “why this fits” rows for the UI (template key + data)."""
    rows: list[dict[str, object]] = [
        {
            "key": "match.why_skills",
            "values": {"skills_score": round(ranked.skills_score * 100)},
            "weight": ranked.weights.get("skills", 0),
        }
    ]
    if ranked.interest_fit:
        rows.append(
            {
                "key": "match.why_interests",
                "values": {"interest_score": round(ranked.interest_fit * 100)},
                "weight": ranked.weights.get("interests", 0),
            }
        )
    rows.append(
        {
            "key": "match.why_zone",
            "values": {"zone_score": round(ranked.zone_fit * 100)},
            "weight": ranked.weights.get("job_zone", 0),
        }
    )
    return rows


def get_matcher_v2(weights: dict[str, float] | None = None) -> MatcherV2:
    """Build a matcher v2 (the base matcher's parsed catalog is cached)."""
    return MatcherV2(get_matcher(), weights)
