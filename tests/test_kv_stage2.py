"""Kaam-Vaani Stage 2: RAG ingestion, retrieval, eval harness, kv_rag router.

Covers: migration v12 (kv_rag_chunks table + indexes, idempotent), the
shared voice vocabulary (YAML ↔ frontend parity), the deterministic
profile extractor (English/Hindi/Tamil/noisy/code-mixed transcripts),
the ingestion helpers (HTML cleaning, chunking, O*NET document wording),
the RAG store round-trip, hybrid retrieval (BM25 + TF-IDF, title bonus,
subordinate penalty, filters, query rewriting), grounded answers and
refusals (incl. the figure rule and the topic-split cosine floor), the
kv_rag router (mounted when KV_RAG is on, 404 when off), and the eval
harness (golden-set schema, run_eval mechanics).
"""

from __future__ import annotations

import importlib
import json
import re
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.kv_rag import build_router as build_kv_rag_router
from career_guidance.config import Settings
from career_guidance.kaamvaani.extract import (
    contains_phrase,
    extract_profile,
    fix_asr,
    load_vocabulary,
    normalise_digits,
    parse_income,
)
from career_guidance.kaamvaani.rag import (
    Chunk,
    HybridRetriever,
    RagStore,
    answer_question,
    check_citation,
    load_snapshot_file,
    rewrite_query,
    title_bonus,
    tokenize,
)
from career_guidance.migrations import LATEST_VERSION, applied_versions, migrate
from eval.run_kv import run_eval
from scripts.ingest.common import chunk_text, html_title, html_to_text
from scripts.ingest.onet import ingest_onet, occupation_document

ROOT = Path(__file__).resolve().parent.parent


def _chunk(source_id: str, text: str, title: str = "", topic: str = "occupation") -> Chunk:
    return Chunk(
        source_id=source_id,
        source_url=f"https://example.com/{source_id}",
        source_title=title or source_id,
        source_date="2026-11-06",
        licence="test",
        language="en",
        topic=topic,
        text=text,
    )


# --------------------------------------------------------------------------- #
# Migration v12
# --------------------------------------------------------------------------- #


def test_migration_v12_applies_and_is_idempotent(tmp_path):
    db = str(tmp_path / "kv12.db")
    applied = migrate(db)
    assert 12 in applied
    assert LATEST_VERSION >= 12
    assert applied_versions(db)[-1] == LATEST_VERSION

    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(kv_rag_chunks)")}
        assert {
            "id",
            "source_id",
            "source_url",
            "source_title",
            "source_date",
            "licence",
            "language",
            "topic",
            "state",
            "district",
            "chunk_index",
            "text",
            "tokens",
            "snapshot_version",
            "created_at",
        } <= cols
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(kv_rag_chunks)")}
        assert {
            "idx_kv_rag_chunks_source",
            "idx_kv_rag_chunks_topic",
            "idx_kv_rag_chunks_language",
            "idx_kv_rag_chunks_snapshot",
        } <= indexes
        row = conn.execute("SELECT name FROM schema_migrations WHERE version = 12").fetchone()
        assert row and "kaam-vaani" in row[0]

    # Second run: nothing to apply, and stored chunks survive.
    store = RagStore(db)
    store.replace_snapshot([_chunk("test:1", "hello world")], "v-test")
    assert migrate(db) == []
    assert store.count() == 1


# --------------------------------------------------------------------------- #
# Shared vocabulary parity
# --------------------------------------------------------------------------- #


def _ts_cities() -> list[str]:
    text = (ROOT / "frontend" / "lib" / "voice-profile.ts").read_text(encoding="utf-8")
    block = text.split("const CITIES = [", 1)[1].split("]", 1)[0]
    return re.findall(r'"([^"]+)"', block)


def test_kv_cities_match_frontend_cities():
    """kv_cities.yaml carries the frontend CITIES list exactly — the
    backend extractor and the frontend voice flow must agree on cities."""
    data = yaml.safe_load((ROOT / "data" / "kv_cities.yaml").read_text(encoding="utf-8"))
    yaml_names = [c["name"] for c in data["cities"]]
    assert yaml_names == _ts_cities()
    assert len(yaml_names) == 155


