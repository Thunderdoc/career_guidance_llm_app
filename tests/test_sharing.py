"""Phase 8 shareable report links: hashed tokens, expiry/revoke, privacy.

The privacy tests are the point of the feature: the public payload is built
from an allowlist, so seeded personal markers (the owner's e-mail, name,
city, goals, résumé text) must be absent from the shared JSON *string* —
not merely from its top-level keys.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from career_guidance.migrations import migrate
from career_guidance.models import CareerRecommendation
from career_guidance.sharing import (
    GUEST_CREATOR,
    MAX_EXPIRY_DAYS,
    SHARE_SCOPE,
    ShareStore,
    build_shared_report,
    validate_expiry_days,
)
from career_guidance.storage import StoredRun

# Distinctive personal markers seeded into the stored run's profile. None of
# them may appear anywhere in a shared payload.
MARKERS = {
    "email": "asha.secret@example.com",
    "name": "Asha Secretname",
    "city": "Secretcity-XYZ",
    "goal": "secret goal marker",
    "resume": "SECRET RESUME TEXT MARKER",
    "education": "Secret Education Marker College",
    "budget": "secret-budget-marker",
    "handle": "asha-secret-handle",
}


def _run() -> StoredRun:
    rec = CareerRecommendation(
        title="Web Developers",
        match_reason="Your JavaScript maps onto web work.",
        suitability="beginner",
        matching_skills=["JavaScript", "CSS"],
        missing_skills=["React", "Testing"],
        learning_path=["Deepen JavaScript", "Learn React basics"],
        next_steps=["Build a portfolio site"],
        career_id="15-1134.00",
        match_score=0.82,
        provenance={"why": ["grounded"], "leak_marker": MARKERS["resume"]},
    )
    profile = {
        "skills": f"JavaScript, CSS — contact {MARKERS['email']}",
        "goals": MARKERS["goal"],
        "education": MARKERS["education"],
        "resume_text": MARKERS["resume"],
        "constraints": {"city": MARKERS["city"], "budget_range": MARKERS["budget"]},
        "owner_name": MARKERS["name"],
        "handle": MARKERS["handle"],
    }
    return StoredRun(
        id=42,
        created_at="2026-11-06T00:00:00+00:00",
        provider="matcher-v2",
        is_demo=False,
        profile=profile,
        recommendations=[rec],
        user_id="owner-id",
    )


@pytest.fixture()
def store(tmp_path) -> ShareStore:
    return ShareStore(tmp_path / "share.db")


# --------------------------------------------------------------------- store


def test_migration_v8_creates_share_tokens(tmp_path):
    path = tmp_path / "m.db"
    applied = migrate(path)
    assert 8 in applied
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(share_tokens)")}
    assert {"token_hash", "run_id", "created_by", "expires_at", "revoked_at"} <= cols
    assert migrate(path) == []  # idempotent


def test_token_is_hashed_at_rest(store, tmp_path):
    record, raw = store.create(42, "owner-id")
    assert raw and len(raw) >= 32
    with sqlite3.connect(tmp_path / "share.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM share_tokens WHERE id = ?", (record.id,)).fetchone()
    assert row["token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in dict(row).values()
    assert store.by_token(raw).id == record.id  # type: ignore[union-attr]
    assert store.by_token("not-a-token") is None
    assert store.by_token("") is None


def test_expiry_validation_and_default(store):
    assert validate_expiry_days(None) == 7
    assert validate_expiry_days(1) == 1
    assert validate_expiry_days(MAX_EXPIRY_DAYS) == MAX_EXPIRY_DAYS
    for bad in (0, -1, MAX_EXPIRY_DAYS + 1, "soon"):
        with pytest.raises(ValueError):
            validate_expiry_days(bad)  # type: ignore[arg-type]
    record, _ = store.create(1, "u")
    expires = datetime.fromisoformat(record.expires_at)
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7)
    assert record.active and record.status() == "active"
    assert record.fields_scope == SHARE_SCOPE


def test_revoke_is_idempotent_and_terminal(store):
    record, raw = store.create(1, "u")
    revoked = store.revoke(record.id)
    assert revoked is not None and revoked.revoked and not revoked.active
    assert revoked.status() == "revoked"
    assert store.revoke(record.id).revoked_at == revoked.revoked_at  # type: ignore[union-attr]
    assert store.revoke(999999) is None
    assert store.by_token(raw).revoked  # type: ignore[union-attr]


def test_expired_record_reports_expired(store, tmp_path):
    record, raw = store.create(1, "u")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    with sqlite3.connect(tmp_path / "share.db") as conn:
        conn.execute("UPDATE share_tokens SET expires_at = ? WHERE id = ?", (past, record.id))
    fresh = store.by_token(raw)
    assert fresh is not None and fresh.expired and not fresh.active
    assert fresh.status() == "expired"


def test_list_for_run_and_guest_creator(store):
    first, _ = store.create(7, GUEST_CREATOR)
    second, _ = store.create(7, GUEST_CREATOR)
    store.create(8, GUEST_CREATOR)
    listed = store.list_for_run(7)
    assert [r.id for r in listed] == [second.id, first.id]
    assert all(r.created_by == GUEST_CREATOR for r in listed)
    assert store.list_for_run(1234) == []


# ------------------------------------------------------------------- payload


def test_shared_payload_is_allowlist_only():
    payload = build_shared_report(_run())
    assert set(payload) == {
        "run_id",
        "created_at",
        "scope",
        "fields",
        "priority_skills",
        "recommendations",
        "source",
    }
    assert payload["scope"] == SHARE_SCOPE
    assert payload["priority_skills"] == ["React", "Testing"]
    (rec,) = payload["recommendations"]
    assert set(rec) == {
        "career_id",
        "title",
        "match_percent",
        "matching_skills",
        "missing_skills",
        "learning_path",
        "reality",
    }
    assert rec["title"] == "Web Developers"
    assert rec["match_percent"] == 82.0
    reality = rec["reality"]
    assert reality is not None and reality["score"] is not None
    assert set(reality) == {"score", "confidence", "components", "salary_ladder"}
    ladder = reality["salary_ladder"]
    assert ladder is not None and ladder["kind"] == "estimate"
    assert ladder["fresher_salary_inr"] and ladder["salary_7yr_inr"]
    for comp in reality["components"]:
        assert set(comp) == {"key", "label", "value", "explanation", "kind", "source"}


def test_shared_payload_contains_no_personal_markers():
    blob = json.dumps(build_shared_report(_run()))
    for marker in MARKERS.values():
        assert marker not in blob
    for forbidden_key in (
        "profile",
        "constraints",
        "email",
        "handle",
        "resume",
        "goals",
        "provenance",
        "counsellor",
        "institute",
    ):
        assert f'"{forbidden_key}"' not in blob


def test_shared_payload_unknown_career_has_no_reality():
    run = _run()
    orphan = StoredRun(
        id=run.id,
        created_at=run.created_at,
        provider=run.provider,
        is_demo=False,
        profile=run.profile,
        recommendations=[
            CareerRecommendation(
                title="Ghost Role",
                match_reason="",
                suitability="beginner",
                career_id="99-9999.99",
                match_score=0.5,
            )
        ],
        user_id=run.user_id,
    )
    payload = build_shared_report(orphan)
    assert payload["recommendations"][0]["reality"] is None
    assert payload["recommendations"][0]["match_percent"] == 50.0


# --------------------------------------------------------------------- API

from fastapi.testclient import TestClient  # noqa: E402

from tests.conftest import login  # noqa: E402

OWNER_EMAIL = "asha.secret@example.com"
GOAL_MARKER = "secret goal marker xyz"
CITY_MARKER = "Secretcity-XYZ"


def _make_run(client, *, signed_in: bool) -> int:
    r = client.post(
        "/api/v1/recommend",
        json={
            "skills": "JavaScript, CSS, HTML",
            "goals": GOAL_MARKER,
            "constraints": {"city": CITY_MARKER, "budget_range": "secret-budget"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anonymous"] is (not signed_in)
    return body["run_id"]


def _guest_client(client) -> TestClient:
    return TestClient(client.app)


def test_share_api_owner_flow_and_privacy(client):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    r = client.post(f"/api/v1/runs/{run_id}/share", json={})
    assert r.status_code == 201, r.text
    created = r.json()
    token = created["token"]
    assert created["share_path"] == f"/shared/{token}"
    assert created["status"] == "active" and created["fields_scope"] == SHARE_SCOPE

    listed = client.get(f"/api/v1/runs/{run_id}/shares")
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()["shares"]] == [created["id"]]
    assert token not in listed.text  # metadata only — never the token again

    public = _guest_client(client).get(f"/api/v1/shared/{token}")
    assert public.status_code == 200, public.text
    payload = public.json()
    assert payload["shared"] is True and payload["expires_at"] == created["expires_at"]
    assert payload["recommendations"], "shared report must carry recommendations"
    blob = public.text
    for marker in (OWNER_EMAIL, GOAL_MARKER, CITY_MARKER, "secret-budget"):
        assert marker not in blob
    top = payload["recommendations"][0]
    assert top["title"] and top["matching_skills"] is not None
    if top["reality"] and top["reality"]["salary_ladder"]:
        assert top["reality"]["salary_ladder"]["kind"] == "estimate"


def test_share_api_token_hashed_at_rest_via_api(client, app_module):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    token = client.post(f"/api/v1/runs/{run_id}/share", json={"expiry_days": 3}).json()["token"]
    with sqlite3.connect(app_module.settings.database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM share_tokens").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in json.dumps(dict(rows[0]))


def test_share_api_guest_flow(client):
    run_id = _make_run(client, signed_in=False)  # no login — anonymous run
    r = client.post(f"/api/v1/runs/{run_id}/share", json={"expiry_days": 30})
    assert r.status_code == 201, r.text
    public = _guest_client(client).get(f"/api/v1/shared/{r.json()['token']}")
    assert public.status_code == 200


def test_share_api_non_owner_forbidden(client):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    created = client.post(f"/api/v1/runs/{run_id}/share", json={}).json()

    other = TestClient(client.app)
    login(other, "intruder@example.com")
    assert other.post(f"/api/v1/runs/{run_id}/share", json={}).status_code == 403
    assert other.get(f"/api/v1/runs/{run_id}/shares").status_code == 403
    assert other.delete(f"/api/v1/runs/{run_id}/share/{created['id']}").status_code == 403
    guest = _guest_client(client)
    assert guest.post(f"/api/v1/runs/{run_id}/share", json={}).status_code == 403
    # The owner's link still works after the failed attempts.
    assert guest.get(f"/api/v1/shared/{created['token']}").status_code == 200


def test_share_api_signed_in_cannot_manage_anonymous_run(client):
    run_id = _make_run(client, signed_in=False)
    signed = TestClient(client.app)
    login(signed, "late@example.com")
    assert signed.post(f"/api/v1/runs/{run_id}/share", json={}).status_code == 403


def test_share_api_unknown_run_and_token(client):
    assert client.post("/api/v1/runs/999999/share", json={}).status_code == 404
    assert client.get("/api/v1/shared/definitely-not-a-token").status_code == 404
    assert client.delete("/api/v1/runs/999999/share/1").status_code == 404


def test_share_api_expiry_days_validation(client):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    assert client.post(f"/api/v1/runs/{run_id}/share", json={"expiry_days": 0}).status_code == 422
    assert client.post(f"/api/v1/runs/{run_id}/share", json={"expiry_days": 31}).status_code == 422
    assert client.post(f"/api/v1/runs/{run_id}/share", json={"expiry_days": 30}).status_code == 201


def test_share_api_expired_returns_410(client, app_module):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    created = client.post(f"/api/v1/runs/{run_id}/share", json={}).json()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    with sqlite3.connect(app_module.settings.database_path) as conn:
        conn.execute("UPDATE share_tokens SET expires_at = ? WHERE id = ?", (past, created["id"]))
    r = _guest_client(client).get(f"/api/v1/shared/{created['token']}")
    assert r.status_code == 410


def test_share_api_revoke_then_410_and_idempotent(client):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    created = client.post(f"/api/v1/runs/{run_id}/share", json={}).json()
    r = client.delete(f"/api/v1/runs/{run_id}/share/{created['id']}")
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert r.json()["share"]["status"] == "revoked"
    assert _guest_client(client).get(f"/api/v1/shared/{created['token']}").status_code == 410
    again = client.delete(f"/api/v1/runs/{run_id}/share/{created['id']}")
    assert again.status_code == 200  # idempotent
    assert client.delete(f"/api/v1/runs/{run_id}/share/999999").status_code == 404


def test_share_api_deleted_run_returns_404(client):
    login(client, OWNER_EMAIL)
    run_id = _make_run(client, signed_in=True)
    created = client.post(f"/api/v1/runs/{run_id}/share", json={}).json()
    assert client.delete("/api/v1/history").status_code == 200
    assert _guest_client(client).get(f"/api/v1/shared/{created['token']}").status_code == 404
