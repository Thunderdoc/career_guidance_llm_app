"""Tests for the taxonomy engine: catalog, normalisation, matching, grounding."""

import json

import pytest

from career_guidance.config import Settings
from career_guidance.engine import GroundedOpenAIProvider, TaxonomyProvider, build_recommendation
from career_guidance.learning import resources_for
from career_guidance.market import StaticMarketAdapter
from career_guidance.matching import get_matcher, prioritise_gaps
from career_guidance.models import CareerRecommendation, ProviderError
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.suggestions import generate_recommendations
from career_guidance.taxonomy import extract_skills, load_taxonomy, normalize_skill


@pytest.fixture(scope="module")
def matcher():
    return get_matcher()


def test_catalog_is_large_and_well_formed():
    tax = load_taxonomy()
    assert len(tax) >= 300
    occ = tax.get("15-1134.00")
    assert occ is not None and occ.title == "Web Developers"
    assert occ.skills and occ.technology and occ.holland_code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("JS", "javascript"),
        ("Python 3", "python"),
        ("MS Excel", "excel"),
        ("Tally ERP", "accounting"),
    ],
)
def test_normalize_skill_maps_synonyms(raw, expected):
    assert normalize_skill(raw) == expected


def test_extract_skills_from_free_text_and_sentences():
    skills = extract_skills("JS, React and Git; built dashboards with SQL")
    assert {"javascript", "react", "git"} <= set(skills)
    assert "sql" in extract_skills(
        "I have used sql daily for reporting on large datasets in my job"
    )


@pytest.mark.parametrize(
    ("skills", "goal", "expected_title"),
    [
        ("JS, React, HTML, CSS, Git", "frontend developer", "Web Developers"),
        ("Tally, accounting, Excel, GST filing", "accountant", "Accountants"),
        ("AutoCAD, SolidWorks, mechanical design", "", "Mechanical Drafters"),
        ("photoshop, illustrator, figma, ui, ux", "designer", "Graphic Designers"),
    ],
)
def test_matcher_returns_relevant_top_results(matcher, skills, goal, expected_title):
    profile = CareerProfile(skills=skills, goals=goal, experience_level=EXPERIENCE_LEVELS[0])
    titles = [m.occupation.title for m in matcher.rank(profile)]
    assert expected_title in titles


def test_matcher_explains_have_and_gap(matcher):
    profile = CareerProfile(skills="Python, SQL, statistics", goals="data")
    top = matcher.rank(profile)[0]
    assert top.matching_skills and top.missing_skills
    assert not set(top.matching_skills) & set(top.missing_skills)


def test_gap_prioritisation_returns_three(matcher):
    matches = matcher.rank(CareerProfile(skills="Python, SQL"))
    assert len(prioritise_gaps(matches)) == 3


def test_taxonomy_provider_builds_full_recommendations():
    recs = TaxonomyProvider().recommend(
        CareerProfile(skills="Python, SQL, pandas", goals="data analyst")
    )
    assert len(recs) == 5
    rec = recs[0]
    assert rec.career_id and rec.market is not None and rec.market.salary_p50
    assert rec.learning_path and rec.next_steps and rec.provenance["ids"] == [rec.career_id]


def test_generate_recommendations_uses_taxonomy_and_priorities():
    result = generate_recommendations(CareerProfile(skills="JS, React, CSS"), Settings())
    assert result.is_demo and "O*NET" in result.provider_name
    assert len(result.priority_skills) == 3


def test_recommendation_roundtrip_with_nested_dataclasses():
    from dataclasses import asdict

    rec = TaxonomyProvider().recommend(CareerProfile(skills="nursing, first aid"))[0]
    restored = CareerRecommendation.from_dict(json.loads(json.dumps(asdict(rec))))
    assert restored.market == rec.market and restored.resources == rec.resources


def test_from_dict_tolerates_legacy_rows():
    legacy = {"title": "X", "match_reason": "y", "suitability": "beginner"}
    assert CareerRecommendation.from_dict(legacy).career_id == ""


def test_grounded_provider_filters_invented_skills(matcher):
    provider = GroundedOpenAIProvider(Settings(openai_api_key="k"), matcher)
    profile = CareerProfile(skills="Python, SQL")
    matches = matcher.rank(profile)
    base = {m.occupation.id: build_recommendation(m, profile, matcher) for m in matches}
    first = next(iter(base.values()))
    payload = json.dumps(
        [
            {
                "career_id": first.career_id,
                "title": first.title,
                "match_reason": "Great fit.",
                "suitability": "advanced",
                "matching_skills": [first.matching_skills[0], "Quantum Knitting"],
                "missing_skills": ["Telepathy"],
                "learning_path": ["a", "b"],
                "next_steps": ["c"],
            }
        ]
    )
    merged = provider._merge(payload, base)
    assert merged[0].matching_skills == [first.matching_skills[0]]
    assert merged[0].missing_skills == first.missing_skills  # invented list rejected -> fallback
    assert merged[0].suitability == "advanced" and merged[0].learning_path == ["a", "b"]
    assert len(merged) == len(base)  # dropped occupations appended


def test_grounded_provider_rejects_garbage():
    with pytest.raises(ProviderError):
        GroundedOpenAIProvider._merge("not json", {})


def test_static_market_adapter_scales_with_zone():
    tax = load_taxonomy()
    adapter = StaticMarketAdapter()
    low = adapter.snapshot(next(o for o in tax.occupations if o.job_zone == 1))
    high = adapter.snapshot(next(o for o in tax.occupations if o.job_zone == 5))
    assert low.salary_p50 < high.salary_p50 and low.currency == "INR"


def test_learning_resources_lookup_and_fallback():
    assert resources_for("SQL")[0].url.startswith("https://")
    assert resources_for("Systems Evaluation")  # alias to systems analysis
    assert resources_for("Completely Unknown Thing") == []
