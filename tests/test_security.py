"""Phase 6 security pass: headers, cookie flags, upload caps (see also
tests/test_error_shapes.py for the CSV/resume cap regression tests)."""

from __future__ import annotations

from fastapi import Response

from backend.auth import Auth, AuthSettings
from career_guidance.users import User


def test_security_headers_on_api_responses(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers["permissions-policy"]
    csp = r.headers["content-security-policy-report-only"]
    assert "default-src 'self'" in csp and "object-src 'none'" in csp


def test_security_headers_on_error_responses(client):
    r = client.get("/api/v1/careers/nope", follow_redirects=False)
    assert r.headers.get("x-content-type-options") == "nosniff"


def _auth(app_env: str, public_url: str) -> Auth:
    settings = AuthSettings(
        secret="test-secret",
        google_client_id="",
        google_client_secret="",
        public_url=public_url,
        admin_emails=set(),
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        app_env=app_env,
    )
    return Auth(settings, store=None)  # type: ignore[arg-type]


_USER = User(
    id="u1",
    email="u@example.com",
    name="U",
    picture="",
    provider="test",
    role="user",
    created_at="",
    last_login_at="",
)


def _cookie_header(auth: Auth) -> str:
    response = Response()
    auth.issue(response, _USER)
    return response.headers.get("set-cookie", "")


def test_session_cookie_flags_in_production():
    header = _cookie_header(_auth("production", "http://internal.example"))
    assert "HttpOnly" in header
    assert "Secure" in header  # forced on in production even over http base
    assert "samesite=lax" in header.lower()


def test_session_cookie_secure_on_https_dev():
    header = _cookie_header(_auth("development", "https://app.example"))
    assert "Secure" in header and "HttpOnly" in header


def test_session_cookie_not_secure_on_http_dev():
    header = _cookie_header(_auth("development", "http://localhost:3000"))
    assert "Secure" not in header  # local dev must keep working over http
    assert "HttpOnly" in header
