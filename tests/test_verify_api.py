"""Phase 3 API tests: authz (401), quiz flow, cooldown, project validation,
admin review, public-profile privacy, and the 90-day plan endpoints."""

from __future__ import annotations

import pytest

from career_guidance import verify
from tests.conftest import login


def _correct_answers(attempt: dict, skill: str, right: int | None = None) -> dict[str, int]:
    quiz = verify.get_quiz(skill)
    answers: dict[str, int] = {}
    remaining = len(attempt["questions"]) if right is None else right
    for shown in attempt["questions"]:
        original = next(q for q in quiz.questions if q.id == shown["id"])
        idx = shown["options"].index(original.options[original.correct])
        if remaining > 0:
            answers[shown["id"]] = idx
            remaining -= 1
        else:
            answers[shown["id"]] = (idx + 1) % len(shown["options"])
    return answers


def _pass_quiz(client, skill: str = "python") -> dict:
    r = client.get(f"/api/v1/skills/verify/{skill}/quiz")
    assert r.status_code == 200, r.text
    attempt = r.json()
    r = client.post(
        f"/api/v1/skills/verify/{skill}/submit",
        json={
            "attempt_token": attempt["attempt_token"],
            "answers": _correct_answers(attempt, skill),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------- authz
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/skills/verify/quizzes"),
        ("get", "/api/v1/skills/verify/mine"),
        ("get", "/api/v1/skills/verify/python/quiz"),
        ("post", "/api/v1/skills/verify/python/project"),
        ("get", "/api/v1/plan/90day"),
        ("post", "/api/v1/plan/90day"),
        ("put", "/api/v1/me/public-profile"),
    ],
)
def test_verify_routes_require_sign_in(client, method, path):
    if method in ("post", "put"):
        r = getattr(client, method)(path, json={})
    else:
        r = getattr(client, method)(path)
    assert r.status_code == 401, (method, path, r.status_code)


# ------------------------------------------------------------------ quiz flow
def test_quiz_flow_pass_verifies_skill(auth_client):
    body = _pass_quiz(auth_client)
    assert body["result"]["passed"] is True
    assert body["result"]["score_percent"] == 100.0
    assert body["verification"]["status"] == "verified"
    assert body["verification"]["source"] == "quiz"

    mine = auth_client.get("/api/v1/skills/verify/mine").json()
    states = {v["skill"]: v for v in mine["verifications"]}
    assert states["python"]["status"] == "verified"
    assert {q["skill"] for q in mine["quizzes"]} == {
        "python",
        "sql",
        "html-css",
        "excel",
        "communication",
    }


def test_quiz_response_has_no_answer_key(auth_client):
    r = auth_client.get("/api/v1/skills/verify/sql/quiz")
    assert r.status_code == 200
    assert "correct" not in r.text and "explanation" not in r.text


def test_unknown_skill_quiz_is_honest_404(auth_client):
    r = auth_client.get("/api/v1/skills/verify/astrophysics/quiz")
    assert r.status_code == 404
    assert "No quiz available for this skill" in r.json()["detail"]


def test_failed_attempt_triggers_cooldown(auth_client):
    attempt = auth_client.get("/api/v1/skills/verify/excel/quiz").json()
    r = auth_client.post(
        "/api/v1/skills/verify/excel/submit",
        json={
            "attempt_token": attempt["attempt_token"],
            "answers": _correct_answers(attempt, "excel", right=0),
        },
    )
    assert r.status_code == 200
    assert r.json()["result"]["passed"] is False
    assert r.json()["verification"]["status"] == "unverified"
    r = auth_client.get("/api/v1/skills/verify/excel/quiz")
    assert r.status_code == 429
    assert "cooldown" in r.json()["detail"].lower()


def test_submit_rejects_forged_token(auth_client):
    r = auth_client.post(
        "/api/v1/skills/verify/python/submit",
        json={"attempt_token": "AAAA.invalid", "answers": {}},
    )
    assert r.status_code == 400


