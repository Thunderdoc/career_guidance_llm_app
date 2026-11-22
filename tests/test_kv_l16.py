"""Kaam-Vaani L16: answers in the question's language.

Covers: the inverted glossary (English term -> Tamil/Hindi term,
plural forms, the "card" denylist), the glossary answer renderer
(longest-phrase-first substitution, figures/separators preserved,
no-match stays English), the fixed translated refusal strings,
``answer_question`` integration (rendered ``answer`` + verified
English ``answer_en`` + language/method metadata, citations still
grounded, verification still on the English quote, Roman-script
questions stay English), the translator injection point (stub used,
failure falls back to glossary), the ``translate_answer`` trace
span, and the eval's answer-language coverage on the gold set.
"""

from __future__ import annotations

import re

import pytest

from career_guidance.kaamvaani.answer_lang import (
    METHOD_FIXED,
    METHOD_GLOSSARY,
    METHOD_NONE,
    REFUSAL_TEXT_LOCAL,
    TranslatedAnswer,
    load_inverted_glossary,
    render_answer,
    translate_answer_glossary,
    translate_refusal,
)
from career_guidance.kaamvaani.citations import verify_answer_dict
from career_guidance.kaamvaani.rag import (
    REFUSAL_TEXT,
    Chunk,
    HybridRetriever,
    answer_question,
    check_citation,
)
from career_guidance.kaamvaani.trace import Trace

_TAMIL_RE = re.compile(r"[\u0b80-\u0bff]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")


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
            "equipment, and fixtures. Skills: Troubleshooting, Repairing, "
            "Installation. Preparation level: 3.",
            "Electricians",
        ),
        _chunk(
            "onet:47-2152.02",
            "Plumbers install and repair pipes, fixtures, and other plumbing "
            "equipment. Preparation level: 2.",
            "Plumbers",
        ),
        _chunk(
            "wages:construction-unskilled-a",
            "Central sphere minimum wage — Construction or maintenance of "
            "roads, runways and buildings. Unskilled: Area A ₹840 per day "
            "(basic ₹523 + VDA ₹317). Labour Bureau order File No. "
            "6/1/2026-VDA, dated 30 September 2026.",
            "Construction unskilled Area A",
            topic="wages",
        ),
    ]


@pytest.fixture()
def retriever() -> HybridRetriever:
    return HybridRetriever(_small_chunks())


# --------------------------------------------------------------------------- #
# Inverted glossary
# --------------------------------------------------------------------------- #


def test_inverted_glossary_has_occupation_and_phrase_terms() -> None:
    ta = load_inverted_glossary("ta")
    assert ta["electrician"] in ("மின் பணியாளர்", "மின்வினைஞர்")
    assert ta["minimum wage"] == "குறைந்தபட்ச சம்பளம்"
    assert ta["security guard"] == "காவலாளி"
    hi = load_inverted_glossary("hi")
    assert hi["electrician"] in ("बिजली मिस्त्री", "इलेक्ट्रीशियन")
    assert hi["minimum wage"] == "न्यूनतम मजदूरी"


def test_inverted_glossary_plural_forms() -> None:
    ta = load_inverted_glossary("ta")
    assert ta["electricians"] == ta["electrician"]
    # A direct glossary plural wins over the generated form:
    # "workers" is its own entry ("தொழிலாளர்கள்"), not the
    # singular "தொழிலாளர்" with an "s".
    assert ta["workers"] == "தொழிலாளர்கள்"
    assert ta["workers"] != ta["worker"]
    hi = load_inverted_glossary("hi")
    assert hi["courses"] == hi["course"]


def test_inverted_glossary_denies_card_homonym() -> None:
    # L17: "card" is the ID-card/playing-card homonym — a wrong
    # substitution is worse than an untranslated word.
    assert "card" not in load_inverted_glossary("ta")
    assert "card" not in load_inverted_glossary("hi")


# --------------------------------------------------------------------------- #
# Glossary renderer
# --------------------------------------------------------------------------- #


