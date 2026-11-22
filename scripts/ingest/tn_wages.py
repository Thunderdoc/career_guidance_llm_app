"""Tamil Nadu STATE minimum-wage ingestion (queue item 5, 22 Nov 2026).

The sources are the Tamil Nadu Labour Department's own G.O. PDFs on
labour.tn.gov.in — Shops and Commercial Establishments (G.O.(2D)
No.65, 20.08.2024), Tailoring Industry (G.O.(2D) No.29, 31.05.2024)
and Agriculture (G.O.(2D) No.21, 07.06.2021). Step 7B (21 Nov 2026)
found these PDFs at their old ``gopdf/gopdf/...`` URLs returning HTTP
404; on 22 Nov 2026 the links on minimum-wages.php had moved to a new
``pdf/GO/...`` pattern and all return HTTP 200.

Each G.O. is a SCANNED PDF with no text layer, so the numbers were
read by OCR (RapidOCR/onnxruntime, 150 DPI) and every schedule page
was then read visually at 300 DPI to confirm the category-to-figure
grouping — the OCR flattens merged table cells, and the visual read
corrected the grouping in two places (shops general categories
(1)-(5) share one rate, not (1)-(2); (6)-(13) share one rate, not
(3)-(10)). The two DA per-point amounts the OCR garbled (shops
Rs.40.18, tailoring Rs.33.94) were read visually from the page
images, words and figures agreeing.

Honest scope — read before extending this file:

* Shops and tailoring give BASIC wages only. The G.O.s print basic
  rates plus a dearness-allowance FORMULA (a fixed rupee amount per
  month for every point the average Chennai City Consumer Price
  Index, base 2001=100, rises above a base figure), calculated every
  1 April by the Commissioner of Labour. The Commissioner's annual
  DA statement for the current year (cited by third parties as Order
  No. Z3/3459/2026, dated 18.02.2026, effective 01.04.2026) could
  not be located on any official site on 22 Nov 2026 — the TN Labour
  Department site (minimum-wages page, home page, CPI page, press
  releases, statistics), the TN Government Gazette weekly Part II
  Section 2 issues 7-18 of 2026, and the 2026 Extraordinary Gazette
  list were all searched — so NO current DA amount and NO total is
  stated for shops or tailoring anywhere in the data file or the
  chunks. The chunk text says so explicitly, so a worker is never
  shown a basic wage as if it were the total.
* Agriculture rates are all-inclusive (basic + cost of living
  allowance + cash value of concessions, per the G.O.'s own
  explanation), so the printed daily rate IS the total.
* Third-party aggregator figures were never used: one aggregator's
  hospitals DA figure (Rs.44 per point) contradicts the hospitals
  G.O. itself (Rs.53.90 per point, G.O.(2D) No.21, 26.05.2025).
* Four further TN G.O.s (construction, domestic work, hospitals,
  security guards) were downloaded and OCR'd on 22 Nov 2026 but are
  NOT ingested here — their schedules were not visually verified
  page by page. Wage questions about those employments still refuse
  honestly until their schedules are verified the same way.

Because the G.O.s print basic rates only, there are no printed
``basic + VDA = total`` sums to re-add the way Step 7B did for the
central order. The validator below therefore checks structure
(positive rates, consistent zone sets, a DA block exactly where the
G.O. has a DA clause) instead of sums — and the data file's
``notes.verification`` block records how each number was verified.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from career_guidance.kaamvaani.rag import Chunk

from .common import chunk_text

logger = logging.getLogger("kaamvaani.ingest.tn_wages")

ROOT = Path(__file__).resolve().parent.parent.parent
TN_WAGE_DATA_PATH = ROOT / "data" / "kv_tn_wage_tables.json"

SOURCE_ID_PREFIX = "web:tn-labour"
TOPIC = "wages"
LANGUAGE = "en"


def _money(n: int) -> str:
    """Format a rupee figure the way the figure-grounding rule reads
    it: the ₹ sign directly before the number, thousands separated."""
    return f"₹{n:,}"


def _da_sentence(emp: dict) -> str:
    """The G.O.'s dearness-allowance formula, in the G.O.'s own terms,
    plus the honest statement that the current declared amount is not
    in the knowledge base — so no total is ever implied."""
    da = emp["da"]
    return (
        f"Dearness allowance is paid on top of these basic wages: "
        f"Rs.{da['per_point']:.2f} ({da['per_point_words']}) per month "
        f"for every one point the Average Chennai City Consumer Price "
        f"Index (base 2001=100) rises over and above "
        f"{da['base_points']} points (the average for the year "
        f"{da['base_year']}), {da['calc']}. The Commissioner of "
        f"Labour declares the dearness allowance amount every year, "
        f"and the current declared amount is not in this knowledge "
        f"base, so no total wage is given here — add the declared "
        f"dearness allowance to the basic wage to get the total "
        f"minimum wage."
    )


def _zone_rates(rate: dict, zones: list[str]) -> str:
    """'Zone A ₹7,390; Zone B ₹7,328; ...' for one category row."""
    return "; ".join(f"Zone {z} {_money(rate[z])}" for z in zones)


def employment_chunk_text(emp: dict) -> str:
    """Prose table for one TN scheduled employment. The employment's
    plain-language synonyms (from the data file's ``keywords``) are
    in the first sentence so worker-style queries match it. Every
    rate line says 'basic' (or 'all-inclusive' for agriculture) so a
    chunk retrieved on its own never reads as a total it is not.
    The text LEADS with a one-line summary carrying the printed
    rate range (min/max of the schedule — no arithmetic beyond the
    range of printed rates), because the answerer quotes only the
    first 600 characters: without it the quote is intro + keywords
    + G.O. line and no figure at all."""
    zones = sorted(emp["zones"])
    values = []
    for rate in emp["rates"]:
        if "rate" in rate:
            values.append(rate["rate"])
        else:
            values.extend(rate[z] for z in zones)
    if emp.get("all_inclusive"):
        summary = (
            f"{emp['title']} — Tamil Nadu state minimum wage: "
            f"{_money(min(values))} to {_money(max(values))} "
            f"{emp['unit']}, all-inclusive."
        )
    else:
        summary = (
            f"{emp['title']} — Tamil Nadu state minimum wage: basic "
            f"{_money(min(values))} to {_money(max(values))} "
            f"{emp['unit']} by zone and category, plus dearness "
            f"allowance."
        )
    lines = [
        summary,
        f"Tamil Nadu state minimum wage — {emp['title']} "
        f"({emp['keywords']}). {emp['go']}, in force from its "
        f"publication in the Tamil Nadu Government Gazette.",
    ]
    if emp.get("all_inclusive"):
        lines.append(
            "These rates are all-inclusive — basic wage, cost of "
            "living allowance and the cash value of concessions "
            "together — so the rate below is the total minimum wage. "
            "The cost of food, if any is supplied, is not included "
            "and must not be deducted from these wages."
        )
    else:
        lines.append(
            "These are BASIC wages "
            f"{emp['unit']} — the dearness allowance declared by the "
            "Commissioner of Labour is paid on top, so the basic "
            "wage alone is not the total minimum wage. " + _da_sentence(emp)
        )
    if zones:
        zone_defs = "; ".join(f"Zone {z} — {emp['zones'][z]}" for z in zones)
        lines.append(f"Zones: {zone_defs}.")
    if emp.get("daily_rule"):
        lines.append(emp["daily_rule"])
    for rate in emp["rates"]:
        if "rate" in rate:  # agriculture: single all-inclusive daily rate
            lines.append(f"{rate['category']}: {_money(rate['rate'])} {rate['note']}.")
        else:
            lines.append(f"{rate['category']} (basic, {emp['unit']}): {_zone_rates(rate, zones)}.")
    if emp.get("extra"):
        lines.append(emp["extra"])
    lines.append(
        "Tamil Nadu state rates — a central-government establishment "
        "(railways, mines, banks) follows the central sphere rates, "
        "not these rates."
    )
    return " ".join(lines)


def validate_tn_wage_data(data: dict) -> None:
    """Fail loudly on bad structure — a wage table whose rates are
    not positive, whose zone sets disagree, or whose DA block does
    not match its G.O. must never be ingested. (No sums to re-add:
    the G.O.s print basic rates only — see the module docstring.)"""
    checked = 0
    for emp in data["employments"]:
        if emp.get("all_inclusive"):
            if emp.get("da") is not None:
                raise ValueError(
                    f"TN wage data {emp['id']}: all-inclusive rates must not carry a DA block"
                )
        else:
            da = emp.get("da")
            if not da:
                raise ValueError(
                    f"TN wage data {emp['id']}: a DA block is required "
                    "(the G.O. has a dearness-allowance clause)"
                )
            if not (da["per_point"] > 0 and da["base_points"] > 0):
                raise ValueError(
                    f"TN wage data {emp['id']}: DA per-point rate and base points must be positive"
                )
        zone_keys: tuple[str, ...] | None = None
        for rate in emp["rates"]:
            if "rate" in rate:
                checked += 1
                if not (isinstance(rate["rate"], int) and rate["rate"] > 0):
                    raise ValueError(
                        f"TN wage data {emp['id']} {rate['category']}: bad rate {rate['rate']!r}"
                    )
                continue
            keys = tuple(sorted(k for k in rate if k != "category"))
            if zone_keys is None:
                zone_keys = keys
            elif keys != zone_keys:
                raise ValueError(
                    f"TN wage data {emp['id']} {rate['category']}: zone set {keys} != {zone_keys}"
                )
            if set(keys) != set(emp["zones"]):
                raise ValueError(
                    f"TN wage data {emp['id']} {rate['category']}: "
                    f"zone set {keys} != declared zones "
                    f"{sorted(emp['zones'])}"
                )
            for key in keys:
                checked += 1
                if not (isinstance(rate[key], int) and rate[key] > 0):
                    raise ValueError(
                        f"TN wage data {emp['id']} {rate['category']} {key}: bad rate {rate[key]!r}"
                    )
    logger.info("TN wage data validated: %d rates checked", checked)


def ingest_tn_wages(
    snapshot_version: str, data_path: Path = TN_WAGE_DATA_PATH
) -> tuple[list[Chunk], dict]:
    """Build the TN wage chunks from the verified data file. Returns
    (chunks, fetch-log entry) in the runner's shape — the 'fetch'
    is the local data file, whose per-employment provenance names
    the official G.O. PDF each schedule was read from.

    There is deliberately NO TN scope chunk: a first version had one
    (figure-free, like the central scope chunk), but the eval showed
    it outranking the employment chunks on wage questions — it is
    short and dense with 'Tamil Nadu', 'minimum wage' and 'Chennai',
    so it took rank 1 for the shops question itself (kv-x017) and
    for construction and law questions, and its figure-free text
    then made the answerer refuse. The scope context it carried
    (which employments are covered, the DA honesty statement, the
    central-vs-state distinction) already lives in every employment
    chunk's intro and closing sentences; the not-covered list lives
    in docs/SOURCES.md and LIMITATIONS.md instead, where it cannot
    outrank a rate.
    """
    data = json.loads(data_path.read_text(encoding="utf-8"))
    validate_tn_wage_data(data)
    chunks: list[Chunk] = []
    for emp in data["employments"]:
        text = employment_chunk_text(emp)
        # No header: the first sentence already identifies the chunk
        # ("Tamil Nadu state minimum wage — ..."), and a "Minimum
        # wage" header would repeat the phrase and let short wage
        # chunks outrank the Code on Wages chunk on law questions
        # (measured Step 7B: kv-r070/r100).
        for index, piece in enumerate(chunk_text(text)):
            chunks.append(
                Chunk(
                    source_id=f"{SOURCE_ID_PREFIX}-{emp['id']}",
                    source_url=emp["source_url"],
                    # The citation title is the employment name alone:
                    # the title bonus (rag.py) reads source_title, and
                    # the employment name is what a wage question asks
                    # about — "G.O.(2D) No.65" boilerplate would dilute
                    # the bonus and add no meaning. The chunk text
                    # still names the G.O., and the citation URL is
                    # the official PDF.
                    source_title=emp["title"],
                    source_date=emp["source_date"],
                    licence=emp["licence"],
                    language=LANGUAGE,
                    topic=TOPIC,
                    state="Tamil Nadu",
                    district="",
                    chunk_index=index,
                    text=piece,
                    snapshot_version=snapshot_version,
                )
            )
    log_entry = {
        "source_id": "tn-wages",
        "url": f"{data_path} (read from labour.tn.gov.in G.O. PDFs)",
        "ok": True,
        "status": None,
        "bytes": data_path.stat().st_size,
        "chunks": len(chunks),
        "error": "",
    }
    logger.info("ingest TN wages: %d chunks", len(chunks))
    return chunks, log_entry
