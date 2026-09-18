"""Golden-set evaluation: Hit@5 for the offline taxonomy matcher.

python -m eval.run [--min-hit 0.7] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from career_guidance.matching import get_matcher
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile

GOLDEN = Path(__file__).with_name("golden.json")
REPORT = Path(__file__).with_name("report.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-hit", type=float, default=0.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases = json.loads(GOLDEN.read_text())
    matcher = get_matcher()
    hits = 0
    mrr = 0.0
    latencies = []
    misses = []
    for case in cases:
        profile = CareerProfile(
            skills=case["skills"],
            goals=case.get("goals", ""),
            experience_level=EXPERIENCE_LEVELS[case.get("level", 0)],
        )
        t0 = time.perf_counter()
        matches = matcher.rank(profile)
        latencies.append(time.perf_counter() - t0)
        titles = [m.occupation.title for m in matches]
        rank = next((i for i, t in enumerate(titles) if t in case["expect"]), None)
        if rank is not None:
            hits += 1
            mrr += 1 / (rank + 1)
        else:
            misses.append({"skills": case["skills"], "got": titles, "expected": case["expect"]})
        if args.verbose:
            mark = "OK " if rank is not None else "MISS"
            print(f"{mark} {case['skills'][:45]:45s} -> {titles[0]}")

    n = len(cases)
    report = {
        "cases": n,
        "hit_at_5": round(hits / n, 3),
        "mrr": round(mrr / n, 3),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (n - 1))] * 1000, 1),
        "misses": misses,
    }
    REPORT.write_text(json.dumps(report, indent=2))
    print(
        f"Hit@5 = {report['hit_at_5']}  MRR = {report['mrr']}  "
        f"p95 = {report['p95_latency_ms']} ms  ({n} cases)"
    )
    for m in misses:
        print(f"  MISS {m['skills'][:50]:50s} got {m['got'][:3]}")
    return 0 if report["hit_at_5"] >= args.min_hit else 1


if __name__ == "__main__":
    sys.exit(main())
