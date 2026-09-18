"""Taxonomy-grounded recommendation engine.

``TaxonomyProvider`` is the offline engine (974 O*NET occupations, semantic
matching). ``GroundedOpenAIProvider`` retrieves the same top candidates and
asks the LLM only to *explain and plan* around them (RAG), so every career
and skill it returns exists in the taxonomy — no invented skills.
"""

from __future__ import annotations

import json
import logging

from career_guidance.config import Settings
from career_guidance.learning import resources_for_gaps
from career_guidance.market import get_market_adapter
from career_guidance.matching import (
    Match,
    Matcher,
    get_matcher,
    prioritise_gaps,
    suitability_for,
    transition_path,
)
from career_guidance.models import CareerRecommendation, CareerSuggestion, ProviderError
from career_guidance.profile import CareerProfile
from career_guidance.providers import SuggestionProvider, _strip_code_fence

logger = logging.getLogger("career_guidance.engine")

_ZONE_LABEL = {
    1: "little or no preparation",
    2: "some preparation (short training)",
    3: "medium preparation (diploma / vocational or associate level)",
    4: "considerable preparation (bachelor's degree)",
    5: "extensive preparation (master's or higher)",
}


def _learning_path(match: Match, level: str) -> list[str]:
    occ = match.occupation
    gaps = match.missing_skills
    core = [g for g in gaps if g in occ.skills or g in occ.knowledge][:2]
    tools = [g for g in gaps if g not in core][:2]
    steps: list[str] = []
    if core:
        steps.append(f"Build the core foundation: {' and '.join(core)}")
    if tools:
        steps.append(f"Get hands-on with the tools employers list: {', '.join(tools)}")
    steps.append(f"Complete one portfolio project that mirrors real {occ.title.split(',')[0]} work")
    if occ.job_zone >= 4 and "student" in level.lower():
        steps.append(
            "Plan the qualification path — this role typically expects a bachelor's degree"
        )
    steps.append("Apply for internships / entry roles and iterate on feedback")
    return steps


def _next_steps(match: Match) -> list[str]:
    occ = match.occupation
    first_gap = match.missing_skills[0] if match.missing_skills else None
    steps = []
    if first_gap:
        steps.append(f"This week: start a free course on {first_gap} (see resources)")
    if occ.hot_technology:
        steps.append(f"Install and try {occ.hot_technology[0]} on a small task")
    steps.append(
        f"Read 5 job posts for '{occ.alt_titles[0] if occ.alt_titles else occ.title}' and list repeated requirements"  # noqa: E501
    )
    steps.append("Talk to one person doing this job (LinkedIn / alumni) about a typical week")
    return steps[:4]


def _reason(match: Match, profile: CareerProfile) -> str:
    have = match.matching_skills[:3]
    occ = match.occupation
    parts = []
    if have:
        parts.append(
            f"Your {', '.join(have)} map directly onto what {occ.title.split(',')[0]}s use every day."  # noqa: E501
        )
    else:
        parts.append(f"Your interests point toward {occ.title.split(',')[0]} work.")
    parts.append(f"Typical preparation: {_ZONE_LABEL.get(occ.job_zone, 'varies')}.")
    if match.missing_skills:
        parts.append(
            f"Closing {len(match.missing_skills)} gaps — starting with {match.missing_skills[0]} — would make you competitive."  # noqa: E501
        )
    return " ".join(parts)


def build_recommendation(
    match: Match, profile: CareerProfile, matcher: Matcher, country: str = "in"
) -> CareerRecommendation:
    """Turn a scored match into a full recommendation with market + resources."""
    occ = match.occupation
    return CareerRecommendation(
        title=occ.title,
        match_reason=_reason(match, profile),
        suitability=suitability_for(profile.experience_level),
        matching_skills=match.matching_skills,
        missing_skills=match.missing_skills,
        learning_path=_learning_path(match, profile.experience_level),
        next_steps=_next_steps(match),
        career_id=occ.id,
        match_score=round(match.score, 3),
        description=occ.description,
        job_zone=occ.job_zone,
        transition_path=transition_path(occ, matcher.taxonomy, matcher.user_terms(profile)),
        market=get_market_adapter().snapshot(occ, country),
        resources=resources_for_gaps(match.missing_skills),
        provenance={
            "taxonomy": "O*NET 24.1 (CC BY 4.0)",
            "ids": [occ.id],
            "signals": {
                "competency": round(match.competency, 2),
                "technology": round(match.technology, 2),
                "semantic": round(match.semantic, 2),
            },
        },
    )


class TaxonomyProvider(SuggestionProvider):
    """Offline provider: semantic matching over the O*NET-derived catalog."""

    name = "Offline taxonomy matching (O*NET)"
    is_demo = True

    def __init__(self, matcher: Matcher | None = None, country: str = "in") -> None:
        self._matcher = matcher or get_matcher()
        self._country = country
        self.interests: dict[str, float] | None = None

    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        profile = CareerProfile(skills=profile_text)
        return [
            CareerSuggestion(m.occupation.title, m.occupation.description[:200])
            for m in self._matcher.rank(profile)
        ]

    def recommend(self, profile: CareerProfile) -> list[CareerRecommendation]:
        matches = self._matcher.rank(profile, interests=self.interests)
        if not matches:
            raise ProviderError("No matching occupations found for this profile.")
        return [build_recommendation(m, profile, self._matcher, self._country) for m in matches]

    def priority_skills(self, profile: CareerProfile) -> list[str]:
        return prioritise_gaps(self._matcher.rank(profile, interests=self.interests))


