"""Phase 10: migration v10 (indexes + API keys) and the institute
public API — key management gates, header-only auth, slug binding,
aggregate-only payloads, revocation, last-used stamping."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from career_guidance.migrations import applied_versions, migrate
from career_guidance.models import CareerRecommendation
from career_guidance.storage import Database
from tests.conftest import login


def _client(app_module, email: str) -> TestClient:
    c = TestClient(app_module.app)
    login(c, email)
    return c


def _me(client) -> dict:
    return client.get("/api/v1/auth/me").json()["user"]


def _seed_run(app_module, user_id: str, title="Data Analyst", score=0.9, missing=("sql",)):
    db = Database(app_module.settings.database_path)
    return db.save_run(
        {"skills": "python"},
        [
            CareerRecommendation(
                title=title,
                match_reason="fit",
                suitability="beginner",
                missing_skills=list(missing),
                match_score=score,
            )
        ],
        "offline",
        False,
        user_id,
    )


@pytest.fixture()
def world(app_module):
    """One institute (admin + student with a run) and a second institute."""
    w = {}
    w["iadmin"] = _client(app_module, "iadmin@demo.example")
    w["student"] = _client(app_module, "student@demo.example")
    w["other"] = _client(app_module, "other@demo.example")
    w["platform"] = _client(app_module, "boss@example.com")
    w["student_id"] = _me(w["student"])["id"]

    r = w["iadmin"].post("/api/v1/institutes", json={"name": "DEMO Public Institute"})
    assert r.status_code == 201, r.text
    w["iid"] = r.json()["institute"]["id"]
    w["slug"] = r.json()["institute"]["slug"]
    r = w["iadmin"].post(
        f"/api/v1/institutes/{w['iid']}/invites",
        json={"members": [{"email": "student@demo.example", "role": "student"}]},
    )
    assert r.json()["invited"] == 1, r.text
    w["student"].post("/api/v1/institutes/invites/claim")
    _seed_run(app_module, w["student_id"])

    r = w["other"].post("/api/v1/institutes", json={"name": "DEMO Other Institute"})
    assert r.status_code == 201, r.text
    w["slug2"] = r.json()["institute"]["slug"]
    return w


def _mint(world, label="ci"):
    r = world["iadmin"].post(f"/api/v1/institutes/{world['iid']}/api-keys", json={"label": label})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------- migration v10
def test_migration_v10_from_v9_idempotent(tmp_path, monkeypatch):
    import career_guidance.migrations as migrations

    path = str(tmp_path / "v9.db")
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:9])
    assert migrate(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    monkeypatch.undo()
    assert migrate(path) == [10]
    assert migrate(path) == []  # idempotent
    assert applied_versions(path)[-1] == 10
    with sqlite3.connect(path) as conn:
        indexes = {r[1] for r in conn.execute("PRAGMA index_list('recommendation_runs')")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "idx_runs_user" in indexes
    assert "institute_api_keys" in tables


def test_v10_indexes_cover_hot_lookups(tmp_path):
    path = str(tmp_path / "fresh.db")
    migrate(path)
    expected = {
        "recommendation_runs": "idx_runs_user",
        "assessment_runs": "idx_assessment_runs_user",
        "plans": "idx_plans_user",
        "interview_sessions": "idx_interview_sessions_user",
        "payments": "idx_payments_user",
    }
    with sqlite3.connect(path) as conn:
        for table, index in expected.items():
            names = {r[1] for r in conn.execute(f"PRAGMA index_list('{table}')")}
            assert index in names, (table, names)


# ------------------------------------------------------------ key management
def test_key_create_list_revoke_and_raw_shown_once(world, app_module):
    created = _mint(world)
    raw = created["api_key"]
    assert raw.startswith("cgk_")
    assert created["active"] is True and created["last_used_at"] == ""

    listing = world["iadmin"].get(f"/api/v1/institutes/{world['iid']}/api-keys").json()
    assert len(listing["api_keys"]) == 1
    assert "api_key" not in listing["api_keys"][0]  # raw key never re-shown
    assert "key_hash" not in listing["api_keys"][0]

    r = world["iadmin"].delete(f"/api/v1/institutes/{world['iid']}/api-keys/{created['id']}")
    assert r.json() == {"revoked": True}
    r = world["iadmin"].delete(f"/api/v1/institutes/{world['iid']}/api-keys/{created['id']}")
    assert r.status_code == 404  # already revoked

    # At rest only the SHA-256 hash exists: the raw key appears nowhere
    # in the table, and a revoked key no longer authenticates.
    import hashlib

    from career_guidance.api_keys import InstituteApiKeyStore

    store = InstituteApiKeyStore(app_module.settings.database_path)
    assert store.authenticate(raw) is None  # revoked
    with sqlite3.connect(app_module.settings.database_path) as conn:
        stored = conn.execute("SELECT key_hash FROM institute_api_keys").fetchall()
    assert stored[0][0] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in stored[0][0]


def test_key_management_role_gates(world):
    # A student member may not manage keys.
    r = world["student"].post(f"/api/v1/institutes/{world['iid']}/api-keys", json={"label": "x"})
    assert r.status_code == 403
    # An outsider may not either.
    r = world["other"].get(f"/api/v1/institutes/{world['iid']}/api-keys")
    assert r.status_code == 403
    # A platform admin may.
    r = world["platform"].post(f"/api/v1/institutes/{world['iid']}/api-keys", json={"label": "ops"})
    assert r.status_code == 201


# -------------------------------------------------------------- public reads
def test_public_cohort_valid_key_and_privacy(world, app_module):
    created = _mint(world)
    raw = created["api_key"]
    anon = TestClient(app_module.app)  # no session at all
    r = anon.get(f"/api/v1/public/institutes/{world['slug']}/cohort", headers={"X-API-Key": raw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["institute"]["slug"] == world["slug"]
    cohort = body["cohort"]
    assert cohort["student_count"] == 1 and cohort["runs_count"] == 1
    assert cohort["top_recommended_careers"][0]["title"] == "Data Analyst"
    assert "needs_attention" not in cohort  # individual list stripped
    assert cohort["needs_attention_count"] == 0
    text = r.text.lower()
    for forbidden in ("@demo.example", "student_id", "user_id", "email", world["student_id"]):
        assert forbidden not in text

    r = anon.get(
        f"/api/v1/public/institutes/{world['slug']}/top-careers", headers={"X-API-Key": raw}
    )
    assert r.status_code == 200
    assert r.json()["top_careers"][0] == {"title": "Data Analyst", "count": 1}

    # last_used_at was stamped by the successful calls.
    listing = world["iadmin"].get(f"/api/v1/institutes/{world['iid']}/api-keys").json()
    assert listing["api_keys"][0]["last_used_at"] != ""


def test_public_reads_reject_bad_keys(world, app_module):
    created = _mint(world)
    raw = created["api_key"]
    anon = TestClient(app_module.app)
    url = f"/api/v1/public/institutes/{world['slug']}/cohort"
    assert anon.get(url).status_code == 401  # missing
    assert anon.get(url, headers={"X-API-Key": "cgk_wrong"}).status_code == 401
    assert anon.get(url, headers={"X-API-Key": "not-a-key"}).status_code == 401
    # Correct key, wrong institute slug -> 404 (key does not bind there).
    r = anon.get(f"/api/v1/public/institutes/{world['slug2']}/cohort", headers={"X-API-Key": raw})
    assert r.status_code == 404
    # Unknown slug + valid key -> 404 as well.
    r = anon.get("/api/v1/public/institutes/nope/cohort", headers={"X-API-Key": raw})
    assert r.status_code == 404
    # After revocation the key is dead.
    world["iadmin"].delete(f"/api/v1/institutes/{world['iid']}/api-keys/{created['id']}")
    assert anon.get(url, headers={"X-API-Key": raw}).status_code == 401


def test_public_reads_ignore_session(world, app_module):
    """A session cookie without a key does NOT authenticate public reads."""
    created = _mint(world)
    url = f"/api/v1/public/institutes/{world['slug']}/cohort"
    assert world["iadmin"].get(url).status_code == 401
    r = world["iadmin"].get(url, headers={"X-API-Key": created["api_key"]})
    assert r.status_code == 200
