"""Kaam-Vaani Step 7A: multilingual retrieval (glossary translation,
dense embeddings + RRF fusion, per-language eval).

Covers: the Tamil/Hindi/Roman glossary translator (longest-phrase
first, Tamil suffix strip with the pulli retry, Latin pass-through,
English no-op), the combining-mark shredding regression (the shared
``[^\\w]+`` tokenizer splits Indic words at vowel signs — the translator
must not use it), retrieval of English chunks from Tamil/Hindi
questions, the translation fields on grounded answers, reciprocal rank
fusion (unit + fused search with a stub dense scorer + metadata
filters), the dense retriever (model-backed, skipped without
``sentence-transformers``; missing-package error without it), and the
per-language eval breakdown.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from career_guidance.kaamvaani.dense import DenseRetriever
from career_guidance.kaamvaani.rag import (
    Chunk,
    HybridRetriever,
    answer_question,
    reciprocal_rank_fusion,
)
from career_guidance.kaamvaani.translate import (
    GLOSSARY_PATH,
    _glossary_tokens,
    translate_query,
)
from eval.run_kv import DEFAULT_SNAPSHOT, run_eval

ROOT = Path(__file__).resolve().parent.parent

_ST_AVAILABLE = importlib.util.find_spec("sentence_transformers") is not None


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


def _small_chunks() -> list[Chunk]:
    return [
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
            "onet:47-2152.02",
            "Plumbers install and repair pipes, fixtures, and other plumbing "
            "equipment. Preparation level: 2.",
            "Plumbers",
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


def _small_retriever() -> HybridRetriever:
    return HybridRetriever(_small_chunks())


# --------------------------------------------------------------------------- #
# Glossary translation
# --------------------------------------------------------------------------- #


def test_translate_tamil_occupation_queries():
    assert translate_query("மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?").text == "electrician become"
    assert translate_query("பேருந்து ஓட்டுநர் வேலைக்கு என்ன தேவை?").text == "bus driver work"
    assert translate_query("ஐடிஐயில் என்னென்ன தொழில் படிப்புகள் உள்ளன?").text == "ITI trades courses"
    assert translate_query("குறைந்தபட்ச சம்பள சட்டம் என்ன சொல்கிறது?").text == "minimum wage law"
    assert translate_query("இலவச ஆன்லைன் படிப்புகள் எங்கே கிடைக்கும்?").text == ("free online courses")


def test_translate_hindi_occupation_queries():
    assert translate_query("बिजली मिस्त्री बनने के लिए क्या करना चाहिए?").text == "electrician become"
    assert translate_query("बस ड्राइवर की नौकरी के लिए क्या चाहिए?").text == "bus driver job"
    assert translate_query("मुफ्त ऑनलाइन कोर्स कहाँ मिलेंगे?").text == "free online course"
    assert translate_query("मजदूरी संहिता क्या है?").text == "Code on Wages"


def test_translate_longest_phrase_first():
    # "பேருந்து ஓட்டுநர்" must win over bare "ஓட்டுநர்" (driver), and
    # "बिजली का काम" over bare "काम" (work).
    assert translate_query("பேருந்து ஓட்டுநர்").text == "bus driver"
    assert translate_query("बिजली का काम क्या होता है?").text == "electrical work"
    assert translate_query("வேலை தேட என்சிஎஸ் எப்படி உதவும்?").text == (
        "job search NCS National Career Service"
    )


def test_translate_tamil_suffix_strip():
    # Locative -யில், dative -க்கு, and the plural dative -களுக்கு
    # (which loses the "கள்" pulli to the u-vowel sign).
    assert translate_query("ஐடிஐயில்").text == "ITI"
    assert translate_query("வேலைக்கு").text == "work"
    assert translate_query("தொழிலாளர்களுக்கு சமூக பாதுகாப்பு என்றால் என்ன?").text == "workers social security"


def test_translate_latin_tokens_pass_through():
    assert translate_query("PMKVY பயிற்சி என்றால் என்ன?").text == "pmkvy training"
    assert translate_query("NSDC कोर्स के बारे में बताइए").text == "nsdc course"


def test_translate_english_is_noop():
    result = translate_query("how do i become an electrician")
    assert result.text == "how do i become an electrician"
    assert result.applied == ()
    assert result.source_language == ""


def test_translate_roman_forms():
    assert translate_query("min velai").text == "electrician"
    assert translate_query("kheti").text == "farm farming agriculture"


def test_translate_no_combining_mark_shredding():
    """Regression: the shared [^\\w]+ tokenizer splits Tamil/Hindi words
    at combining marks (vowel signs, pulli), so "மின் பணியாளர்" once
    translated to "security guard" and "என்ன" to "data entry". Whole
    words must stay whole."""
    assert translate_query("மின் பணியாளர்").text == "electrician"
    assert "security guard" not in translate_query("மின் பணியாளர்").text
    result = translate_query("என்ன?")
    assert result.text == "" and result.applied == ()


def test_glossary_keys_unique_after_tokenization():
    """No two glossary entries may collapse onto the same token tuple
    (a silent overwrite would mistranslate one of them), and every
    entry must have a non-empty English side."""
    data = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))
    seen: dict[tuple[str, ...], str] = {}
    for section in ("tamil", "hindi", "roman"):
        for source, english in (data.get(section) or {}).items():
            assert str(english).strip(), f"empty English for {source!r}"
            key = tuple(_glossary_tokens(str(source)))
            assert key, f"empty key for {source!r}"
            assert key not in seen, f"key collision: {source!r} vs {seen[key]!r}"
            seen[key] = str(source)
    assert len(seen) >= 100


# --------------------------------------------------------------------------- #
# Retrieval from Tamil/Hindi questions
# --------------------------------------------------------------------------- #


def test_tamil_query_retrieves_english_chunk():
    hits = _small_retriever().search("மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?")
    assert hits[0].chunk.source_id == "onet:47-2111.00"
    hits = _small_retriever().search("குழாய் பணியாளர் வேலை எப்படி இருக்கும்?")
    assert hits[0].chunk.source_id == "onet:47-2152.02"


def test_hindi_query_retrieves_english_chunk():
    hits = _small_retriever().search("बिजली मिस्त्री बनने के लिए क्या करना चाहिए?")
    assert hits[0].chunk.source_id == "onet:47-2111.00"


def test_tamil_scheme_query_retrieves_courses_chunk():
    hits = _small_retriever().search("இலவச ஆன்லைன் படிப்புகள் எங்கே கிடைக்கும்?")
    assert hits[0].chunk.source_id == "web:swayam"


def test_answer_question_reports_translation():
    result = answer_question("மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?", _small_retriever())
    assert result["refused"] is False
    assert result["translated_query"] == "electrician become"
    assert result["source_language"] == "ta"
    result = answer_question("how do i become an electrician", _small_retriever())
    assert result["translated_query"] is None
    assert result["source_language"] is None


# --------------------------------------------------------------------------- #
# Reciprocal rank fusion
# --------------------------------------------------------------------------- #


def test_reciprocal_rank_fusion_orders_by_summed_reciprocals():
    fused = reciprocal_rank_fusion([[0, 1, 2], [2, 0]])
    assert [idx for idx, _ in fused] == [0, 2, 1]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[2][1] == pytest.approx(1 / 62)


class _StubDense:
    """A dense scorer with canned per-chunk cosines (no model)."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    def scores(self, query: str) -> list[float]:
        return list(self._scores)