_GROUNDED_PROMPT = """You are an expert career counsellor. You will receive a candidate profile
and a list of CANDIDATE OCCUPATIONS retrieved from the O*NET taxonomy, each with the skills
the candidate already has (matching_skills) and the skills they lack (missing_skills).

Rules:
1. Recommend exactly the given occupations, in the order you judge best for this candidate.
2. Do NOT invent skills. matching_skills and missing_skills MUST be subsets of the lists provided.
3. Write match_reason (2-3 sentences, specific to the candidate's own words), a learning_path of
   4-6 ordered milestones, and 3-4 practical next_steps (projects, certifications, actions).
4. Write in {language}.
Respond ONLY with a JSON array of objects with fields: career_id, title, match_reason, suitability
(beginner|intermediate|advanced), matching_skills, missing_skills, learning_path, next_steps."""


class GroundedOpenAIProvider(SuggestionProvider):
    """RAG provider: taxonomy retrieval + LLM explanation, validated against the context."""

    name = "OpenAI (grounded in O*NET)"
    is_demo = False

    def __init__(
        self,
        settings: Settings,
        matcher: Matcher | None = None,
        country: str = "in",
        language: str = "English",
    ) -> None:
        self._settings = settings
        self._matcher = matcher or get_matcher()
        self._country = country
        self._language = language
        self._offline = TaxonomyProvider(self._matcher, country)
        self.interests: dict[str, float] | None = None

    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        return self._offline.suggest(profile_text)

    def recommend(self, profile: CareerProfile) -> list[CareerRecommendation]:
        matches = self._matcher.rank(profile, interests=self.interests)
        if not matches:
            raise ProviderError("No matching occupations found for this profile.")
        base = {
            m.occupation.id: build_recommendation(m, profile, self._matcher, self._country)
            for m in matches
        }
        context = [
            {
                "career_id": r.career_id,
                "title": r.title,
                "description": r.description[:300],
                "matching_skills": r.matching_skills,
                "missing_skills": r.missing_skills,
            }
            for r in base.values()
        ]
        user = f"CANDIDATE PROFILE:\n{profile.to_prompt_text()}\n\nCANDIDATE OCCUPATIONS:\n{json.dumps(context, ensure_ascii=False)}"  # noqa: E501
        payload = self._complete(_GROUNDED_PROMPT.format(language=self._language), user)
        return self._merge(payload, base)

    def _complete(self, system: str, user: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover
            raise ProviderError("The 'openai' package is not installed.") from error
        try:
            client = OpenAI(
                api_key=self._settings.openai_api_key, timeout=self._settings.openai_timeout_seconds
            )
            response = client.chat.completions.create(
                model=self._settings.openai_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.4,
            )
            return response.choices[0].message.content or ""
        except Exception as error:
            raise ProviderError(f"OpenAI request failed: {error}") from error

    @staticmethod
    def _merge(payload: str, base: dict[str, CareerRecommendation]) -> list[CareerRecommendation]:
        try:
            items = json.loads(_strip_code_fence(payload))
        except json.JSONDecodeError as error:
            raise ProviderError("Could not parse the AI recommendation response.") from error
        out: list[CareerRecommendation] = []
        used: set[str] = set()
        for item in items if isinstance(items, list) else []:
            cid = str(item.get("career_id", ""))
            rec = base.get(cid)
            if rec is None or cid in used:
                continue
            used.add(cid)
            allowed_have, allowed_gap = set(rec.matching_skills), set(rec.missing_skills)
            have = [
                s for s in map(str, item.get("matching_skills", [])) if s in allowed_have
            ] or rec.matching_skills
            gap = [
                s for s in map(str, item.get("missing_skills", [])) if s in allowed_gap
            ] or rec.missing_skills
            suit = str(item.get("suitability", rec.suitability)).lower()
            out.append(
                CareerRecommendation(
                    title=rec.title,
                    match_reason=str(item.get("match_reason") or rec.match_reason),
                    suitability=suit
                    if suit in {"beginner", "intermediate", "advanced"}
                    else rec.suitability,
                    matching_skills=have,
                    missing_skills=gap,
                    learning_path=[str(s) for s in item.get("learning_path", [])]
                    or rec.learning_path,
                    next_steps=[str(s) for s in item.get("next_steps", [])] or rec.next_steps,
                    career_id=rec.career_id,
                    match_score=rec.match_score,
                    description=rec.description,
                    job_zone=rec.job_zone,
                    transition_path=rec.transition_path,
                    market=rec.market,
                    resources=rec.resources,
                    provenance={**rec.provenance, "llm": "grounded"},
                )
            )
        # Anything the model dropped is appended in original order.
        for cid, rec in base.items():
            if cid not in used:
                out.append(rec)
        if not out:
            raise ProviderError("The AI response contained no usable recommendations.")
        return out
