"""Kaam-Vaani queue item 5 tests: Tamil Nadu state minimum wages.

Covers the TN wage data file (structure + provenance — the G.O.s
print basic rates only, so there are no printed sums to re-add),
the TN ingester (6 chunks, no scope chunk), the DA-formula honesty
wording (basics, never totals, for shops/tailoring), and end-to-end
TN wage retrieval + refusal on snapshot v3.
"""

import json

import pytest

from career_guidance.kaamvaani.rag import (
    HybridRetriever,
    answer_question,
    load_snapshot_file,
)
from scripts.ingest.tn_wages import (
    TN_WAGE_DATA_PATH,
    ingest_tn_wages,
    validate_tn_wage_data,
)

ROOT = TN_WAGE_DATA_PATH.parent.parent  # TN_WAGE_DATA_PATH lives in data/
SNAPSHOT_V3 = ROOT / "data" / "kv_rag_snapshot_v3.jsonl"

EXPECTED_IDS = {
    "web:tn-labour-shops",
    "web:tn-labour-tailoring",
    "web:tn-labour-agriculture",
}


def _load_data() -> dict:
    return json.loads(TN_WAGE_DATA_PATH.read_text(encoding="utf-8"))


def _retriever_v3() -> HybridRetriever:
    chunks, _meta = load_snapshot_file(SNAPSHOT_V3)
    return HybridRetriever(chunks)


# --------------------------------------------------------------------------- #
# TN wage data file
# --------------------------------------------------------------------------- #
def test_tn_wage_data_file_loads_with_provenance():
    """Three employments, each naming its official G.O. — number,
    date and the labour.tn.gov.in PDF it was read from."""
    data = _load_data()
    assert len(data["employments"]) == 3
    by_id = {emp["id"]: emp for emp in data["employments"]}
    assert by_id["shops"]["go"].startswith("G.O.(2D) No.65")
    assert by_id["shops"]["source_date"] == "2024-08-20"
    assert by_id["tailoring"]["go"].startswith("G.O.(2D) No.29")
    assert by_id["tailoring"]["source_date"] == "2024-05-31"
    assert by_id["agriculture"]["go"].startswith("G.O.(2D) No.21")
    assert by_id["agriculture"]["source_date"] == "2021-06-07"
    for emp in data["employments"]:
        assert emp["source_url"].startswith("https://labour.tn.gov.in/pdf/GO/")
        assert emp["licence"] == "Public information (Government of Tamil Nadu)"


def test_tn_wage_data_rate_counts():
    """65 rate rows in total: shops 35, tailoring 24, agriculture 6."""
    data = _load_data()
    counts = {emp["id"]: len(emp["rates"]) for emp in data["employments"]}
    assert counts == {"shops": 35, "tailoring": 24, "agriculture": 6}
    assert sum(counts.values()) == 65


def test_tn_wage_data_validation_passes():
    """The shipped file validates (positive rates, consistent zone
    sets, DA block exactly where the G.O. has a DA clause)."""
    validate_tn_wage_data(_load_data())


def test_tn_wage_data_validation_fails_on_bad_rate():
    """A non-positive or non-integer rate fails loudly."""
    data = _load_data()
    data["employments"][0]["rates"][0]["A"] = -1
    with pytest.raises(ValueError, match="bad rate"):
        validate_tn_wage_data(data)


def test_tn_wage_data_validation_fails_on_zone_mismatch():
    """A rate row missing a zone fails — every row must cover every
    zone, or a worker in the missing zone gets no answer."""
    data = _load_data()
    del data["employments"][0]["rates"][0]["D"]
    with pytest.raises(ValueError, match="zone set"):
        validate_tn_wage_data(data)


def test_tn_wage_data_validation_fails_on_missing_da_block():
    """Shops and tailoring G.O.s carry a DA clause — a data file
    without it would silently drop the formula."""
    data = _load_data()
    data["employments"][0]["da"] = None
    with pytest.raises(ValueError, match="DA block is required"):
        validate_tn_wage_data(data)


