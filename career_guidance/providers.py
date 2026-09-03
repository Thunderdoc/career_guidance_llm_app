"""Suggestion providers: pluggable backends for career guidance.

Includes an offline demo provider and an OpenAI-backed provider. The
active provider is chosen from configuration; callers fall back to demo
mode when no API key is configured or the external service fails.
"""

import json
import logging
from abc import ABC, abstractmethod

from career_guidance.config import Settings
from career_guidance.models import CareerSuggestion, ProviderError

logger = logging.getLogger("career_guidance.providers")

_SYSTEM_PROMPT = (
    "You are an experienced career counselor. Given a person's skills, "
    "resume summary, or interests, respond ONLY with a JSON array of "
    'exactly 5 objects, each with "title" and "rationale" string fields, '
    "recommending suitable career paths tailored to the person."
)


class SuggestionProvider(ABC):
    """Interface every suggestion backend must implement."""

    name: str = "base"
    is_demo: bool = False

    @abstractmethod
    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        """Return career suggestions for the given profile text."""


class MockProvider(SuggestionProvider):
    """Offline provider returning curated suggestions (demo mode)."""

    name = "Curated (offline demo)"
    is_demo = True

    _SUGGESTIONS: tuple[CareerSuggestion, ...] = (
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

    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        return list(self._SUGGESTIONS)


class OpenAIProvider(SuggestionProvider):
    """Provider backed by the OpenAI API."""

    name = "OpenAI"
    is_demo = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def suggest(self, profile_text: str) -> list[CareerSuggestion]:
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - env specific
            raise ProviderError("The 'openai' package is not installed.") from error

        try:
            client = OpenAI(
                api_key=self._settings.openai_api_key,
                timeout=self._settings.openai_timeout_seconds,
            )
            response = client.chat.completions.create(
                model=self._settings.openai_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": profile_text},
                ],
            )
            payload = response.choices[0].message.content or ""
        except Exception as error:
            raise ProviderError(f"OpenAI request failed: {error}") from error
        return _parse_suggestions(payload)


def _parse_suggestions(payload: str) -> list[CareerSuggestion]:
    """Parse a JSON array of suggestions from a model response."""
    cleaned = payload.strip()
    if cleaned.startswith("```"):
        start, end = cleaned.find("["), cleaned.rfind("]")
        cleaned = cleaned[start : end + 1] if start != -1 and end != -1 else cleaned
    try:
        data = json.loads(cleaned)
        suggestions = [
            CareerSuggestion(title=str(item["title"]), rationale=str(item["rationale"]))
            for item in data
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ProviderError("Could not parse the AI response.") from error
    if not suggestions:
        raise ProviderError("The AI response contained no suggestions.")
    return suggestions


def get_provider(settings: Settings) -> SuggestionProvider:
    """Select the provider based on configuration."""
    if settings.openai_api_key:
        return OpenAIProvider(settings)
    logger.info("No OPENAI_API_KEY configured; using offline demo provider")
    return MockProvider()
