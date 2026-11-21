"""Central-sphere minimum-wage ingestion (Step 7B).

The source is the Labour Bureau's VDA order (File No. 6/1/2026-VDA,
dated 30 September 2026, rates from 1 October 2026) — the official
central-sphere minimum-wage order. The order is a SCANNED PDF with
no text layer (pypdf extracts 1,915 chars from 30 pages), so the
numbers were read by OCR (RapidOCR/onnxruntime, 150 DPI, 21 Nov
2026) and every total verified two ways: each printed
``basic + VDA = total`` sum was re-added (52 sums, 0 mismatches),
and all totals were cross-checked against three independent
readings of the same order (factohr.com, shiftelio.com,
in.scrolljob.org — all agree).

The verified numbers live in ``data/kv_wage_tables_2026-10.json``
(with full provenance in its ``provenance`` block); this module
builds one chunk per scheduled employment from that file plus one
scope chunk. It performs NO network fetch and NO OCR itself — the
OCR evidence step is ``scripts/ingest/ocr_vda_order.py`` (optional,
needs rapidocr-onnxruntime + poppler) and the structured file is
rebuilt from its output by hand, then re-verified (see
``scripts/ingest/README.md``). The arithmetic check below fails
loudly if the data file is ever corrupted — bad wage numbers must
never reach a worker.

Scope (honest): these are CENTRAL sphere rates only. Tamil Nadu
STATE rates are NOT in this file — the TN Labour Department's
minimum-wage G.O. PDFs all return 404 (verified 21 Nov 2026) and
the Commissioner's VDA statement is not published on the official
site, so TN-specific wage questions stay refusal cases
(LIMITATIONS.md L18/L39). Third-party aggregator figures are never
ingested, however plausible they look.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from career_guidance.kaamvaani.rag import Chunk

from .common import chunk_text

logger = logging.getLogger("kaamvaani.ingest.wages")

ROOT = Path(__file__).resolve().parent.parent.parent
WAGE_DATA_PATH = ROOT / "data" / "kv_wage_tables_2026-10.json"

SOURCE_ID_PREFIX = "web:labourbureau-vda"
TOPIC = "wages"
LANGUAGE = "en"


def _money(n: int) -> str:
    """Format a rupee figure the way the figure-grounding rule reads
    it: the ₹ sign directly before the number, thousands separated."""
    return f"₹{n:,}"


def _area_rates(rate: dict) -> str:
    """'Area A ₹840 per day (basic ₹523 + VDA ₹317); ...' for one
    skill row with A/B/C areas."""
    parts = []
    for area in ("A", "B", "C"):
        v = rate[area]
        parts.append(
            f"Area {area} {_money(v['total'])} per day "
            f"(basic {_money(v['basic'])} + VDA {_money(v['vda'])})"
        )
    return "; ".join(parts)


def _ground_rates(rate: dict) -> str:
    """Above/below-ground variant (mines): no area split."""
    parts = []
    for key, label in (("above_ground", "above ground"), ("below_ground", "below ground")):
        v = rate[key]
        parts.append(
            f"{label} {_money(v['total'])} per day "
            f"(basic {_money(v['basic'])} + VDA {_money(v['vda'])})"
        )
    return "; ".join(parts)


def employment_chunk_text(emp: dict, prov: dict) -> str:
    """Prose table for one scheduled employment. The employment's
    plain-language synonyms (from the data file's ``keywords``) are
    in the first sentence so worker-style queries match it, and the
    central-sphere scope warning is in the last sentence so a
    retrieved chunk never reads as a state rate."""
    lines = [
        f"Central sphere minimum wage — {emp['title']} "
        f"({emp['keywords']}). Labour Bureau order {prov['order']}, "
        f"rates from {prov['effective_from']}. Each rate is a basic "
        f"wage plus Variable Dearness Allowance (VDA); the total is "
        f"the least a worker must be paid.",
    ]
    if emp.get("note"):
        lines.append(emp["note"])
    for rate in emp["rates"]:
        if "A" in rate:
            lines.append(f"{rate['category']}: {_area_rates(rate)}.")
            if rate["category"] == "Unskilled":
                monthly = "; ".join(
                    f"Area {a} {_money(rate[a]['total'] * 26)}" for a in ("A", "B", "C")
                )
                lines.append(
                    f"Unskilled monthly salary (daily rate x 26 working days): {monthly} per month."
                )
        elif "above_ground" in rate:
            lines.append(f"{rate['category']}: {_ground_rates(rate)}.")
        else:  # piece rates (stone mines): single basic/VDA/total
            lines.append(
                f"{rate['category']}: {_money(rate['total'])} "
                f"(basic {_money(rate['basic'])} + VDA "
                f"{_money(rate['vda'])})."
            )
    lines.append(
        "Central sphere rates only — a private shop, factory or "
        "restaurant follows its state's minimum wages, not these rates."
    )
    return " ".join(lines)


def scope_chunk_text(data: dict) -> str:
    """Scope, area classes and the conversion rules — deliberately
    figure-free (no ₹ amounts), so a bare 'what is the minimum
    wage?' question with no employment named hits the
    figure-grounding rule and refuses instead of answering with a
    rate for the wrong job."""
    prov = data["provenance"]
    notes = data["notes"]
    return (
        f"Central sphere minimum wages — scope, areas and how the "
        f"rates work. Labour Bureau order {prov['order']}, rates "
        f"from {prov['effective_from']}, next revision due "
        f"{prov['next_revision_due']}. These rates apply ONLY in "
        f"the central sphere — where the Central Government is the "
        f"appropriate Government: railways, mines, oilfields, "
        f"banks, and establishments run by or under the authority "
        f"of the central government, including contractors "
        f"supplying workers to them (for example a security agency "
        f"supplying guards to a bank branch). A private shop, "
        f"restaurant, clinic or factory follows its STATE's "
        f"minimum wages, not these rates. Tamil Nadu state rates "
        f"are not in this knowledge base. {notes['areas']} "
        f"{notes['monthly']} {notes['revision']} The VDA is "
        f"rounded up to the next rupee."
    )


def validate_wage_data(data: dict) -> None:
    """Fail loudly on bad arithmetic — a wage table whose sums do
    not add up must never be ingested."""
    checked = 0
    for emp in data["employments"]:
        for rate in emp["rates"]:
            for key in ("A", "B", "C", "above_ground", "below_ground"):
                if key in rate:
                    v = rate[key]
                    checked += 1
                    if v["basic"] + v["vda"] != v["total"]:
                        raise ValueError(
                            f"wage data {emp['id']} {rate['category']} "
                            f"{key}: {v['basic']} + {v['vda']} != {v['total']}"
                        )
            if "basic" in rate:
                checked += 1
                if rate["basic"] + rate["vda"] != rate["total"]:
                    raise ValueError(
                        f"wage data {emp['id']} {rate['category']}: "
                        f"{rate['basic']} + {rate['vda']} != {rate['total']}"
                    )
    logger.info("wage data validated: %d sums checked", checked)


def ingest_wages(
    snapshot_version: str, data_path: Path = WAGE_DATA_PATH
) -> tuple[list[Chunk], dict]:
    """Build the wage chunks from the verified data file. Returns
    (chunks, fetch-log entry) in the runner's shape — the 'fetch'
    is the local data file, whose provenance block names the
    official PDF it was read from."""
    data = json.loads(data_path.read_text(encoding="utf-8"))
    validate_wage_data(data)
    prov = data["provenance"]
    chunks: list[Chunk] = []
    for emp in data["employments"]:
        text = employment_chunk_text(emp, prov)
        # No header: the first sentence already identifies the chunk
        # ("Central sphere minimum wage — ..."), and a "Minimum wage"
        # header would repeat the phrase and let short wage chunks
        # outrank the Code on Wages chunk on law questions (measured
        # Step 7B: kv-r070/r100).
        for index, piece in enumerate(chunk_text(text)):
            chunks.append(
                Chunk(
                    source_id=f"{SOURCE_ID_PREFIX}-{emp['id']}",
                    source_url=prov["source_url"],
                    # The citation title is the employment name alone:
                    # the title bonus (rag.py) reads source_title, and
                    # the employment name is what a wage question asks
                    # about — "Labour Bureau VDA order" boilerplate
                    # would dilute the bonus and add no meaning. The
                    # chunk text still names the order, and the
                    # citation URL is the official PDF.
                    source_title=emp["title"],
                    source_date=prov["source_date"],
                    licence=prov["licence"],
                    language=LANGUAGE,
                    topic=TOPIC,
                    state="",
                    district="",
                    chunk_index=index,
                    text=piece,
                    snapshot_version=snapshot_version,
                )
            )
    scope = scope_chunk_text(data)
    # No header here either (same reason as above).
    for index, piece in enumerate(chunk_text(scope)):
        chunks.append(
            Chunk(
                source_id=f"{SOURCE_ID_PREFIX}-scope",
                source_url=prov["source_url"],
                source_title="Labour Bureau VDA order — scope and areas",
                source_date=prov["source_date"],
                licence=prov["licence"],
                language=LANGUAGE,
                topic=TOPIC,
                state="",
                district="",
                chunk_index=index,
                text=piece,
                snapshot_version=snapshot_version,
            )
        )
    log_entry = {
        "source_id": "wages",
        "url": f"{data_path} (read from {prov['source_url']})",
        "ok": True,
        "status": None,
        "bytes": data_path.stat().st_size,
        "chunks": len(chunks),
        "error": "",
    }
    logger.info("ingest wages: %d chunks", len(chunks))
    return chunks, log_entry
