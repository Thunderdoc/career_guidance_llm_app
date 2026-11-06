"""Phase 7 faithfulness checker: planted ungrounded skills must be caught."""

from career_guidance.faithfulness import (
    filter_grounded_skills,
    skill_violations,
    text_violations,
)

ALLOWED_HAVE = {"Python", "SQL"}
ALLOWED_GAP = {"Statistics", "Excel"}


def test_skill_violations_catches_planted_skills():
    violations = skill_violations(
        ["Python", "Quantum Knitting"],
        ["Telepathy"],
        ALLOWED_HAVE,
        ALLOWED_GAP,
    )
    assert violations == {
        "matching_skills": ["Quantum Knitting"],
        "missing_skills": ["Telepathy"],
    }


def test_skill_violations_empty_when_faithful():
    assert skill_violations(["Python"], ["Excel"], ALLOWED_HAVE, ALLOWED_GAP) == {
        "matching_skills": [],
        "missing_skills": [],
    }


def test_filter_grounded_skills_drops_planted_and_falls_back_when_all_planted():
    have, gap, violations = filter_grounded_skills(
        ["Python", "Quantum Knitting"],
        ["Telepathy"],
        ALLOWED_HAVE,
        ALLOWED_GAP,
        ["Python", "SQL"],
        ["Statistics", "Excel"],
    )
    assert have == ["Python"]
    assert gap == ["Statistics", "Excel"]  # all planted -> retrieved list restored
    assert violations["missing_skills"] == ["Telepathy"]


def test_text_violations_finds_ungrounded_candidate_terms():
    allowed = {"python", "sql", "data analyst"}
    candidates = ["python", "sql", "welding", "data analyst", "plumbing"]
    text = "Your Python fits, but you should also learn welding this month."
    assert text_violations(text, allowed, candidates) == ["welding"]


def test_text_violations_clean_text_and_short_terms_ignored():
    allowed = {"python"}
    candidates = ["python", "r", "sql"]
    assert text_violations("Python is your strongest skill.", allowed, candidates) == []