def test_frontend_vocabulary_contains_yaml_aliases():
    """The generated frontend vocabulary includes the shared spoken-form
    aliases (regenerate with scripts/gen_voice_vocab.py after edits)."""
    data = yaml.safe_load((ROOT / "data" / "voice_aliases.yaml").read_text(encoding="utf-8"))
    generated = (ROOT / "frontend" / "lib" / "voice-vocabulary.ts").read_text(encoding="utf-8")
    for alias in ("tailor", "can type", "kheti", "vivasaayam", "mobile repairing"):
        assert data["extra_aliases"][alias]
        assert alias in generated


def test_vocabulary_loads_and_aliases_are_valid_canonicals():
    """load_vocabulary fails loudly on an alias pointing at an unknown
    canonical, so the vocabulary can never invent a skill."""
    vocab = load_vocabulary()
    assert len(vocab.skill_aliases) > 800
    assert len(vocab.cities) == 155
    assert vocab.canonical_skills >= {
        "carpentry",
        "masonry",
        "painting",
        "hairdressing",
        "security services",
        "construction",
    }


# --------------------------------------------------------------------------- #
# Deterministic profile extractor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "I am a carpenter in Madurai, 10th pass, need a job",
            {
                "skills": ["carpentry"],
                "education": "10th pass",
                "city": "Madurai",
                "income_monthly": None,
                "goal_type": "job_6_months",
            },
        ),
        (
            "I do masonry work, I am a mason in Trichy",
            {"skills": ["masonry"], "city": "Trichy", "goal_type": "job_6_months"},
        ),
        (
            "I am a barber in Salem, need 12000 per month",
            {
                "skills": ["hairdressing"],
                "city": "Salem",
                "income_monthly": 12000,
                "goal_type": "explore",
            },  # no job keyword: "need 12000" alone is not a goal
        ),
        (
            "I work as a security guard in Coimbatore",
            {"skills": ["security services"], "city": "Coimbatore", "goal_type": "job_6_months"},
        ),
        (
            "मैं बढ़ई हूँ, मदुरै से हूँ",
            {"skills": ["carpentry"], "city": "Madurai", "goal_type": "explore"},
        ),
        (
            "நான் கொத்தனார், மதுரையில் இருக்கிறேன்",
            {"skills": ["masonry"], "city": "Madurai", "goal_type": "explore"},
        ),
        (
            "I do cooking work, khana banana aata hai",
            {"skills": ["hospitality"], "goal_type": "job_6_months"},
        ),
        (
            "I am a bus driver in Chennai, 12th pass",
            {"skills": ["automotive"], "education": "12th pass", "city": "Chennai"},
        ),
        (
            "I finished 12th in Madurai. I know farming and basic computer "
            "work, and I can type. I need a job that pays about 15000 "
            "rupees a month.",
            {
                "skills": ["attention to detail", "computer literacy", "agricultural science"],
                "education": "12th pass",
                "city": "Madurai",
                "income_monthly": 15000,
                "goal_type": "job_6_months",
            },
        ),
    ],
)
def test_extract_profile_verified_cases(text, expected):
    profile = extract_profile(text)
    for field, value in expected.items():
        actual = getattr(profile, field)
        if isinstance(value, list):
            assert sorted(actual) == sorted(value), (field, actual)
        else:
            assert actual == value, (field, actual)
    assert profile.raw_text == text  # raw transcript is kept verbatim


def test_extract_income_comma_before_number_regression():
    """Regression: a comma before a lakh-unit word ("…, looking for…")
    used to parse as a number, swallowing the real income later on."""
    amount, _ = parse_income(
        "electrical work, ITI done, looking for a job in Chennai, 20000 per month"
    )
    assert amount == 20000
    amount, _ = parse_income("I passed 12th in 2021")
    assert amount is None
    amount, _ = parse_income("no money mentioned")
    assert amount is None


def test_extract_income_devanagari_and_tamil_digits():
    amount, _ = parse_income("मुझे १५००० रुपये महीना चाहिए")
    assert amount == 15000
    amount, _ = parse_income("எனக்கு ௧௫௦௦௦ ரூபாய் மாதம் வேண்டும்")
    assert amount == 15000
    assert normalise_digits("௧௨௩") == "123"
    assert normalise_digits("१२३") == "123"


def test_extract_city_tamil_locative_sandhi():
    """Tamil sandhi changes the stem in the -இல் locative, so the plain
    city name is NOT a substring of it — locative aliases are needed."""
    assert extract_profile("சேலத்தில் வேலை வேண்டும்").city == "Salem"
    assert extract_profile("ஈரோட்டில் வேலை வேண்டும்").city == "Erode"
    assert extract_profile("காஞ்சிபுரத்தில் வேலை வேண்டும்").city == "Kanchipuram"
    assert extract_profile("குருகிராமத்தில் வேலை வேண்டும்").city == "Gurugram"
    assert extract_profile("கோழிக்கோட்டில் வேலை வேண்டும்").city == "Kozhikode"


