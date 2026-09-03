"""Core career guidance orchestration.

This module is UI-agnostic so it can be unit-tested and reused by any
front end (Streamlit, CLI, API). Suggestions are produced by pluggable
providers (see ``career_guidance.providers``), with automatic fallback
to offline demo suggestions when the AI provider fails.
"""

import logging
from dataclasses import dataclass

from career_guidance.config import Settings, load_settings
from career_guidance.models import (
    CareerSuggestion,
    InvalidInputError,
    ProviderError,
)
from career_guidance.providers import MockProvider, SuggestionProvider, get_provider

logger = logging.getLogger("career_guidance.suggestions")

__all__ = [
    "CareerSuggestion",
    "GuidanceResult",
    "InvalidInputError",
    "format_suggestions_markdown",
    "generate_guidance",
    "get_career_suggestions",
    "validate_input",
]


@dataclass(frozen=True)
class GuidanceResult:
    """Outcome of a guidance run, including provenance metadata."""

    suggestions: list[CareerSuggestion]
    provider_name: str
    is_demo: bool
    used_fallback: bool


def validate_input(raw_input: str, settings: Settings | None = None) -> str:
    """Validate and normalize user input.

    Args:
        raw_input: Free-text skills, resume summary, or interests.
        settings: Optional settings; loaded from environment if omitted.

    Returns:
        The stripped, validated input text.

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
        raise InvalidInputError(
            f"Input must not exceed {settings.max_input_length} characters."
        )
    return text


def generate_guidance(
    raw_input: str,
    settings: Settings | None = None,
    provider: SuggestionProvider | None = None,
) -> GuidanceResult:
    """Generate career guidance for the given skills/resume text.

    Falls back to the offline demo provider when the configured provider
    fails, so the user always receives usable results.

    Raises:
        InvalidInputError: If the input fails validation.
    """
    settings = settings or load_settings()
    text = validate_input(raw_input, settings)
    provider = provider or get_provider(settings)

    logger.info(
        "Generating suggestions via %s for input of length %d", provider.name, len(text)
    )
    try:
        suggestions = provider.suggest(text)
        return GuidanceResult(
            suggestions=suggestions,
            provider_name=provider.name,
            is_demo=provider.is_demo,
            used_fallback=False,
        )
    except ProviderError:
        logger.exception(
            "Provider %s failed; falling back to offline suggestions", provider.name
        )
        fallback = MockProvider()
        return GuidanceResult(
            suggestions=fallback.suggest(text),
            provider_name=fallback.name,
            is_demo=True,
            used_fallback=True,
        )


def get_career_suggestions(
    raw_input: str, settings: Settings | None = None
) -> list[CareerSuggestion]:
    """Backwards-compatible helper returning only the suggestion list."""
    return generate_guidance(raw_input, settings).suggestions


def format_suggestions_markdown(suggestions: list[CareerSuggestion]) -> str:
    """Render suggestions as a numbered Markdown list."""
    return "\n".join(
        f"{index}. **{item.title}** – {item.rationale}"
        for index, item in enumerate(suggestions, start=1)
    )
