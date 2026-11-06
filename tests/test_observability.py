"""Phase 6 observability: /ready, request ids, JSON logs, 500 shape, webhook."""

from __future__ import annotations

import json
import logging
import urllib.request

import pytest

from career_guidance import logging_setup
from career_guidance.logging_setup import JsonFormatter, redact_path


def test_health_is_liveness(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["version"]


def test_ready_ok(client):
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "catalog": "ok"}


def test_ready_503_with_breakdown_when_db_down(app_module, client, monkeypatch):
    class Down:
        def ping(self):
            return False

    monkeypatch.setattr(app_module, "_db", Down())
    r = client.get("/api/v1/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "error"
    assert body["checks"]["catalog"] == "ok"


def test_request_id_assigned_and_propagated(client):
    r = client.get("/api/v1/health")
    assert len(r.headers.get("x-request-id", "")) == 32
    r2 = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r2.headers["x-request-id"] == "trace-abc-123"


def test_recommend_log_line_has_no_profile_text(client, caplog):
    marker = "ZanzibarUniqueSkillText"
    with caplog.at_level(logging.INFO):
        r = client.post(
            "/api/v1/recommend",
            json={"skills": f"{marker} python sql", "goals": marker},
        )
    assert r.status_code == 200
    formatter = JsonFormatter()
    request_lines = [
        formatter.format(rec)
        for rec in caplog.records
        if getattr(rec, "path", None) == "/api/v1/recommend"
    ]
    assert request_lines, "expected a structured access log line"
    line = json.loads(request_lines[-1])
    assert line["method"] == "POST" and line["status"] == 200
    assert line["request_id"] and line["duration_ms"] >= 0
    for rec in caplog.records:  # nothing logged anywhere may carry profile text
        assert marker not in formatter.format(rec)


def test_unhandled_exception_becomes_uniform_500(app_module, client, monkeypatch):
    # Force an unhandled error inside an existing handler, after startup
    # (a late-added route would be shadowed by the SPA catch-all, and the
    # startup warm-up uses the same function, so patch only now).
    def _boom():
        raise RuntimeError("kaboom-test")

    monkeypatch.setattr(app_module, "load_taxonomy", _boom)
    r = client.get("/api/v1/health")
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Internal server error."
    assert body["request_id"] == r.headers["x-request-id"]
    assert "kaboom" not in r.text


def test_redact_path_scrubs_token_segments():
    token = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    assert redact_path(f"/api/v1/consent/confirm/{token}") == ("/api/v1/consent/confirm/[redacted]")
    assert redact_path("/api/v1/health") == "/api/v1/health"


def test_json_formatter_shape():
    record = logging.LogRecord(
        name="career_guidance",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    record.request_id = "rid-1"  # type: ignore[attr-defined]
    record.method, record.path, record.status, record.duration_ms = "GET", "/x", 200, 3.5  # type: ignore[attr-defined]
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "request"
    assert payload["request_id"] == "rid-1"
    assert payload["status"] == 200 and payload["duration_ms"] == 3.5


def test_webhook_noop_by_default(monkeypatch):
    monkeypatch.delenv("ERROR_WEBHOOK_URL", raising=False)
    assert logging_setup.notify_error_webhook("RuntimeError", "x") is False


def test_webhook_posts_minimal_payload(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode())
        return _Resp()

    monkeypatch.setenv("ERROR_WEBHOOK_URL", "https://hooks.example.test/err")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert logging_setup.notify_error_webhook("ValueError", "bad thing", "rid-9") is True
    assert captured["url"] == "https://hooks.example.test/err"
    assert captured["payload"] == {
        "event": "unhandled_error",
        "error_type": "ValueError",
        "message": "bad thing",
        "request_id": "rid-9",
    }


def test_webhook_failure_is_swallowed(monkeypatch):
    def boom(request, timeout=0):
        raise OSError("network down")

    monkeypatch.setenv("ERROR_WEBHOOK_URL", "https://hooks.example.test/err")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert logging_setup.notify_error_webhook("ValueError", "x") is False


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/ready"])
def test_public_endpoints_carry_request_id(client, path):
    assert client.get(path).headers.get("x-request-id")
