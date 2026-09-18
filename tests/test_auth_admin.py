"""Auth, account and admin API tests (magic-link flow, no external services)."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    import importlib

    import backend.main as main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def _login(client: TestClient, email: str) -> None:
    r = client.post("/api/v1/auth/magic-link", json={"email": email})
    assert r.status_code == 200
    link = r.json()["dev_link"]  # SMTP not configured in tests
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 303
    assert "cg_session" in r.cookies or client.cookies.get("cg_session")


def test_anonymous_me_is_null(client):
    assert client.get("/api/v1/auth/me").json() == {"user": None}
    assert client.get("/api/v1/me/runs").status_code == 401
    assert client.get("/api/v1/admin/overview").status_code == 401


def test_magic_link_login_and_scoped_history(client):
    _login(client, "user@example.com")
    me = client.get("/api/v1/auth/me").json()["user"]
    assert me["email"] == "user@example.com" and me["is_admin"] is False

    r = client.post(
        "/api/v1/recommend",
        json={"skills": "Python, SQL, statistics", "goals": "data analyst"},
    )
    assert r.status_code == 200
    runs = client.get("/api/v1/me/runs").json()["runs"]
    assert len(runs) == 1 and runs[0]["recommendations"]

    client.post("/api/v1/me/progress", json={"skill": "SQL", "done": True})
    assert client.get("/api/v1/me/progress").json()["done"] == ["sql"]
    assert client.get("/api/v1/admin/overview").status_code == 403


def test_expired_or_reused_link_rejected(client):
    r = client.post("/api/v1/auth/magic-link", json={"email": "x@example.com"})
    link = r.json()["dev_link"]
    client.get(link, follow_redirects=False)
    again = client.get(link, follow_redirects=False)
    assert again.headers["location"].endswith("auth=expired")


def test_admin_flow(client):
    _login(client, "boss@example.com")
    assert client.get("/api/v1/auth/me").json()["user"]["is_admin"] is True
    ov = client.get("/api/v1/admin/overview").json()
    assert ov["users"]["total"] == 1 and "system" in ov

    users = client.get("/api/v1/admin/users").json()["users"]
    me_id = users[0]["id"]
    assert client.delete(f"/api/v1/admin/users/{me_id}").status_code == 400  # self-protect

    # content management: override + reset resources
    body = {"resources": [{"title": "T", "url": "https://x.y", "provider": "P", "free": True}]}
    assert client.put("/api/v1/admin/resource-overrides/sql", json=body).status_code == 200
    res = client.get("/api/v1/admin/resource-overrides?q=sql").json()["skills"]
    sql = next(s for s in res if s["skill"] == "sql")
    assert sql["overridden"] and sql["resources"][0]["title"] == "T"
    assert client.delete("/api/v1/admin/resource-overrides/sql").status_code == 200

    # feedback triage
    client.post("/api/v1/me/feedback", json={"rating": 4, "comment": "nice"})
    fb = client.get("/api/v1/admin/feedback").json()["feedback"]
    assert fb and fb[0]["status"] == "new"
    client.patch(f"/api/v1/admin/feedback/{fb[0]['id']}", json={"status": "resolved"})
    assert client.get("/api/v1/admin/feedback?status=resolved").json()["feedback"]
    assert client.get("/api/v1/admin/audit").json()["log"]
    assert os.environ["ADMIN_EMAILS"]