def test_glossary_renderer_substitutes_title_and_terms() -> None:
    out = translate_answer_glossary(
        "Electricians install, maintain, and repair electrical wiring.",
        "ta",
    )
    assert out.method == METHOD_GLOSSARY
    assert out.language == "ta"
    assert out.terms_translated >= 1
    assert _TAMIL_RE.search(out.text)
    # The occupation name is Tamil; the connective prose stays English.
    assert out.text.startswith("மின் பணியாளர்") or out.text.startswith("மின்வினைஞர்")
    # "repair" is a glossary term too, so it translates as well.
    assert "பழுதுபார்ப்பு" in out.text
    assert "install, maintain, and" in out.text


def test_glossary_renderer_longest_phrase_first() -> None:
    out = translate_answer_glossary("The minimum wage is ₹840 per day.", "ta")
    # The 2-gram "minimum wage" wins over the 1-grams "minimum" +
    # "wage" — one term, not two.
    assert "குறைந்தபட்ச சம்பளம்" in out.text
    assert out.terms_translated == 1


def test_glossary_renderer_preserves_figures_and_separators() -> None:
    text = (
        "Central sphere minimum wage — Construction.\nUnskilled: Area A ₹840 per day (2026-10-01)."
    )
    out = translate_answer_glossary(text, "hi")
    assert "₹840" in out.text
    assert "2026-10-01" in out.text
    assert "\n" in out.text  # title/body line break survives


def test_glossary_renderer_no_match_stays_english() -> None:
    out = translate_answer_glossary("Zebra xylophone quantum.", "ta")
    assert out.text == "Zebra xylophone quantum."
    assert out.language == "en"
    assert out.method == METHOD_NONE
    assert out.terms_translated == 0
    assert out.translated_share == 0.0


def test_glossary_renderer_reports_honest_share() -> None:
    out = translate_answer_glossary("Electricians install wiring.", "ta")
    # "மின் பணியாளர்" is two whitespace tokens, so 2 of 4 tokens
    # are Tamil — the share says so, no rounding up.
    assert out.translated_share == pytest.approx(0.5, abs=0.01)


# --------------------------------------------------------------------------- #
# render_answer + refusals
# --------------------------------------------------------------------------- #


def test_render_answer_english_and_roman_unchanged() -> None:
    text = "Electricians install wiring."
    for language in (None, "", "en", "roman"):
        out = render_answer(text, language)
        assert out.text == text
        assert out.language == "en"
        assert out.method == METHOD_NONE


def test_render_answer_uses_injected_translator() -> None:
    def stub(text: str, language: str) -> TranslatedAnswer:
        return TranslatedAnswer(
            text="STUB-" + language, language=language, method="stub", terms_translated=9
        )

    out = render_answer("Electricians install wiring.", "ta", translator=stub)
    assert out.text == "STUB-ta"
    assert out.method == "stub"
    assert out.terms_translated == 9


def test_render_answer_translator_failure_falls_back_to_glossary() -> None:
    def broken(text: str, language: str) -> TranslatedAnswer:
        raise RuntimeError("model missing")

    out = render_answer("Electricians install wiring.", "ta", translator=broken)
    assert out.method == METHOD_GLOSSARY
    assert _TAMIL_RE.search(out.text)


def test_translate_refusal_tamil_hindi_english() -> None:
    text, language, method = translate_refusal("ta")
    assert text == REFUSAL_TEXT_LOCAL["ta"]
    assert language == "ta"
    assert method == METHOD_FIXED
    assert _TAMIL_RE.search(text)
    text, language, method = translate_refusal("hi")
    assert text == REFUSAL_TEXT_LOCAL["hi"]
    assert language == "hi"
    assert method == METHOD_FIXED
    assert _DEVANAGARI_RE.search(text)
    text, language, method = translate_refusal("en")
    assert text == REFUSAL_TEXT
    assert language == "en"
    assert method == METHOD_NONE
    text, _, _ = translate_refusal("roman")
    assert text == REFUSAL_TEXT  # Roman-script users read Latin script


# --------------------------------------------------------------------------- #
# answer_question integration
# --------------------------------------------------------------------------- #


