"""Ladder + pathway engines: the flagship “what should I do next?” logic."""

from __future__ import annotations

import pytest

from career_guidance.ladder import (
    HOURS_PER_SKILL,
    owned_terms,
    skill_set,
)
from career_guidance.ladder import (
    build as build_ladder,
)
from career_guidance.market_seed import build_adapter
from career_guidance.pathway import (
    build_pathway,
    evaluate,
    load_bridges,
    read_resume_signals,
    user_zone,
)
from career_guidance.taxonomy import load_taxonomy

BIA = "15-1199.08"  # Business Intelligence Analysts (data family)
NURSE = "29-1141.00"
HOSPITALIST = "29-1069.03"  # MBBS + MD gated
LAWYER = "23-1011.00"


@pytest.fixture(scope="module")
def tax():
    return load_taxonomy()


@pytest.fixture(scope="module")
def market():
    return build_adapter()


def test_skill_set_is_deduped_and_curated(tax):
    skills = skill_set(tax.get(BIA))
    assert "SQL" in skills and "Microsoft Excel" in skills
    assert len(skills) == len({s.lower() for s in skills})
    # Alphabetical O*NET noise is not promoted to the top of the list.
    assert skills[0] in {"SQL", "Microsoft Excel"}


def test_owned_terms_uses_ratings_resume_and_synonyms():
    owned = owned_terms({"sql": 5, "excel": 2}, resume_text="tableau dashboards and python")
    assert "sql" in owned  # rated 5 → held
    assert "excel" not in owned and "microsoft excel" not in owned  # rated 2 → not held
    assert "tableau" in owned and "python" in owned  # from the résumé
    assert "data visualization" in owned or "tableau" in owned  # synonym expansion


def test_ladder_directions_are_sensible(tax, market):
    ladder = build_ladder(
        tax.get(BIA),
        tax,
        ratings={"SQL": 4, "Microsoft Excel": 5, "Data analysis": 3},
        resume_text="python tableau dashboards",
        market=market,
    )
    assert ladder["current"]["id"] == BIA
    assert ladder["current"]["family"] == "data-and-analytics"
    up = ladder["step_up"]
    assert up and all(rung["job_zone"] >= tax.get(BIA).job_zone for rung in up)
    assert up[0]["coverage"] >= up[-1]["coverage"]
    for rung in up[:3]:
        assert rung["gap_count"] == len(rung["gap_skills"])
        assert rung["study_hours"] == int(round(HOURS_PER_SKILL * rung["gap_count"]))
        assert rung["salary_p50"] and rung["market_source"].startswith("Source:")
    across = ladder["step_across"]
    assert all(rung["job_zone"] == tax.get(BIA).job_zone for rung in across)
    # Lateral move candidates stay inside the same market family.
    assert {rung["family"] for rung in across[:3]} == {"data-and-analytics"}


def test_ladder_never_suggests_the_origin_or_absurd_jumps(tax, market):
    ladder = build_ladder(
        tax.get("47-2111.00"), tax, ratings={"Electrical wiring": 5}, market=market
    )
    ids = {
        rung["id"]
        for bucket in ("entry_points", "step_across", "step_up")
        for rung in ladder[bucket]
    }
    assert "47-2111.00" not in ids
    for bucket in ("entry_points", "step_across", "step_up"):
        for rung in ladder[bucket]:
            assert abs(rung["job_zone"] - 3) <= 2


def test_zone_from_education_and_experience():
    assert user_zone("10th pass") == 1
    assert user_zone("Bachelor's degree") == 4
    assert user_zone("Bachelor's degree", 3) == 4
    assert user_zone("Bachelor's degree", 7) == 5
    assert user_zone("", 0) == 3  # unknown → medium preparation


def test_resume_signals_are_best_effort_and_labelled():
    signals = read_resume_signals(
        "B.Tech IT graduate with 3 years experience as a business analyst. "
        "Skills: SQL, Excel, Tableau, Python."
    )
    assert signals["education"] == "Bachelor's degree"
    assert signals["experience_years"] == 3.0
    assert signals["experience_level"] == "Mid-level (2-5 years)"
    assert {"sql", "excel", "tableau", "python"} <= set(signals["skills"])
    assert signals["source"].startswith("Source:")
    empty = read_resume_signals("")
    assert empty["education"] == "" and empty["skills"] == []


