"""Core career suggestion logic.

This module is UI-agnostic so it can be unit-tested and reused by any
front end (Streamlit, CLI, API). The current implementation returns
curated mock suggestions; an LLM-backed provider can be plugged in later
without changing the public interface.
"""

import logging
from dataclasses import dataclass

from career_guidance.config import Settings, load_settings

logger = logging.getLogger("career_guidance.suggestions")


@dataclass(frozen=True)
class CareerSuggestion:
    """A single career path recommendation."""

    title: str
    rationale: str


class InvalidInputError(ValueError):
    """Raised when the user-provided input fails validation."""


_MOCK_SUGGESTIONS: tuple[CareerSuggestion, ...] = (
    CareerSuggestion(
        title="Software Developer",
        rationale=(
            "Your programming and web development skills make you suitable "
            "for roles in full-stack or backend development."
        ),
    ),
    CareerSuggestion(
        title="Data Analyst",
        rationale=(
            "With knowledge of Python, Excel, and data visualization, you "
            "can work on data-driven decision making."
        ),
    ),
    CareerSuggestion(
        title="Technical Writer",
        rationale=(
            "Your communication and tech background fit well with "
            "documenting software, APIs, and guides."
        ),
    ),
    CareerSuggestion(
        title="QA Engineer",
        rationale=(
            "Your detail-oriented nature and coding skills are perfect for "
            "testing and quality assurance roles."
        ),
    ),
    CareerSuggestion(
        title="Product Support Specialist",
        rationale=(
            "Strong communication and tech awareness are a great match for "
            "user support and troubleshooting."
        ),
    ),
)


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


def get_career_suggestions(
    raw_input: str, settings: Settings | None = None
) -> list[CareerSuggestion]:
    """Return career suggestions for the given skills/resume text.

    Args:
        raw_input: Free-text skills, resume summary, or interests.
        settings: Optional settings; loaded from environment if omitted.

    Returns:
        A list of career suggestions.

    Raises:
        InvalidInputError: If the input fails validation.
    """
    text = validate_input(raw_input, settings)
    logger.info("Generating career suggestions for input of length %d", len(text))
    return list(_MOCK_SUGGESTIONS)


def format_suggestions_markdown(suggestions: list[CareerSuggestion]) -> str:
    """Render suggestions as a numbered Markdown list."""
    return "\n".join(
        f"{index}. **{item.title}** – {item.rationale}"
        for index, item in enumerate(suggestions, start=1)
    )
