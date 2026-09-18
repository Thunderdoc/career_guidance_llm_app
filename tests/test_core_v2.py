"""Matcher v2, skill-gap, roadmap, transitions, market seeds, interview, résumé."""

from __future__ import annotations

import json

import pytest

from career_guidance.interview import generate as generate_interview
from career_guidance.market_seed import build_adapter, load_seed
from career_guidance.matching2 import (
    DEFAULT_WEIGHTS,
    MatcherV2,
    education_zone,
    why_sentences,
    zone_fit,
)
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.resume_score import detect_sections, detect_years
from career_guidance.resume_score import score as score_resume
from career_guidance.roadmap import generate as generate_roadmap
from career_guidance.roadmap import to_ics, to_json, to_markdown
from career_guidance.skillgap import evaluate, status_for
from career_guidance.tasks import derive_tasks, education_path
from career_guidance.taxonomy import load_taxonomy
from career_guidance.transitions import delta_skills, find_path, transitions_into

TAX = load_taxonomy()


# --------------------------------------------------------------------------- #
# Matcher v2
# --------------------------------------------------------------------------- #
def test_weights_default_to_55_30_15():
    m = MatcherV2(weights=None)
    assert m.weights == {"skills": 0.55, "interests": 0.30, "job_zone": 0.15}
    assert DEFAULT_WEIGHTS["skills"] == 0.55


def test_weights_are_normalised():
    m = MatcherV2(weights={"skills": 2, "interests": 2, "job_zone": 0})
    assert m.weights == {"skills": 0.5, "interests": 0.5, "job_zone": 0.0}


def test_skills_only_ranking_is_sane_and_explainable():
    profile = CareerProfile(skills="Python, SQL, statistics, Excel", goals="data analyst")
    ranked = MatcherV2().rank(profile, top_k=5)
    assert len(ranked) == 5
    top = ranked[0]
    assert 0 < top.score <= 1
    assert top.interest_fit == 0.0  # no quiz taken yet
    assert top.match_percent > 50
    keys = [row["key"] for row in why_sentences(top)]
    assert keys[0] == "match.why_skills" and "match.why_zone" in keys
    assert all(r.weights["interests"] == 0 for r in ranked)  # weight redistributed


def test_interest_profile_changes_ranking():
    profile = CareerProfile(skills="communication, Excel", goals="")
    without = MatcherV2().rank(profile, top_k=5)
    interests = {"R": 2.0, "I": 7.0, "A": 3.0, "S": 6.0, "E": 2.0, "C": 3.0}
    with_interests = MatcherV2().rank(profile, top_k=5, interests=interests)
    assert any(r.interest_fit > 0 for r in with_interests)
    assert [r.occupation.id for r in without] != [r.occupation.id for r in with_interests]


def test_interest_only_input_returns_ranked_careers():
    profile = CareerProfile(skills="", interests="helping people learn", goals="")
    interests = {"R": 1.0, "I": 3.0, "A": 3.0, "S": 7.0, "E": 3.0, "C": 2.0}
    ranked = MatcherV2().rank(profile, top_k=5, interests=interests)
    assert len(ranked) == 5
    # With no skills given, interests + zone decide the order.
    assert all(r.interest_fit > 0 for r in ranked)
    assert all(r.weights["interests"] > 0 for r in ranked)


def test_zone_fit_and_education_zone():
    assert zone_fit(4, 4.0) == 1.0
    assert zone_fit(2, 4.0) < 1.0
    assert education_zone("B.Tech Computer Science", EXPERIENCE_LEVELS[0]) > education_zone(
        "10th pass", EXPERIENCE_LEVELS[0]
    )
    assert education_zone("", EXPERIENCE_LEVELS[3]) >= 3.5


# --------------------------------------------------------------------------- #
# Skill gap / readiness
# --------------------------------------------------------------------------- #
def test_status_thresholds():
    assert status_for(5) == "strong"
    assert status_for(4) == "strong"
    assert status_for(3) == "weak"
    assert status_for(2) == "weak"
    assert status_for(1) == "missing"
    assert status_for(0) == "missing"


def test_readiness_is_importance_weighted():
    occ = TAX.get("15-1199.08")
    ratings = {skill: 5 for skill in occ.skills[:3]}
    result = evaluate("15-1199.08", ratings)
    # Unrated skills count as missing, so readiness stays well below 100%.
    assert 0 < result.readiness_weighted < 100
    assert len(result.strong) == 3 and result.missing
    assert result.to_dict()["source"].startswith("Source: O*NET")
    assert len(result.radar()) == 8
    assert result.next_gap() is not None


