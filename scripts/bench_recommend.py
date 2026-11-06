"""Local /recommend latency benchmark (Phase 10).

Starts the API on a scratch port with a scratch database (direct
uvicorn, no reload), waits for readiness, fires N anonymous
``POST /api/v1/recommend`` requests with a fixed representative payload,
and prints count / min / median / p95 / max in milliseconds.

The numbers are same-machine development numbers only — they are
comparable to earlier runs of THIS script on THIS machine (the Phase 1
eval-baseline of ~292 ms p95 was measured differently, via the eval
harness on the golden set; see docs/PERFORMANCE.md for the honest
comparison caveat).

Usage:  python scripts/bench_recommend.py [--requests 30] [--port 8123]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAYLOAD = {
    "skills": "python, data analysis, sql, communication",
    "interests": "technology, education",
    "education": "B.Sc. Computer Science",
    "experience_level": "Junior (0-2 years)",
    "goals": "become a data analyst",
    "country": "in",
}


def _post(url: str, payload: dict) -> float:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - localhost bench
        resp.read()
        assert resp.status == 200
    return (time.perf_counter() - start) * 1000


def _wait_ready(port: int, proc: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(  # noqa: S310 - localhost bench
                f"http://127.0.0.1:{port}/api/v1/ready", timeout=2
            ) as resp:
                if resp.status == 200:
                    return
        except Exception:  # noqa: BLE001 - still starting
            time.sleep(0.25)
    raise RuntimeError("server did not become ready in time")


def main() -> int:
    parser = argparse.ArgumentParser()
    # /recommend is rate-limited to 30 requests/minute per client, so the
    # default run (1 warm-up + 25 measured = 26) stays under the limit.
    parser.add_argument("--requests", type=int, default=25)
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="cg-bench-"))
    env = {
        **os.environ,
        "DATABASE_PATH": str(scratch / "bench.db"),
        "SESSION_SECRET": "bench-secret",
        "PUBLIC_URL": f"http://127.0.0.1:{args.port}",
        "PYTHONPATH": str(ROOT),
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_ready(args.port, proc)
        url = f"http://127.0.0.1:{args.port}/api/v1/recommend"
        _post(url, PAYLOAD)  # warm-up (excluded from the stats)
        times = [_post(url, PAYLOAD) for _ in range(args.requests)]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    times.sort()
    p95 = times[min(len(times) - 1, int(0.95 * len(times)))]
    print(f"requests: {len(times)} (plus 1 warm-up, excluded)")
    print(f"min:    {times[0]:.1f} ms")
    print(f"median: {statistics.median(times):.1f} ms")
    print(f"p95:    {p95:.1f} ms")
    print(f"max:    {times[-1]:.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