def test_extract_asr_fixes():
    fixed, applied = fix_asr("i want electrisian work in madhurai")
    assert fixed == "i want electrician work in madurai"
    assert "electrisian->electrician" in applied
    assert "madhurai->madurai" in applied
    profile = extract_profile("i am a tailer in tuticorin")
    assert "fashion design" in profile.skills  # "tailor" maps to fashion design
    assert profile.city == "Thoothukudi"


def test_extract_word_boundaries_are_mark_aware():
    """The Devanagari alias "कर" (tax) must NOT match inside "नौकरी"
    (job): the vowel sign before it is a Unicode mark, not a letter."""
    assert contains_phrase("मुझे नौकरी चाहिए", "कर") is False
    assert contains_phrase("मुझे कर के बारे में बताओ", "कर") is True


def test_extract_bare_drive_is_not_a_skill():
    """Known verb-form gap (LIMITATIONS.md): "I drive a bus" names no
    skill — bare "drive" would false-positive on "pen drive". The
    occupation phrasing ("bus driver") extracts automotive."""
    assert extract_profile("I drive a bus").skills == []
    assert "automotive" in extract_profile("I am a bus driver").skills


# --------------------------------------------------------------------------- #
# Ingestion helpers
# --------------------------------------------------------------------------- #


def test_html_to_text_drops_boilerplate():
    html = (
        "<html><head><title>Test Page</title><style>.x{}</style>"
        "<script>alert(1)</script></head><body><nav>menu links here</nav>"
        "<h1>Free Online Courses for All</h1><p>SWAYAM offers free online courses from "
        "top Indian institutions for learners across the country.</p>"
        "<footer>copyright notice here</footer></body></html>"
    )
    assert html_title(html) == "Test Page"
    text = html_to_text(html)
    assert "Free Online Courses for All" in text
    assert "SWAYAM offers free online courses" in text
    assert "alert(1)" not in text
    assert "menu links here" not in text
    assert "copyright notice" not in text


def test_chunk_text_respects_size_and_header():
    sentences = [
        f"This is sentence number {i} about electrician training and "
        "safety practices in the workshop."
        for i in range(60)
    ]
    chunks = chunk_text(" ".join(sentences), header="Electricians")
    assert chunks
    assert all(c.startswith("Electricians") for c in chunks)
    for c in chunks:
        tokens = len(c.split())
        assert tokens <= 500, tokens
    # Overlap: a middle chunk shares words with its neighbours.
    assert len(chunks) >= 2


def test_chunk_text_drops_tiny_fragments():
    assert chunk_text("Too short.") == []


def test_onet_document_says_preparation_level_not_job_zone():
    """The O*NET label "Job Zone" injected the word "job" into all 974
    chunks (df 95%), drowning real signal — documents say
    "Preparation level" instead (Stage 2 eval finding)."""
    chunks = ingest_onet()
    assert len(chunks) == 974
    for chunk in chunks:
        assert "Job Zone" not in chunk.text
        assert "Preparation level" in chunk.text
        assert chunk.source_id.startswith("onet:")
        assert chunk.source_url.startswith("https://www.onetonline.org/link/summary/")
        assert chunk.licence.startswith("CC BY 4.0")
        assert chunk.language == "en"
        assert chunk.topic == "occupation"
    doc = occupation_document(
        {
            "id": "47-2111.00",
            "title": "Electricians",
            "description": "Install electrical systems.",
            "job_zone": 3,
            "skills": ["Installation"],
            "knowledge": ["Building and Construction"],
            "technology": [],
            "alt_titles": [],
        }
    )
    assert "Preparation level: 3" in doc
    assert "Job Zone" not in doc


# --------------------------------------------------------------------------- #
# RAG store round-trip
# --------------------------------------------------------------------------- #


