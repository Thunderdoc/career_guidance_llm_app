"""Tests for guidance orchestration and fallback behavior."""

from career_guidance.config import Settings
from career_guidance.models import CareerSuggestion, ProviderError
from career_guidance.providers import SuggestionProvider
from career_guidance.suggestions import generate_guidance

SETTINGS = Settings()


class FailingProvider(SuggestionProvider):
    name = "Failing"
    is_demo = False

    def suggest(self, profile_text):
        raise ProviderError("boom")


class StaticProvider(SuggestionProvider):
    name = "Static"
    is_demo = False

    def suggest(self, profile_text):
        return [CareerSuggestion(title="Dev", rationale="Codes well.")]


def test_generate_guidance_uses_given_provider():
    result = generate_guidance("Python and SQL", SETTINGS, provider=StaticProvider())
    assert result.provider_name == "Static"
    assert result.used_fallback is False
    assert len(result.suggestions) == 1


def test_generate_guidance_falls_back_when_provider_fails():
    result = generate_guidance("Python and SQL", SETTINGS, provider=FailingProvider())
    assert result.used_fallback is True
    assert result.is_demo is True
    assert len(result.suggestions) == 5
