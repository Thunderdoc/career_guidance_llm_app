"""Kaam-Vaani eval harness (Stage 2).

Measures the deterministic voice-profile extractor and the RAG retriever
against ``eval/kv_golden.json`` — realistic voice-style queries in Tamil,
Hindi and English, including noisy, code-mixed and vague ones.

    python -m eval.run_kv --min-profile 0.90 --min-recall5 0.85 --min-faithfulness 0.90

Metrics (master prompt §5.6):

* ``profile`` — field accuracy of ``extract_profile`` over the scored
  fields (skills as a set, education, city, income_monthly, goal_type).
  Interests are free text and are not scored.
* ``recall@5`` / ``mrr`` — retrieval: an expected source in the top 5
  hits, and the reciprocal rank of the first expected source.
* ``per_language`` — the same retrieval metrics broken out by language
  family (en / hi / ta), so multilingual retrieval is measured per
  language instead of hiding a Tamil/Hindi gap inside the aggregate.
* ``faithfulness`` — the grounded answer quotes a chunk whose citation
  is one of the expected sources (a refused answer is unfaithful).
* ``refusal`` — refusal cases (out-of-scope or ungrounded questions)
  answered with a refusal, with the expected reason where given.
* ``latency`` — per-case wall time (extraction or retrieval + answer),
  p50/p95 in milliseconds. Retriever construction is excluded.

Writes ``eval/kv_report.json`` (per-case results, misses, aggregates)
and exits 0 only when every threshold passes. The report is committed
alongside the golden set so a regression is visible in the diff.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career_guidance.kaamvaani.extract import extract_profile  # noqa: E402
from career_guidance.kaamvaani.rag import (  # noqa: E402
    HybridRetriever,
    answer_question,
    check_citation,
    load_snapshot_file,
)

GOLDEN = Path(__file__).with_name("kv_golden.json")
REPORT = Path(__file__).with_name("kv_report.json")
DEFAULT_SNAPSHOT = ROOT / "data" / "kv_rag_snapshot_v2.jsonl"

PROFILE_FIELDS = ("skills", "education", "city", "income_monthly", "goal_type")

# Language families for per-language retrieval metrics (Step 7A). Roman
# code-mixed tags (ta-roman, hi-roman) count with their family; en-noisy
# counts as English.
LANGUAGE_FAMILIES = ("en", "hi", "ta")


def lang_family(language: str) -> str:
    """Map a case language tag (en, en-noisy, hi, hi-roman, ta, ta-roman)
    to its family for per-language metrics."""
    prefix = (language or "").split("-")[0]
    return prefix if prefix in LANGUAGE_FAMILIES else "other"


def _profile_case(case: dict) -> dict:
    """Run one profile case; returns per-field matches + latency."""
    started = time.perf_counter()
    got = extract_profile(case["text"])
    latency_ms = (time.perf_counter() - started) * 1000
    expected = case["expected"]
    fields: dict[str, bool] = {
        "skills": set(got.skills) == set(expected.get("skills", [])),
        "education": got.education == expected.get("education", ""),
        "city": got.city == expected.get("city", ""),
        "income_monthly": got.income_monthly == expected.get("income_monthly"),
        "goal_type": got.goal_type == expected.get("goal_type", "explore"),
    }
    return {
        "id": case["id"],
        "kind": "profile",
        "language": case.get("language", ""),
        "text": case["text"],
        "fields": fields,
        "accuracy": sum(fields.values()) / len(fields),
        "got": {
            "skills": got.skills,
            "education": got.education,
            "city": got.city,
            "income_monthly": got.income_monthly,
            "goal_type": got.goal_type,
        },
        "expected": expected,
        "latency_ms": round(latency_ms, 1),
    }


def _retrieval_case(case: dict, retriever: HybridRetriever, top_k: int) -> dict:
    """Run one retrieval case; returns recall@k, MRR, faithfulness."""
    started = time.perf_counter()
    hits = retriever.search(case["text"], top_k=top_k)
    result = answer_question(case["text"], retriever, top_k=top_k)
    latency_ms = (time.perf_counter() - started) * 1000
    expected = set(case["expected_sources"])
    rank = next(
        (i + 1 for i, hit in enumerate(hits) if hit.chunk.source_id in expected),
        0,
    )
    return {
        "id": case["id"],
        "kind": "retrieval",
        "language": case.get("language", ""),
        "text": case["text"],
        "recall_at_k": 1.0 if rank else 0.0,
        "mrr": (1.0 / rank) if rank else 0.0,
        "rank": rank,
        "top_sources": [hit.chunk.source_id for hit in hits],
        "faithful": check_citation(result, sorted(expected)),
        "refused": result["refused"],
        "top_cosine": result.get("top_cosine", 0.0),
        "answer": result["answer"],
        "citation": result["citations"][0] if result["citations"] else None,
        "expected_sources": sorted(expected),
        "latency_ms": round(latency_ms, 1),
    }


def _refusal_case(case: dict, retriever: HybridRetriever, top_k: int) -> dict:
    """Run one refusal case; correct when the answer refuses (and the
    reason matches, where the case specifies one)."""
    started = time.perf_counter()
    result = answer_question(case["text"], retriever, top_k=top_k)
    latency_ms = (time.perf_counter() - started) * 1000
    expected_reason = case.get("reason", "")
    correct = result["refused"] and (not expected_reason or result["reason"] == expected_reason)
    return {
        "id": case["id"],
        "kind": "refusal",
        "language": case.get("language", ""),
        "text": case["text"],
        "correct": bool(correct),
        "refused": result["refused"],
        "reason": result["reason"],
        "expected_reason": expected_reason,
        "top_cosine": result.get("top_cosine", 0.0),
        "latency_ms": round(latency_ms, 1),
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * pct / 100)))
    return ordered[index]


def run_eval(
    golden_path: Path,
    snapshot_path: Path,
    top_k: int = 5,
    dense_model: str | None = None,
) -> dict:
    """Run the whole golden set; returns the report dict (no thresholds).
    With ``dense_model`` set, the retriever fuses the hybrid ranking
    with multilingual-e5 dense rankings by RRF (Step 7A comparison)."""
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    chunks, meta = load_snapshot_file(snapshot_path)
    dense = None
    if dense_model:
        from career_guidance.kaamvaani.dense import DenseRetriever

        dense = DenseRetriever(chunks, dense_model)
    retriever = HybridRetriever(chunks, dense=dense)

    results: list[dict] = []
    for case in golden["cases"]:
        if case["kind"] == "profile":
            results.append(_profile_case(case))
        elif case["kind"] == "retrieval":
            results.append(_retrieval_case(case, retriever, top_k))
        elif case["kind"] == "refusal":
            results.append(_refusal_case(case, retriever, top_k))
        else:  # pragma: no cover - golden set is curated
            raise ValueError(f"unknown case kind: {case['kind']!r}")

    profile = [r for r in results if r["kind"] == "profile"]
    retrieval = [r for r in results if r["kind"] == "retrieval"]
    refusal = [r for r in results if r["kind"] == "refusal"]
    latencies = [r["latency_ms"] for r in results]

    # Per-language retrieval metrics (Step 7A): a Tamil/Hindi gap must be
    # visible on its own, not averaged away inside the aggregate.
    per_language: dict[str, dict] = {}
    for family in LANGUAGE_FAMILIES:
        subset = [r for r in retrieval if lang_family(r["language"]) == family]
        if not subset:
            continue
        per_language[family] = {
            "cases": len(subset),
            "recall_at_5": round(sum(r["recall_at_k"] for r in subset) / len(subset), 4),
            "mrr": round(sum(r["mrr"] for r in subset) / len(subset), 4),
            "faithfulness": round(sum(1 for r in subset if r["faithful"]) / len(subset), 4),
            "misses": [r["id"] for r in subset if not r["recall_at_k"]],
        }

    field_totals = {f: 0 for f in PROFILE_FIELDS}
    field_correct = {f: 0 for f in PROFILE_FIELDS}
    for result in profile:
        for field, matched in result["fields"].items():
            field_totals[field] += 1
            field_correct[field] += int(matched)

    report = {
        "golden": str(golden_path),
        "snapshot": str(snapshot_path),
        "snapshot_version": meta.get("version", "") if meta else "",
        "snapshot_chunks": len(chunks),
        "dense_model": dense_model or "",
        "cases": len(results),
        "profile": {
            "cases": len(profile),
            "accuracy": round(sum(r["accuracy"] for r in profile) / len(profile), 4)
            if profile
            else 0.0,
            "field_accuracy": {
                f: round(field_correct[f] / field_totals[f], 4) if field_totals[f] else 0.0
                for f in PROFILE_FIELDS
            },
            "misses": [r["id"] for r in profile if r["accuracy"] < 1.0],
        },
        "retrieval": {
            "cases": len(retrieval),
            "recall_at_5": round(sum(r["recall_at_k"] for r in retrieval) / len(retrieval), 4)
            if retrieval
            else 0.0,
            "mrr": round(sum(r["mrr"] for r in retrieval) / len(retrieval), 4)
            if retrieval
            else 0.0,
            "faithfulness": round(sum(1 for r in retrieval if r["faithful"]) / len(retrieval), 4)
            if retrieval
            else 0.0,
            "misses": [r["id"] for r in retrieval if not r["recall_at_k"]],
            "unfaithful": [r["id"] for r in retrieval if not r["faithful"]],
            "per_language": per_language,
        },
        "refusal": {
            "cases": len(refusal),
            "accuracy": round(sum(1 for r in refusal if r["correct"]) / len(refusal), 4)
            if refusal
            else 0.0,
            "misses": [r["id"] for r in refusal if not r["correct"]],
        },
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 1),
            "p95": round(_percentile(latencies, 95), 1),
            "max": round(max(latencies), 1) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        },
        "results": results,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--dense-model",
        type=str,
        default=None,
        help="Fuse the hybrid ranking with dense rankings from this "
        "sentence-transformers model (Step 7A comparison; needs the "
        "sentence-transformers + torch packages).",
    )
    parser.add_argument("--min-profile", type=float, default=0.90)
    parser.add_argument("--min-recall5", type=float, default=0.85)
    parser.add_argument("--min-faithfulness", type=float, default=0.90)
    parser.add_argument("--min-refusal", type=float, default=0.90)
    args = parser.parse_args(argv)

    report = run_eval(args.golden, args.snapshot, top_k=args.top_k, dense_model=args.dense_model)
    report["thresholds"] = {
        "min_profile": args.min_profile,
        "min_recall5": args.min_recall5,
        "min_faithfulness": args.min_faithfulness,
        "min_refusal": args.min_refusal,
    }
    passed = (
        report["profile"]["accuracy"] >= args.min_profile
        and report["retrieval"]["recall_at_5"] >= args.min_recall5
        and report["retrieval"]["faithfulness"] >= args.min_faithfulness
        and report["refusal"]["accuracy"] >= args.min_refusal
    )
    report["passed"] = passed
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(
        f"Kaam-Vaani eval: {report['cases']} cases, snapshot {report['snapshot_version']} "
        f"({report['snapshot_chunks']} chunks)"
        + (f", dense {report['dense_model']}" if report["dense_model"] else "")
    )
    print(
        f"  profile      {report['profile']['accuracy']:.3f} "
        f"(min {args.min_profile:.2f})  field: "
        + ", ".join(f"{f} {a:.2f}" for f, a in report["profile"]["field_accuracy"].items())
    )
    print(
        f"  recall@5     {report['retrieval']['recall_at_5']:.3f} "
        f"(min {args.min_recall5:.2f})  mrr {report['retrieval']['mrr']:.3f}"
    )
    for family, metrics in report["retrieval"]["per_language"].items():
        print(
            f"  recall@5 [{family}] {metrics['recall_at_5']:.3f}  "
            f"mrr {metrics['mrr']:.3f}  faithful {metrics['faithfulness']:.3f}  "
            f"({metrics['cases']} cases)"
        )
    print(
        f"  faithfulness {report['retrieval']['faithfulness']:.3f} "
        f"(min {args.min_faithfulness:.2f})"
    )
    print(f"  refusal      {report['refusal']['accuracy']:.3f} (min {args.min_refusal:.2f})")
    print(
        f"  latency      p50 {report['latency_ms']['p50']:.0f} ms  "
        f"p95 {report['latency_ms']['p95']:.0f} ms  max {report['latency_ms']['max']:.0f} ms"
    )
    for section in ("profile", "retrieval", "refusal"):
        misses = report[section]["misses"]
        if misses:
            print(f"  {section} misses: {', '.join(misses)}")
    if report["retrieval"]["unfaithful"]:
        print(f"  unfaithful: {', '.join(report['retrieval']['unfaithful'])}")
    print(f"  report: {args.report}")
    print("  PASS" if passed else "  FAIL — below threshold")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
