"""Phase 1 guest-first access.

Anonymous visitors may run ONE thing: POST /api/v1/recommend (rate-limited,
stored as an anonymous run). Every saved-data surface stays authenticated.
"""

from __future__ import annotations

import pytest

from tests.conftest import login


def test_anonymous_recommend_works_and_is_flagged(client):
    r = client.post(
        "/api/v1/recommend",
        json={"skills": "Python, SQL, Excel", "goals": "data analyst"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anonymous"] is True
    assert len(body["recommendations"]) == 5
    assert body["run_id"] is not None
    # stored as an anonymous run (user_id NULL) in the admin "anonymous" sense
    from backend.main import _db  # the app under test shares this module

    stored = [run for run in _db.list_runs(limit=10) if run.id == body["run_id"]]
    assert stored and stored[0].user_id is None
    assert stored[0].profile.get("anonymous") is True


def test_signed_in_recommend_is_not_anonymous(auth_client):
    r = auth_client.post("/api/v1/recommend", json={"skills": "Python, SQL"})
    assert r.status_code == 200, r.text
    assert r.json()["anonymous"] is False


def test_anonymous_recommend_accepts_constraints_and_echoes_them(client):
    payload = {
        "skills": "Python, SQL",
        "constraints": {
            "persona": "college",
            "city": "Madurai",
            "relocate": True,
            "hours_per_week": 8,
            "budget_range": "free",
            "language": "en",
            "goal_type": "job_6_months",
        },
    }
    r = client.post("/api/v1/recommend", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["constraints_used"] == payload["constraints"]
    from backend.main import _db

    stored = [run for run in _db.list_runs(limit=10) if run.id == r.json()["run_id"]]
    assert stored and stored[0].profile.get("constraints") == payload["constraints"]


def test_recommend_without_constraints_stays_backward_compatible(client):
    r = client.post("/api/v1/recommend", json={"skills": "Java, Spring"})
    assert r.status_code == 200, r.text
    assert r.json()["constraints_used"] is None


def test_anonymous_recommend_rejects_bad_constraints(client):
    r = client.post(
        "/api/v1/recommend",
        json={"skills": "Python", "constraints": {"hours_per_week": 500}},
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/history"),
        ("DELETE", "/api/v1/history"),
        ("GET", "/api/v1/me/runs"),
        ("GET", "/api/v1/me/progress"),
        ("GET", "/api/v1/analytics"),
        ("GET", "/api/v1/assessment/questions"),
        ("POST", "/api/v1/jobs/fit"),
        ("GET", "/api/v1/export/1.md"),
    ],
)
def test_saved_data_routes_stay_401_anonymously(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


def test_admin_stays_locked_anonymously(client):
    assert client.get("/api/v1/admin/overview").status_code == 401
    assert client.get("/api/v1/billing/demo-requests").status_code == 401


def test_anonymous_run_not_visible_in_signed_in_history(client):
    r = client.post("/api/v1/recommend", json={"skills": "Python, SQL"})
    assert r.status_code == 200
    anon_run_id = r.json()["run_id"]
    login(client)
    history = client.get("/api/v1/history").json()["runs"]
    assert all(run["id"] != anon_run_id for run in history)
    # and the anonymous run cannot be exported by the signed-in stranger
    assert client.get(f"/api/v1/export/{anon_run_id}.md").status_code == 404


def test_demo_request_stores_lead_and_admin_can_read_it(client, admin_client):
    payload = {
        "name": "Priya Nair",
        "email": "priya@example-college.edu",
        "organisation": "Example College",
        "seats": 120,
        "message": "Placement cell demo please",
    }
    r = client.post("/api/v1/billing/demo-request", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["stored"] is True
    leads = admin_client.get("/api/v1/billing/demo-requests").json()["requests"]
    assert leads and leads[0]["organisation"] == "Example College"
    assert leads[0]["email"] == "priya@example-college.edu"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "A", "email": "a@b.co", "organisation": "X"},
        {"name": "Ab", "email": "not-an-email", "organisation": "Xy"},
        {"name": "Ab", "email": "a@b.co", "organisation": "Xy", "seats": 0},
    ],
)
def test_demo_request_rejects_invalid(client, payload):
    assert client.post("/api/v1/billing/demo-request", json=payload).status_code == 422