def test_tn_wage_data_validation_fails_on_extra_da_block():
    """Agriculture rates are all-inclusive — a DA block there would
    be an invented clause."""
    data = _load_data()
    data["employments"][2]["da"] = {
        "per_point": 40.18,
        "base_points": 161,
        "base_year": 2010,
    }
    with pytest.raises(ValueError, match="must not carry a DA block"):
        validate_tn_wage_data(data)


# --------------------------------------------------------------------------- #
# TN ingester
# --------------------------------------------------------------------------- #
def test_ingest_tn_wages_builds_six_chunks_no_scope():
    """Shops 3 + tailoring 2 + agriculture 1 — and deliberately NO
    scope chunk: the first version's figure-free scope chunk
    outranked the employment chunks on wage questions and made the
    answerer refuse (kv-x017, kv-r107, kv-r110, kv-r113)."""
    chunks, log = ingest_tn_wages("v3-test")
    assert log["chunks"] == 6
    assert len(chunks) == 6
    assert {c.source_id for c in chunks} == EXPECTED_IDS
    assert not any(c.source_id.endswith("-scope") for c in chunks)
    for chunk in chunks:
        assert chunk.state == "Tamil Nadu"
        assert chunk.source_url.startswith("https://labour.tn.gov.in/pdf/GO/")
        assert chunk.licence == "Public information (Government of Tamil Nadu)"
        assert not chunk.text.startswith("Minimum wage")


def test_tn_chunks_state_da_formula_and_no_total():
    """Shops/tailoring chunks print the verified DA formula AND say
    plainly that no total is given — a retrieved middle piece must
    never read as a total wage."""
    chunks, _ = ingest_tn_wages("v3-test")
    shops = " ".join(c.text for c in chunks if c.source_id.endswith("-shops"))
    tailoring = " ".join(c.text for c in chunks if c.source_id.endswith("-tailoring"))
    assert "Rs.40.18" in shops
    assert "Rs.33.94" in tailoring
    for text in (shops, tailoring):
        assert "dearness allowance" in text
        assert "no total wage is given here" in text
        assert "(basic, per month)" in text
    # Every rate line in shops/tailoring says "(basic, per month)".
    for chunk in chunks:
        if chunk.source_id.endswith("-agriculture"):
            continue
        for line in chunk.text.split("\n"):
            if "Rs." in line and "—" in line:
                assert "(basic, per month)" in line, line


def test_tn_chunks_lead_with_rate_range():
    """Each chunk's first line carries the printed rate range, so
    the answerer's 600-character quote always shows a figure —
    without it the quote is intro + keywords + G.O. line and no
    rate at all."""
    chunks, _ = ingest_tn_wages("v3-test")
    ranges = {
        "web:tn-labour-shops": ("₹6,470", "₹7,390", "basic"),
        "web:tn-labour-tailoring": ("₹7,400", "₹8,819", "basic"),
        "web:tn-labour-agriculture": ("₹229", "₹500", "all-inclusive"),
    }
    firsts = {}
    for chunk in chunks:
        if chunk.chunk_index == 0:
            firsts[chunk.source_id] = chunk.text
    assert set(firsts) == set(ranges)
    for source_id, (low, high, kind) in ranges.items():
        first_line = firsts[source_id].split(". ")[0]
        assert low in first_line and high in first_line, first_line
        assert kind in first_line, first_line


def test_tn_agriculture_chunk_is_all_inclusive_no_da():
    """Agriculture rates are all-inclusive totals — the chunk says
    so and carries no DA formula to confuse them with basics."""
    chunks, _ = ingest_tn_wages("v3-test")
    agri = " ".join(c.text for c in chunks if c.source_id.endswith("-agriculture"))
    assert "all-inclusive" in agri
    assert "₹229" in agri
    assert "dearness allowance" not in agri


