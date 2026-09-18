"""API contract tests for the FastAPI backend (authenticated product)."""

from __future__ import annotations

import pytest

from tests.conftest import login

PUBLIC_GET = ["/api/v1/health", "/api/v1/meta", "/api/v1/skills/suggest?q=py"]
PRIVATE = [
    ("GET", "/api/v1/careers/15-1134.00"),
    ("GET", "/api/v1/assessment/questions"),
    ("GET", "/api/v1/history"),
    ("GET", "/api/v1/analytics"),
    ("POST", "/api/v1/recommend"),
    ("POST", "/api/v1/assessment"),
    ("POST", "/api/v1/jobs/fit"),
]


@pytest.mark.parametrize("path", PUBLIC_GET)
def test_public_endpoints_stay_open(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("method,path", PRIVATE)
def test_private_endpoints_require_session(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


def test_health_reports_private_app(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["public_app"] is False


def test_recommend_flow_and_history(auth_client):
    client = auth_client
    r = client.post(
        "/api/v1/recommend", json={"skills": "Python, SQL, Excel", "goals": "data analyst"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["recommendations"]) == 5 and len(body["priority_skills"]) == 3
    rec = body["recommendations"][0]
    assert rec["career_id"] and rec["market"]["salary_p50"] and rec["provenance"]["ids"]
    h = client.get("/api/v1/history").json()
    assert h["runs"][0]["id"] == body["run_id"]
    assert client.get(f"/api/v1/export/{body['run_id']}.md").status_code == 200
    assert client.get("/api/v1/analytics").json()["total_runs"] >= 1


def test_recommend_rejects_empty(auth_client):
    assert auth_client.post("/api/v1/recommend", json={"skills": ""}).status_code == 422


def test_resume_upload(auth_client):
    r = auth_client.post(
        "/api/v1/resume/extract",
        files={"file": ("cv.txt", b"Worked with Python and SQL on dashboards")},
    )
    assert r.status_code == 200 and "python" in r.json()["skills"]


def test_career_detail_and_search(auth_client):
    assert auth_client.get("/api/v1/careers/search", params={"q": "web dev"}).json()["results"]
    d = auth_client.get("/api/v1/careers/15-1134.00").json()
    assert d["title"] == "Web Developers" and d["market"]["currency"] == "INR"
    assert auth_client.get("/api/v1/careers/nope").status_code == 404


def test_assessment_roundtrip(auth_client):
    qs = auth_client.get("/api/v1/assessment/questions").json()["questions"]
    answers = {q["id"]: (5 if q["dim"] == "I" else 2) for q in qs}
    s = auth_client.post("/api/v1/assessment", json={"answers": answers}).json()
    assert s["holland_code"][0] == "I" and len(s["scores"]) == 6


def test_job_fit(auth_client):
    r = auth_client.post(
        "/api/v1/jobs/fit",
        json={
            "skills": "Python, SQL",
            "job_description": "Need Python, SQL, Tableau and statistics for a data analyst role",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert 0 < body["readiness"] < 100 and "tableau" in body["missing"]


def test_history_is_scoped_to_the_owner(client):
    login(client, "a@example.com")
    client.post("/api/v1/recommend", json={"skills": "Python, SQL, Excel", "goals": "data"})
    run_id = client.get("/api/v1/history").json()["runs"][0]["id"]
    client.post("/api/v1/auth/logout")

    login(client, "b@example.com")
    assert client.get("/api/v1/history").json()["runs"] == []
    # The other user's run is not exportable either.
    assert client.get(f"/api/v1/export/{run_id}.md").status_code == 404
