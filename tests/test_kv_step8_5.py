"""Kaam-Vaani Step 8.5: citation verifier.

Covers: sentence splitting (including the truncation marker),
overlap + support verdicts, truncated-sentence handling, dropping
unsupported sentences, verifying an answer dict (including the
refused / no-citation / missing-chunk None cases), the
answer_question integration (verification summary on every
answer, the unverified-refusal wiring via monkeypatched
verification — unreachable with verbatim quotes), and the
gold-set measurement pinned in the suite: 115/115 answers
verified, 591/591 sentences supported, 0 dropped — including
the 6 unfaithful cases, which are VERIFIED but not faithful
(grounding is not relevance, L58).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import career_guidance.kaamvaani.rag as rag_module
from career_guidance.kaamvaani.citations import (
    VerificationResult,
    drop_unsupported,
    split_sentences,
    verify_answer,
    verify_answer_dict,
)
from career_guidance.kaamvaani.rag import (
    HybridRetriever,
    answer_question,
    check_citation,
    load_snapshot_file,
)

ROOT = Path(__file__).resolve().parent.parent

CHUNK = (
    "Electricians install and repair electrical wiring in homes and "
    "buildings. They read blueprints and follow safety codes. "
    "Training takes two years through an apprenticeship."
)

UNFAITHFUL = {"kv-r015", "kv-r033", "kv-r056", "kv-r059", "kv-r086", "kv-r089"}


@pytest.fixture(scope="module")
def retriever():
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    return HybridRetriever(chunks)


@pytest.fixture(scope="module")
def gold_cases():
    return json.loads((ROOT / "eval" / "kv_golden.json").read_text())["cases"]


# --------------------------------------------------------------------------- #
# Splitting + overlap + verdicts
# --------------------------------------------------------------------------- #


def test_split_sentences():
    assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]
    assert split_sentences("No terminator here") == ["No terminator here"]
    assert split_sentences("First. Second…") == ["First.", "Second"]
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_verify_verbatim_quote():
    result = verify_answer(CHUNK, CHUNK)
    assert result.verified is True
    assert len(result.sentences) == 3
    assert result.supported_count == 3
    assert result.truncated_count == 0
    assert all(v.overlap == 1.0 for v in result.sentences)
    assert result.support_rate == 1.0


def test_verify_unsupported_sentence():
    answer = (
        "Electricians install and repair electrical wiring in homes and "
        "buildings. They earn forty lakh rupees per month in Madurai."
    )
    result = verify_answer(answer, CHUNK)
    assert result.verified is False
    assert result.supported_count == 1
    assert result.sentences[0].supported is True
    assert result.sentences[1].supported is False
    assert result.sentences[1].overlap < 0.8
    assert result.support_rate == pytest.approx(0.5)


def test_verify_truncated_last_sentence_excluded():
    # The final sentence is cut mid-sentence (the 600-char cap):
    # it is reported as truncated and excluded from the verdict,
    # even though its fragment scores below the support threshold.
    answer = (
        "Electricians install and repair electrical wiring in homes and "
        "buildings. Zqxj wvnb plok…"  # nonsense fragment, overlap 0.0
    )
    result = verify_answer(answer, CHUNK)
    assert result.sentences[-1].truncated is True
    assert result.sentences[-1].supported is False
    assert result.verified is True  # the truncated fragment cannot fail it
    assert result.truncated_count == 1


def test_verify_empty_answer():
    result = verify_answer("", CHUNK)
    assert result.verified is False
    assert result.sentences == ()


def test_drop_unsupported():
    answer = (
        "Electricians install and repair electrical wiring in homes and "
        "buildings. They earn forty lakh rupees per month in Madurai. "
        "Training takes two years through an apprenticeship."
    )
    cleaned, dropped = drop_unsupported(answer, CHUNK)
    assert dropped == 1
    assert "forty lakh" not in cleaned
    assert "Training takes two years" in cleaned
    # Nothing grounded: empty result.
    cleaned, dropped = drop_unsupported("Zqxj wvnb plok.", CHUNK)
    assert cleaned == ""
    assert dropped == 1


def test_drop_unsupported_keeps_grounded_truncation():
    answer = CHUNK[:60].rsplit(" ", 1)[0] + "…"
    cleaned, dropped = drop_unsupported(answer, CHUNK)
    assert dropped == 0
    assert cleaned == answer  # the fragment is grounded; the "…" stays


# --------------------------------------------------------------------------- #
# Verifying an answer dict
# --------------------------------------------------------------------------- #


def _answer_dict(answer, chunk_text, source_id="onet:47-2111.00"):
    return {
        "refused": False,
        "answer": answer,
        "citations": [{"source_id": source_id}],
        "retrieved": [{"chunk": {"source_id": source_id, "text": chunk_text}}],
    }


def test_verify_answer_dict():
    result = verify_answer_dict(_answer_dict(CHUNK, CHUNK))
    assert result is not None and result.verified is True
    assert verify_answer_dict({"refused": True, "answer": "", "citations": []}) is None
    assert verify_answer_dict({"refused": False, "answer": CHUNK, "citations": []}) is None
    missing = _answer_dict(CHUNK, CHUNK, source_id="onet:47-2111.00")
    missing["retrieved"] = [{"chunk": {"source_id": "other:1", "text": CHUNK}}]
    assert verify_answer_dict(missing) is None


# --------------------------------------------------------------------------- #
# answer_question integration
# --------------------------------------------------------------------------- #


def test_answer_carries_verification_summary(retriever):
    result = answer_question("how do i become an electrician", retriever)
    assert result["refused"] is False
    verification = result["verification"]
    assert verification["verified"] is True
    assert verification["sentences"] >= 1
    assert verification["supported"] == verification["sentences"]
    assert verification["dropped_sentences"] == 0


def test_refused_answer_carries_no_verification(retriever):
    result = answer_question("tell me a joke", retriever)
    assert result["refused"] is True
    assert result["verification"] is None


def test_unverified_refusal_wiring(monkeypatch, retriever):
    # Unreachable with verbatim quotes (they always verify), so the
    # wiring is pinned with a stubbed verifier: an unverified answer
    # whose sentences all drop refuses with reason "unverified".
    monkeypatch.setattr(
        rag_module,
        "verify_answer",
        lambda answer, chunk: VerificationResult((), False),
    )
    monkeypatch.setattr(rag_module, "drop_unsupported", lambda answer, chunk: ("", 1))
    result = answer_question("how do i become an electrician", retriever)
    assert result["refused"] is True
    assert result["reason"] == "unverified"
    assert result["citations"] == []


def test_partial_drop_wiring(monkeypatch, retriever):
    # A dropped sentence shortens the answer but keeps it grounded.
    from career_guidance.kaamvaani.citations import SentenceVerdict

    calls = {"n": 0}

    def fake_verify(answer, chunk):
        calls["n"] += 1
        if calls["n"] == 1:
            return VerificationResult(
                (
                    SentenceVerdict("kept sentence.", 1.0, True, False),
                    SentenceVerdict("dropped sentence.", 0.0, False, False),
                ),
                False,
            )
        return VerificationResult((SentenceVerdict("kept sentence.", 1.0, True, False),), True)

    monkeypatch.setattr(rag_module, "verify_answer", fake_verify)
    monkeypatch.setattr(rag_module, "drop_unsupported", lambda answer, chunk: ("kept sentence.", 1))
    result = answer_question("how do i become an electrician", retriever)
    assert result["refused"] is False
    assert result["answer"] == "kept sentence."
    assert result["verification"]["dropped_sentences"] == 1


# --------------------------------------------------------------------------- #
# Gold-set measurement, pinned
# --------------------------------------------------------------------------- #


def test_gold_set_all_answers_verified(retriever, gold_cases):
    retrieval = [c for c in gold_cases if c.get("kind") == "retrieval"]
    assert len(retrieval) == 115
    sentences = supported = dropped = 0
    for case in retrieval:
        result = answer_question(case["text"], retriever, top_k=5)
        assert result["refused"] is False, case["id"]
        verification = result["verification"]
        assert verification["verified"] is True, case["id"]
        assert verification["dropped_sentences"] == 0, case["id"]
        sentences += verification["sentences"]
        supported += verification["supported"]
        dropped += verification["dropped_sentences"]
    # Measured 21 Nov 2026: 591 sentences, all supported, none dropped.
    assert sentences == 591
    assert supported == 591
    assert dropped == 0


def test_unfaithful_cases_are_verified_but_not_faithful(retriever, gold_cases):
    # Grounding is not relevance (L58): these six answers are
    # verbatim from their cited chunk (verified) but the chunk is
    # the wrong one for the question (not faithful). The verifier
    # must NOT catch them — catching them is the ranker's job.
    by_id = {c["id"]: c for c in gold_cases}
    assert UNFAITHFUL <= set(by_id)
    for case_id in sorted(UNFAITHFUL):
        case = by_id[case_id]
        result = answer_question(case["text"], retriever, top_k=5)
        assert result["verification"]["verified"] is True, case_id
        assert check_citation(result, sorted(case["expected_sources"])) is False, case_id