def test_tamil_answer_rendered_with_english_quote_and_citation(retriever) -> None:
    result = answer_question("மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?", retriever)
    assert result["refused"] is False
    assert result["answer_language"] == "ta"
    assert result["translation_method"] == METHOD_GLOSSARY
    assert result["translated_terms"] >= 1
    assert _TAMIL_RE.search(result["answer"])
    # The verified English quote is still there, grounded and cited.
    assert result["answer_en"].startswith("Electricians install")
    assert check_citation(result, ["onet:47-2111.00"])
    assert result["verification"]["verified"] is True
    assert result["citations"][0]["source_id"] == "onet:47-2111.00"


def test_hindi_answer_rendered_with_figures_preserved(retriever) -> None:
    result = answer_question("निर्माण कार्य के लिए न्यूनतम मजदूरी कितनी है?", retriever)
    assert result["refused"] is False
    assert result["answer_language"] == "hi"
    assert _DEVANAGARI_RE.search(result["answer"])
    assert "₹840" in result["answer"]  # the figure survives rendering
    assert "₹840" in result["answer_en"]
    assert check_citation(result, ["wages:construction-unskilled-a"])


def test_english_answer_unchanged(retriever) -> None:
    result = answer_question("how do i become an electrician", retriever)
    assert result["refused"] is False
    assert result["answer"] == result["answer_en"]
    assert result["answer_language"] == "en"
    assert result["translation_method"] == METHOD_NONE
    assert result["translated_terms"] == 0


def test_roman_question_stays_english(retriever) -> None:
    result = answer_question("min velai eppadi seivathu", retriever)
    assert result["refused"] is False
    assert result["answer_language"] == "en"
    assert result["translation_method"] == METHOD_NONE


def test_tamil_refusal_uses_translated_text(retriever) -> None:
    result = answer_question("எனக்கு காய்ச்சல், என்ன மருந்து சாப்பிட வேண்டும்?", retriever)
    assert result["refused"] is True
    assert result["reason"] == "out_of_scope"
    assert result["answer"] == REFUSAL_TEXT_LOCAL["ta"]
    assert result["answer_en"] == REFUSAL_TEXT
    assert result["answer_language"] == "ta"
    assert result["translation_method"] == METHOD_FIXED


def test_verify_answer_dict_reads_english_quote(retriever) -> None:
    result = answer_question("மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?", retriever)
    verdict = verify_answer_dict(result)
    assert verdict is not None
    assert verdict.verified is True  # verified against answer_en, not the Tamil text


def test_translate_answer_trace_span(retriever) -> None:
    trace = Trace("/api/v1/kv/rag/ask", query_hash="0" * 16)
    answer_question("மின் பணியாளர் ஆவதற்கு என்ன செய்ய வேண்டும்?", retriever, trace=trace)
    record = trace.finish(status="ok", outcome="answered")
    spans = {span["name"]: span for span in record["spans"]}
    assert "translate_answer" in spans
    detail = spans["translate_answer"]["detail"]
    assert detail["method"] == METHOD_GLOSSARY
    assert detail["language"] == "ta"
    assert detail["terms"] >= 1
    # No raw text in the trace — method/language/counts only.
    assert "answer" not in detail


# --------------------------------------------------------------------------- #
# Eval coverage on the gold set
# --------------------------------------------------------------------------- #


def test_eval_reports_answer_language_for_hindi_tamil() -> None:
    """The KV eval records answer language per retrieval case: HI/TA
    cases carry answer_language + translation_method, and the
    aggregate reports the rendered share. (Slow: builds the full
    retriever — the Step 7A precedent for eval-level tests.)"""
    from eval.run_kv import DEFAULT_SNAPSHOT, GOLDEN, run_eval

    report = run_eval(GOLDEN, DEFAULT_SNAPSHOT)
    assert report["retrieval"]["faithfulness"] >= 0.90  # L16 must not regress grounding
    section = report["retrieval"]["answer_language"]
    for family in ("ta", "hi"):
        assert section[family]["cases"] > 0
        assert section[family]["rendered"] > 0
        assert section[family]["mean_translated_share"] > 0
    rendered = [r for r in report["results"] if r["kind"] == "retrieval" and not r["refused"]]
    tamil = [r for r in rendered if r["language"].startswith("ta")]
    assert tamil, "gold set has Tamil retrieval cases"
    assert all(r["answer_language"] in ("ta", "en") for r in tamil)
    assert any(r["answer_language"] == "ta" for r in tamil)