def test_rag_store_round_trip(tmp_path):
    db = str(tmp_path / "rag.db")
    migrate(db)  # RagStore expects the v12 table to exist
    store = RagStore(db)
    chunks = [
        _chunk("onet:47-2111.00", "Electricians install electrical systems.", "Electricians"),
        _chunk("web:ncs", "NCS helpline 1514 is toll free.", "NCS", topic="employment"),
    ]
    assert store.replace_snapshot(chunks, "v1") == 2
    assert store.count() == 2
    assert store.count_by_topic() == {"occupation": 1, "employment": 1}
    assert store.snapshot_versions() == ["v1"]
    sources = {s["source_id"]: s for s in store.sources()}
    assert sources["web:ncs"]["chunks"] == 1
    assert sources["web:ncs"]["source_title"] == "NCS"
    loaded = store.all_chunks()
    assert [c.source_id for c in loaded] == ["onet:47-2111.00", "web:ncs"]
    assert loaded[0].text.startswith("Electricians install")
    assert loaded[0].snapshot_version == "v1"

    # A new snapshot replaces the old one wholesale.
    store.replace_snapshot([_chunk("onet:47-2111.00", "Updated text.", "Electricians")], "v2")
    assert store.count() == 1
    assert store.snapshot_versions() == ["v2"]
    assert store.all_chunks()[0].text == "Updated text."


def test_chunk_from_dict_requires_source_and_text():
    with pytest.raises(ValueError):
        Chunk.from_dict({"text": "no source"})
    with pytest.raises(ValueError):
        Chunk.from_dict({"source_id": "x"})


def test_snapshot_v2_loads_with_full_citations():
    """The shipped snapshot: 1,048 chunks (1,040 v1 + 8 wage chunks
    from Step 7B), every one carrying a source URL, title, date,
    licence and language."""
    chunks, meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    assert meta["version"] == "v2"
    assert len(chunks) == 1048
    topics = {c.topic for c in chunks}
    assert topics >= {
        "occupation",
        "courses",
        "skilling",
        "employment",
        "schemes",
        "rights",
        "scam",
        "wages",
    }
    for chunk in chunks:
        assert chunk.source_id and chunk.text
        assert chunk.source_url and chunk.source_title
        assert chunk.source_date and chunk.licence and chunk.language
    assert sum(1 for c in chunks if c.source_id.startswith("onet:")) == 974
    assert sum(1 for c in chunks if c.text.count("e-Shram")) == 0  # known gap, not hidden


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


def _small_retriever() -> HybridRetriever:
    return HybridRetriever(
        [
            _chunk(
                "onet:47-2111.00",
                "Electricians install, maintain, and repair electrical wiring, "
                "equipment, and fixtures. Preparation level: 3.",
                "Electricians",
            ),
            _chunk(
                "onet:47-3013.00",
                "Helpers--Electricians help electricians by performing duties "
                "requiring less skill. Preparation level: 1.",
                "Helpers--Electricians",
            ),
            _chunk(
                "web:ncs",
                "National Career Service helpline 1514 is toll free. NCS "
                "services are free of cost. Jobseekers should not pay fees "
                "to employers.",
                "NCS",
                topic="employment",
            ),
            _chunk(
                "web:swayam",
                "SWAYAM offers free online courses from Indian institutions. "
                "Learn programming, mathematics, and more at no cost.",
                "SWAYAM",
                topic="courses",
            ),
        ]
    )


def test_tokenize_stems_plurals_and_drops_stopwords():
    assert tokenize("Electricians install wiring") == ["electrician", "install", "wiring"]
    assert tokenize("how do i become an electrician") == ["become", "electrician"]
    assert "work" not in tokenize("plumber work")  # generic voice filler
    assert "job" in tokenize("job fraud")  # real word again after the Job Zone fix


def test_rewrite_query_fixes_asr_and_expands_places():
    rewritten, applied = rewrite_query("i want electrisian work in madhurai")
    assert rewritten == "i want electrician work in madurai madhurai"
    assert "electrisian->electrician" in applied
    rewritten, _ = rewrite_query("car mechanic")
    assert "automotive" in rewritten and "repairer" in rewritten
    # Synonym expansion matches on stemmed tokens, not substrings:
    # "card" must not fire the "car" expansion.
    rewritten, _ = rewrite_query("e-shram card")
    assert "automotive" not in rewritten


def test_hybrid_retrieval_ranks_exact_occupation_first():
    hits = _small_retriever().search("how do i become an electrician")
    assert hits[0].chunk.source_id == "onet:47-2111.00"
    assert hits[0].chunk.citation()["title"] == "Electricians"


