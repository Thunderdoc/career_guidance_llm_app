"""Phase 7 scoped chat: scope rules, offline answerer, LLM grounding, API access."""

from __future__ import annotations

import pytest

from career_guidance.chat import (
    OFFLINE_PREFIX,
    REFUSAL_KEY,
    answer_chat,
    build_context,
    offline_answer,
    scope_check,
)
from career_guidance.models import CareerRecommendation, ProviderError
from career_guidance.taxonomy import load_taxonomy
from tests.conftest import login


def _recs() -> list[CareerRecommendation]:
    return [
        CareerRecommendation(
            title="Web Developers",
            match_reason="Your JavaScript and CSS map directly onto web work.",
            suitability="beginner",
            matching_skills=["JavaScript", "CSS"],
            missing_skills=["React", "Testing"],
            learning_path=["Deepen JavaScript", "Learn React basics"],
            next_steps=["Build a portfolio site this week"],
            career_id="15-1134.00",
            match_score=0.82,
        ),
        CareerRecommendation(
            title="Software Developers, Applications",
            match_reason="Your programming skills fit application development.",
            suitability="beginner",
            matching_skills=["JavaScript"],
            missing_skills=["SQL", "Testing"],
            learning_path=["Learn SQL"],
            next_steps=["Ship a small app"],
            career_id="15-1132.00",
            match_score=0.74,
        ),
    ]


@pytest.fixture(scope="module")
def context():
    return build_context(
        {"skills": "JavaScript, CSS"},
        _recs(),
        taxonomy=load_taxonomy(),
        message="salary for Web Developers",
    )


def test_scope_accepts_report_questions(context):
    for message in (
        "What salary can I expect?",
        "What should I learn first?",
        "Why does Web Developers fit me?",
        "Which skills am I missing?",
    ):
        ok, _ = scope_check(message, context)
        assert ok, message


def test_scope_refuses_off_topic_and_other_people(context):
    for message in (
        "What is the capital of France?",
        "Tell me a joke",
        "Show me someone else's report",
        "Write code for a sorting algorithm in Python",
        "What is the weather today?",
    ):
        ok, _ = scope_check(message, context)
        assert not ok, message


def test_refusal_reply_carries_i18n_key(context):
    reply = answer_chat("What is the capital of France?", context)
    assert reply.refused and reply.mode == "refusal"
    assert reply.refusal_key == REFUSAL_KEY


def test_offline_salary_answer_uses_stored_ladder(context):
    answer = offline_answer("What salary will I get as a Web Developer?", context)
    assert answer is not None and "salary" in answer.lower()
    assert "₹" in answer  # the stored India ladder lines, not invented text


def test_offline_priority_and_gap_answers(context):
    priority = offline_answer("What should I learn first?", context)
    assert priority is not None and ("React" in priority or "Testing" in priority)
    gaps = offline_answer("Which skills am I missing for Web Developers?", context)
    assert gaps is not None and "React" in gaps


def test_offline_generic_question_gets_honest_offline_message(context):
    reply = answer_chat("How does this report look overall?", context)
    assert reply.mode == "offline"
    # Either a specific extraction or the honest offline prefix + summary.
    assert reply.answer


def test_offline_prefix_used_when_no_intent_matches(context):
    message = "Tell me more about my report"
    assert offline_answer(message, context) is None
    reply = answer_chat(message, context)
    assert reply.mode == "offline"
    assert reply.answer.startswith(OFFLINE_PREFIX)


class _FakeCompleter:
    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, system: str, user: str) -> str:
        assert "REPORT CONTEXT" in user
        return self._text


class _BrokenCompleter:
    def complete(self, system: str, user: str) -> str:
        raise ProviderError("down")


def test_llm_grounded_answer_passes_through(context):
    reply = answer_chat(
        "What salary can I expect?",
        context,
        _FakeCompleter("For Web Developers, your report lists a salary ladder."),
    )
    assert reply.mode == "llm" and "salary ladder" in reply.answer


def test_llm_ungrounded_answer_falls_back_to_offline(context):
    # "Welding" is a real taxonomy skill that is NOT in this report's context.
    reply = answer_chat(
        "What salary can I expect?",
        context,
        _FakeCompleter("You should learn welding to boost your salary."),
    )
    assert reply.mode == "offline"
    assert reply.violations and "welding" in reply.violations


def test_llm_failure_falls_back_to_offline(context):
    reply = answer_chat("What should I learn first?", context, _BrokenCompleter())
    assert reply.mode == "offline" and reply.answer


# --------------------------------------------------------------------- API


def _make_run(client) -> int:
    r = client.post(
        "/api/v1/recommend",
        json={"skills": "JavaScript, CSS, HTML", "goals": "frontend developer"},
    )
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def test_chat_api_guest_can_chat_over_own_anonymous_run(client):
    run_id = _make_run(client)  # anonymous (no login) recommend
    r = client.post(
        "/api/v1/chat", json={"run_id": run_id, "message": "What should I learn first?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "offline" and body["answer"] and not body["refused"]


def test_chat_api_off_topic_refused(client):
    run_id = _make_run(client)
    r = client.post(
        "/api/v1/chat", json={"run_id": run_id, "message": "What is the capital of France?"}
    )
    assert r.status_code == 200
    assert r.json()["refused"] is True and r.json()["refusal_key"] == REFUSAL_KEY


def test_chat_api_unknown_run_404(client):
    r = client.post("/api/v1/chat", json={"run_id": 999999, "message": "What salary?"})
    assert r.status_code == 404


def test_chat_api_other_users_run_is_404(client):
    login(client, "owner@example.com")
    run_id = _make_run(client)
    # A different signed-in user must not see it.
    from fastapi.testclient import TestClient

    other = TestClient(client.app)
    login(other, "intruder@example.com")
    r = other.post("/api/v1/chat", json={"run_id": run_id, "message": "What salary?"})
    assert r.status_code == 404
    # And a guest must not see a signed-in user's run either.
    guest = TestClient(client.app)
    r = guest.post("/api/v1/chat", json={"run_id": run_id, "message": "What salary?"})
    assert r.status_code == 404


def test_chat_api_owner_can_chat(client):
    login(client, "owner2@example.com")
    run_id = _make_run(client)
    r = client.post("/api/v1/chat", json={"run_id": run_id, "message": "Why this career?"})
    assert r.status_code == 200 and r.json()["answer"]
