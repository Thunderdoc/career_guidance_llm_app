"""Kaam-Vaani Step 7B tests: sourced central-sphere minimum-wage data.

Covers the wage data file (arithmetic + provenance), the wages
ingester (8 chunks, figures present, scope chunk figure-free), the
figure-rule extension (Tamil/Hindi/Roman patterns + law exclusion),
the currency-figure false-positive fix ("Sewers,"), the title-bonus
extension to wage chunks, and end-to-end wage retrieval + refusal
on snapshot v2.
"""

import json

import pytest

from career_guidance.kaamvaani.rag import (
    _CURRENCY_FIGURE,
    _FIGURE_QUESTION,
    _LAW_QUESTION,
    HybridRetriever,
    answer_question,
    load_snapshot_file,
    title_bonus,
)
from scripts.ingest.wages import (
    WAGE_DATA_PATH,
    ingest_wages,
    validate_wage_data,
)

ROOT = WAGE_DATA_PATH.parent.parent  # WAGE_DATA_PATH lives in data/
SNAPSHOT_V2 = ROOT / "data" / "kv_rag_snapshot_v2.jsonl"


# --------------------------------------------------------------------------- #
# Wage data file
# --------------------------------------------------------------------------- #
def test_wage_data_file_loads_with_provenance():
    """The data file names its official source, order and dates — a
    wage table without provenance is not ingestible."""
    data = json.loads(WAGE_DATA_PATH.read_text(encoding="utf-8"))
    assert len(data["employments"]) == 7
    prov = data["provenance"]
    assert prov["source"].startswith("Labour Bureau")
    assert prov["source_url"].startswith("https://labourbureau.gov.in/")
    assert prov["source_date"] == "2026-09-30"
    assert prov["order"] == "File No. 6/1/2026-VDA, dated 30 September 2026"
    assert prov["effective_from"] == "2026-10-01"
    assert "CENTRAL SPHERE ONLY" in prov["scope_note"]


def test_wage_data_sums_check_out():
    """Every printed basic+VDA=total sum re-adds (52 sums)."""
    data = json.loads(WAGE_DATA_PATH.read_text(encoding="utf-8"))
    validate_wage_data(data)  # raises on any mismatch


def test_wage_data_validation_fails_on_corrupt_total():
    """A corrupted total fails loudly — bad wage numbers must never
    reach a worker."""
    data = json.loads(WAGE_DATA_PATH.read_text(encoding="utf-8"))
    data["employments"][0]["rates"][0]["A"]["total"] += 1
    with pytest.raises(ValueError, match="basic.*VDA.*total|!="):
        validate_wage_data(data)


# --------------------------------------------------------------------------- #
# Wages ingester
# --------------------------------------------------------------------------- #
def test_ingest_wages_builds_eight_chunks_with_citations():
    """One chunk per scheduled employment + one scope chunk, each
    carrying the official source URL, date and licence."""
    chunks, log = ingest_wages("v2-test")
    assert log["chunks"] == 8
    assert len(chunks) == 8
    ids = {c.source_id for c in chunks}
    assert ids == {
        "web:labourbureau-vda-construction",
        "web:labourbureau-vda-agriculture",
        "web:labourbureau-vda-sweeping-cleaning",
        "web:labourbureau-vda-loading-unloading",
        "web:labourbureau-vda-watch-ward",
        "web:labourbureau-vda-mines",
        "web:labourbureau-vda-stone-mines-piece",
        "web:labourbureau-vda-scope",
    }
    for chunk in chunks:
        assert chunk.topic == "wages"
        assert chunk.source_url.startswith("https://labourbureau.gov.in/")
        assert chunk.source_date == "2026-09-30"
        assert chunk.licence == "Public information (Government of India)"
        assert chunk.snapshot_version == "v2-test"


def test_wage_employment_chunks_carry_figures_and_scope_warning():
    """Every employment chunk has a ₹ figure (the figure-grounding
    rule needs one) and says it is central-sphere only."""
    chunks, _log = ingest_wages("v2-test")
    for chunk in chunks:
        if chunk.source_id.endswith("-scope"):
            continue
        assert "₹" in chunk.text
        assert "Central sphere rates only" in chunk.text


def test_wage_scope_chunk_is_figure_free():
    """The scope chunk deliberately carries NO ₹ figure, so a bare
    'what is the minimum wage?' (no employment named) hits the
    figure rule and refuses instead of answering with a rate for
    the wrong job."""
    chunks, _log = ingest_wages("v2-test")
    scope = next(c for c in chunks if c.source_id.endswith("-scope"))
    assert "₹" not in scope.text
    assert "Madurai" in scope.text  # Area B list
    assert "Chennai" in scope.text  # Area A list


def test_snapshot_v2_has_eight_wage_chunks():
    chunks, meta = load_snapshot_file(SNAPSHOT_V2)
    assert meta["version"] == "v2"
    wage = [c for c in chunks if c.topic == "wages"]
    assert len(wage) == 8
    assert len(chunks) == 1048