def test_bridge_book_covers_the_flag_question():
    book = load_bridges()
    ids = {profession.id for profession in book.professions}
    assert {"doctor", "nurse", "lawyer", "chartered-accountant", "teacher"} <= ids
    assert book.open_doors and all(door["eligibility"] for door in book.open_doors)
    doctor = next(p for p in book.professions if p.id == "doctor")
    assert "NEET" in " ".join(doctor.requires)
    assert doctor.bridges and all(
        bridge["duration"] and bridge["cost_inr"] for bridge in doctor.bridges
    )


def test_evaluate_blocks_only_on_hard_gates(tax, market):
    doctor = evaluate(
        tax.get(HOSPITALIST),
        taxonomy=tax,
        resume_text="B.Tech IT, 3 years experience, SQL Python",
        education="Bachelor's degree",
        experience_level="Junior (0-2 years)",
    )
    assert doctor["verdict"] == "blocked"
    assert doctor["hard_blockers"] and doctor["profession"]["id"] == "doctor"
    assert any(r["status"] == "missing" for r in doctor["requirements"])

    nurse = evaluate(tax.get(NURSE), taxonomy=tax, education="Bachelor's degree")
    assert nurse["profession"]["id"] == "nurse"

    accountant = evaluate(
        tax.get("13-2011.01"),
        taxonomy=tax,
        resume_text="Tally, GST filing, Excel, accounts payable",
        education="Bachelor's degree",
    )
    assert accountant["verdict"] == "reachable"
    assert not accountant["hard_blockers"]  # skills can be learned: soft blocker only
    assert accountant["coverage"] > 0

    lawyer = evaluate(tax.get(LAWYER), taxonomy=tax, education="Bachelor's degree")
    assert lawyer["verdict"] == "reachable"
    assert lawyer["profession"]["open_to_any_degree"] is True


def test_pathway_plan_is_ordered_and_sourced(tax, market):
    plan = build_pathway(
        tax.get(BIA),
        taxonomy=tax,
        ratings={"SQL": 4, "Microsoft Excel": 5},
        resume_text="tableau dashboards python",
        education="Bachelor's degree",
        experience_level="Junior (0-2 years)",
        hours_per_week=6,
        market=market,
        resource_lookup=lambda skill: [{"title": f"{skill} course", "url": "https://example.org"}],
    )
    assert plan["verdict"]["verdict"] in {"reachable", "eligible"}
    phases = plan["plan"]["phases"]
    assert phases and phases[0]["focus_skills"]
    assert phases[0]["start_week"] == 1
    assert phases[0]["resources"] and phases[0]["resources"][0]["title"].endswith("course")
    assert plan["plan"]["eta"] and plan["plan"]["total_hours"] > 0
    assert plan["plan"]["weeks"] == phases[-1]["start_week"] + phases[-1]["weeks"] - 1
    assert plan["market"]["band"].startswith("₹")
    assert plan["target"]["core_skills"]
    assert plan["next_step"].startswith("Step 1:")
    assert plan["sources"]["pathways"].startswith("Source:")


def test_pathway_teaches_the_doctor_story(tax, market):
    """A B.Tech aiming at an MBBS role gets the truth *and* a route."""
    plan = build_pathway(
        tax.get(HOSPITALIST),
        taxonomy=tax,
        resume_text="B.Tech Information Technology, 3 years experience, SQL, Python",
        education="Bachelor's degree",
        experience_level="Junior (0-2 years)",
        market=market,
    )
    assert plan["verdict"]["verdict"] == "blocked"
    assert "cannot be converted" in " ".join(plan["verdict"]["hard_blockers"])
    bridge_titles = " ".join(b["title"] for b in plan["bridges"])
    assert "Hospital & Health Administration" in bridge_titles
    assert plan["open_doors"] and plan["alternatives"]
    assert plan["plan"]["phases"], "even a blocked path gets a concrete next step"


def test_pathway_is_deterministic(tax, market):
    kwargs = dict(
        taxonomy=tax,
        resume_text="sql excel python",
        education="Bachelor's degree",
        experience_level="Junior (0-2 years)",
        market=market,
    )
    first = build_pathway(tax.get("13-2011.01"), **kwargs)
    again = build_pathway(tax.get("13-2011.01"), **kwargs)
    assert first["plan"] == again["plan"]
    assert first["verdict"]["coverage"] == again["verdict"]["coverage"]