# --------------------------------------------------------------------------- #
# Snapshot v3 + end-to-end retrieval
# --------------------------------------------------------------------------- #
def test_snapshot_v3_carries_tn_chunks():
    """Snapshot v3 holds the 6 TN chunks (and no TN scope chunk)."""
    chunks, _meta = load_snapshot_file(SNAPSHOT_V3)
    tn = [c for c in chunks if c.source_id.startswith("web:tn-labour")]
    assert len(tn) == 6
    assert {c.source_id for c in tn} == EXPECTED_IDS


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "what is the minimum wage for a tailor in Madurai?",
            "web:tn-labour-tailoring",
        ),
        (
            "what is the minimum wage for shop workers in Tamil Nadu?",
            "web:tn-labour-shops",
        ),
        (
            "what is the minimum wage for farm workers in Tamil Nadu?",
            "web:tn-labour-agriculture",
        ),
    ],
)
def test_tn_wage_questions_answer_from_tn_chunk(question, expected):
    """A TN wage question answers from the TN G.O. chunk, not from a
    central chunk and not with a refusal."""
    result = answer_question(question, _retriever_v3())
    assert not result["refused"]
    assert result["citations"][0]["source_id"] == expected
    assert "₹" in result["answer"]


def test_tn_construction_question_answers_from_central_chunk():
    """Construction is a TN scheduled employment whose G.O. schedule
    was NOT visually verified, so it stays out of the KB — but the
    central construction chunk exists. The employment-grounding
    walk must answer from it (its own text says it is a central
    rate), never from a TN chunk for another employment: before the
    walk, this question answered from the TN agriculture chunk."""
    result = answer_question(
        "what is the Tamil Nadu state minimum wage for construction workers?",
        _retriever_v3(),
    )
    assert not result["refused"]
    assert result["citations"][0]["source_id"] == "web:labourbureau-vda-construction"


def test_uncovered_tn_employment_refuses():
    """Domestic work is a TN scheduled employment with no verified
    schedule in the KB — the question must refuse (no_grounding via
    the employment-grounding walk) rather than borrow another
    employment's rate."""
    result = answer_question(
        "what is the minimum wage for domestic workers in Tamil Nadu?",
        _retriever_v3(),
    )
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"


def test_hospital_wage_question_refuses():
    """Hospitals are a TN scheduled employment with no verified
    schedule in the KB — the question refuses. (It refuses via the
    out-of-scope medical pattern, which fires before the walk —
    either way, no rate is quoted for an uncovered employment.)"""
    result = answer_question(
        "what is the minimum wage for hospital workers in Tamil Nadu?",
        _retriever_v3(),
    )
    assert result["refused"] is True


def test_employment_vocabulary_covers_wage_data():
    """The answerer's employment vocabulary must cover every term
    in the wage data files' titles and keyword lists (plus the TN
    not-covered employments) — a new employment added to the data
    without its terms in the vocabulary would silently lose the
    employment-grounding check."""
    from career_guidance.kaamvaani.rag import _WAGE_EMPLOYMENT_TERMS

    generic = {
        "32",
        "ancillary",
        "and",
        "bee-keeping",
        "boy",
        "bunds",
        "bunk",
        "climbing",
        "export",
        "goods",
        "hair",
        "industry",
        "iron",
        "keeper",
        "labour",
        "labourer",
        "machine",
        "master",
        "minerals",
        "named",
        "of",
        "operations",
        "or",
        "ore",
        "petrol",
        "piece",
        "rates",
        "room",
        "seedlings",
        "shed",
        "store",
        "to",
        "trees",
        "trimming",
        "work",
        "worker",
        "works",
        "—",
    }
    missing = set()
    for path in (
        ROOT / "data" / "kv_wage_tables_2026-10.json",
        ROOT / "data" / "kv_tn_wage_tables.json",
    ):
        data = json.loads(path.read_text(encoding="utf-8"))
        for emp in data["employments"]:
            text = f"{emp.get('title', '')} {emp.get('keywords', '')}"
            for token in text.lower().replace(",", " ").split():
                token = token.strip("().")
                if token and token not in generic:
                    if token not in _WAGE_EMPLOYMENT_TERMS:
                        missing.add(token)
    # The TN not-covered employments (notes field, not a table).
    tn = json.loads((ROOT / "data" / "kv_tn_wage_tables.json").read_text(encoding="utf-8"))
    for term in ("domestic", "hospitals"):
        assert term in _WAGE_EMPLOYMENT_TERMS
    assert tn["notes"]["not_covered"]  # the note itself must exist
    assert not missing, sorted(missing)
