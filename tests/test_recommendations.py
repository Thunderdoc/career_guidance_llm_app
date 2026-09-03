"""Tests for structured recommendations and fallback behavior."""

import pytest

from career_guidance.config import Settings
from career_guidance.models import ProviderError
from career_guidance.profile import CareerProfile
from career_guidance.providers import MockProvider, _parse_recommendations
from career_guidance.suggestions import generate_recommendations

SETTINGS = Settings()


def test_mock_recommendations_are_structured():
    profile = CareerProfile(skills="Python, SQL, statistics and data visualization")
    recommendations = MockProvider().recommend(profile)
    assert len(recommendations) == 5
    top = recommendations[0]
    assert top.title and top.match_reason
    assert top.learning_path and top.next_steps
    assert top.suitability in {"beginner", "intermediate", "advanced"}


def test_mock_recommendations_detect_matching_skills():
    profile = CareerProfile(skills="Python, SQL and statistics")
    recommendations = MockProvider().recommend(profile)
    assert any("python" in rec.matching_skills for rec in recommendations)


def test_suitability_follows_experience_level():
    profile = CareerProfile(skills="Python", experience_level="Senior (5+ years)")
    recommendations = MockProvider().recommend(profile)
    assert all(rec.suitability == "advanced" for rec in recommendations)


def test_generate_recommendations_falls_back_on_provider_error():
    class FailingProvider(MockProvider):
        name = "Failing"
        is_demo = False

        def recommend(self, profile):
            raise ProviderError("boom")

    result = generate_recommendations(
        CareerProfile(skills="Python and SQL"), SETTINGS, provider=FailingProvider()
    )
    assert result.used_fallback is True
    assert result.is_demo is True
    assert len(result.recommendations) == 5


def test_parse_recommendations_accepts_valid_json():
    payload = (
        '[{"title": "Dev", "match_reason": "Fits well", "suitability": "advanced",'
        ' "matching_skills": ["python"], "missing_skills": ["go"],'
        ' "learning_path": ["learn go"], "next_steps": ["build a project"]}]'
    )
    recommendations = _parse_recommendations(payload)
    assert recommendations[0].suitability == "advanced"
    assert recommendations[0].missing_skills == ["go"]


def test_parse_recommendations_normalizes_unknown_suitability():
    payload = (
        '[{"title": "Dev", "match_reason": "r", "suitability": "expert",'
        ' "matching_skills": [], "missing_skills": [],'
        ' "learning_path": [], "next_steps": []}]'
    )
    assert _parse_recommendations(payload)[0].suitability == "beginner"


def test_parse_recommendations_rejects_invalid_payloads():
    with pytest.raises(ProviderError):
        _parse_recommendations("not json")
    with pytest.raises(ProviderError):
        _parse_recommendations("[]")