def test_title_bonus_and_subordinate_penalty():
    """A title covering the query outranks a keyword-soup chunk, and a
    Helper occupation never beats its own trade when the query does not
    ask for a helper."""
    assert title_bonus("Electricians", {"electrician"}) > title_bonus(
        "Helpers--Electricians", {"electrician"}
    )
    assert title_bonus("Farmworkers and Laborers, Crop", {"farm", "worker"}) > 0.4
    hits = _small_retriever().search("electrician")
    assert hits[0].chunk.source_id == "onet:47-2111.00"


def test_retrieval_filters_apply_before_scoring():
    retriever = _small_retriever()
    hits = retriever.search("free courses", topic="courses")
    assert [h.chunk.source_id for h in hits] == ["web:swayam"]
    assert retriever.search("free courses", topic="occupation") == []
    assert retriever.search("free courses", language="ta") == []


def test_rerank_is_identity_in_v1():
    retriever = _small_retriever()
    from career_guidance.kaamvaani.rag import rerank

    hits = retriever.search("electrician")
    assert rerank("electrician", hits, top_k=5) == hits


# --------------------------------------------------------------------------- #
# Grounded answers and refusals
# --------------------------------------------------------------------------- #


def test_answer_quotes_chunk_with_citation():
    result = answer_question("how do i become an electrician", _small_retriever())
    assert result["refused"] is False
    assert "Electricians install" in result["answer"]
    assert result["citations"][0]["source_id"] == "onet:47-2111.00"
    assert result["citations"][0]["date"] == "2026-11-06"
    assert check_citation(result, ["onet:47-2111.00"]) is True
    assert check_citation(result, ["web:ncs"]) is False


def test_answer_refuses_medical_and_off_topic():
    for question in (
        "can you cure my back pain",
        "मुझे बुखार है, कौन सी दवा लूँ",
        "tell me today's horoscope",
        "what is the cricket score",
    ):
        result = answer_question(question, _small_retriever())
        assert result["refused"] is True, question
        assert result["reason"] == "out_of_scope"
        assert result["answer"] == "I don't know — please ask your coordinator."


def test_answer_refuses_ungrounded_questions():
    for question in ("what is my passport status", "who won the election"):
        result = answer_question(question, _small_retriever())
        assert result["refused"] is True, question
        assert result["reason"] == "no_grounding"


def test_answer_refuses_figure_question_without_a_figure():
    """A wage question whose top chunk carries no currency figure is
    refused — quoting framework text would look like an answer while
    answering nothing. But "what is the Code on Wages" is NOT a figure
    question (no "what wage" phrasing) and may answer."""
    retriever = HybridRetriever(
        [
            _chunk(
                "wiki:code-on-wages",
                "The Code on Wages, 2019 is an Act of the Parliament of "
                "India that consolidates laws relating to wages and bonus.",
                "Code on Wages, 2019",
                topic="rights",
            )
        ]
    )
    result = answer_question("what is the minimum wage in tamil nadu", retriever)
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"
    result = answer_question("what is the Code on Wages", retriever)
    assert result["refused"] is False


def test_answer_two_term_rule_blocks_single_incidental_match():
    """A weak match resting on one incidental word ("tell" in "tell me
    a joke") is not grounding, even when that word is rare. Measured on
    the real snapshot: the scam chunk matches "tell" at cosine 0.0763
    and the answer is refused."""
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    retriever = HybridRetriever(chunks)
    result = answer_question("tell me a joke", retriever)
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"


# --------------------------------------------------------------------------- #
# kv_rag router
# --------------------------------------------------------------------------- #


