"""Production-hardening regressions.

Two deploy-time footguns are pinned here:
- production must refuse to boot without SESSION_SECRET (the old behaviour
  logged an error and kept running on a public, known dummy secret, which
  would let anyone forge a session cookie);
- the CORS allow-list is env-driven (CORS_ALLOW_ORIGINS) instead of a
  hardcoded wildcard.
"""

import pytest

from backend.auth import load_auth_settings
from backend.main import _cors_allow_origins


def test_session_secret_required_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        load_auth_settings()


def test_session_secret_dummy_only_in_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    assert load_auth_settings().secret == "dev-insecure-secret-change-me"


def test_session_secret_from_env_is_used(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "a-real-secret")
    assert load_auth_settings().secret == "a-real-secret"


def test_cors_defaults_to_wildcard(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert _cors_allow_origins() == ["*"]


def test_cors_origins_parsed_from_env(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://career-guidance-web-sigma.vercel.app, https://example.com ",
    )
    assert _cors_allow_origins() == [
        "https://career-guidance-web-sigma.vercel.app",
        "https://example.com",
    ]


def test_cors_empty_env_falls_back_to_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", " , ")
    assert _cors_allow_origins() == ["*"]
