"""Golden-set evaluation: Hit@5 for matcher v2 (offline, no API keys).

Two suites are scored:

* ``golden.json`` — 50 skill/goal profiles (the original bar, ≥ 0.70/0.75);
* ``golden_interests.json`` — RIASEC-only profiles that exercise the interest
  term of matcher v2 (users who take the quiz before typing any skills).

    python -m eval.run [--min-hit 0.7] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from career_guidance.matching2 import MatcherV2
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile

GOLDEN = Path(__file__).with_name("golden.json")
GOLDEN_INTERESTS = Path(__file__).with_name("golden_interests.json")
REPORT = Path(__file__).with_name("report.json")


def _rank_titles(matcher: MatcherV2, profile: CareerProfile, interests: dict | None) -> list[str]:
    ranked = matcher.rank(profile, top_k=5, interests=interests)
    return [r.occupation.title for r in ranked]


def evaluate_skills(matcher: MatcherV2, cases: list[dict], verbose: bool) -> dict:
    hits, mrr, latencies, misses = 0, 0.0, [], []
    for case in cases:
        profile = CareerProfile(
            skills=case["skills"],
            goals=case.get("goals", ""),
            education=case.get("education", ""),
            experience_level=EXPERIENCE_LEVELS[case.get("level", 0)],
        )
        started = time.perf_counter()
        titles = _rank_titles(matcher, profile, None)
        latencies.append(time.perf_counter() - started)
        rank = next((i for i, t in enumerate(titles) if t in case["expect"]), None)
        if rank is not None:
            hits += 1
            mrr += 1 / (rank + 1)
        else:
            misses.append({"skills": case["skills"], "got": titles, "expected": case["expect"]})
        if verbose:
            print(
                f"{'OK  ' if rank is not None else 'MISS'} {case['skills'][:45]:45s} -> {titles[0]}"
            )
    return {
        "cases": len(cases),
        "hit_at_5": round(hits / len(cases), 3),
        "mrr": round(mrr / len(cases), 3),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (len(cases) - 1))] * 1000, 1),
        "misses": misses,
    }


def evaluate_interests(matcher: MatcherV2, cases: list[dict], verbose: bool) -> dict:
    hits, latencies, misses = 0, [], []
    for case in cases:
        profile = CareerProfile(skills="", interests="", goals="")
        started = time.perf_counter()
        titles = _rank_titles(matcher, profile, case["scores"])
        latencies.append(time.perf_counter() - started)
        if any(t in case["expect"] for t in titles):
            hits += 1
        else:
            misses.append({"scores": case["scores"], "got": titles, "expected": case["expect"]})
        if verbose:
            print(f"{case['id']:26s} -> {titles[0]}")
    return {
        "cases": len(cases),
        "hit_at_5": round(hits / len(cases), 3),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (len(cases) - 1))] * 1000, 1),
        "misses": misses,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-hit", type=float, default=0.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    matcher = MatcherV2()
    skills = evaluate_skills(matcher, json.loads(GOLDEN.read_text()), args.verbose)
    interests = evaluate_interests(matcher, json.loads(GOLDEN_INTERESTS.read_text()), args.verbose)

    report = {
        "matcher": "v2 (skills 0.55 / interests 0.30 / job zone 0.15)",
        "skills": skills,
        "interests": interests,
        "hit_at_5": min(skills["hit_at_5"], interests["hit_at_5"]),
        "cases": skills["cases"] + interests["cases"],
        "p95_latency_ms": max(skills["p95_latency_ms"], interests["p95_latency_ms"]),
    }
    REPORT.write_text(json.dumps(report, indent=2))
    print(
        f"skills   Hit@5 = {skills['hit_at_5']}  MRR = {skills['mrr']}  "
        f"p95 = {skills['p95_latency_ms']} ms  ({skills['cases']} cases)"
    )
    print(
        f"interests Hit@5 = {interests['hit_at_5']}  "
        f"p95 = {interests['p95_latency_ms']} ms  ({interests['cases']} cases)"
    )
    for miss in skills["misses"]:
        print(f"  MISS {miss['skills'][:50]:50s} got {miss['got'][:3]}")
    for miss in interests["misses"]:
        print(f"  MISS interests {miss['scores']} got {miss['got'][:3]}")
    return 0 if report["hit_at_5"] >= args.min_hit else 1


if __name__ == "__main__":
    sys.exit(main())
