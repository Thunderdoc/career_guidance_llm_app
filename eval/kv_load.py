"""Kaam-Vaani load test (Step 9.5).

A self-contained async load script (no k6/Locust — neither is
installed, and httpx is already a dependency). It starts a real
uvicorn server on a COPY of the dev database, warms it up, then
drives N virtual users through the five public KV endpoints
(/rag/ask, /rag/search, /rights/ask, /voice/extract, /matches) and
publishes per-endpoint p50/p95/p99 latencies, error counts,
throughput and server memory (RSS from /proc).

Honesty notes, read before quoting the numbers:
- Questions are DISTINCT per request (cycled from the 115
  retrieval cases in eval/kv_golden.json; transcripts from the
  55 profile cases), so the 8.6 answer/profile caches do NOT
  dominate — this measures the uncached path under concurrency.
  Repeated identical questions are served from cache at ~4 ms
  (Step 8.6 numbers), which is a different measurement.
- Each virtual user sends its own X-Forwarded-For
  (10.0.0.N), so the Step 9.4 per-IP rate limiters see distinct
  users — the way real users arrive. No limiter is disabled.
- One uvicorn worker (the Render free-tier shape), 20
  concurrent users by default. The machine is this dev VM, not
  Render — absolute numbers are indicative of the code, not of
  the deployment.
- The server runs on a scratch COPY of data/career_guidance.db;
  the dev database is never touched.

Usage (from the repo root):
    python -m eval.kv_load [--users 20] [--rounds 5] [--port 8791]
        [--work-dir PATH] [--output eval/kv_load_report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "eval" / "kv_golden.json"

ENDPOINTS = ("/rag/ask", "/rag/search", "/rights/ask", "/voice/extract", "/matches")

# The /matches and /voice/extract bodies are built in-process
# (same construction as the Stage 3/4 tests).
MATCHES_PROFILE = {
    "skills": ["attention to detail", "computer literacy", "agricultural science"],
    "interests": "farming and basic computer work, and I can type. Madurai. I need a job",
    "education": "12th pass",
    "city": "Madurai",
    "income_text": "₹15,000 / month",
    "income_monthly": 15000,
    "goal_type": "job_6_months",
    "raw_text": "farming and basic computer work, and I can type. 12th pass. Madurai. "
    "15000 rupees a month. I need a job",
}


def _rss_mb(pid: int) -> float | None:
    """Resident set size in MB from /proc (psutil is not installed)."""
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * pct / 100)))
    return ordered[index]


def _load_questions() -> tuple[list[str], list[str]]:
    with open(GOLDEN_PATH, encoding="utf-8") as handle:
        cases = json.load(handle)["cases"]
    questions = [c["text"] for c in cases if c["kind"] == "retrieval"]
    transcripts = [c["text"] for c in cases if c["kind"] == "profile"]
    return questions, transcripts


# Guided-flow answers that drive a session to the ``matches``
# state (same content as the Stage 4 test's DEMO_ANSWERS).
DEMO_ANSWERS = {
    "skills": "farming and basic computer work, and I can type",
    "education": "12th pass",
    "city": "Madurai",
    "income": "15000 rupees a month",
    "goal": "I need a job",
}


def _matches_body() -> dict:
    """A session driven to the ``matches`` state + a profile."""
    sys.path.insert(0, str(REPO_ROOT))
    from career_guidance.kaamvaani.extract import VoiceProfile
    from career_guidance.kaamvaani.profile import new_session, transition

    profile = VoiceProfile(**MATCHES_PROFILE)
    session = new_session("en")
    session = transition(session, "start")
    session = transition(session, "set_language", language="en")
    for qid, text in DEMO_ANSWERS.items():
        session = transition(session, "answer", question_id=qid, transcript=text, source="typed")
    session = transition(session, "extracted", profile=profile)
    session = transition(session, "confirm", confirmed=True)
    return {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "top_k": 5,
    }


def _start_server(work_dir: Path, port: int) -> subprocess.Popen:
    db_copy = work_dir / "load.db"
    shutil.copyfile(REPO_ROOT / "data" / "career_guidance.db", db_copy)
    env = dict(os.environ)
    env["DATABASE_PATH"] = str(db_copy)
    env["SESSION_SECRET"] = "load-test-secret"
    env["PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    env["ADMIN_EMAILS"] = "boss@example.com"
    env.pop("PUBLIC_APP", None)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
            "--log-level",
            "warning",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


async def _wait_healthy(base: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    # trust_env=False: the sandbox NO_PROXY list holds bracketed IPv6
    # entries httpx cannot parse (InvalidURL on client construction),
    # and this script only ever talks to localhost anyway.
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{base}/api/v1/health")
                if r.status_code == 200:
                    return
            except httpx.RequestError:
                pass
            await asyncio.sleep(1.0)
    raise RuntimeError(f"server did not become healthy within {timeout:.0f}s")


async def _one_request(
    client: httpx.AsyncClient,
    base: str,
    endpoint: str,
    body: dict,
    headers: dict,
    latencies: dict[str, list[float]],
    errors: dict[str, dict[int, int]],
) -> None:
    started = time.monotonic()
    try:
        r = await client.post(f"{base}/api/v1/kv{endpoint}", json=body, headers=headers)
        status = r.status_code
    except httpx.RequestError:
        status = 0
    elapsed_ms = (time.monotonic() - started) * 1000
    latencies[endpoint].append(elapsed_ms)
    if status != 200:
        errors.setdefault(endpoint, {}).setdefault(status, 0)
        errors[endpoint][status] += 1


async def _user(
    user_id: int,
    base: str,
    rounds: int,
    questions: list[str],
    transcripts: list[str],
    matches_body: dict,
    latencies: dict[str, list[float]],
    errors: dict[str, dict[int, int]],
) -> None:
    """One virtual user: the 5-endpoint sequence, ``rounds`` times,
    with its own X-Forwarded-For (distinct users, per the Step 9.4
    rate limiters). Questions are distinct per request (cycled)."""
    headers = {"X-Forwarded-For": f"10.0.0.{user_id + 1}"}
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        for round_no in range(rounds):
            n = user_id * rounds + round_no
            question = questions[n % len(questions)]
            transcript = transcripts[n % len(transcripts)]
            await _one_request(
                client,
                base,
                "/rag/ask",
                {"question": question},
                headers,
                latencies,
                errors,
            )
            await _one_request(
                client,
                base,
                "/rag/search",
                {"query": question, "top_k": 5},
                headers,
                latencies,
                errors,
            )
            await _one_request(
                client,
                base,
                "/rights/ask",
                {"question": question},
                headers,
                latencies,
                errors,
            )
            await _one_request(
                client,
                base,
                "/voice/extract",
                {"text": transcript},
                headers,
                latencies,
                errors,
            )
            await _one_request(client, base, "/matches", matches_body, headers, latencies, errors)


async def _sample_rss(pid: int, samples: list[float], stop: asyncio.Event) -> None:
    while not stop.is_set():
        rss = _rss_mb(pid)
        if rss is not None:
            samples.append(rss)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def run_load(users: int, rounds: int, port: int, work_dir: Path) -> dict:
    questions, transcripts = _load_questions()
    matches_body = _matches_body()
    base = f"http://127.0.0.1:{port}"
    proc = _start_server(work_dir, port)
    try:
        await _wait_healthy(base)
        rss_before = _rss_mb(proc.pid)
        # Warm-up: one request per endpoint (builds the retriever,
        # so the timed run does not pay the ~4 s first build).
        latencies: dict[str, list[float]] = {e: [] for e in ENDPOINTS}
        errors: dict[str, dict[int, int]] = {}
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            await _one_request(
                client,
                base,
                "/rag/ask",
                {"question": questions[0]},
                {},
                latencies,
                errors,
            )
            await _one_request(
                client,
                base,
                "/rag/search",
                {"query": questions[0], "top_k": 5},
                {},
                latencies,
                errors,
            )
            await _one_request(
                client,
                base,
                "/rights/ask",
                {"question": questions[0]},
                {},
                latencies,
                errors,
            )
            await _one_request(
                client,
                base,
                "/voice/extract",
                {"text": transcripts[0]},
                {},
                latencies,
                errors,
            )
            await _one_request(client, base, "/matches", matches_body, {}, latencies, errors)
        # Timed run (warm-up latencies discarded).
        latencies = {e: [] for e in ENDPOINTS}
        errors = {}
        rss_samples: list[float] = []
        stop = asyncio.Event()
        sampler = asyncio.create_task(_sample_rss(proc.pid, rss_samples, stop))
        started = time.monotonic()
        await asyncio.gather(
            *(
                _user(
                    user_id,
                    base,
                    rounds,
                    questions,
                    transcripts,
                    matches_body,
                    latencies,
                    errors,
                )
                for user_id in range(users)
            )
        )
        wall_seconds = time.monotonic() - started
        stop.set()
        await sampler
        rss_after = _rss_mb(proc.pid)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    total = sum(len(v) for v in latencies.values())
    report: dict = {
        "users": users,
        "rounds": rounds,
        "total_requests": total,
        "wall_seconds": round(wall_seconds, 2),
        "requests_per_second": round(total / wall_seconds, 2) if wall_seconds else 0,
        "rss_mb_before": rss_before,
        "rss_mb_after": rss_after,
        "rss_mb_peak_sampled": max(rss_samples) if rss_samples else None,
        "endpoints": {},
    }
    for endpoint in ENDPOINTS:
        values = latencies[endpoint]
        report["endpoints"][endpoint] = {
            "n": len(values),
            "p50_ms": round(statistics.median(values), 1) if values else 0,
            "p95_ms": round(_percentile(values, 95), 1),
            "p99_ms": round(_percentile(values, 99), 1),
            "mean_ms": round(statistics.mean(values), 1) if values else 0,
            "max_ms": round(max(values), 1) if values else 0,
            "errors": errors.get(endpoint, {}),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kaam-Vaani load test (Step 9.5).")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--work-dir", type=str, default=None)
    parser.add_argument("--output", type=str, default="eval/kv_load_report.json")
    args = parser.parse_args(argv)
    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="kv-load-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_load(args.users, args.rounds, args.port, work_dir))
    output = Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(
        f"users={report['users']} rounds={report['rounds']} "
        f"total={report['total_requests']} wall={report['wall_seconds']}s "
        f"rps={report['requests_per_second']}"
    )
    print(
        f"RSS MB: before={report['rss_mb_before']} after={report['rss_mb_after']} "
        f"peak_sampled={report['rss_mb_peak_sampled']}"
    )
    print(
        f"{'endpoint':<16} {'n':>4} {'p50':>8} {'p95':>8} {'p99':>8} {'mean':>8} {'max':>8} errors"
    )
    for endpoint, stats in report["endpoints"].items():
        print(
            f"{endpoint:<16} {stats['n']:>4} {stats['p50_ms']:>8.1f} "
            f"{stats['p95_ms']:>8.1f} {stats['p99_ms']:>8.1f} "
            f"{stats['mean_ms']:>8.1f} {stats['max_ms']:>8.1f} {stats['errors']}"
        )
    print(f"report written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
