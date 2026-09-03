"""Unit tests for the career suggestion core logic."""

import pytest

from career_guidance.config import Settings
from career_guidance.suggestions import (
    CareerSuggestion,
    InvalidInputError,
    format_suggestions_markdown,
    get_career_suggestions,
    validate_input,
)

SETTINGS = Settings()


class TestValidateInput:
    def test_valid_input_is_stripped(self):
        assert validate_input("  Python, SQL  ", SETTINGS) == "Python, SQL"

    def test_empty_input_raises(self):
        with pytest.raises(InvalidInputError):
            validate_input("", SETTINGS)

    def test_whitespace_only_input_raises(self):
        with pytest.raises(InvalidInputError):
            validate_input("   ", SETTINGS)

    def test_too_short_input_raises(self):
        with pytest.raises(InvalidInputError):
            validate_input("ab", SETTINGS)

    def test_too_long_input_raises(self):
        with pytest.raises(InvalidInputError):
            validate_input("x" * (SETTINGS.max_input_length + 1), SETTINGS)


class TestGetCareerSuggestions:
    def test_returns_five_suggestions(self):
        suggestions = get_career_suggestions("Python, communication", SETTINGS)
        assert len(suggestions) == 5
        assert all(isinstance(item, CareerSuggestion) for item in suggestions)

    def test_invalid_input_propagates(self):
        with pytest.raises(InvalidInputError):
            get_career_suggestions("", SETTINGS)


class TestFormatSuggestionsMarkdown:
    def test_renders_numbered_markdown(self):
        suggestions = [
            CareerSuggestion(title="Dev", rationale="Codes well."),
            CareerSuggestion(title="Analyst", rationale="Loves data."),
        ]
        output = format_suggestions_markdown(suggestions)
        assert output.splitlines() == [
            "1. **Dev** – Codes well.",
            "2. **Analyst** – Loves data.",
        ]