# --------------------------------------------------------------------------- #
# Figure rule: Tamil / Hindi / Roman patterns + law exclusion
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "query",
    [
        "what is the minimum wage for construction work?",
        "how much should a security guard be paid?",
        "கட்டுமான வேலைக்கு குறைந்தபட்ச கூலி எவ்வளவு?",
        "பாதுகாவலர் வேலைக்கு நாள் சம்பளம் எவ்வளவு?",
        "விவசாய வேலைக்கு குறைந்தபட்ச சம்பளம் என்ன?",
        "निर्माण कार्य के लिए न्यूनतम मजदूरी कितनी है?",
        "सुरक्षा गार्ड को दिन में कितना वेतन मिलना चाहिए?",
        "construction kaam ka kitna mazdoori hai?",
    ],
)
def test_figure_question_fires_for_wage_figure_questions(query):
    assert _FIGURE_QUESTION.search(query)


@pytest.mark.parametrize(
    "query",
    [
        "ஊதிய சட்டம் என்றால் என்ன?",
        "குறைந்தபட்ச சம்பள சட்டம் என்ன சொல்கிறது?",
        "मजदूरी संहिता क्या है?",
        "न्यूनतम मजदूरी कानून क्या कहता है?",
        "what does the minimum wage law say?",
    ],
)
def test_law_questions_are_not_figure_questions(query):
    """A question about the law asks for an explanation, not a
    number — the law exclusion must fire even though a wage word
    and 'what' are both present (Step 7B regression: kv-r068/r098
    refused on the figure rule before the exclusion)."""
    assert _FIGURE_QUESTION.search(query)  # the wage+what pair IS there
    assert _LAW_QUESTION.search(query)  # ...but the law marker wins
    assert not (_FIGURE_QUESTION.search(query) and not _LAW_QUESTION.search(query))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("₹840 per day", True),
        ("Rs 500", True),
        ("Rs. 15,000", True),
        ("500 rupees", True),
        ("Sewers, and makers", False),
        ("workers, 500 of them", False),
        ("Preparation level: 3", False),
        ("200 workers", False),
        ("Rs, and then text", False),
    ],
)
def test_currency_figure_pattern(text, expected):
    """The 'Sewers,' regression: 'rs' at the end of a word plus a
    comma is not rupees, and a bare number is not a figure. The
    Tailors chunk passed the old pattern on 'Sewers,' and answered
    a minimum-wage question with a job description (kv-x016)."""
    assert bool(_CURRENCY_FIGURE.search(text)) is expected


# --------------------------------------------------------------------------- #
# Title bonus for wage chunks
# --------------------------------------------------------------------------- #
def test_title_bonus_fires_for_wage_chunk_titles():
    """A wage chunk's title is its employment name, like an
    occupation title — it earns the bonus when the query names the
    employment, and earns nothing when it does not."""
    assert title_bonus("Watch and ward (security guards)", {"security", "guard", "wage"}) > 0
    assert title_bonus("Sweeping and cleaning", {"construction", "wage"}) == 0
    # The scope chunk's title matches no wage-question term.
    assert (
        title_bonus(
            "Labour Bureau VDA order — scope and areas",
            {"minimum", "wage", "construction"},
        )
        == 0
    )


# --------------------------------------------------------------------------- #
# End-to-end wage retrieval + refusal on snapshot v2
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def retriever_v2():
    chunks, _meta = load_snapshot_file(SNAPSHOT_V2)
    return HybridRetriever(chunks)


@pytest.mark.parametrize(
    "query,expected_source",
    [
        (
            "what is the minimum wage for unskilled construction work?",
            "web:labourbureau-vda-construction",
        ),
        (
            "how much should a security guard be paid per day?",
            "web:labourbureau-vda-watch-ward",
        ),
        (
            "what is the monthly minimum wage for unskilled construction work in Chennai?",
            "web:labourbureau-vda-construction",
        ),
        (
            "which area is Madurai in for minimum wages?",
            "web:labourbureau-vda-scope",
        ),
        (
            "கட்டுமான வேலைக்கு குறைந்தபட்ச கூலி எவ்வளவு?",
            "web:labourbureau-vda-construction",
        ),
        (
            "பாதுகாவலர் வேலைக்கு நாள் சம்பளம் எவ்வளவு?",
            "web:labourbureau-vda-watch-ward",
        ),
        (
            "निर्माण कार्य के लिए न्यूनतम मजदूरी कितनी है?",
            "web:labourbureau-vda-construction",
        ),
        (
            "अकुशल निर्माण मजदूर का मासिक वेतन कितना है?",
            "web:labourbureau-vda-construction",
        ),
    ],
)
def test_wage_questions_answer_from_the_right_chunk(retriever_v2, query, expected_source):
    result = answer_question(query, retriever_v2)
    assert result["refused"] is False
    assert result["citations"][0]["source_id"] == expected_source
    assert "₹" in result["answer"] or expected_source.endswith("-scope")


@pytest.mark.parametrize(
    "query",
    [
        "what is the minimum wage for a tailor in Madurai?",
        "what is the minimum wage for shop workers in Tamil Nadu?",
        "what will the minimum wage be in 2027?",
        "what is the minimum wage for IT workers in Chennai?",
    ],
)
def test_unanswerable_wage_questions_refuse(retriever_v2, query):
    """TN state rates, future rates and non-scheduled employments
    are not in the KB — the assistant must say it does not know,
    never answer with a central rate for the wrong job."""
    result = answer_question(query, retriever_v2)
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"
