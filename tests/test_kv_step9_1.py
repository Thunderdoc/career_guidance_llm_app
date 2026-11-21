"""Kaam-Vaani Step 9.1: rights/scam assistant.

Covers: the ``topics`` parameter on HybridRetriever.search /
answer_question (multi-topic restriction, backward compatible);
the rights module (topic restriction, scam-intent detection,
verified-helpline escalation — no number the file does not hold);
the kv_rights router (status, ask, caching, trace, flag-off 404).
Probe questions were measured against the real snapshot v2 before
these tests were pinned (~/workspace/tmp/kv91_probe.log).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.kv_rights import build_router as build_kv_rights_router
from career_guidance.config import Settings
from career_guidance.kaamvaani.rag import (
    Chunk,
    HybridRetriever,
    RagStore,
    answer_question,
    load_snapshot_file,
)
from career_guidance.kaamvaani.rights import (
    RIGHTS_TOPICS,
    answer_rights_question,
    clear_helplines_cache,
    escalation_for,
    load_helplines,
    scam_intent,
)
from career_guidance.migrations import migrate

ROOT = Path(__file__).resolve().parent.parent


def _chunk(source_id: str, text: str, topic: str) -> Chunk:
    return Chunk(
        source_id=source_id,
        source_url=f"https://example.com/{source_id}",
        source_title=source_id,
        source_date="2026-11-21",
        licence="test",
        language="en",
        topic=topic,
        text=text,
    )


def _small_retriever() -> HybridRetriever:
    return HybridRetriever(
        [
            _chunk(
                "occ:weld",
                "Welders join metal parts with heat. Welders use torches and read blueprints.",
                "occupation",
            ),
            _chunk(
                "rights:epf",
                "The Employees Provident Fund gives workers a retirement "
                "savings account. EPF contributions come from the worker "
                "and the employer.",
                "rights",
            ),
            _chunk(
                "scam:fee",
                "An advance fee scam asks the worker to pay a registration "
                "fee before starting a job. Genuine employers never ask "
                "for money upfront.",
                "scam",
            ),
        ]
    )


@pytest.fixture()
def real_retriever():
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    return HybridRetriever(chunks)


# --------------------------------------------------------------------------- #
# topics parameter on search / answer_question (rag.py)
# --------------------------------------------------------------------------- #


def test_search_topics_param_restricts_to_listed_topics():
    retriever = _small_retriever()
    hits = retriever.search("fee job employer", topics=("scam",))
    assert hits
    assert all(h.chunk.topic == "scam" for h in hits)

    hits = retriever.search("worker job", topics=("rights", "scam"))
    assert hits
    assert {h.chunk.topic for h in hits} <= {"rights", "scam"}
    assert all(h.chunk.topic != "occupation" for h in hits)

    # No topics = everything, as before (backward compatible).
    hits = retriever.search("welders metal torches")
    assert hits and hits[0].chunk.topic == "occupation"


def test_search_topic_and_topics_intersect():
    retriever = _small_retriever()
    assert retriever.search("fee", topic="scam", topics=("rights",)) == []
    hits = retriever.search("fee", topic="scam", topics=("scam", "rights"))
    assert hits and all(h.chunk.topic == "scam" for h in hits)


def test_answer_question_topics_param():
    retriever = _small_retriever()
    # The occupation question answers on the open path...
    assert answer_question("what do welders do", retriever)["refused"] is False
    # ...and refuses when retrieval is restricted to the rights topics.
    restricted = answer_question("what do welders do", retriever, topics=("rights", "scam"))
    assert restricted["refused"] is True
    assert restricted["reason"] == "no_grounding"


def test_answer_question_keeps_old_retriever_contract():
    """A duck-typed retriever whose search() takes no ``topics``
    parameter (the pre-9.1 interface, e.g. the Step 8.1 stub) must
    keep working through answer_question when no topic restriction
    is asked for — the 9.1 gate caught this: passing topics=None
    unconditionally broke all five title-rescue tests."""
    from career_guidance.kaamvaani.rag import Chunk, Hit

    chunk = Chunk(
        source_id="onet:47-2111.00",
        source_url="https://example.test/onet",
        source_title="Electricians",
        source_date="2026-01-01",
        licence="Public domain",
        language="en",
        topic="occupation",
        text="Electricians install and repair electrical wiring.",
    )

    class OldRetriever:
        def search(self, query, top_k=5):
            return [Hit(chunk=chunk, score=0.9, raw_tfidf=0.5, index=0)]

    result = answer_question("what do electricians do", OldRetriever())
    assert result["refused"] is False
    assert result["citations"][0]["source_id"] == "onet:47-2111.00"


# --------------------------------------------------------------------------- #
# Helplines file: verified numbers only
# --------------------------------------------------------------------------- #


def test_load_helplines_real_file():
    lines = load_helplines()
    assert len(lines) == 2
    by_number = {entry["number"]: entry for entry in lines}
    assert set(by_number) == {"1930", "1514"}
    for entry in lines:
        for field in ("number", "name", "purpose", "source_url", "source_date", "for"):
            assert entry[field], field
        assert entry["source_url"].startswith("https://")
    assert by_number["1930"]["source_url"].startswith("https://www.pib.gov.in/")
    assert "scam" in by_number["1930"]["for"]
    assert by_number["1514"]["source_url"] == "https://www.ncs.gov.in/"


def test_load_helplines_missing_file_returns_empty(tmp_path):
    clear_helplines_cache()
    try:
        assert load_helplines(tmp_path / "no-such-file.json") == []
    finally:
        clear_helplines_cache()


def test_load_helplines_skips_incomplete_entries(tmp_path):
    clear_helplines_cache()
    try:
        path = tmp_path / "helplines.json"
        path.write_text(
            json.dumps(
                {
                    "helplines": [
                        {
                            "number": "1930",
                            "name": "Cyber",
                            "purpose": "fraud",
                            "source_url": "https://example.com/",
                            "source_date": "2026-11-21",
                            "for": ["scam"],
                        },
                        {"number": "9999", "name": "No source"},  # incomplete
                    ]
                }
            ),
            encoding="utf-8",
        )
        lines = load_helplines(path)
        assert [entry["number"] for entry in lines] == ["1930"]
    finally:
        clear_helplines_cache()


# --------------------------------------------------------------------------- #
# Scam-intent detection + escalation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "question",
    [
        "is this a scam",
        "I was cheated by an agent",
        "an employer asked for money before joining",
        "they want a registration fee",
        "how do I get my money back",
        "fake job offer on WhatsApp",
    ],
)
def test_scam_intent_positive(question):
    assert scam_intent(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "what is EPF",
        "minimum wage for construction work",
        "how do I become an electrician",
        "what is the NCS helpline number",
    ],
)
def test_scam_intent_negative(question):
    assert scam_intent(question) is False


def test_escalation_only_on_scam_and_only_scam_tagged():
    lines = load_helplines()
    assert escalation_for(False, lines) == []
    escalated = escalation_for(True, lines)
    assert [entry["number"] for entry in escalated] == ["1930"]
    assert escalated[0]["source_url"].startswith("https://www.pib.gov.in/")
    assert escalated[0]["toll_free"] is True


def test_escalation_numbers_come_only_from_the_file(tmp_path):
    """The no-invented-numbers pin: escalation can only quote numbers
    the loaded helplines file holds. A fixture file with a made-up
    number proves the file is the ONLY source."""
    clear_helplines_cache()
    try:
        path = tmp_path / "helplines.json"
        path.write_text(
            json.dumps(
                {
                    "helplines": [
                        {
                            "number": "9999",
                            "name": "Fixture scam line",
                            "purpose": "test",
                            "source_url": "https://example.com/",
                            "source_date": "2026-11-21",
                            "for": ["scam"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        lines = load_helplines(path)
        escalated = escalation_for(True, lines)
        assert [entry["number"] for entry in escalated] == ["9999"]
    finally:
        clear_helplines_cache()


# --------------------------------------------------------------------------- #
# Rights answers on the real snapshot v2
# --------------------------------------------------------------------------- #


def test_rights_topics_constant():
    assert RIGHTS_TOPICS == ("rights", "scam", "wages", "employment")


def test_rights_epf_question_grounded(real_retriever):
    result = answer_rights_question("What is EPF?", real_retriever)
    assert result["refused"] is False
    assert result["citations"][0]["source_id"] == "wiki:epfo"
    assert result["escalation"] == []
    assert result["scam_intent"] is False
    assert result["topics"] == list(RIGHTS_TOPICS)


def test_rights_wage_question_grounded(real_retriever):
    result = answer_rights_question(
        "What is the minimum wage for construction work?", real_retriever
    )
    assert result["refused"] is False
    assert result["citations"][0]["source_id"] == "web:labourbureau-vda-construction"
    assert result["escalation"] == []


def test_rights_occupation_question_refuses(real_retriever):
    """The topic restriction, pinned: the same question answers on
    the open path and refuses on the rights path."""
    assert answer_question("what does a welder do?", real_retriever)["refused"] is False
    result = answer_rights_question("what does a welder do?", real_retriever)
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"
    assert result["citations"] == []
    assert result["escalation"] == []


def test_rights_scam_question_answered_and_escalated(real_retriever):
    result = answer_rights_question(
        "An employer asked me to pay a registration fee. Is that a scam?",
        real_retriever,
    )
    assert result["refused"] is False
    assert result["citations"][0]["source_id"] == "wiki:advance-fee-scam"
    assert result["scam_intent"] is True
    assert [entry["number"] for entry in result["escalation"]] == ["1930"]
    assert result["escalation"][0]["source_url"].startswith("https://www.pib.gov.in/")


def test_rights_scam_refusal_still_escalates(real_retriever):
    """No grounded answer — but the worker gets the helpline anyway:
    the escalation matters most exactly when the base cannot answer."""
    result = answer_rights_question("I was cheated by an agent who took my money", real_retriever)
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"
    assert [entry["number"] for entry in result["escalation"]] == ["1930"]


def test_rights_uncovered_question_refuses_without_escalation(real_retriever):
    result = answer_rights_question("what is the capital of France?", real_retriever)
    assert result["refused"] is True
    assert result["citations"] == []
    assert result["escalation"] == []


# --------------------------------------------------------------------------- #
# Router: kv_rights (populated snapshot v2)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def populated_rights_client(tmp_path):
    """A standalone app with only the kv_rights router, over a scratch
    DB holding the real snapshot v2."""
    db = str(tmp_path / "rights.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_rights_router(settings))
    with TestClient(app) as client:
        yield client


def test_kv_rights_status_populated(populated_rights_client):
    r = populated_rights_client.get("/api/v1/kv/rights/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["topics"] == {"rights": 27, "scam": 19, "wages": 8, "employment": 2}
    assert body["chunks"] == 56
    assert {h["number"] for h in body["helplines"]} == {"1930", "1514"}
    assert body["snapshot_versions"] == ["v2"]


def test_kv_rights_ask_grounded_and_escalated(populated_rights_client):
    r = populated_rights_client.post(
        "/api/v1/kv/rights/ask",
        json={"question": "An employer asked me to pay a registration fee. Is that a scam?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is False
    assert body["citations"][0]["source_id"] == "wiki:advance-fee-scam"
    assert [entry["number"] for entry in body["escalation"]] == ["1930"]
    assert body["trace_id"]


def test_kv_rights_ask_refuses_occupation(populated_rights_client):
    r = populated_rights_client.post(
        "/api/v1/kv/rights/ask", json={"question": "what does a welder do?"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["refused"] is True
    assert r.json()["reason"] == "no_grounding"


def test_kv_rights_ask_validates_input(populated_rights_client):
    assert (
        populated_rights_client.post("/api/v1/kv/rights/ask", json={"question": ""}).status_code
        == 422
    )


def test_kv_rights_ask_cached(populated_rights_client):
    question = {"question": "What is EPF?"}
    first = populated_rights_client.post("/api/v1/kv/rights/ask", json=question).json()
    second = populated_rights_client.post("/api/v1/kv/rights/ask", json=question).json()
    assert first["answer"] == second["answer"]
    assert first["citations"] == second["citations"]
    status = populated_rights_client.get("/api/v1/kv/rights/status").json()
    assert status["cache"]["hits"] >= 1


@pytest.fixture()
def app_module_kv_rag_off(tmp_path, monkeypatch):
    """backend.main reloaded with KV_RAG=false (dev otherwise)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_RAG", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_rights_routes_404_when_flag_off(app_module_kv_rag_off):
    with TestClient(app_module_kv_rag_off.app) as c:
        assert c.get("/api/v1/kv/rights/status").status_code == 404
        assert c.get("/api/v1/kv/rag/status").status_code == 404
        # The rest of the app is unaffected by the flag being off.
        assert c.get("/api/v1/kv/voice/status").status_code == 200
        assert c.get("/api/v1/health").status_code == 200
