"""Counsellor-validation agreement stats (Phase 5, eval evidence).

Reads a CSV a counsellor filled in while reviewing sampled recommendation
runs (see eval/COUNSELLOR_VALIDATION.md for the sampling + scoring
protocol and the exact column definitions) and prints agreement stats:

- top-1 agreement: the counsellor's first-choice career == the system's
  top recommendation;
- top-5 inclusion: the counsellor's first choice appears anywhere in the
  system's top 5;
- the counsellor's own agree / partial / disagree rating distribution.

This script computes *agreement with a human reviewer*, not accuracy.
It makes no claim about the product; results are only meaningful when
run on a real, consented sample per the protocol doc.

Usage:
    python -m eval.counsellor_validation eval/counsellor_sample.csv
    python eval/counsellor_validation.py path/to/filled.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REQUIRED_COLUMNS = ("run_id", "counsellor_top_pick", "system_top_pick", "system_top5", "rating")
RATINGS = ("agree", "partial", "disagree")


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = [f.strip() for f in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in fields]
        if missing:
            raise SystemExit(f"CSV is missing required column(s): {', '.join(missing)}")
        rows = []
        for raw in reader:
            row = {str(k).strip(): (v or "").strip() for k, v in raw.items() if k}
            if not row.get("run_id"):
                continue  # blank line
            rating = row["rating"].lower()
            if rating not in RATINGS:
                raise SystemExit(
                    f"run {row['run_id']}: rating must be one of {RATINGS}, got {rating!r}"
                )
            rows.append(row)
    if not rows:
        raise SystemExit("No data rows in the CSV.")
    return rows


def agreement_stats(rows: list[dict]) -> dict:
    total = len(rows)
    top1 = sum(1 for r in rows if _norm(r["counsellor_top_pick"]) == _norm(r["system_top_pick"]))
    top5 = 0
    for r in rows:
        picks = {_norm(p) for p in r["system_top5"].split("|") if p.strip()}
        if _norm(r["counsellor_top_pick"]) in picks:
            top5 += 1
    ratings = {name: sum(1 for r in rows if r["rating"].lower() == name) for name in RATINGS}
    return {
        "runs_reviewed": total,
        "top1_agreement": top1,
        "top1_agreement_percent": round(100.0 * top1 / total, 1),
        "top5_inclusion": top5,
        "top5_inclusion_percent": round(100.0 * top5 / total, 1),
        "ratings": ratings,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-3])
        print("usage: python -m eval.counsellor_validation <filled.csv>")
        return 2
    rows = load_rows(Path(argv[0]))
    stats = agreement_stats(rows)
    print(f"Runs reviewed:        {stats['runs_reviewed']}")
    print(
        f"Top-1 agreement:      {stats['top1_agreement']}/{stats['runs_reviewed']} "
        f"= {stats['top1_agreement_percent']}%"
    )
    print(
        f"Top-5 inclusion:      {stats['top5_inclusion']}/{stats['runs_reviewed']} "
        f"= {stats['top5_inclusion_percent']}%"
    )
    print(
        "Counsellor ratings:   "
        + " · ".join(f"{name} {stats['ratings'][name]}" for name in RATINGS)
    )
    print(
        "\nAgreement with a reviewer is not an accuracy measurement. "
        "See eval/COUNSELLOR_VALIDATION.md for what this number can and cannot support."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
