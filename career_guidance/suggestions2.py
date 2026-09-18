"""Matcher-v2 recommendation pipeline used by ``POST /api/v1/recommend``.

No LLM is involved: every sentence comes from the curated templates in
``data/templates/explanations.*.yaml`` and every number from the bundled O*NET
catalog, the curated market seeds or the user's own ratings.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from career_guidance.explanations import get_explanations
from career_guidance.learning import resources_for as default_resources
from career_guidance.market_seed import build_adapter
from career_guidance.matching import Matcher
from career_guidance.matching2 import MatcherV2, RankedMatch, why_sentences
from career_guidance.models import CareerRecommendation, MarketSnapshot
from career_guidance.profile import CareerProfile
from career_guidance.synonyms import SynonymStore
from career_guidance.tasks import derive_tasks
from career_guidance.taxonomy import load_taxonomy

SUITABILITY_BY_LEVEL = {
    "Student / intern": "beginner",
    "Fresher (0–2 years)": "beginner",
    "Mid-level (2–5 years)": "intermediate",
    "Senior (5–10 years)": "advanced",
    "Lead / manager (10+ years)": "advanced",
}


def market_payload(adapter, occupation, country: str = "in") -> dict:
    """MarketSnapshot → JSON with the labels the UI shows next to numbers."""
    snapshot: MarketSnapshot = adapter.snapshot(occupation, country)
    payload = asdict(snapshot)
    payload["trend_label"] = {
        "up": "rising demand",
        "flat": "stable demand",
        "down": "declining demand",
    }.get(snapshot.trend, "trend unknown")
    payload["remote_friendly"] = adapter.seed.remote_friendly(occupation)
    payload["demand_label"] = adapter.seed.demand_label(occupation)
    return payload


def recommend_v2(
    profile: CareerProfile,
    *,
    weights: dict[str, float] | None = None,
    interests: dict[str, float] | None = None,
    locale: str = "en",
    top_k: int = 5,
    country: str = "in",
    normalizer: SynonymStore | None = None,
    market=None,
    resource_lookup=default_resources,
    explanations=None,
    taxonomy=None,
    db_path: str | Path | None = None,
) -> dict:
    """Rank careers with matcher v2 and return an explainable payload."""
    explanations = explanations or get_explanations()
    market = market or build_adapter()
    taxonomy = taxonomy or load_taxonomy()
    normalizer = normalizer or (SynonymStore(db_path) if db_path else None)

    skills_text = " ".join(filter(None, [profile.skills, profile.resume_text]))
    if normalizer is not None:
        resolved = normalizer.resolve(skills_text)
        detected = list(resolved.matched)
        unmatched = list(resolved.unmatched)
        normalizer.log_unmatched(unmatched)
    else:
        from career_guidance.taxonomy import extract_skills

        detected = extract_skills(skills_text)
        unmatched = []

    base = Matcher(taxonomy)
    matcher = MatcherV2(base, weights)
    ranked = matcher.rank(profile, top_k=top_k, interests=interests)
    active = matcher.active_weights(bool(detected or profile.goals), bool(interests))

    recommendations: list[dict] = []
    for position, match in enumerate(ranked):
        recommendations.append(
            _to_recommendation(
                match,
                profile,
                locale,
                country,
                market,
                explanations,
                resource_lookup,
                detected,
                position,
            )
        )

    priority = _priority_skills(ranked)
    return {
        "provider": "matcher-v2",
        "is_demo": False,
        "used_fallback": False,
        "priority_skills": priority,
        "detected_skills": detected,
        "unmatched_skills": unmatched,
        "weights": matcher.weights,
        "active_weights": active,
        "recommendations": recommendations,
        "source": explanations.source(),
    }


def _to_recommendation(
    ranked: RankedMatch,
    profile: CareerProfile,
    locale: str,
    country: str,
    market,
    explanations,
    resource_lookup,
    detected: list[str],
    position: int,
) -> dict:
    occupation = ranked.occupation
    match = ranked.match
    matching = match.matching_skills
    missing = match.missing_skills
    strongest = matching[0] if matching else (detected[0] if detected else "")
    gap = missing[0] if missing else ""

    def render(key: str, **values) -> str:
        return explanations.render(key, locale=locale, **values)

    why = [
        render(
            "match.headline",
            matched_count=len(matching),
            total_skills=len(matching) + len(missing),
            title=occupation.title,
        )
    ]
    if strongest:
        why.append(render("match.strongest", strongest=strongest))
    if gap:
        why.append(render("match.missing", missing_count=len(missing), gap=gap))
    interest_pct = round(ranked.interest_fit * 100)
    if ranked.interest_fit:
        key = "match.interests" if ranked.interest_fit >= 0.55 else "match.interests_weak"
        why.append(
            render(
                key,
                interest_top=_top_interest(occupation),
                interest_pct=interest_pct,
            )
        )
    why.append(
        render(
            "match.jobzone",
            job_zone=occupation.job_zone,
            job_zone_label=_zone_label(occupation.job_zone),
            target_zone=f"{_zone_target(profile):.1f}",
        )
    )

    snapshot = market_payload(market, occupation, country)
    if snapshot.get("salary_p50"):
        why.append(
            render(
                "match.salary",
                salary_band=market.seed.band(occupation, country),
                currency=snapshot.get("currency", "INR"),
                source=snapshot.get("source", ""),
            )
        )
    why.append(
        render(
            "match.demand",
            demand=market.seed.demand_label(occupation),
            source=market.seed.label,
        )
    )

    resources = [
        asdict(r) for s in (missing or occupation.skills[:2])[:4] for r in resource_lookup(s, 1)
    ][:6]  # noqa: E501
    if resources:
        why.append(
            render(
                "match.resources", resource_count=len(resources), gap=gap or occupation.skills[0]
            )
        )  # noqa: E501

    learning_path = _learning_path(occupation, missing)
    next_steps = [
        f"Rate yourself on the {min(6, max(3, len(missing)))} core skills for {occupation.title}",
        f"Open the week-by-week roadmap for {occupation.title}",
        "Save the plan and mark items off as you finish them",
    ]

    suitability = SUITABILITY_BY_LEVEL.get(profile.experience_level, "intermediate")
    if position == 0 and missing:
        next_steps.insert(0, f"Start with {gap}: it is the highest-importance gap for this role")

    recommendation = CareerRecommendation(
        title=occupation.title,
        match_reason=why[0],
        suitability=suitability,
        matching_skills=matching,
        missing_skills=missing,
        learning_path=learning_path,
        next_steps=next_steps,
        career_id=occupation.id,
        match_score=ranked.score,
        description=(occupation.description or "")[:600],
        job_zone=occupation.job_zone,
        transition_path=[occupation.title],
        market=MarketSnapshot(**{k: snapshot.get(k) for k in MarketSnapshot.__dataclass_fields__}),
        resources=[
            _resource_for(r, skill)
            for skill in (missing or occupation.skills[:2])[:4]
            for r in resource_lookup(skill, 1)
        ][:6],
        provenance={
            "ids": [occupation.id],
            "why": why,
            "score_parts": {
                "skills": round(ranked.skills_score, 4),
                "interests": round(ranked.interest_fit, 4),
                "job_zone": round(ranked.zone_fit, 4),
            },
            "weights": ranked.weights,
            "why_rows": why_sentences(ranked),
            "tasks": derive_tasks(occupation, limit=4),
            "market": snapshot,
            "sources": [
                explanations.source(),
                market.seed.label,
                "Source: O*NET occupation catalog bundled with the app",
            ],
        },
    )
    payload = asdict(recommendation)
    payload["match_percent"] = ranked.match_percent
    payload["readiness"] = round(ranked.skills_score * 100, 1)
    payload["demand"] = market.seed.demand_label(occupation)
    payload["why"] = why
    payload["score_parts"] = payload["provenance"]["score_parts"]
    payload["template_source"] = explanations.source()
    return payload


def _resource_for(entry, skill: str):
    from career_guidance.models import LearningResource

    if isinstance(entry, LearningResource):
        return entry
    return LearningResource(
        skill=skill,
        title=str(entry.get("title", "")),
        url=str(entry.get("url", "")),
        provider=str(entry.get("provider", "")),
        free=bool(entry.get("free", True)),
    )


def _learning_path(occupation, missing: list[str]) -> list[str]:
    """Ordered learning path: missing skills first, then the role's own list."""
    path = list(dict.fromkeys([*missing[:6], *occupation.skills[:6]]))
    return path[:6]


def _top_interest(occupation) -> str:
    from career_guidance.riasec import DIMENSION_NAMES

    if not occupation.interests:
        return "—"
    top = max(occupation.interests, key=lambda k: occupation.interests[k])
    return DIMENSION_NAMES.get(top.upper(), top)


def _zone_label(zone: int) -> str:
    from career_guidance.matching2 import ZONE_LABELS

    return ZONE_LABELS.get(int(zone), "medium preparation needed")


def _zone_target(profile: CareerProfile) -> float:
    from career_guidance.matching2 import education_zone

    return education_zone(profile.education, profile.experience_level)


def _priority_skills(ranked: list[RankedMatch], limit: int = 3) -> list[str]:
    seen: list[str] = []
    for match in ranked[:3]:
        for skill in match.match.missing_skills:
            if skill not in seen:
                seen.append(skill)
    return seen[:limit]
