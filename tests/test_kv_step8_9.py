"""Step 8.9 tests: the agent trace log — the Trace/Sink unit
behaviour (spans, PII rejection, ring eviction, file rotation),
the router wiring (/ask, /search, /extract, /matches), the
admin-only traces endpoint, and the PII audit (no raw text in
any recorded trace).

The sink is process-wide (shared by every KV router), so the
router fixtures reset it first — counts are then deterministic
within each test regardless of what other test files stored.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.kv_matching import build_router as build_kv_matching_router
from backend.kv_rag import build_router as build_kv_rag_router
from backend.kv_traces import build_router as build_kv_traces_router
from backend.kv_voice import build_router as build_kv_voice_router
from career_guidance.config import Settings
from career_guidance.kaamvaani.rag import (
    RagStore,
    load_snapshot_file,
)
from career_guidance.kaamvaani.trace import (
    Trace,
    TraceSink,
    get_sink,
    hash_query,
    null_span,
    reset_sink,
    span_for,
)
from career_guidance.migrations import migrate
from career_guidance.users import User

ROOT = Path(__file__).resolve().parents[1]


def _admin_user():
    return User(
        id="admin-1",
        email="admin@example.com",
        name="Admin",
        picture="",
        provider="test",
        role="admin",
        created_at="2026-11-21T00:00:00+00:00",
        last_login_at="2026-11-21T00:00:00+00:00",
    )


def _deny_user():
    raise HTTPException(status_code=403, detail="admin only")


# --------------------------------------------------------------------------- #
# hash_query
# --------------------------------------------------------------------------- #


def test_hash_query_is_deterministic_hex():
    assert hash_query("how do i become an electrician") == hash_query(
        "how do i become an electrician"
    )
    assert len(hash_query("x")) == 16
    assert all(c in "0123456789abcdef" for c in hash_query("x"))
    assert hash_query("a") != hash_query("b")


# --------------------------------------------------------------------------- #
# Trace + spans (deterministic clock)
# --------------------------------------------------------------------------- #


class _FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_trace_records_spans_with_deterministic_durations():
    clock = _FakeClock()
    now = lambda: datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)  # noqa: E731
    trace = Trace("/api/v1/kv/rag/ask", query_hash="abc123", clock=clock, now=now)
    clock.advance(0.010)
    with trace.span("translate") as span:
        span.detail["applied"] = True
        clock.advance(0.002)
    with trace.span("retrieve") as span:
        span.detail["hits"] = 5
        clock.advance(0.020)
    clock.advance(0.005)
    record = trace.finish(status="ok", outcome="answered")
    assert record["endpoint"] == "/api/v1/kv/rag/ask"
    assert record["query_hash"] == "abc123"
    assert record["started_at"] == "2026-11-21T10:00:00+00:00"
    assert record["duration_ms"] == pytest.approx(37.0)
    assert record["status"] == "ok"
    assert record["outcome"] == "answered"
    assert record["cache_hit"] is False
    assert [s["name"] for s in record["spans"]] == ["translate", "retrieve"]
    assert record["spans"][0]["duration_ms"] == pytest.approx(2.0)
    assert record["spans"][0]["started_at_ms"] == pytest.approx(10.0)
    assert record["spans"][0]["detail"] == {"applied": True}
    assert record["spans"][1]["duration_ms"] == pytest.approx(20.0)
    assert record["spans"][1]["detail"] == {"hits": 5}
    assert all(s["status"] == "ok" for s in record["spans"])


def test_span_exception_marks_error_and_propagates():
    trace = Trace("/x")
    with pytest.raises(RuntimeError, match="boom"):
        with trace.span("retrieve"):
            raise RuntimeError("boom")
    record = trace.finish(status="error", outcome="error")
    assert record["spans"][0]["status"] == "error"
    assert record["spans"][0]["name"] == "retrieve"


def test_unsafe_detail_is_rejected_not_stored():
    trace = Trace("/x")
    with trace.span("extract") as span:
        span.detail["city"] = "Madurai"
        span.detail["skills_count"] = 3
    record = trace.finish()
    span_record = record["spans"][0]
    assert span_record["status"] == "error"
    assert span_record["detail"]["_rejected"] == 1
    assert "city" in span_record["detail"]["_reason"]
    assert "Madurai" not in json.dumps(record)
    # The safe key is dropped with the unsafe one: a rejected detail
    # is replaced wholesale, never partially kept.
    assert "skills_count" not in span_record["detail"]


@pytest.mark.parametrize(
    "key", ["query", "transcript", "profile", "answer", "phone", "City", "NAME"]
)
def test_forbidden_detail_keys_are_rejected(key):
    trace = Trace("/x")
    with trace.span("s") as span:
        span.detail[key] = "some value"
    assert trace.finish()["spans"][0]["status"] == "error"


def test_long_detail_value_is_rejected():
    trace = Trace("/x")
    with trace.span("s") as span:
        span.detail["note"] = "x" * 501
    record = trace.finish()
    assert record["spans"][0]["status"] == "error"
    assert "too long" in record["spans"][0]["detail"]["_reason"]


def test_long_detail_list_value_is_rejected():
    trace = Trace("/x")
    with trace.span("s") as span:
        span.detail["notes"] = ["ok", "x" * 501]
    record = trace.finish()
    assert record["spans"][0]["status"] == "error"
    assert "too long" in record["spans"][0]["detail"]["_reason"]
    assert "x" * 501 not in json.dumps(record)


def test_non_scalar_detail_value_is_rejected():
    trace = Trace("/x")
    with trace.span("s") as span:
        span.detail["nested"] = {"a": 1}
    assert trace.finish()["spans"][0]["status"] == "error"


def test_safe_detail_values_pass_through():
    trace = Trace("/x")
    with trace.span("s") as span:
        span.detail["hits"] = 5
        span.detail["top_score"] = 0.9123
        span.detail["applied"] = True
        span.detail["label"] = "answered"
        span.detail["nothing"] = None
        span.detail["ids"] = ["a", "b"]
        span.detail["pair"] = ("x", 1)  # tuples of scalars are fine too
    record = trace.finish()
    assert record["spans"][0]["status"] == "ok"
    assert record["spans"][0]["detail"]["ids"] == ["a", "b"]


def test_span_for_none_discards():
    with span_for(None, "retrieve") as span:
        span.detail["hits"] = 5
    with null_span() as span:
        span.detail["hits"] = 5
    # No trace exists to inspect — the point is no error is raised.


# --------------------------------------------------------------------------- #
# Sink
# --------------------------------------------------------------------------- #


def _record(trace_id: str) -> dict:
    return {
        "trace_id": trace_id,
        "endpoint": "/x",
        "request_id": None,
        "query_hash": None,
        "cache_hit": False,
        "started_at": "2026-11-21T10:00:00+00:00",
        "duration_ms": 1.0,
        "status": "ok",
        "outcome": "answered",
        "spans": [],
    }


def test_sink_ring_evicts_oldest():
    sink = TraceSink(max_traces=3)
    for i in range(5):
        sink.store(_record(f"t{i}"))
    assert len(sink) == 3
    assert sink.get("t0") is None  # evicted
    assert sink.get("t1") is None  # evicted
    assert sink.get("t4") is not None
    assert [r["trace_id"] for r in sink.recent()] == ["t4", "t3", "t2"]
    assert [r["trace_id"] for r in sink.recent(2)] == ["t4", "t3"]
    assert sink.get("nope") is None


def test_sink_rejects_bad_capacity():
    with pytest.raises(ValueError, match="max_traces"):
        TraceSink(max_traces=0)
    with pytest.raises(ValueError, match="max_files"):
        TraceSink(max_files=0)


def test_sink_file_appends_jsonl_and_rotates(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = TraceSink(max_traces=100, file_path=path, max_file_bytes=200, max_files=3)
    for i in range(12):
        sink.store(_record(f"f{i}"))
    # Rotation happened (files .1 and/or .2 exist) and every line
    # across all files is valid JSON with a trace_id.
    files = sorted(p for p in tmp_path.iterdir() if p.name.startswith("traces.jsonl"))
    assert len(files) >= 2
    seen = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            seen.append(json.loads(line)["trace_id"])
    assert seen  # non-empty
    assert len(set(seen)) == len(seen)  # no duplicates across rotations
    assert "f11" in seen  # the newest trace is in the current file


def test_sink_is_thread_safe():
    sink = TraceSink(max_traces=1000)
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(25):
                sink.store(_record(f"w{n}-{i}"))
        except Exception as error:  # noqa: BLE001 - collected, asserted below
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(sink) == 100


def test_get_sink_singleton_and_reset():
    reset_sink()
    a = get_sink(Settings())
    b = get_sink(Settings())
    assert a is b
    reset_sink()
    assert get_sink(Settings()) is not a
    reset_sink()


def test_sink_from_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KV_TRACE_FILE", str(tmp_path / "t.jsonl"))
    monkeypatch.setenv("KV_TRACE_MAX_TRACES", "5")
    from career_guidance.config import load_settings

    sink = TraceSink.from_settings(load_settings())
    assert sink.file_path == tmp_path / "t.jsonl"
    for i in range(7):
        sink.store(_record(f"s{i}"))
    assert len(sink) == 5


# --------------------------------------------------------------------------- #
# Router wiring
# --------------------------------------------------------------------------- #


@pytest.fixture()
def rag_app(tmp_path):
    """Standalone app: kv_rag + kv_traces (admin stub) over a scratch
    DB holding the real snapshot v2."""
    reset_sink()
    db = str(tmp_path / "rag.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_rag_router(settings))
    app.include_router(build_kv_traces_router(settings, _admin_user))
    with TestClient(app) as client:
        yield client
    reset_sink()


@pytest.fixture()
def rag_app_denied(tmp_path):
    """Same, but the admin dependency denies everyone (403)."""
    reset_sink()
    db = str(tmp_path / "rag.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_rag_router(settings))
    app.include_router(build_kv_traces_router(settings, _deny_user))
    with TestClient(app) as client:
        yield client
    reset_sink()


def _get_trace(client, trace_id):
    r = client.get(f"/api/v1/kv/traces/{trace_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_ask_is_traced_with_stages(rag_app):
    r = rag_app.post("/api/v1/kv/rag/ask", json={"question": "how do i become an electrician"})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    trace_id = body["trace_id"]
    trace = _get_trace(rag_app, trace_id)
    assert trace["endpoint"] == "/api/v1/kv/rag/ask"
    assert trace["query_hash"] == hash_query("how do i become an electrician")
    assert trace["outcome"] == "answered"
    assert trace["status"] == "ok"
    assert trace["cache_hit"] is False
    assert [s["name"] for s in trace["spans"]] == ["translate", "retrieve", "verify"]
    assert all(s["status"] == "ok" for s in trace["spans"])
    assert all(s["duration_ms"] >= 0 for s in trace["spans"])
    assert trace["duration_ms"] >= 0
    retrieve = trace["spans"][1]
    assert retrieve["detail"]["hits"] >= 1
    assert retrieve["detail"]["top_score"] > 0
    verify = trace["spans"][2]
    assert verify["detail"]["verified"] is True
    assert verify["detail"]["sentences"] >= 1
    translate = trace["spans"][0]
    assert translate["detail"]["applied"] is False  # English: no translation
    assert translate["detail"]["terms"] == 0
    assert translate["detail"]["source_language"] == "en"


def test_ask_refusal_is_traced(rag_app):
    r = rag_app.post("/api/v1/kv/rag/ask", json={"question": "can you cure my back pain"})
    assert r.json()["refused"] is True
    trace = _get_trace(rag_app, r.json()["trace_id"])
    assert trace["outcome"] == "refused:out_of_scope"
    # The out-of-scope refusal happens before retrieval: only the
    # translate span ran.
    assert [s["name"] for s in trace["spans"]] == ["translate"]


def test_ask_cache_hit_is_traced_without_spans(rag_app):
    q = {"question": "how do i become an electrician"}
    first = rag_app.post("/api/v1/kv/rag/ask", json=q).json()
    second = rag_app.post("/api/v1/kv/rag/ask", json=q).json()
    assert second["trace_id"] != first["trace_id"]
    trace = _get_trace(rag_app, second["trace_id"])
    assert trace["cache_hit"] is True
    assert trace["outcome"] == "cache_hit"
    assert trace["spans"] == []  # nothing was computed


def test_search_is_traced(rag_app):
    r = rag_app.post("/api/v1/kv/rag/search", json={"query": "electrician training", "top_k": 3})
    assert r.status_code == 200
    trace = _get_trace(rag_app, r.json()["trace_id"])
    assert trace["endpoint"] == "/api/v1/kv/rag/search"
    assert [s["name"] for s in trace["spans"]] == ["retrieve"]
    assert trace["spans"][0]["detail"]["hits"] >= 1


def test_trace_contains_no_raw_text(rag_app):
    """PII audit: the question (with a phone number in it) and the
    answer text must not appear anywhere in the recorded trace."""
    question = "my phone is 9876543210, how do i become an electrician"
    r = rag_app.post("/api/v1/kv/rag/ask", json={"question": question})
    assert r.status_code == 200
    trace = _get_trace(rag_app, r.json()["trace_id"])
    blob = json.dumps(trace)
    assert "9876543210" not in blob
    assert question not in blob
    assert "my phone is" not in blob
    # The answer text (a chunk quote) is not in the trace either.
    assert r.json()["answer"] not in blob
    assert "answer" not in trace
    for span in trace["spans"]:
        assert "query" not in span["detail"]
        assert "question" not in span["detail"]


def test_traces_list_is_newest_first(rag_app):
    ids = []
    for q in ("how do i become an electrician", "what is an ITI course"):
        ids.append(rag_app.post("/api/v1/kv/rag/ask", json={"question": q}).json()["trace_id"])
    r = rag_app.get("/api/v1/kv/traces")
    assert r.status_code == 200
    listed = [t["trace_id"] for t in r.json()["traces"]]
    assert listed[0] == ids[1]  # newest first
    assert listed[1] == ids[0]
    assert r.json()["count"] == 2
    r = rag_app.get("/api/v1/kv/traces?limit=1")
    assert len(r.json()["traces"]) == 1
    assert r.json()["traces"][0]["trace_id"] == ids[1]


def test_unknown_trace_is_404(rag_app):
    assert rag_app.get("/api/v1/kv/traces/doesnotexist").status_code == 404


def test_traces_endpoints_require_admin(rag_app_denied):
    r = rag_app_denied.post(
        "/api/v1/kv/rag/ask", json={"question": "how do i become an electrician"}
    )
    assert r.status_code == 200
    trace_id = r.json()["trace_id"]
    assert rag_app_denied.get("/api/v1/kv/traces").status_code == 403
    assert rag_app_denied.get(f"/api/v1/kv/traces/{trace_id}").status_code == 403


@pytest.fixture()
def voice_app():
    reset_sink()
    settings = Settings()
    app = FastAPI()
    app.include_router(build_kv_voice_router(settings))
    app.include_router(build_kv_traces_router(settings, _admin_user))
    with TestClient(app) as client:
        yield client
    reset_sink()


def test_extract_is_traced_without_transcript_or_profile(voice_app):
    text = "I finished 12th in Madurai. I know tailoring and stitching. I need 21000 a month."
    r = voice_app.post("/api/v1/kv/voice/extract", json={"text": text, "language": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "deterministic"
    trace = _get_trace(voice_app, body["trace_id"])
    assert trace["endpoint"] == "/api/v1/kv/voice/extract"
    assert trace["outcome"] == "extracted"
    assert [s["name"] for s in trace["spans"]] == ["extract"]
    assert trace["spans"][0]["detail"]["method"] == "deterministic"
    assert trace["spans"][0]["detail"]["skills_count"] == len(body["profile"]["skills"])
    blob = json.dumps(trace)
    assert text not in blob
    assert "Madurai" not in blob
    assert "tailoring" not in blob
    assert "21000" not in blob


@pytest.fixture()
def matching_app(tmp_path):
    reset_sink()
    db = str(tmp_path / "kv.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_matching_router(settings))
    app.include_router(build_kv_traces_router(settings, _admin_user))
    with TestClient(app) as client:
        yield client
    reset_sink()


def test_matches_is_traced_without_profile(matching_app):
    from career_guidance.kaamvaani.profile import VoiceSession

    session = VoiceSession(state="matches")
    profile = {
        "skills": ["farming", "computer literacy"],
        "interests": "",
        "education": "12th pass",
        "city": "Madurai",
        "income_text": "₹15,000 / month",
        "income_monthly": 15000,
        "goal_type": "job_6_months",
        "raw_text": "I finished 12th in Madurai.",
    }
    r = matching_app.post(
        "/api/v1/kv/matches",
        json={"session": session.model_dump(mode="json"), "profile": profile, "top_k": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    trace = _get_trace(matching_app, body["trace_id"])
    assert trace["endpoint"] == "/api/v1/kv/matches"
    assert trace["outcome"] == "matched"
    assert [s["name"] for s in trace["spans"]] == ["match"]
    assert trace["spans"][0]["detail"]["returned"] == len(body["matches"])
    assert trace["spans"][0]["detail"]["top_score"] > 0
    blob = json.dumps(trace)
    assert "Madurai" not in blob
    assert "farming" not in blob
    assert "15000" not in blob


def test_matches_wrong_state_is_not_traced(matching_app):
    from career_guidance.kaamvaani.profile import VoiceSession

    session = VoiceSession(state="questions")
    profile = {
        "skills": ["farming"],
        "interests": "",
        "education": "12th pass",
        "city": "Madurai",
        "income_text": "",
        "income_monthly": None,
        "goal_type": "explore",
        "raw_text": "",
    }
    r = matching_app.post(
        "/api/v1/kv/matches",
        json={"session": session.model_dump(mode="json"), "profile": profile},
    )
    assert r.status_code == 400
    assert "trace_id" not in r.json()
    assert matching_app.get("/api/v1/kv/traces").json()["count"] == 0
