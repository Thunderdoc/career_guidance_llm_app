"""Agent trace log (Step 8.9): per-request structured JSON traces of
what the agent did — translation, retrieval, ranking, verification —
with latency per stage.

PII safety is enforced BY CONSTRUCTION, not by convention:
- A trace never carries raw user text. The request is identified by
  ``query_hash`` — the first 16 hex chars of the SHA-256 of the
  question/transcript — which lets an operator correlate a trace
  with a reported question (by hashing the reported text) without
  storing the text itself.
- Span ``detail`` dicts are validated on write: keys naming personal
  data or raw content (``FORBIDDEN_DETAIL_KEYS``) and string values
  over 500 chars are REJECTED — the span is recorded with status
  "error" and the detail replaced by a rejection note, and the
  unsafe content is never stored. Tracing never breaks a request:
  a tracing bug degrades the trace, not the answer. Only counts,
  scores, IDs, flags and short labels are allowed.
- No user id, no name, no phone, no email, no profile content, no
  answer text — ever. The test suite greps recorded traces for the
  raw test inputs to prove it.

Storage: an in-memory ring (default 200 traces, newest first) plus
an optional JSONL file sink (``KV_TRACE_FILE``; off by default).
Rotation: the file rotates at 10 MB, keeping 3 files (~30 MB max,
~30k traces at ~1 KB each). Retention: traces live until they
rotate out of the ring/file — at pilot volume that is days to
weeks. The recommended ops retention is 7 days; strict time-based
pruning is an ops concern (logrotate / a pruning cron on the
JSONL file) and is NOT built in — the sink rotates by size, not
by date. Traces are process-local: a restart starts empty, and
the file sink (when configured) is the only durable copy.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Detail keys that must never appear in a trace: personal data, raw
# user content, and anything that reproduces a profile or an answer.
# Checked case-insensitively on every write (see _validate_detail).
FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "name",
        "phone",
        "email",
        "address",
        "query",
        "question",
        "text",
        "transcript",
        "profile",
        "answer",
        "skills",
        "city",
        "income",
        "income_text",
        "income_monthly",
        "education",
        "interests",
        "goal",
        "goal_type",
        "user_id",
        "user_email",
        "worker_name",
        "employer_name",
        "password",
        "token",
    }
)

# A detail string value longer than this is rejected: it is almost
# certainly raw content (an answer is up to 600 chars, a transcript
# unbounded). Titles and URLs fit comfortably under it.
MAX_DETAIL_VALUE_CHARS = 500

DEFAULT_MAX_TRACES = 200
DEFAULT_MAX_FILE_BYTES = 10_000_000  # 10 MB per file
DEFAULT_MAX_FILES = 3  # current + 2 rotated = ~30 MB max


def hash_query(text: str) -> str:
    """The trace identifier for a question/transcript: the first 16
    hex chars of its SHA-256. Deterministic (the same question
    always maps to the same hash), one-way, and short enough to
    read. It identifies a request for correlation; it is NOT a
    security boundary — a guessable question can be re-hashed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _validate_detail(detail: dict[str, Any]) -> list[str]:
    """Problems with a span detail dict (empty = safe to store)."""
    problems: list[str] = []
    for key, value in detail.items():
        if key.lower() in FORBIDDEN_DETAIL_KEYS:
            problems.append(f"forbidden detail key: {key!r}")
        if isinstance(value, str) and len(value) > MAX_DETAIL_VALUE_CHARS:
            problems.append(f"detail value too long ({len(value)} chars): {key!r}")
        elif not isinstance(value, (str, int, float, bool, type(None))):
            if isinstance(value, (list, tuple)) and all(
                isinstance(v, (str, int, float, bool, type(None))) for v in value
            ):
                for v in value:
                    if isinstance(v, str) and len(v) > MAX_DETAIL_VALUE_CHARS:
                        problems.append(f"detail list value too long: {key!r}")
            else:
                problems.append(f"detail value must be a scalar or list of scalars: {key!r}")
    return problems


class Span:
    """One traced stage. ``detail`` is mutable while the span is
    open (the caller fills in counts as they become known) and is
    validated when the span closes."""

    def __init__(self, name: str, started_at_ms: float) -> None:
        self.name = name
        self.started_at_ms = started_at_ms
        self.detail: dict[str, Any] = {}
        self.status = "ok"
        self.duration_ms = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "started_at_ms": round(self.started_at_ms, 3),
            "detail": dict(self.detail),
        }


@contextmanager
def null_span():
    """A span that discards everything — used when tracing is off
    (``trace=None``) so instrumented code needs no conditionals."""
    yield Span("null", 0.0)


def span_for(trace: Trace | None, name: str):
    """The span context manager for ``name`` on ``trace`` — a real
    span when tracing is on, a discarding one when it is not."""
    if trace is None:
        return null_span()
    return trace.span(name)


