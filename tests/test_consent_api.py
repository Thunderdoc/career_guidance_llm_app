"""Phase 5 API tests: age declaration, consent flow + failure paths,
minor gating (analytics / gamification / institute attention), and the
export/delete end-to-end verification."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from career_guidance.consent import ConsentStore
from career_guidance.models import CareerRecommendation
from career_guidance.storage import Database
from tests.conftest import login


def _client(app_module, email: str) -> TestClient:
    c = TestClient(app_module.app)
    login(c, email)
    return c


def _me(client) -> dict:
    return client.get("/api/v1/auth/me").json()["user"]


def _declare_minor(client, year: int = 2013) -> dict:
    r = client.put("/api/v1/me/age-declaration", json={"age_band": "minor", "birth_year": year})
    assert r.status_code == 200, r.text
    return r.json()


def _request_consent(client, guardian: str = "mum@example.com") -> dict:
    r = client.post("/api/v1/me/consent/request", json={"guardian_email": guardian})
    assert r.status_code == 200, r.text
    return r.json()["consent"]


def _token_from_dev_link(payload: dict) -> str:
    link = payload["dev_link"]
    return link.rsplit("/consent/confirm/", 1)[1]


def _db_path(app_module) -> str:
    return app_module.settings.database_path


def _count(app_module, sql: str, params=()) -> int:
    with sqlite3.connect(_db_path(app_module)) as conn:
        return conn.execute(sql, params).fetchone()[0]


# ---------------------------------------------------------------------- authz
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/me/consent"),
        ("post", "/api/v1/me/consent/request"),
        ("post", "/api/v1/me/consent/revoke"),
        ("put", "/api/v1/me/age-declaration"),
    ],
)
def test_consent_routes_require_sign_in(client, method, path):
    if method in ("post", "put"):
        r = getattr(client, method)(path, json={})
    else:
        r = getattr(client, method)(path)
    assert r.status_code == 401, (method, path, r.status_code)


# -------------------------------------------------------------- age declaration
def test_age_declaration_endpoint_and_profile_flow(app_module, client):
    login(client, "kid@example.com")
    out = _declare_minor(client)
    assert out["user"]["is_minor"] is True
    assert out["user"]["age_band"] == "minor" and out["user"]["birth_year"] == 2013
    assert out["privacy"]["restrictions"]["restricted"] is True
    assert _me(client)["is_minor"] is True

    # The same declaration rides the onboarding/profile payload (additive).
    login(client, "kid2@example.com")
    r = client.put(
        "/api/v1/profile",
        json={"persona": "Student", "age_band": "minor", "birth_year": 2014},
    )
    assert r.status_code == 200, r.text
    assert _me(client)["is_minor"] is True
    profile = client.get("/api/v1/profile").json()
    assert profile["age"]["age_band"] == "minor"
    assert profile["age"]["consent_status"] == "none"

    # Invalid declarations are 422s, never silent.
    r = client.put("/api/v1/me/age-declaration", json={"age_band": "teen"})
    assert r.status_code == 422
    r = client.put("/api/v1/profile", json={"age_band": "minor", "birth_year": 1800})
    assert r.status_code == 422


def test_age_declaration_fail_safe_year_beats_adult_band(app_module, client):
    login(client, "sneaky@example.com")
    r = client.put("/api/v1/me/age-declaration", json={"age_band": "adult", "birth_year": 2015})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["is_minor"] is True


# ----------------------------------------------------------------- consent flow
def test_consent_full_flow_grant_deny_revoke(app_module, client):
    login(client, "kid@example.com")
    _declare_minor(client)
    consent = _request_consent(client)
    assert consent["status"] == "pending"
    assert consent["guardian_email"] == "mum@example.com"
    token = _token_from_dev_link(consent)

    # The guardian needs no account: a bare client can decide.
    anon = TestClient(app_module.app)
    r = anon.get(f"/api/v1/consent/confirm/{token}?decision=deny")
    assert r.status_code == 200 and r.json()["status"] == "denied"
    status = client.get("/api/v1/me/consent").json()
    assert status["effective_status"] == "denied"
    assert status["restrictions"]["restricted"] is True

    # Ask again, guardian grants this time.
    token = _token_from_dev_link(_request_consent(client))
    r = anon.get(f"/api/v1/consent/confirm/{token}")
    assert r.status_code == 200 and r.json()["status"] == "granted"
    status = client.get("/api/v1/me/consent").json()
    assert status["effective_status"] == "granted"
    assert status["restrictions"]["restricted"] is False
    assert status["restrictions"]["behavioural_analytics_allowed"] is True

    # Re-requesting while granted is a conflict.
    r = client.post("/api/v1/me/consent/request", json={"guardian_email": "mum@example.com"})
    assert r.status_code == 409

    # The user can revoke; restrictions return.
    r = client.post("/api/v1/me/consent/revoke")
    assert r.status_code == 200 and r.json()["consent"]["status"] == "revoked"
    assert client.get("/api/v1/me/consent").json()["restrictions"]["restricted"] is True


def test_guardian_revoke_via_action_token(app_module, client):
    login(client, "kid@example.com")
    _declare_minor(client)
    token = _token_from_dev_link(_request_consent(client))
    anon = TestClient(app_module.app)
    assert anon.get(f"/api/v1/consent/confirm/{token}").json()["status"] == "granted"
    store = ConsentStore(_db_path(app_module))
    action = store.issue_action_token(_me(client)["id"])
    r = anon.get(f"/api/v1/consent/confirm/{action}?decision=revoke")
    assert r.status_code == 200 and r.json()["status"] == "revoked"


def test_consent_failure_paths(app_module, client):
    anon = TestClient(app_module.app)
    # Unknown token -> 404.
    assert anon.get("/api/v1/consent/confirm/nope-not-a-token").status_code == 404

    login(client, "kid@example.com")
    _declare_minor(client)
    uid = _me(client)["id"]
    # Expired token -> 410.
    store = ConsentStore(_db_path(app_module))
    _, stale = store.create_request(uid, "mum@example.com", ttl_hours=-1)
    assert anon.get(f"/api/v1/consent/confirm/{stale}").status_code == 410
    # Superseded token -> 409 (already decided: auto-revoked by the newer request).
    first = _token_from_dev_link(_request_consent(client))
    _request_consent(client)
    assert anon.get(f"/api/v1/consent/confirm/{first}").status_code == 409
    # Bad guardian e-mail -> 422.
    r = client.post("/api/v1/me/consent/request", json={"guardian_email": "not-an-email"})
    assert r.status_code == 422
    # Revoke with nothing to revoke -> 404.
    login(client, "fresh@example.com")
    assert client.post("/api/v1/me/consent/revoke").status_code == 404


def test_adult_cannot_request_parental_consent(app_module, client):
    login(client, "adult@example.com")
    client.put("/api/v1/me/age-declaration", json={"age_band": "adult", "birth_year": 1998})
    r = client.post("/api/v1/me/consent/request", json={"guardian_email": "mum@example.com"})
    assert r.status_code == 422


# --------------------------------------------------------------- minor gating
def test_unconsented_minor_no_tool_events_or_xp_until_consent(app_module, client):
    login(client, "kid@example.com")
    _declare_minor(client)
    uid = _me(client)["id"]

    r = client.post("/api/v1/recommend", json={"skills": "Python, SQL"})
    assert r.status_code == 200, r.text
    assert (
        _count(
            app_module,
            "SELECT COUNT(*) FROM tool_events WHERE user_id = ?",
            (uid,),
        )
        == 0
    )
    assert _count(app_module, "SELECT COUNT(*) FROM xp_events WHERE user_id = ?", (uid,)) == 0
    # Core guidance still works, and the run IS saved for the user.
    assert len(client.get("/api/v1/history").json()["runs"]) == 1
    dash = client.get("/api/v1/me/dashboard").json()
    assert dash["xp"]["minor_restricted"] is True
    assert dash["xp"]["streak"] == {"current": 0, "longest": 0, "days": []}
    activity = client.get("/api/v1/me/activity").json()
    assert activity["minor_restricted"] is True and activity["daily"] == []

    # Guardian grants -> analytics + XP flow again.
    token = _token_from_dev_link(_request_consent(client))
    anon = TestClient(app_module.app)
    assert anon.get(f"/api/v1/consent/confirm/{token}").json()["status"] == "granted"
    r = client.post("/api/v1/recommend", json={"skills": "Python, SQL"})
    assert r.status_code == 200
    assert _count(app_module, "SELECT COUNT(*) FROM tool_events WHERE user_id = ?", (uid,)) == 1
    assert _count(app_module, "SELECT COUNT(*) FROM xp_events WHERE user_id = ?", (uid,)) >= 1


def test_adult_analytics_and_xp_unchanged(app_module, auth_client):
    uid = _me(auth_client)["id"]
    r = auth_client.post("/api/v1/recommend", json={"skills": "Python, SQL"})
    assert r.status_code == 200
    assert _count(app_module, "SELECT COUNT(*) FROM tool_events WHERE user_id = ?", (uid,)) == 1
    assert _count(app_module, "SELECT COUNT(*) FROM xp_events WHERE user_id = ?", (uid,)) >= 1


# ------------------------------------------------------- institute attention
def _seed_run(app_module, user_id: str, score: float = 0.3) -> int:
    db = Database(app_module.settings.database_path)
    return db.save_run(
        {"skills": "python"},
        [
            CareerRecommendation(
                title="Data Analyst",
                match_reason="fit",
                suitability="beginner",
                missing_skills=["sql"],
                match_score=score,
            )
        ],
        "offline",
        False,
        user_id,
    )


def test_institute_attention_excludes_unconsented_minors_only(app_module):
    iadmin = _client(app_module, "iadmin@demo.example")
    minor = _client(app_module, "minor-student@demo.example")
    adult = _client(app_module, "adult-student@demo.example")
    _declare_minor(minor)
    adult.put("/api/v1/me/age-declaration", json={"age_band": "adult", "birth_year": 2000})
    minor_id, adult_id = _me(minor)["id"], _me(adult)["id"]

    r = iadmin.post("/api/v1/institutes", json={"name": "DEMO Phase5 Institute"})
    assert r.status_code == 201, r.text
    iid = r.json()["institute"]["id"]
    r = iadmin.post(
        f"/api/v1/institutes/{iid}/invites",
        json={
            "members": [
                {"email": "minor-student@demo.example", "role": "student"},
                {"email": "adult-student@demo.example", "role": "student"},
            ]
        },
    )
    assert r.json()["invited"] == 2, r.text
    _seed_run(app_module, minor_id)
    _seed_run(app_module, adult_id)

    cohort = iadmin.get(f"/api/v1/institutes/{iid}/cohort").json()["cohort"]
    # Aggregates still count BOTH students and both runs.
    assert cohort["student_count"] == 2 and cohort["runs_count"] == 2
    # The individual list excludes only the unconsented minor.
    attention_ids = [a["user_id"] for a in cohort["needs_attention"]]
    assert attention_ids == [adult_id]
    students = iadmin.get(f"/api/v1/institutes/{iid}/students").json()["students"]
    by_id = {s["user_id"]: s for s in students}
    assert by_id[adult_id]["needs_attention"] is True
    assert by_id[minor_id]["needs_attention"] is False

    # A student hitting the staff-only list is a 403.
    assert minor.get(f"/api/v1/institutes/{iid}/students").status_code == 403

    # Once the guardian consents, the minor is visible again.
    token = _token_from_dev_link(_request_consent(minor))
    anon = TestClient(app_module.app)
    assert anon.get(f"/api/v1/consent/confirm/{token}").json()["status"] == "granted"
    cohort = iadmin.get(f"/api/v1/institutes/{iid}/cohort").json()["cohort"]
    assert {a["user_id"] for a in cohort["needs_attention"]} == {minor_id, adult_id}


# ------------------------------------------------------------ export / delete
def test_export_and_delete_end_to_end(app_module):
    a = _client(app_module, "a@example.com")
    b = _client(app_module, "b@example.com")
    a_id, b_id = _me(a)["id"], _me(b)["id"]

    for c, title in ((a, "A project"), (b, "B project")):
        r = c.post("/api/v1/recommend", json={"skills": "Python, SQL"})
        assert r.status_code == 200, r.text
        r = c.post(
            "/api/v1/skills/verify/python/project",
            json={
                "title": title,
                "link": "https://example.com/p",
                "description": "demo",
                "checklist": [],
            },
        )
        assert r.status_code == 200, r.text
        r = c.post("/api/v1/plan/90day", json={})
        assert r.status_code == 200, r.text
    a.post("/api/v1/feedback", json={"rating": 4, "comment": "great", "tool": "recommend"})

    export_a = a.get("/api/v1/me/export").json()
    assert [p["title"] for p in export_a["skill_projects"]] == ["A project"]
    assert export_a["plans_90day"] and export_a["runs"]
    assert export_a["account"]["email"] == "a@example.com"
    assert "privacy" in export_a
    export_b = b.get("/api/v1/me/export").json()
    assert [p["title"] for p in export_b["skill_projects"]] == ["B project"]
    blob_a = str(export_a)
    assert "b@example.com" not in blob_a and "B project" not in blob_a

    # Delete A: everything personal goes, B is untouched.
    r = a.delete("/api/v1/me")
    assert r.status_code == 200 and r.json()["deleted"] is True
    for table in (
        "skill_verifications",
        "skill_projects",
        "plans_90day",
        "recommendation_runs",
        "consent_records",
        "tool_events",
        "xp_events",
    ):
        assert (
            _count(app_module, f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (a_id,)) == 0
        ), table
    assert _count(app_module, "SELECT COUNT(*) FROM users WHERE id = ?", (a_id,)) == 0
    # Feedback survives only anonymised.
    assert _count(app_module, "SELECT COUNT(*) FROM feedback WHERE user_id = ?", (a_id,)) == 0
    assert _count(app_module, "SELECT COUNT(*) FROM feedback WHERE user_id IS NULL") >= 1
    # B intact.
    assert _count(app_module, "SELECT COUNT(*) FROM users WHERE id = ?", (b_id,)) == 1
    assert b.get("/api/v1/me/export").json()["skill_projects"][0]["title"] == "B project"
    # A's session is dead with the account.
    assert a.get("/api/v1/me/consent").status_code == 401