def test_dense_fusion_reorders_by_rrf():
    # Hybrid ranks Electricians #1, Helpers #2 for "electrician". The
    # stub dense ranks Helpers #2 and Electricians LAST, so RRF puts
    # Helpers first — and the dense-only Plumbers chunk appears with a
    # hybrid score of 0.
    chunks = _small_chunks()
    stub = _StubDense([0.5, 0.8, 0.9, 0.7, 0.6])
    retriever = HybridRetriever(chunks, dense=stub)
    hits = retriever.search("electrician")
    assert hits[0].chunk.source_id == "onet:47-3013.00"
    assert hits[0].raw_dense == pytest.approx(0.8)
    assert hits[0].dense > 0
    plumber = next(h for h in hits if h.chunk.source_id == "onet:47-2152.02")
    assert plumber.score == 0.0
    assert plumber.raw_dense == pytest.approx(0.9)


def test_dense_fusion_respects_metadata_filters():
    chunks = _small_chunks()
    stub = _StubDense([0.1, 0.1, 0.1, 0.1, 0.99])  # SWAYAM first on dense
    retriever = HybridRetriever(chunks, dense=stub)
    hits = retriever.search("free courses", topic="occupation")
    assert all(h.chunk.topic == "occupation" for h in hits)
    assert not any(h.chunk.source_id == "web:swayam" for h in hits)


def test_answer_top_cosine_uses_dense_when_stronger():
    chunks = _small_chunks()
    stub = _StubDense([0.9, 0.1, 0.1, 0.1, 0.1])  # Electricians first on dense
    retriever = HybridRetriever(chunks, dense=stub)
    result = answer_question("how do i become an electrician", retriever)
    assert result["refused"] is False
    assert result["top_cosine"] == pytest.approx(0.9)


# --------------------------------------------------------------------------- #
# Per-language eval + dense retriever
# --------------------------------------------------------------------------- #


