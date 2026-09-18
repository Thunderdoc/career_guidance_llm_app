"""Tests for the career profile model."""

import pytest

from career_guidance.models import InvalidInputError
from career_guidance.profile import CareerProfile


def test_requires_skills_or_resume():
    with pytest.raises(InvalidInputError):
        CareerProfile(skills="   ").validate()


def test_resume_alone_is_sufficient():
    CareerProfile(skills="", resume_text="Experienced Python developer").validate()


def test_too_long_profile_raises():
    with pytest.raises(InvalidInputError):
        CareerProfile(skills="x" * 20001).validate()


def test_prompt_text_includes_optional_fields():
    profile = CareerProfile(skills="Python", interests="AI", goals="Become an ML engineer")
    text = profile.to_prompt_text()
    assert "Skills: Python" in text
    assert "Interests: AI" in text
    assert "Career goals: Become an ML engineer" in text


def test_to_dict_truncates_resume():
    profile = CareerProfile(skills="Python", resume_text="x" * 5000)
    assert len(profile.to_dict()["resume_text"]) == 1000
