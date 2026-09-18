"""Shared pytest fixtures.

The product is private (all content endpoints require a session), so the API
tests need a signed-in client. ``login`` performs the magic-link flow, which
needs no external services.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    """A freshly imported backend with an isolated SQLite database."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


@pytest.fixture()
def client(app_module):
    with TestClient(app_module.app) as c:
        yield c


def login(client: TestClient, email: str = "user@example.com") -> dict:
    """Sign in via the magic-link fallback and return the user payload."""
    r = client.post("/api/v1/auth/magic-link", json={"email": email})
    assert r.status_code == 200, r.text
    link = r.json()["dev_link"]
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 303
    me = client.get("/api/v1/auth/me").json()["user"]
    assert me and me["email"] == email
    return me


@pytest.fixture()
def auth_client(client):
    """Signed-in client (regular user)."""
    login(client)
    return client


@pytest.fixture()
def admin_client(client):
    """Signed-in client whose e-mail is in ADMIN_EMAILS."""
    login(client, "boss@example.com")
    return client
