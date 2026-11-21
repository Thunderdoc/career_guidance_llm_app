#!/usr/bin/env python3
"""Build the Kaam-Vaani LoRA dataset (Step 8.8).

Reads the gold profile cases, validates the deterministic
extractor's output against the gold expectations, and writes
``kv_lora_train.jsonl`` + ``kv_lora_val.jsonl``. Deterministic:
re-running reproduces byte-identical files. Prints the build
report as JSON.

Usage (from the repo root):
    python scripts/build_lora_data.py [--gold eval/kv_golden.json]
        [--out-dir training/data] [--val-fraction 0.1] [--seed 42]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as `python scripts/build_lora_data.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from career_guidance.kaamvaani.lora_data import (  # noqa: E402
    DEFAULT_SEED,
    DEFAULT_VAL_FRACTION,
    build_dataset,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="eval/kv_golden.json")
    parser.add_argument("--out-dir", default="training/data")
    parser.add_argument("--val-fraction", type=float, default=DEFAULT_VAL_FRACTION)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    try:
        report = build_dataset(
            args.gold, args.out_dir, val_fraction=args.val_fraction, seed=args.seed
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["skipped"]:
        print(
            f"WARNING: {len(report['skipped'])} gold case(s) skipped "
            "(extractor/gold drift — reconcile before trusting the dataset)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
