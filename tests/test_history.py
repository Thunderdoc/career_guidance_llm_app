"""Tests for the session history."""

from career_guidance.config import Settings
from career_guidance.history import GuidanceHistory
from career_guidance.providers import MockProvider
from career_guidance.suggestions import generate_guidance


def _result():
    return generate_guidance(
        "Python, SQL and dashboards", Settings(), provider=MockProvider()
    )


def test_add_and_export():
    history = GuidanceHistory()
    history.add("Python, SQL and dashboards", _result())
    assert len(history) == 1
    assert "Software Developer" in history.to_markdown()
    assert "Software Developer" in history.to_json()


def test_excerpt_is_truncated():
    history = GuidanceHistory()
    entry = history.add("x" * 500, _result())
    assert len(entry.input_excerpt) <= 120
    assert entry.input_excerpt.endswith("...")


def test_clear():
    history = GuidanceHistory()
    history.add("Python skills", _result())
    history.clear()
    assert len(history) == 0