class Trace:
    """One request's trace. Created by the router, passed down to
    the pipeline (``answer_question(..., trace=trace)``), finished
    by the router, stored in the sink. ``clock`` / ``now`` are
    injectable for deterministic tests."""

    def __init__(
        self,
        endpoint: str,
        *,
        query_hash: str | None = None,
        request_id: str | None = None,
        cache_hit: bool = False,
        clock: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.trace_id = uuid.uuid4().hex
        self.endpoint = endpoint
        self.query_hash = query_hash
        self.request_id = request_id
        self.cache_hit = cache_hit
        self._clock = clock or time.perf_counter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._started = self._clock()
        self._started_at = self._now()
        self._spans: list[Span] = []

    @contextmanager
    def span(self, name: str):
        """Time one stage. The span's detail is validated when the
        block exits; an exception marks the span as an error and
        propagates. An UNSAFE detail never reaches the store: the
        span is recorded with status "error" and the detail
        replaced by a rejection note — tracing degrades, it never
        breaks the request."""
        span = Span(name, (self._clock() - self._started) * 1000.0)
        try:
            yield span
        except Exception:
            span.status = "error"
            raise
        finally:
            span.duration_ms = (self._clock() - self._started) * 1000.0 - span.started_at_ms
            problems = _validate_detail(span.detail)
            if problems:
                span.status = "error"
                span.detail = {"_rejected": len(problems), "_reason": problems[0]}
            self._spans.append(span)

    def finish(self, *, status: str = "ok", outcome: str = "") -> dict[str, Any]:
        """Close the trace and return its JSON record (also what the
        sink stores). ``outcome`` is a short label: \"answered\",
        \"refused:no_grounding\", \"cache_hit\", \"error\", ..."""
        return {
            "trace_id": self.trace_id,
            "endpoint": self.endpoint,
            "request_id": self.request_id,
            "query_hash": self.query_hash,
            "cache_hit": self.cache_hit,
            "started_at": self._started_at.isoformat(),
            "duration_ms": round((self._clock() - self._started) * 1000.0, 3),
            "status": status,
            "outcome": outcome,
            "spans": [s.to_dict() for s in self._spans],
        }


class TraceSink:
    """Where finished traces go: a bounded in-memory ring (newest
    first on read) plus an optional size-rotated JSONL file.
    Thread-safe (one lock around store + read)."""

    def __init__(
        self,
        *,
        max_traces: int = DEFAULT_MAX_TRACES,
        file_path: str | Path | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        if max_traces < 1:
            raise ValueError("max_traces must be >= 1")
        if max_files < 1:
            raise ValueError("max_files must be >= 1")
        self._max_traces = max_traces
        self._ring: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._file_path = Path(file_path) if file_path else None
        self._max_file_bytes = max_file_bytes
        self._max_files = max_files

    @classmethod
    def from_settings(cls, settings) -> TraceSink:
        return cls(
            max_traces=settings.kv_trace_max_traces,
            file_path=settings.kv_trace_file or None,
        )

    @property
    def file_path(self) -> Path | None:
        return self._file_path

    def store(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._ring[record["trace_id"]] = record
            while len(self._ring) > self._max_traces:
                self._ring.popitem(last=False)  # evict oldest
            if self._file_path is not None:
                self._append_to_file(record)

    def get(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._ring.get(trace_id)
            return dict(record) if record is not None else None

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            records = list(reversed(self._ring.values()))
        return [dict(r) for r in records[: max(0, limit)]]

    def __len__(self) -> int:
        with self._lock:
            return len(self._ring)

    def _append_to_file(self, record: dict[str, Any]) -> None:
        assert self._file_path is not None
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        if self._file_path.exists() and self._file_path.stat().st_size >= self._max_file_bytes:
            self._rotate()
        with self._file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rotate(self) -> None:
        """Shift trace.jsonl -> .1 -> .2, dropping the oldest."""
        assert self._file_path is not None
        base = self._file_path
        oldest = base.with_name(base.name + f".{self._max_files - 1}")
        if oldest.exists():
            oldest.unlink()
        for i in range(self._max_files - 2, 0, -1):
            older = base.with_name(base.name + f".{i}")
            if older.exists():
                older.rename(base.with_name(base.name + f".{i + 1}"))
        if base.exists():
            base.rename(base.with_name(base.name + ".1"))


# The process-wide sink, shared by every KV router (RAG, voice,
# matching) and read by the admin traces endpoint. Configured from
# settings on first use; all routers share the same Settings object,
# so the configuration is identical whichever router builds first.
_sink: TraceSink | None = None
_sink_lock = threading.Lock()


def get_sink(settings=None) -> TraceSink:
    global _sink
    with _sink_lock:
        if _sink is None:
            _sink = TraceSink.from_settings(settings) if settings is not None else TraceSink()
        return _sink


def reset_sink() -> None:
    """Drop the process-wide sink (tests only — the next get_sink
    builds a fresh one)."""
    global _sink
    with _sink_lock:
        _sink = None