def test_kv_rag_status_empty_store_via_app(client):
    """The app fixture's scratch DB holds no RAG snapshot: status is
    honest about it (0 chunks), search returns no hits, ask refuses."""
    r = client.get("/api/v1/kv/rag/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["chunks"] == 0
    assert body["snapshot_versions"] == []
    r = client.post("/api/v1/kv/rag/search", json={"query": "electrician"})
    assert r.status_code == 200
    assert r.json()["hits"] == []
    r = client.post("/api/v1/kv/rag/ask", json={"question": "how do i become an electrician"})
    assert r.status_code == 200
    assert r.json()["refused"] is True


@pytest.fixture()
def populated_rag_client(tmp_path):
    """A standalone app with only the kv_rag router, over a scratch DB
    holding the real snapshot v2."""
    db = str(tmp_path / "rag.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_rag_router(settings))
    with TestClient(app) as client:
        yield client


def test_kv_rag_status_populated(populated_rag_client):
    r = populated_rag_client.get("/api/v1/kv/rag/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunks"] == 1048
    assert body["by_topic"]["occupation"] == 974
    assert body["by_topic"]["wages"] == 8
    assert body["snapshot_versions"] == ["v2"]
    assert any(s["source_id"] == "web:ncs" for s in body["sources"])


def test_kv_rag_search_and_ask_populated(populated_rag_client):
    r = populated_rag_client.post(
        "/api/v1/kv/rag/search", json={"query": "how do i become an electrician"}
    )
    assert r.status_code == 200, r.text
    hits = r.json()["hits"]
    assert hits[0]["chunk"]["source_id"] == "onet:47-2111.00"
    assert hits[0]["citation"]["title"] == "Electricians"

    r = populated_rag_client.post(
        "/api/v1/kv/rag/ask", json={"question": "what is the NCS helpline number"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is False
    assert body["citations"][0]["source_id"] == "web:ncs"
    # The helpline number is in the cited chunk (the 600-char answer
    # quote starts with the NCS page header, so it may not reach it).
    assert "1514" in body["retrieved"][0]["chunk"]["text"]

    r = populated_rag_client.post(
        "/api/v1/kv/rag/ask", json={"question": "can you cure my back pain"}
    )
    assert r.json()["refused"] is True
    assert r.json()["reason"] == "out_of_scope"


def test_kv_rag_search_validates_input(populated_rag_client):
    assert populated_rag_client.post("/api/v1/kv/rag/search", json={"query": ""}).status_code == 422
    assert (
        populated_rag_client.post(
            "/api/v1/kv/rag/search", json={"query": "x", "top_k": 99}
        ).status_code
        == 422
    )


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


def test_kv_rag_status_404_when_flag_off(app_module_kv_rag_off):
    with TestClient(app_module_kv_rag_off.app) as c:
        assert c.get("/api/v1/kv/rag/status").status_code == 404
        assert c.get("/api/v1/kv/voice/status").status_code == 200
        assert c.get("/api/v1/health").status_code == 200


# --------------------------------------------------------------------------- #
# Eval harness
# --------------------------------------------------------------------------- #


def test_kv_golden_set_schema_and_size():
    """At least 100 realistic voice-style cases across Tamil, Hindi and
    English, each with the fields the harness scores."""
    data = json.loads((ROOT / "eval" / "kv_golden.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) >= 100
    kinds = {c["kind"] for c in cases}
    assert kinds == {"profile", "retrieval", "refusal"}
    languages = {c["language"] for c in cases}
    assert languages >= {"en", "hi", "ta", "hi-roman", "ta-roman", "en-noisy"}
    for case in cases:
        assert case["id"] and case["text"]
        if case["kind"] == "profile":
            assert "expected" in case
        elif case["kind"] == "retrieval":
            assert case["expected_sources"]
        else:
            assert case["reason"] in ("out_of_scope", "no_grounding")


def test_run_eval_mechanics_on_tiny_golden(tmp_path):
    """The harness scores, thresholds and writes a report on a tiny
    golden file — without depending on the full golden-set run."""
    golden = {
        "version": 1,
        "snapshot": "data/kv_rag_snapshot_v2.jsonl",
        "cases": [
            {
                "id": "tiny-p1",
                "kind": "profile",
                "language": "en",
                "text": "I am a carpenter in Madurai, 10th pass, need a job",
                "expected": {
                    "skills": ["carpentry"],
                    "education": "10th pass",
                    "city": "Madurai",
                    "income_monthly": None,
                    "goal_type": "job_6_months",
                },
            },
            {
                "id": "tiny-r1",
                "kind": "retrieval",
                "language": "en",
                "text": "how do i become an electrician",
                "expected_sources": ["onet:47-2111.00"],
            },
            {
                "id": "tiny-x1",
                "kind": "refusal",
                "language": "en",
                "text": "can you cure my back pain",
                "reason": "out_of_scope",
            },
        ],
    }
    path = tmp_path / "tiny_golden.json"
    path.write_text(json.dumps(golden), encoding="utf-8")
    report = run_eval(path, ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    assert report["profile"]["accuracy"] == 1.0
    assert report["retrieval"]["recall_at_5"] == 1.0
    assert report["retrieval"]["faithfulness"] == 1.0
    assert report["refusal"]["accuracy"] == 1.0
    assert report["latency_ms"]["p50"] >= 0