def test_run_eval_reports_per_language_metrics(tmp_path):
    """The harness breaks retrieval metrics out by language family."""
    golden = {
        "version": 1,
        "snapshot": "data/kv_rag_snapshot_v1.jsonl",
        "cases": [
            {
                "id": "tiny-r-en",
                "kind": "retrieval",
                "language": "en",
                "text": "how do i become an electrician",
                "expected_sources": ["onet:47-2111.00"],
            },
            {
                "id": "tiny-r-hi",
                "kind": "retrieval",
                "language": "hi",
                "text": "बिजली मिस्त्री बनने के लिए क्या करना चाहिए?",
                "expected_sources": ["onet:47-2111.00"],
            },
            {
                "id": "tiny-r-ta",
                "kind": "retrieval",
                "language": "ta",
                "text": "மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?",
                "expected_sources": ["onet:47-2111.00"],
            },
        ],
    }
    path = tmp_path / "tiny_golden.json"
    path.write_text(json.dumps(golden), encoding="utf-8")
    report = run_eval(path, DEFAULT_SNAPSHOT)
    per_language = report["retrieval"]["per_language"]
    assert set(per_language) == {"en", "hi", "ta"}
    for family in ("en", "hi", "ta"):
        assert per_language[family]["cases"] == 1
        assert per_language[family]["recall_at_5"] == 1.0


@pytest.mark.skipif(_ST_AVAILABLE, reason="sentence-transformers is installed in this env")
def test_dense_retriever_missing_package_raises():
    with pytest.raises(RuntimeError, match="sentence-transformers"):
        DenseRetriever(_small_chunks())


@pytest.mark.skipif(not _ST_AVAILABLE, reason="needs sentence-transformers + torch (dense venv)")
def test_dense_retriever_reads_tamil_query():
    """The multilingual model reads Tamil natively: no translation on
    the dense side. Downloads ~470 MB on first run (cached after).

    Measured 21 Nov 2026 (intfloat/multilingual-e5-small): for the
    Tamil query the two electrical chunks score 0.8307
    (Helpers--Electricians) and 0.8279 (Electricians) — effectively
    tied, the helper ahead by noise — while the unrelated chunks
    score 0.75-0.78. So the test pins what the model actually
    delivers: Tamil comprehension (the electrical family ranks
    above the unrelated chunks, Electricians in the top 2), NOT
    rank-1 precision between siblings. The sibling tie is the same
    mechanism behind the dense eval's faithfulness drop
    (EVAL_REPORT.md Step 7A; L52). The compressed score band
    (every chunk >= 0.75 for an electrician query) is why dense
    cosines cannot drive the refusal gates.
    """
    retriever = DenseRetriever(_small_chunks())
    ranked = retriever.search("மின் பணியாளர் வேலை", top_k=5)
    top2 = {_small_chunks()[i].source_id for i, _ in ranked[:2]}
    assert top2 == {"onet:47-2111.00", "onet:47-3013.00"}
    assert _small_chunks()[ranked[0][0]].source_id in top2
    # The electrical family outranks the unrelated chunks.
    assert {ranked[2][0], ranked[3][0], ranked[4][0]} == {2, 3, 4}


def test_dense_retriever_with_stubbed_model(monkeypatch):
    """DenseRetriever's encode/score/search paths run in the MAIN venv
    with a stubbed SentenceTransformer (no 470 MB download). The stub
    returns 2-D unit vectors keyed on the word "electric", and records
    the texts it is asked to encode — so this also pins the E5
    "query: "/"passage: " prefixes and the model-name passthrough.
    """
    import sys
    import types

    import numpy as np

    seen: list[list[str]] = []

    class StubModel:
        def __init__(self, name: str):
            self.name = name

        def encode(self, texts, **kwargs):
            seen.append(list(texts))
            assert kwargs.get("normalize_embeddings") is True
            vecs = []
            for text in texts:
                hot = 1.0 if "electric" in text.lower() else 0.0
                vecs.append([hot, 1.0 - hot])
            return np.array(vecs, dtype=float)

    stub_module = types.ModuleType("sentence_transformers")
    stub_module.SentenceTransformer = StubModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", stub_module)

    retriever = DenseRetriever(_small_chunks(), model_name="stub-model")
    assert retriever.model_name == "stub-model"
    assert retriever.dim == 2
    # Chunk texts were encoded with the passage prefix.
    assert seen[0][0].startswith("passage: ")
    assert "Electricians install" in seen[0][0]
    # The query is encoded with the query prefix; the electrical
    # chunks score 1.0, the rest 0.0.
    scores = retriever.scores("electrician work")
    assert seen[1] == ["query: electrician work"]
    assert scores[0] == 1.0 and scores[1] == 1.0
    assert scores[2] == 0.0 and scores[3] == 0.0 and scores[4] == 0.0
    ranked = retriever.search("electrician work", top_k=2)
    assert {i for i, _ in ranked} == {0, 1}
    # Empty chunk list scores nothing (no encode call for chunks).
    empty = DenseRetriever([], model_name="stub-model")
    assert empty.scores("anything") == []
    assert empty.search("anything") == []