# ------------------------------------------------------------------- projects
def test_project_submission_and_admin_review(client):
    # One shared TestClient: log in as the user first, then re-login as admin.
    me = login(client, "user@example.com")
    r = client.post(
        "/api/v1/skills/verify/python/project",
        json={
            "title": "Marks CLI tool",
            "link": "https://github.com/example/marks-cli",
            "description": "Parses CSV marksheets.",
            "checklist": ["Has automated tests", "README explains usage"],
        },
    )
    assert r.status_code == 200, r.text
    state = r.json()["verification"]
    assert state["status"] == "project_submitted"
    assert state["self_reported"] is True

    # A non-admin cannot review.
    r = client.post(
        "/api/v1/skills/verify/admin/review",
        json={"user_id": me["id"], "skill": "python", "approve": True},
    )
    assert r.status_code == 403

    client.post("/api/v1/auth/logout")
    login(client, "boss@example.com")
    r = client.post(
        "/api/v1/skills/verify/admin/review",
        json={"user_id": me["id"], "skill": "python", "approve": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification"]["status"] == "verified"
    assert r.json()["verification"]["self_reported"] is False


@pytest.mark.parametrize(
    "link", ["not-a-url", "ftp://example.com/x", "https://localhost", "javascript:alert(1)", ""]
)
def test_project_rejects_malformed_links(auth_client, link):
    r = auth_client.post(
        "/api/v1/skills/verify/sql/project",
        json={"title": "Some project", "link": link},
    )
    assert r.status_code == 422, link


# -------------------------------------------------------------- public profile
def _enable_profile(client, handle="ankit-dev", minor=False):
    r = client.put(
        "/api/v1/me/public-profile",
        json={"handle": handle, "public_profile": True, "is_minor": minor},
    )
    assert r.status_code == 200, r.text
    return r.json()["user"]


def test_public_profile_only_when_opted_in(auth_client):
    # No opt-in yet → 404 for any handle.
    assert auth_client.get("/api/v1/p/ankit-dev").status_code == 404
    _enable_profile(auth_client)
    _pass_quiz(auth_client)
    r = auth_client.get("/api/v1/p/ankit-dev")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handle"] == "ankit-dev"
    assert [s["skill"] for s in body["verified_skills"]] == ["python"]
    # Privacy: nothing identifying beyond display name/handle may appear.
    blob = r.text.lower()
    for forbidden in ("user@example.com", "email", "age", "school", "institute"):
        assert forbidden not in blob, forbidden


def test_public_profile_minor_is_force_disabled(auth_client):
    _enable_profile(auth_client, handle="young-dev", minor=True)
    assert auth_client.get("/api/v1/p/young-dev").status_code == 404


def test_public_profile_handle_must_be_unique(client):
    login(client, "one@example.com")
    _enable_profile(client, handle="taken-handle")
    client.post("/api/v1/auth/logout")
    login(client, "two@example.com")
    r = client.put(
        "/api/v1/me/public-profile",
        json={"handle": "taken-handle", "public_profile": True},
    )
    assert r.status_code == 422
    r = client.put(
        "/api/v1/me/public-profile",
        json={"handle": "Bad Handle!", "public_profile": True},
    )
    assert r.status_code == 422


def test_public_profile_opt_out_hides_it_again(auth_client):
    _enable_profile(auth_client, handle="temp-handle")
    assert auth_client.get("/api/v1/p/temp-handle").status_code == 200
    auth_client.put(
        "/api/v1/me/public-profile",
        json={"handle": "temp-handle", "public_profile": False},
    )
    assert auth_client.get("/api/v1/p/temp-handle").status_code == 404


# ------------------------------------------------------------------ 90-day plan
def _seed_run(app_module, user_id: str) -> int:
    from career_guidance.models import CareerRecommendation

    rec = CareerRecommendation(
        title="Data Analyst",
        match_reason="skills",
        suitability="beginner",
        missing_skills=["python", "sql"],
        career_id="x",
    )
    return app_module._db.save_run(
        {"skills": "python", "constraints": {"hours_per_week": 2}},
        [rec],
        "offline",
        False,
        user_id,
    )


def test_plan90_lifecycle(auth_client, app_module):
    me = auth_client.get("/api/v1/auth/me").json()["user"]
    # No run yet → honest 422.
    r = auth_client.post("/api/v1/plan/90day", json={})
    assert r.status_code == 422

    _seed_run(app_module, me["id"])
    r = auth_client.post("/api/v1/plan/90day", json={})
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert len(plan["weeks"]) == 13
    assert plan["hours_per_week"] == 2  # from the run's constraints
    assert len(plan["weeks"][0]["tasks"]) == 1  # 2 h/week → 1 task/week
    assert "Python basics" in plan["weeks"][0]["verification_check"]

    r = auth_client.get("/api/v1/plan/90day")
    body = r.json()
    assert body["current_week"]["week"] == 1
    assert body["progress"]["tasks_done"] == 0

    task_id = plan["weeks"][0]["tasks"][0]["id"]
    r = auth_client.patch(
        f"/api/v1/plan/90day/{plan['plan_id']}/tasks",
        json={"task_id": task_id, "done": True},
    )
    assert r.status_code == 200
    assert r.json()["progress"]["tasks_done"] == 1

    md = auth_client.get("/api/v1/plan/90day/export.md")
    assert md.status_code == 200 and "# 90-day plan" in md.text
    ics = auth_client.get("/api/v1/plan/90day/export.ics")
    assert ics.status_code == 200 and ics.text.count("BEGIN:VEVENT") == 13


def test_plan90_hours_override_changes_task_load(auth_client, app_module):
    me = auth_client.get("/api/v1/auth/me").json()["user"]
    _seed_run(app_module, me["id"])
    r = auth_client.post("/api/v1/plan/90day", json={"hours_per_week": 10})
    plan = r.json()["plan"]
    assert plan["hours_per_week"] == 10
    assert len(plan["weeks"][0]["tasks"]) == 3


def test_dashboard_includes_this_week(auth_client, app_module):
    me = auth_client.get("/api/v1/auth/me").json()["user"]
    _seed_run(app_module, me["id"])
    auth_client.post("/api/v1/plan/90day", json={})
    dash = auth_client.get("/api/v1/me/dashboard").json()
    assert dash["plan90"]["current_week"]["week"] == 1
    assert dash["plan90"]["progress"]["tasks_total"] > 0