def test_readiness_full_marks_reach_100():
    occ = TAX.get("15-1134.00")
    ratings = {skill: 5 for skill in [*occ.skills, *occ.knowledge]}
    result = evaluate("15-1134.00", ratings)
    assert result.readiness_weighted == 100.0


def test_readiness_unknown_career_raises():
    with pytest.raises(KeyError):
        evaluate("nope", {})


# --------------------------------------------------------------------------- #
# Roadmap
# --------------------------------------------------------------------------- #
@pytest.fixture()
def readiness():
    return evaluate("15-1199.08", {"Critical Thinking": 5, "SQL": 3, "Programming": 2})


def test_roadmap_packs_weeks_and_orders_prerequisites(readiness):
    plan = generate_roadmap(readiness, hours_per_week=6)
    assert plan.weeks >= 1
    assert plan.items and plan.items[0].week == 1
    assert plan.items[0].hours > 0
    assert plan.readiness_before == readiness.readiness_weighted
    assert plan.readiness_after > plan.readiness_before
    assert plan.readiness_after < 100  # conservative projection
    # prerequisite ordering: foundations before advanced skills
    layers = [i.week for i in plan.items]
    assert layers == sorted(layers)
    assert plan.eta and len(plan.eta) == 10


def test_roadmap_respects_more_hours_per_week(readiness):
    slow = generate_roadmap(readiness, hours_per_week=3)
    fast = generate_roadmap(readiness, hours_per_week=20)
    assert fast.weeks <= slow.weeks


def test_roadmap_exports(readiness):
    plan = generate_roadmap(readiness, hours_per_week=6)
    md = to_markdown(plan)
    assert "# Learning roadmap" in md and "- [ ]" in md
    payload = json.loads(to_json(plan))
    assert payload["items"] and payload["source"]
    ics = to_ics(plan)
    assert ics.startswith("BEGIN:VCALENDAR") and "END:VEVENT" in ics and "\r\n" in ics


# --------------------------------------------------------------------------- #
# Transition paths
# --------------------------------------------------------------------------- #
def test_delta_skills_between_related_occupations():
    source = TAX.get("15-1134.00")
    target = TAX.get("15-1131.00")
    delta, shared = delta_skills(source, target)
    assert isinstance(delta, list) and isinstance(shared, list)


def test_find_path_same_occupation_and_one_hop():
    same = find_path("15-1134.00", "15-1134.00")
    assert not same.found and same.to_dict()["note"].startswith("Source: O*NET")

    related = TAX.get("15-1134.00").related
    if related:
        path = find_path("15-1134.00", related[0])
        assert path.found and len(path.hops) == 1
        assert path.hops[0].occupation.id == related[0]


def test_find_path_respects_three_hop_limit():
    ids = [o.id for o in TAX.occupations][:400]
    found_long = None
    for start in ids[:60]:
        for end in ids[60:120]:
            path = find_path(start, end, max_hops=3)
            if not path.found:
                found_long = (start, end)
                break
        if found_long:
            break
    if found_long:  # some pair needs more than 3 hops — the note explains the cap
        path = find_path(*found_long)
        assert path.to_dict()["hops"] == 0 and "3 hops" in path.to_dict()["note"]


def test_transitions_into_lists_one_hop_sources():
    target = "15-1134.00"
    incoming = transitions_into(target, limit=5)
    assert incoming
    assert all("delta_skills" in row and "title" in row for row in incoming)


# --------------------------------------------------------------------------- #
# Market seeds
# --------------------------------------------------------------------------- #
def test_market_seed_bounds_and_labels():
    seed = load_seed()
    adapter = build_adapter()
    occ = TAX.get("15-1134.00")
    snapshot = adapter.snapshot(occ, "in")
    assert snapshot.currency == "INR"
    assert snapshot.salary_p25 < snapshot.salary_p50 < snapshot.salary_p75
    assert snapshot.source == seed.label == "Source: curated, updated 2026-09"
    us = adapter.snapshot(occ, "us")
    assert us.currency == "USD" and us.salary_p50 > 0


def test_market_seed_family_and_remote_flags():
    seed = load_seed()
    dev = TAX.get("15-1134.00")
    assert seed.family_for(dev).id in {"software-engineering", "it-support-and-security"}
    assert seed.remote_friendly(dev) is True
    assert seed.demand_score(dev) >= 4
    assert seed.trend(dev) == "rising"
    assert seed.indian_titles(dev)


