"""Core career guidance orchestration.

This module is UI-agnostic so it can be unit-tested and reused by any
front end (Streamlit, CLI, API). Recommendations are produced by pluggable
providers (see ``career_guidance.providers``), with automatic fallback
to offline demo results when the AI provider fails.
"""

import logging
from dataclasses import dataclass, field

from career_guidance.config import Settings, load_settings
from career_guidance.models import (
    CareerRecommendation,
    CareerSuggestion,
    InvalidInputError,
    ProviderError,
)
from career_guidance.profile import CareerProfile
from career_guidance.providers import (
    MockProvider,
    SuggestionProvider,
    get_offline_provider,
    get_provider,
)

logger = logging.getLogger("career_guidance.suggestions")

__all__ = [
    "CareerSuggestion",
    "GuidanceResult",
    "InvalidInputError",
    "RecommendationResult",
    "format_recommendations_markdown",
    "format_suggestions_markdown",
    "generate_guidance",
    "generate_recommendations",
    "get_career_suggestions",
    "validate_input",
]


@dataclass(frozen=True)
class GuidanceResult:
    """Outcome of a simple guidance run, including provenance metadata."""

    suggestions: list[CareerSuggestion]
    provider_name: str
    is_demo: bool
    used_fallback: bool


@dataclass(frozen=True)
class RecommendationResult:
    """Outcome of a structured recommendation run."""

    recommendations: list[CareerRecommendation]
    provider_name: str
    is_demo: bool
    used_fallback: bool
    priority_skills: list[str] = field(default_factory=list)


def validate_input(raw_input: str, settings: Settings | None = None) -> str:
    """Validate and normalize user input.

    Raises:
        InvalidInputError: If the input is empty, too short, or too long.
    """
    settings = settings or load_settings()
    text = (raw_input or "").strip()

    if not text:
        raise InvalidInputError("Input must not be empty.")
    if len(text) < settings.min_input_length:
        raise InvalidInputError(
            f"Input must be at least {settings.min_input_length} characters long."
        )
    if len(text) > settings.max_input_length:
        raise InvalidInputError(f"Input must not exceed {settings.max_input_length} characters.")
    return text


def generate_guidance(
    raw_input: str,
    settings: Settings | None = None,
    provider: SuggestionProvider | None = None,
) -> GuidanceResult:
    """Generate simple career suggestions with automatic fallback.

    Raises:
        InvalidInputError: If the input fails validation.
    """
    settings = settings or load_settings()
    text = validate_input(raw_input, settings)
    provider = provider or get_provider(settings)

    logger.info("Generating suggestions via %s for input of length %d", provider.name, len(text))
    try:
        suggestions = provider.suggest(text)
        return GuidanceResult(suggestions, provider.name, provider.is_demo, False)
    except ProviderError:
        logger.exception("Provider %s failed; falling back to offline suggestions", provider.name)
        fallback = MockProvider()
        return GuidanceResult(fallback.suggest(text), fallback.name, True, True)


def generate_recommendations(
    profile: CareerProfile,
    settings: Settings | None = None,
    provider: SuggestionProvider | None = None,
) -> RecommendationResult:
    """Generate structured career recommendations with automatic fallback.

    Raises:
        InvalidInputError: If the profile fails validation.
    """
    settings = settings or load_settings()
    profile.validate(settings.min_input_length, settings.max_input_length)
    provider = provider or get_provider(settings)

    logger.info("Generating recommendations via %s", provider.name)
    try:
        recommendations = provider.recommend(profile)
        return RecommendationResult(
            recommendations,
            provider.name,
            provider.is_demo,
            False,
            _priority_skills(recommendations),
        )
    except ProviderError:
        logger.exception("Provider %s failed; falling back to offline matching", provider.name)
        fallback = get_offline_provider()
        recommendations = fallback.recommend(profile)
        return RecommendationResult(
            recommendations, fallback.name, True, True, _priority_skills(recommendations)
        )


def _priority_skills(recommendations: list[CareerRecommendation], limit: int = 3) -> list[str]:
    """Rank skill gaps by how many top recommendations need them."""
    from collections import Counter

    scores: Counter[str] = Counter()
    for rank, rec in enumerate(recommendations):
        for pos, skill in enumerate(rec.missing_skills[:6]):
            scores[skill] += (1.0 / (rank + 1)) * (1.0 - 0.1 * pos)
    return [skill for skill, _ in scores.most_common(limit)]


def get_career_suggestions(
    raw_input: str, settings: Settings | None = None
) -> list[CareerSuggestion]:
    """Backwards-compatible helper returning only the suggestion list."""
    return generate_guidance(raw_input, settings).suggestions


def format_suggestions_markdown(suggestions: list[CareerSuggestion]) -> str:
    """Render simple suggestions as a numbered Markdown list."""
    return "\n".join(
        f"{index}. **{item.title}** – {item.rationale}"
        for index, item in enumerate(suggestions, start=1)
    )


def format_recommendations_markdown(
    recommendations: list[CareerRecommendation],
) -> str:
    """Render structured recommendations as a Markdown document."""
    blocks = []
    for index, rec in enumerate(recommendations, start=1):
        lines = [
            f"## {index}. {rec.title} ({rec.suitability})",
            "",
            rec.match_reason,
            "",
            "**Matching skills:** " + (", ".join(rec.matching_skills) or "none detected"),
            "**Skills to learn:** " + (", ".join(rec.missing_skills) or "none"),
            "",
            "**Learning path:**",
        ]
        lines += [f"{i}. {step}" for i, step in enumerate(rec.learning_path, start=1)]
        lines += ["", "**Next steps:**"]
        lines += [f"- {step}" for step in rec.next_steps]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
