"""Kaam-Vaani Stage 4: matching scorer, gap/learning path, router.

The scorer tests pin the Stage 3 demo fix: the farming/computer
12th-pass profile from Madurai (₹15,000/month) used to get teacher
roles at 7–8% with "0 of 8 core skills"; it must now get data-entry /
computer-operator / agricultural roles at 35%+ with real matched
skills. The router tests pin the state-machine wiring (matches only
from the matches state; gap-learning moves matches → gap_learning)
and the F2 acceptance: every learning-path item carries a source.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.kv_matching import build_router as build_kv_matching_router
from career_guidance.config import Settings
from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.matching import (
    KVScorer,
    course_citations_for,
    gap_for_match,
    learning_path_for,
    phrase_variant_sets,
    title_purity,
)
from career_guidance.kaamvaani.profile import (
    VoiceSession,
    new_session,
    transition,
)
from career_guidance.kaamvaani.rag import (
    HybridRetriever,
    RagStore,
    load_snapshot_file,
)
from career_guidance.migrations import migrate

ROOT = Path(__file__).resolve().parent.parent

DEMO_ANSWERS = {
    "skills": "farming and basic computer work, and I can type",
    "education": "12th pass",
    "city": "Madurai",
    "income": "15000 rupees a month",
    "goal": "I need a job",
}


def _demo_profile() -> VoiceProfile:
    """The Stage 3 demo profile, as the guided extractor produces it
    (canonical skills, no LLM — deterministic path)."""
    from career_guidance.kaamvaani.profile import extract_profile_guided

    profile, _ = extract_profile_guided(DEMO_ANSWERS, None)
    return profile


def _profile(**overrides) -> VoiceProfile:
    base = {
        "skills": ["attention to detail", "computer literacy", "agricultural science"],
        "interests": "farming and basic computer work, and I can type. Madurai. I need a job",
        "education": "12th pass",
        "city": "Madurai",
        "income_text": "₹15,000 / month",
        "income_monthly": 15000,
        "goal_type": "job_6_months",
        "raw_text": "farming and basic computer work, and I can type. 12th pass. Madurai. "
        "15000 rupees a month. I need a job",
    }
    base.update(overrides)
    return VoiceProfile(**base)


def _confirmed_session(profile: VoiceProfile) -> VoiceSession:
    """A session driven through the state machine to ``matches``."""
    session = new_session("en")
    session = transition(session, "start")
    session = transition(session, "set_language", language="en")
    for qid, text in DEMO_ANSWERS.items():
        session = transition(session, "answer", question_id=qid, transcript=text, source="typed")
    session = transition(session, "extracted", profile=profile)
    return transition(session, "confirm", confirmed=True)


@pytest.fixture(scope="module")
def scorer() -> KVScorer:
    return KVScorer()


# --------------------------------------------------------------------------- #
# Title phrases
# --------------------------------------------------------------------------- #


def test_title_purity_full_phrase_needs_all_words():
    # "data entry" matches both words of "Data Entry Keyers" (2/3).
    phrases = [phrase_variant_sets("data entry")]
    assert title_purity("Data Entry Keyers", phrases) == pytest.approx(2 / 3)
    # "garment construction" (a fashion-design alias) must NOT match
    # "Construction Carpenters": "garment" is not in the title, so the
    # AND semantics fail the whole phrase.
    phrases = [phrase_variant_sets("garment construction")]
    assert title_purity("Construction Carpenters", phrases) == 0.0
    # But the single word "agricultural" (from the canonical
    # "agricultural science") still earns partial credit.
    phrases = [[{"agricultural"}]]
    assert title_purity("Agricultural Technicians", phrases) == pytest.approx(0.5)


def test_title_purity_stems_plurals():
    phrases = [[{"electrician"}]]
    assert title_purity("Electricians", phrases) == 1.0
    phrases = [[{"farm"}]]
    assert title_purity("Farmworkers, Farm, Ranch, and Aquacultural Animals", phrases) > 0.0


# --------------------------------------------------------------------------- #
# Scorer — the Stage 3 demo fix
# --------------------------------------------------------------------------- #


def test_demo_profile_top_match_is_data_entry(scorer):
    ranked, meta = scorer.rank(_demo_profile(), top_k=5)
    assert ranked[0].occupation.title == "Data Entry Keyers"
    assert ranked[0].score > 0.35
    assert ranked[0].matched == ["clerical"]
    assert meta["target_zone"] == pytest.approx(3.03)


def test_demo_profile_top5_has_no_teachers(scorer):
    ranked, _ = scorer.rank(_demo_profile(), top_k=5)
    titles = [m.occupation.title for m in ranked]
    assert "Agricultural Technicians" in titles
    assert not any("Teacher" in t for t in titles)
    assert all(m.score > 0.3 for m in ranked)


def test_electrician_ranks_electricians_first(scorer):
    profile = _profile(
        skills=["electrical technician"],
        interests="I am an electrician, house wiring and fan repair",
        education="ITI",
        city="Salem",
        income_monthly=20000,
        income_text="₹20,000 / month",
        raw_text="I am an electrician, house wiring and fan repair. ITI. Salem. "
        "20000 rupees a month. I need a job",
    )
    ranked, _ = scorer.rank(profile, top_k=3)
    assert ranked[0].occupation.title == "Electricians"
    assert ranked[0].score > 0.7
    assert "repairing" in ranked[0].matched


def test_tailor_ranks_fashion_designers_first(scorer):
    profile = _profile(
        skills=["fashion design"],
        interests="tailoring and stitching clothes",
        education="10th pass",
        city="Tiruppur",
        income_monthly=12000,
        income_text="₹12,000 / month",
        raw_text="tailoring and stitching clothes. 10th pass. Tiruppur. "
        "12000 rupees a month. I need a job",
    )
    ranked, _ = scorer.rank(profile, top_k=5)
    assert ranked[0].occupation.title == "Fashion Designers"
    assert not any("Construction" in m.occupation.title for m in ranked)


def test_zone_filter_excludes_zone5_for_12th_pass(scorer):
    ranked, meta = scorer.rank(_demo_profile(), top_k=10)
    assert meta["excluded_zone"] == 162
    assert all(m.occupation.job_zone <= 4 for m in ranked)


def test_zone_filter_is_stricter_for_10th_pass(scorer):
    profile = _profile(education="10th pass")
    _, meta = scorer.rank(profile, top_k=5)
    assert meta["excluded_zone"] == 394


def test_income_filter_demotes_low_paying_roles(scorer):
    """At ₹60,000/month the same occupation fits worse than at
    ₹15,000/month — the income filter changes results measurably (F2)."""
    occ_id = next(o.id for o in scorer.taxonomy.occupations if o.title == "Computer Operators")
    low = scorer.match_for(_profile(income_monthly=15000), occ_id)
    high = scorer.match_for(_profile(income_monthly=60000), occ_id)
    assert low is not None and high is not None
    assert low.components["income"] == 1.0
    assert high.components["income"] == 0.7
    assert high.score < low.score


def test_income_text_does_not_leak_into_base_scores(scorer):
    """L55 (Step 8B): the raw income text used to be fed to the base
    matcher as part of the goals string, and paraphrasing it shifted
    base scores by up to ~1e-3 (final scores ~1e-4 at the 0.10 base
    weight). Income is scored by the dedicated income-fit component
    only, so two profiles identical except the income WORDING (same
    parsed number) must produce identical base scores. (Changing
    only the digits never leaked — the semantic tokenizer drops
    numbers — so the pin paraphrases with different words.)"""
    base = scorer._base_scores(_profile(income_text="₹15,000 / month"))
    paraphrased = scorer._base_scores(_profile(income_text="fifteen thousand rupees every month"))
    empty = scorer._base_scores(_profile(income_text=""))
    assert paraphrased == base
    assert empty == base


def test_empty_profile_still_ranks(scorer):
    profile = _profile(
        skills=[],
        interests="",
        education="",
        city="",
        income_monthly=None,
        income_text="",
        raw_text="",
    )
    ranked, _ = scorer.rank(profile, top_k=5)
    assert len(ranked) == 5
    assert all(m.score >= 0 for m in ranked)


def test_match_for_unknown_occupation_returns_none(scorer):
    assert scorer.match_for(_demo_profile(), "99-9999.99") is None


def test_match_dict_has_why_it_fits_reasons(scorer):
    ranked, _ = scorer.rank(_demo_profile(), top_k=1)
    data = ranked[0].to_dict()
    assert data["career_id"]
    assert data["match_percent"] == pytest.approx(ranked[0].score * 100, abs=0.1)
    kinds = {r["kind"] for r in data["reasons"]}
    assert {"skill", "title", "income", "zone"} <= kinds
    skill_reason = next(r for r in data["reasons"] if r["kind"] == "skill")
    assert skill_reason["skills"] == ["clerical"]


# --------------------------------------------------------------------------- #
# Gap + learning path
# --------------------------------------------------------------------------- #


def test_gap_uses_skillgap_engine(scorer):
    ranked, _ = scorer.rank(_demo_profile(), top_k=1)
    gap = gap_for_match(ranked[0], scorer.taxonomy)
    assert gap["title"] == "Data Entry Keyers"
    assert gap["counts"]["strong"] == len(ranked[0].matched) == 1
    assert gap["counts"]["missing"] > 0
    strong = [s["skill"] for s in gap["skills"] if s["status"] == "strong"]
    assert strong == ["Clerical"]


def test_learning_path_items_all_carry_a_source(scorer):
    ranked, _ = scorer.rank(_demo_profile(), top_k=1)
    path = learning_path_for(ranked[0].missing)
    assert 1 <= len(path) <= 5
    for item in path:
        assert item["url"].startswith("http")
        assert item["source"]
        assert item["provider"]
        assert item["free"] is True


def test_learning_path_empty_gap_is_empty():
    assert learning_path_for([]) == []


def test_course_citations_come_from_courses_and_skilling():
    chunks, _ = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    retriever = HybridRetriever(chunks)
    citations = course_citations_for(
        retriever, "Data Entry Keyers", ["complex problem solving", "english language"]
    )
    assert 1 <= len(citations) <= 3
    for citation in citations:
        assert citation["url"].startswith("http")
        assert citation["title"]
        assert citation["source_id"]
        assert citation["snippet"]


def test_course_citations_empty_store_is_empty():
    retriever = HybridRetriever([])
    assert course_citations_for(retriever, "Electricians", ["repairing"]) == []


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


@pytest.fixture()
def matching_client(tmp_path):
    """A standalone app with only the kv_matching router, over a scratch
    DB holding the real snapshot v2."""
    db = str(tmp_path / "kv.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_matching_router(settings))
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def empty_store_client(tmp_path):
    """Same router, but the RAG store is empty — citations must be []."""
    db = str(tmp_path / "kv-empty.db")
    migrate(db)
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_matching_router(settings))
    with TestClient(app) as client:
        yield client


def test_matches_returns_top5_for_confirmed_session(matching_client):
    profile = _demo_profile()
    session = _confirmed_session(profile)
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
    }
    r = matching_client.post("/api/v1/kv/matches", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session"]["state"] == "matches"
    assert data["target_zone"] == pytest.approx(3.03)
    assert data["excluded_zone"] == 162
    matches = data["matches"]
    assert len(matches) == 5
    assert matches[0]["title"] == "Data Entry Keyers"
    assert matches[0]["match_percent"] > 35
    assert matches[0]["matched_skills"] == ["clerical"]
    assert matches[0]["missing_skills"]
    assert matches[0]["reasons"]


def test_matches_rejects_unconfirmed_session(matching_client):
    profile = _demo_profile()
    session = new_session("en")
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
    }
    r = matching_client.post("/api/v1/kv/matches", json=body)
    assert r.status_code == 400


def test_gap_learning_transitions_and_returns_gap_and_path(matching_client):
    profile = _demo_profile()
    session = _confirmed_session(profile)
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "43-9021.00",  # Data Entry Keyers
    }
    r = matching_client.post("/api/v1/kv/gap-learning", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session"]["state"] == "gap_learning"
    assert data["next_state"] == "gap_learning"
    assert data["title"] == "Data Entry Keyers"
    assert data["gap"]["counts"]["missing"] > 0
    assert data["learning_path"]
    for item in data["learning_path"]:
        assert item["url"].startswith("http")
        assert item["source"]
    assert data["citations"]
    for citation in data["citations"]:
        assert citation["url"].startswith("http")


def test_gap_learning_repeat_call_from_gap_learning_state(matching_client):
    """Opening a second match after the first is legal — the session
    stays in gap_learning."""
    profile = _demo_profile()
    session = _confirmed_session(profile)
    first = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "43-9021.00",
    }
    r1 = matching_client.post("/api/v1/kv/gap-learning", json=first)
    assert r1.status_code == 200, r1.text
    second = {
        "session": r1.json()["session"],
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "43-9011.00",  # Computer Operators
    }
    r2 = matching_client.post("/api/v1/kv/gap-learning", json=second)
    assert r2.status_code == 200, r2.text
    assert r2.json()["session"]["state"] == "gap_learning"
    assert r2.json()["title"] == "Computer Operators"


def test_gap_learning_rejects_wrong_state(matching_client):
    profile = _demo_profile()
    session = new_session("en")
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "43-9021.00",
    }
    r = matching_client.post("/api/v1/kv/gap-learning", json=body)
    assert r.status_code == 400


def test_gap_learning_unknown_occupation_404(matching_client):
    profile = _demo_profile()
    session = _confirmed_session(profile)
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "99-9999.99",
    }
    r = matching_client.post("/api/v1/kv/gap-learning", json=body)
    assert r.status_code == 404


def test_gap_learning_empty_store_has_no_citations(empty_store_client):
    profile = _demo_profile()
    session = _confirmed_session(profile)
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "43-9021.00",
    }
    r = empty_store_client.post("/api/v1/kv/gap-learning", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["citations"] == []
    assert r.json()["learning_path"]  # the curated catalogue is independent of RAG


# --------------------------------------------------------------------------- #
# Flag gating (matching shares the KV_VOICE flag)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def app_module_kv_voice_off(tmp_path, monkeypatch):
    """backend.main reloaded with KV_VOICE=false (dev otherwise)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_VOICE", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_matching_routes_404_when_voice_flag_off(app_module_kv_voice_off):
    # POST-only routes answer 405 (not 404) when unmounted: the SPA
    # catch-all is GET-only, so FastAPI reports "path exists, method
    # not allowed" for a POST to a route that was never mounted. The
    # point stands — the matching endpoints are not live when the flag
    # is off.
    with TestClient(app_module_kv_voice_off.app) as c:
        profile = _demo_profile()
        session = _confirmed_session(profile)
        body = {
            "session": session.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
        }
        assert c.post("/api/v1/kv/matches", json=body).status_code == 405
        assert (
            c.post(
                "/api/v1/kv/gap-learning",
                json={**body, "occupation_id": "43-9021.00"},
            ).status_code
            == 405
        )
        assert c.get("/api/v1/health").status_code == 200