def test_market_seed_india_override_beats_family():
    seed = load_seed()
    nurse = next(o for o in TAX.occupations if o.title.startswith("Registered Nurses"))
    override = seed.india_override(nurse)
    assert override is not None
    assert seed.snapshot(nurse, "in").salary_p50 == override.inr[1]


def test_admin_overrides_win_over_seeds():
    adapter = build_adapter()
    adapter.set_overrides({"15-1134.00": {"salary_p25": 1, "salary_p50": 2, "salary_p75": 3}})
    snapshot = adapter.snapshot(TAX.get("15-1134.00"), "in")
    assert snapshot.salary_p50 == 2 and "admin override" in snapshot.source


# --------------------------------------------------------------------------- #
# Tasks & interview questions
# --------------------------------------------------------------------------- #
def test_derived_tasks_are_labelled():
    occ = TAX.get("15-1134.00")
    tasks = derive_tasks(occ, limit=4)
    assert tasks and all(
        t["source"].startswith("Source: O*NET occupation description") for t in tasks
    )
    assert education_path(occ)[0]["source"].startswith("Source: O*NET job-zone")


def test_interview_kit_is_deterministic_and_complete():
    first = generate_interview("15-1199.08")
    second = generate_interview("15-1199.08")
    assert [q.question for q in first.questions] == [q.question for q in second.questions]
    assert len(first.questions) == 20
    kinds = [q.kind for q in first.questions]
    assert kinds.count("behavioural") == 10 and kinds.count("technical") == 10
    assert len({q.question for q in first.questions}) == 20
    assert set(first.questions[0].star) == {"situation", "task", "action", "result"}
    assert first.to_dict()["source"].startswith("Source: template engine")


def test_interview_seed_changes_questions():
    a = generate_interview("15-1199.08", seed=1)
    b = generate_interview("15-1199.08", seed=99)
    assert [q.question for q in a.questions] != [q.question for q in b.questions]


def test_interview_accepts_admin_templates():
    kit = generate_interview(
        "15-1199.08",
        count_behavioural=2,
        count_technical=1,
        extra_behavioural=["How do you use {skill}?"],
    )
    assert len(kit.questions) == 3


# --------------------------------------------------------------------------- #
# Résumé scorer v2
# --------------------------------------------------------------------------- #
RESUME = """PRIYA SHARMA
priya@example.com | +91 98765 43210

SUMMARY
Data analyst with 4 years of experience in retail analytics.

EXPERIENCE
- Built 12 Tableau dashboards used by 40 store managers.
- Automated the weekly sales report in Python, saving 6 hours per week.
- Worked on ad-hoc requests from the merchandising team.
- Responsible for data quality checks across 3 source systems.

EDUCATION
B.Sc. Statistics, University of Madras, 2021

SKILLS
Python, SQL, Statistics, Excel, Tableau
"""


def test_resume_detects_sections_and_years():
    sections = {s.name: s.found for s in detect_sections(RESUME)}
    assert sections["Experience"] and sections["Education"] and sections["Skills"]
    assert sections["Contact"]
    assert detect_years(RESUME) == 4


def test_resume_scores_against_target_career():
    result = score_resume(RESUME, "15-2041.00")  # Statisticians
    payload = result.to_dict()
    assert 0 < payload["score"] <= 100
    assert payload["target_career"]["id"] == "15-2041.00"
    assert payload["keyword_coverage"]["matched"]
    assert payload["keyword_coverage"]["missing"]
    assert payload["quantified_impact"]["quantified"] >= 2
    assert "built" in payload["action_verbs"]["found"]
    assert payload["rewrites"] and all("reason" in r for r in payload["rewrites"])
    assert payload["source"].startswith("Source: rule-based")


def test_resume_without_target_still_scores():
    result = score_resume(RESUME)
    payload = result.to_dict()
    assert payload["target_career"] is None
    assert payload["score"] > 0


def test_empty_resume_scores_low():
    payload = score_resume("", "15-1199.08").to_dict()
    assert payload["score"] < 45
    assert payload["grade"] == "Needs work"


def test_tamil_hindi_item_translations_exist():
    from career_guidance.riasec import load_items, questions

    assert len(questions("en")) == 36
    assert len(questions("ta")) == 36 and len(questions("hi")) == 36
    en_items = {i.id: i.text for i in load_items("en")}
    ta_items = {i.id: i.text for i in load_items("ta")}
    assert all(ta_items[i] != en_items[i] for i in en_items)
