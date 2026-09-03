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


def test_get_provider_defaults_to_demo_mode():
    assert isinstance(get_provider(Settings()), MockProvider)


def test_get_provider_selects_openai_when_key_is_set():
    provider = get_provider(Settings(openai_api_key="test-key"))
    assert isinstance(provider, OpenAIProvider)


def test_parse_suggestions_accepts_valid_json():
    payload = '[{"title": "Dev", "rationale": "Codes well."}]'
    suggestions = _parse_suggestions(payload)
    assert suggestions[0].title == "Dev"


def test_parse_suggestions_rejects_invalid_payloads():
    with pytest.raises(ProviderError):
        _parse_suggestions("not json")
    with pytest.raises(ProviderError):
        _parse_suggestions("[]")
