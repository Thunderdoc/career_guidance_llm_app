"""API contract tests for the FastAPI backend."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    os.environ["DATABASE_PATH"] = str(tmp_path_factory.mktemp("db") / "t.db")
    from backend.main import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["occupations"] >= 300


def test_recommend_flow_and_history(client):
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


def test_recommend_rejects_empty(client):
    assert client.post("/api/v1/recommend", json={"skills": ""}).status_code == 422


def test_resume_upload(client):
    r = client.post(
        "/api/v1/resume/extract",
        files={"file": ("cv.txt", b"Worked with Python and SQL on dashboards")},
    )
    assert r.status_code == 200 and "python" in r.json()["skills"]


def test_career_detail_and_search(client):
    assert client.get("/api/v1/careers/search", params={"q": "web dev"}).json()["results"]
    d = client.get("/api/v1/careers/15-1134.00").json()
    assert d["title"] == "Web Developers" and d["market"]["currency"] == "INR"
    assert client.get("/api/v1/careers/nope").status_code == 404


def test_assessment_roundtrip(client):
    qs = client.get("/api/v1/assessment/questions").json()["questions"]
    answers = {q["id"]: (5 if q["dim"] == "I" else 2) for q in qs}
    s = client.post("/api/v1/assessment", json={"answers": answers}).json()
    assert s["holland_code"].startswith("I")
    r = client.post(
        "/api/v1/recommend", json={"skills": "python", "interests_profile": s["scores"]}
    )
    assert r.status_code == 200


def test_job_fit(client):
    r = client.post(
        "/api/v1/jobs/fit",
        json={"skills": "python, sql", "job_description": "Need Python, SQL, Tableau and AWS"},
    )
    body = r.json()
    assert body["readiness"] == 50 and "tableau" in body["missing"]


def test_skill_suggest(client):
    assert (
        "python" in client.get("/api/v1/skills/suggest", params={"q": "py"}).json()["suggestions"]
    )
