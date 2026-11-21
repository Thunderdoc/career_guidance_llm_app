"""Central-sphere minimum-wage tables for the pay-plausibility check
(L39, Step 8A).

The data is ``data/kv_wage_tables_2026-10.json`` — the Labour
Bureau's VDA order (File No. 6/1/2026-VDA, 30 Sep 2026, rates
from 1 Oct 2026), OCR'd and verified in Step 7B (52 printed
``basic + VDA = total`` sums re-added, 0 mismatches). This module
is the production reader for the scam check; the ingestion side
is ``scripts/ingest/wages.py`` (which builds the RAG chunks).

What the check can and cannot say
---------------------------------
The tables carry CENTRAL-sphere rates for 7 scheduled
employments only. A listing's pay is compared against the
matched employment's WIDE band: floor = the lowest daily total
across all categories and areas x 26 working days, ceiling =
the highest daily total x 26 (the file's own monthly rule,
``notes.monthly``). The band is deliberately wide because the
check does NOT know the listing's area or skill category — the
area lists live as prose in the source notes ("Area B: about 85
other cities including..."), and parsing area membership out of
prose would be a transcription risk. So:

- pay_max below the floor → "below_minimum": the best offered
  pay is below EVERY central-sphere rate for this employment.
- pay_min above the ceiling → "above_range": informational —
  the lowest offered pay exceeds every central-sphere rate
  (likely a different role or seniority, not a violation).
- otherwise → "within_central_range": the band cannot judge
  without area + skill category, and the reason says so.
- no employment match, no pay figures, or a piece-rate
  employment (stone-mines-piece — piece rates cannot convert
  to monthly) → "unknown", with the reason.

The verdict is advisory only — it never flags a listing and
never changes the scam score (see ``scam.check_pay_plausibility``).
And it is CENTRAL-sphere only: a private shop or factory in
Tamil Nadu follows TN state rates, which are absent (L18) —
the reasons carry that caveat, and "below_minimum" means below
the central-sphere band, never "below the legal minimum wage
for this job".

Complexity: O(E x K) keyword phrases per listing (7 employments,
~40 phrases) — a table lookup, not an algorithm.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "WageBand",
    "find_employment",
    "load_wage_tables",
    "wage_band",
]

WAGE_TABLES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "kv_wage_tables_2026-10.json"
)

# Daily rate x 26 working days = monthly minimum (the file's own
# rule, notes.monthly; also ASSUMPTIONS.md A54).
WORKING_DAYS_PER_MONTH = 26


@dataclass(frozen=True)
class WageBand:
    """The monthly pay band for one scheduled employment."""

    employment_id: str
    employment_title: str
    floor_monthly: int
    ceiling_monthly: int
    order: str
    effective_from: str

    def to_dict(self) -> dict:
        return {
            "employment": self.employment_id,
            "employment_title": self.employment_title,
            "floor_monthly": self.floor_monthly,
            "ceiling_monthly": self.ceiling_monthly,
            "order": self.order,
            "effective_from": self.effective_from,
            "scope": "central sphere only",
        }


@lru_cache(maxsize=1)
def load_wage_tables() -> dict:
    """Load and validate the wage tables. Raises on a missing file
    or a malformed structure — bad wage numbers must never reach
    a worker silently (the ingestion script's rule, kept here)."""
    if not WAGE_TABLES_PATH.exists():
        raise FileNotFoundError(f"wage tables not found: {WAGE_TABLES_PATH}")
    data = json.loads(WAGE_TABLES_PATH.read_text(encoding="utf-8"))
    employments = data.get("employments")
    provenance = data.get("provenance") or {}
    if not isinstance(employments, list) or not employments:
        raise ValueError(f"no employments in {WAGE_TABLES_PATH}")
    if not provenance.get("order") or not provenance.get("effective_from"):
        raise ValueError(f"no order/effective_from in {WAGE_TABLES_PATH}")
    for employment in employments:
        if not employment.get("id") or not employment.get("keywords"):
            raise ValueError(f"employment without id/keywords in {WAGE_TABLES_PATH}")
        if not _daily_totals(employment):
            raise ValueError(
                f"employment {employment.get('id')!r} has no rate totals in {WAGE_TABLES_PATH}"
            )
    return data


def _daily_totals(employment: dict) -> list[int]:
    """Every printed daily total for an employment, whatever the
    rate shape: area keys (A/B/C), above/below-ground keys, or a
    flat total. Piece-rate employments also yield totals here —
    the caller must check the unit before converting to monthly."""
    totals: list[int] = []
    for rate in employment.get("rates") or []:
        if isinstance(rate.get("total"), int):
            totals.append(rate["total"])
        for value in rate.values():
            if isinstance(value, dict) and isinstance(value.get("total"), int):
                totals.append(value["total"])
    return totals


def _phrases(employment: dict) -> list[str]:
    return [p.strip().lower() for p in str(employment.get("keywords", "")).split(",") if p.strip()]


def find_employment(listing: dict) -> dict | None:
    """The scheduled employment whose keyword phrase matches the
    listing's title + description + role category. The LONGEST
    matching phrase wins (most specific — "security guard" beats
    "guard"). Word-boundary matching, so "mines" does not match
    "determines". Returns None when nothing matches."""
    haystack = " ".join(
        [
            str(listing.get("title", "")),
            str(listing.get("description", "")),
            str(listing.get("role_category", "")),
        ]
    ).lower()
    best: dict | None = None
    best_len = 0
    for employment in load_wage_tables()["employments"]:
        for phrase in _phrases(employment):
            if len(phrase) <= best_len:
                continue
            if re.search(rf"\b{re.escape(phrase)}\b", haystack):
                best, best_len = employment, len(phrase)
    return best


def wage_band(employment: dict) -> WageBand | None:
    """The monthly band for an employment, or None when its rates
    are not per-day (piece rates cannot convert to monthly)."""
    if employment.get("unit") != "per day":
        return None
    totals = _daily_totals(employment)
    if not totals:
        return None
    provenance = load_wage_tables()["provenance"]
    return WageBand(
        employment_id=employment["id"],
        employment_title=employment.get("title", employment["id"]),
        floor_monthly=min(totals) * WORKING_DAYS_PER_MONTH,
        ceiling_monthly=max(totals) * WORKING_DAYS_PER_MONTH,
        order=provenance["order"],
        effective_from=provenance["effective_from"],
    )
