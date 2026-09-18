"""Tests for suggestion providers."""

import pytest

from career_guidance.config import Settings
from career_guidance.models import ProviderError
from career_guidance.providers import (
    MockProvider,
    OpenAIProvider,
    _parse_suggestions,
    get_provider,
)


def test_mock_provider_returns_five_suggestions():
    assert len(MockProvider().suggest("Python")) == 5


def test_get_provider_defaults_to_offline_mode():
    provider = get_provider(Settings())
    assert provider.is_demo is True


def test_get_provider_selects_ai_when_key_is_set():
    provider = get_provider(Settings(openai_api_key="test-key"))
    assert provider.is_demo is False
    assert "OpenAI" in provider.name


def test_legacy_openai_provider_still_constructs():
    assert OpenAIProvider(Settings(openai_api_key="k")).is_demo is False


def test_parse_suggestions_accepts_valid_json():
    payload = '[{"title": "Dev", "rationale": "Codes well."}]'
    suggestions = _parse_suggestions(payload)
    assert suggestions[0].title == "Dev"


def test_parse_suggestions_rejects_invalid_payloads():
    with pytest.raises(ProviderError):
        _parse_suggestions("not json")
    with pytest.raises(ProviderError):
        _parse_suggestions("[]")
