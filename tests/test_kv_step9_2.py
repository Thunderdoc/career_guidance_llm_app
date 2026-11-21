"""Step 9.2 — pilot/institute console: bulk onboarding, coordinator
verification, metrics + CSV.

Metrics are asserted against seeded rows (plan Stage 8 acceptance:
console metrics match stored data). Nothing here is estimated.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from career_guidance.kaamvaani.consent import ConsentStore
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.kaamvaani.pilot import MAX_BULK_ROWS, bulk_onboard, normalise_phone
from career_guidance.migrations import migrate
from career_guidance.users import UserStore
from tests.conftest import login

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _stores(tmp_path, name="kv92.db"):
    path = str(tmp_path / name)
    migrate(path)
    return path, ConsentStore(path), EmployerStore(path), UserStore(path)


def _user(users, email, name=""):
    return users.upsert_login(email, "email", name=name or email.split("@")[0])


def _employer(employers, user_id="u-emp", **overrides):
    data = {
        "business_name": "Murugan Electricals",
        "contact_name": "Murugan",
        "city": "Madurai",
        "district": "Madurai",
        "business_type": "Electrical shop",
        "description": "House wiring and repair shop in Madurai.",
    }
    data.update(overrides)
    return employers.create_employer(user_id, **data)


def _listing(employers, employer_id, **overrides):
    data = {
        "title": "Electrician helper",
        "role_category": "electrician",
        "description": "Help with house wiring work. 10th pass. Full-time, day shift.",
        "city": "Madurai",
        "district": "Madurai",
        "pay_monthly_min": 12000,
        "pay_monthly_max": 15000,
        "work_type": "full-time",
        "openings": 2,
        "requirements": "Basic wiring knowledge.",
        "contact_info": "Murugan, 98430 12345, 12 Main Road, Madurai.",
    }
    data.update(overrides)
    return employers.create_listing(employer_id, **data)


def _seed_pilot(tmp_path):
    """Seed one of everything; returns (path, consent, employers, users, ids)."""
    path, consent, employers, users = _stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    w2 = _user(users, "w2@example.com", "Worker Two")
    w3 = _user(users, "w3@example.com", "Worker Three")
    consent.save_worker_profile(
        w1.id, skills=["electrical technician"], education="12th pass", city="Madurai"
    )
    consent.save_worker_profile(w2.id, skills=["tailoring"], education="10th pass", city="Dindigul")
    consent.save_worker_profile(
        w3.id, skills=["welding"], education="ITI", city="Madurai", is_sample=True
    )
    e1 = employers.set_employer_status(
        _employer(employers, "u-emp1").id, "verified", reviewer="admin@example.com"
    )
    e2 = _employer(employers, "u-emp2", business_name="Pending Pipes")
    e3 = employers.set_employer_status(
        _employer(employers, "u-emp3", business_name="Rejected Roofs").id,
        "rejected",
        reviewer="admin@example.com",
    )
    l1 = _listing(employers, e1.id, status="verified")
    l2 = _listing(employers, e1.id, title="Plumber helper")
    l3 = employers.set_listing_status(
        _listing(employers, e1.id, title="Rejected role").id,
        "rejected",
        reviewer="admin@example.com",
    )
    c1 = consent.grant_consent(w1.id, e1.id, ["skills"], duration_days=30)
    c2 = consent.grant_consent(w2.id, e1.id, ["skills"], duration_days=30)
    consent.revoke_consent(c2.id, w2.id)
    c3 = consent.grant_consent(w3.id, e1.id, ["skills"], duration_days=30)
    # Expired state, seeded directly: the lazy sweep sets exactly
    # this (status + past expires_at) when it runs.
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE kv_consents SET status = 'expired', expires_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", c3.id),
        )
        conn.commit()
    finally:
        conn.close()
    consent.add_shortlist(e1.id, l1.id, w1.id)
    consent.create_contact_request(e1.id, l1.id, w1.id, "Please call about the helper role.")
    hired = consent.report_outcome(e1.id, l1.id, w1.id, "hired", "u-emp1", "employer")
    consent.record_followup(hired.id, 30, "still_employed")
    consent.report_outcome(e1.id, l1.id, w2.id, "interviewed", "u-emp1", "employer")
    r1, _ = employers.report_listing(l1.id, "fake", "Asked for money upfront.")
    r2, _ = employers.report_listing(l1.id, "not_as_described")
    employers.set_report_status(r2.id, "dismissed", reviewer="admin@example.com")
    r3, _ = employers.report_listing(l2.id, "fake")
    employers.set_report_status(r3.id, "upheld", reviewer="admin@example.com")
    return (
        path,
        consent,
        employers,
        users,
        {
            "w1": w1.id,
            "w2": w2.id,
            "w3": w3.id,
            "e1": e1.id,
            "e2": e2.id,
            "e3": e3.id,
            "l1": l1.id,
            "l2": l2.id,
            "l3": l3.id,
            "c1": c1.id,
            "r1": r1.id,
        },
    )


# --------------------------------------------------------------------------- #
# Phone lookup + normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+919876543210", "+919876543210"),
        ("9876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("98765-43210", "+919876543210"),
        ("(09876543210)", "09876543210"),  # brackets stripped; trunk 0 not guessed, lookup misses
        ("12345", "12345"),  # too short: passes through, lookup misses
        ("", ""),
    ],
)
def test_normalise_phone(raw, expected):
    assert normalise_phone(raw) == expected


def test_get_by_phone(tmp_path):
    _path, _c, _e, users = _stores(tmp_path)
    worker = _user(users, "w@example.com", "Worker")
    assert users.get_by_phone("+919876543210") is None
    users.set_phone_verified(worker.id, "+919876543210")
    found = users.get_by_phone("+919876543210")
    assert found is not None and found.id == worker.id
    assert users.get_by_phone("+911111111111") is None
    assert users.get_by_phone("") is None


# --------------------------------------------------------------------------- #
# Bulk onboarding (module level)
# --------------------------------------------------------------------------- #


def test_bulk_onboard_by_user_id_and_phone(tmp_path):
    _path, consent, _e, users = _stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    w2 = _user(users, "w2@example.com", "Worker Two")
    users.set_phone_verified(w2.id, "+919876543210")
    rows = [
        {"user_id": w1.id, "skills": ["electrical technician"], "city": "Madurai"},
        {"phone": "9876543210", "skills": ["tailoring"], "city": "Dindigul"},
    ]
    result = bulk_onboard(consent, users, rows)
    assert (result["created"], result["updated"], result["failed"]) == (2, 0, 0)
    assert consent.get_worker_profile(w1.id).city == "Madurai"
    assert consent.get_worker_profile(w2.id).city == "Dindigul"
    # A second run updates instead of duplicating (one row per worker).
    result = bulk_onboard(consent, users, rows)
    assert (result["created"], result["updated"], result["failed"]) == (0, 2, 0)
    assert consent.count_worker_profiles()["total"] == 2


def test_bulk_onboard_per_row_failures_never_fail_the_batch(tmp_path):
    _path, consent, _e, users = _stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    rows = [
        {"user_id": w1.id, "skills": ["welding"], "city": "Madurai"},  # good
        {"user_id": "no-such-user", "skills": ["welding"]},  # no account
        {"phone": "+911111111111", "skills": ["welding"]},  # no account
        {"skills": ["welding"]},  # neither id nor phone
        {"user_id": w1.id, "skillz": ["welding"]},  # typo'd column
        {"user_id": w1.id, "income_monthly": -5},  # invalid income
        "not-a-row",  # not an object
    ]
    result = bulk_onboard(consent, users, rows)
    assert (result["created"], result["failed"]) == (1, 6)
    assert result["results"][0]["status"] == "created"
    errors = [r["error"] for r in result["results"][1:]]
    assert "No account with user id 'no-such-user'." in errors
    assert "No account with phone number '+911111111111'." in errors
    assert "Row needs a user_id or a phone number." in errors
    assert "Unknown field(s): skillz." in errors
    assert any("income" in (e or "").lower() for e in errors)
    assert "Row is not an object." in errors
    # The good row still landed.
    assert consent.get_worker_profile(w1.id) is not None


def test_bulk_onboard_cap(tmp_path):
    _path, consent, _e, users = _stores(tmp_path)
    with pytest.raises(ValueError, match="At most 100 workers"):
        bulk_onboard(consent, users, [{"user_id": "x"}] * (MAX_BULK_ROWS + 1))


# --------------------------------------------------------------------------- #
# Roster + metrics (store level)
# --------------------------------------------------------------------------- #


def test_list_worker_profiles_pagination(tmp_path):
    _path, consent, _e, users = _stores(tmp_path)
    ids = [_user(users, f"w{i}@example.com").id for i in range(3)]
    for uid in ids:
        consent.save_worker_profile(uid, skills=["welding"])
    page1 = consent.list_worker_profiles(limit=2, offset=0)
    page2 = consent.list_worker_profiles(limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 1
    assert {p.user_id for p in page1} | {p.user_id for p in page2} == set(ids)
    assert consent.count_worker_profiles() == {"total": 3, "sample": 0}


def test_pilot_metrics_match_stored_data(tmp_path):
    _path, consent, employers, _users, _ids = _seed_pilot(tmp_path)
    metrics = {**consent.pilot_metrics(), **employers.pilot_metrics()}
    assert metrics["profiles"] == {"total": 3, "sample": 1}
    assert metrics["consents"] == {"granted": 1, "revoked": 1, "expired": 1, "total": 3}
    assert metrics["shortlists"] == {"total": 1}
    assert metrics["contact_requests"] == {"total": 1}
    assert metrics["outcomes"] == {"hired": 1, "interviewed": 1, "not_hired": 0, "total": 2}
    assert metrics["retention"]["hired"] == 1
    assert metrics["retention"]["day30"] == {
        "reported": 1,
        "still_employed": 1,
        "left": 0,
        "unknown": 0,
        "rate": 1.0,
    }
    # Day-90 has no follow-up yet: the rate is None, never 0%.
    assert metrics["retention"]["day90"]["reported"] == 0
    assert metrics["retention"]["day90"]["rate"] is None
    assert metrics["employers"] == {
        "pending": 1,
        "verified": 1,
        "rejected": 1,
        "flagged": 0,
        "total": 3,
    }
    assert metrics["listings"] == {
        "pending": 1,
        "verified": 1,
        "rejected": 1,
        "flagged": 0,
        "total": 3,
    }
    assert metrics["scam_reports"] == {"open": 1, "upheld": 1, "dismissed": 1, "total": 3}
    assert metrics["review_queue"] == {
        "employers_pending": 1,
        "employers_flagged": 0,
        "listings_pending": 1,
        "listings_flagged": 0,
        "reports_open": 1,
    }


def test_outcome_counts_and_retention_are_global_without_employer(tmp_path):
    _path, consent, _e, _users, ids = _seed_pilot(tmp_path)
    global_counts = consent.outcome_counts()
    per_employer = consent.outcome_counts(employer_id=ids["e1"])
    assert global_counts == per_employer  # only one employer has outcomes
    assert consent.retention_summary() == consent.retention_summary(employer_id=ids["e1"])


def test_pilot_metrics_empty_database(tmp_path):
    _path, consent, employers, _users = _stores(tmp_path)
    metrics = {**consent.pilot_metrics(), **employers.pilot_metrics()}
    assert metrics["profiles"] == {"total": 0, "sample": 0}
    assert metrics["consents"]["total"] == 0
    assert metrics["outcomes"]["total"] == 0
    assert metrics["retention"]["hired"] == 0
    assert metrics["retention"]["day30"]["rate"] is None
    assert metrics["retention"]["day90"]["rate"] is None


# --------------------------------------------------------------------------- #
# Router tests (TestClient + the app's own database)
# --------------------------------------------------------------------------- #


def _app_stores(tmp_path):
    """Stores on the app's database (app_module uses tmp_path/app.db)."""
    path = str(tmp_path / "app.db")
    return ConsentStore(path), EmployerStore(path), UserStore(path)


def _as_coordinator(client: TestClient, tmp_path):
    """Sign in, then give the account the coordinator role (the session
    reloads the user per request, so the role applies immediately)."""
    me = login(client, "coord@example.com")
    _c, _e, users = _app_stores(tmp_path)
    users.set_role(me["id"], "coordinator")
    return me


def test_pilot_status_requires_coordinator_or_admin(client, tmp_path):
    r = client.get("/api/v1/kv/pilot/status")
    assert r.status_code == 401  # signed out
    login(client, "worker@example.com")
    r = client.get("/api/v1/kv/pilot/status")
    assert r.status_code == 403  # plain worker
    _as_coordinator(client, tmp_path)
    r = client.get("/api/v1/kv/pilot/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is True


def test_pilot_status_admin_allowed(client):
    login(client, "boss@example.com")  # ADMIN_EMAILS in conftest
    r = client.get("/api/v1/kv/pilot/status")
    assert r.status_code == 200


def test_pilot_metrics_endpoint_matches_stored_data(client, tmp_path):
    _as_coordinator(client, tmp_path)
    consent, employers, users = _app_stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    consent.save_worker_profile(w1.id, skills=["welding"], city="Madurai")
    e1 = employers.set_employer_status(
        _employer(employers, "u-emp1").id, "verified", reviewer="admin@example.com"
    )
    _listing(employers, e1.id, status="verified")
    r = client.get("/api/v1/kv/pilot/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["profiles"] == {"total": 1, "sample": 0}
    assert data["employers"]["verified"] == 1
    assert data["listings"]["verified"] == 1
    assert data["retention"]["day30"]["rate"] is None


def test_pilot_metrics_csv(client, tmp_path):
    _as_coordinator(client, tmp_path)
    consent, _e, users = _app_stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    consent.save_worker_profile(w1.id, skills=["welding"], city="Madurai")
    r = client.get("/api/v1/kv/pilot/metrics.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.splitlines()
    assert lines[0] == "metric,value"
    assert "profiles.total,1" in lines
    # A retention rate with no follow-ups yet exports as an empty
    # cell, never 0.
    assert "retention.day30.rate," in lines


def test_pilot_workers_roster_and_csv(client, tmp_path):
    _as_coordinator(client, tmp_path)
    consent, _e, users = _app_stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    w2 = _user(users, "w2@example.com", "Worker Two")
    consent.save_worker_profile(w1.id, skills=["welding"], city="Madurai")
    consent.save_worker_profile(w2.id, skills=["tailoring"], city="Dindigul")
    r = client.get("/api/v1/kv/pilot/workers")
    assert r.status_code == 200
    names = {w["worker_name"] for w in r.json()["workers"]}
    assert names == {"Worker One", "Worker Two"}
    assert r.json()["counts"] == {"total": 2, "sample": 0}
    r = client.get("/api/v1/kv/pilot/workers.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert r.text.splitlines()[0].startswith("user_id,worker_name,worker_email")
    assert "Worker One" in r.text and "Worker Two" in r.text


def test_pilot_bulk_endpoint(client, tmp_path):
    _as_coordinator(client, tmp_path)
    _c, _e, users = _app_stores(tmp_path)
    w1 = _user(users, "w1@example.com", "Worker One")
    w2 = _user(users, "w2@example.com", "Worker Two")
    users.set_phone_verified(w2.id, "+919876543210")
    r = client.post(
        "/api/v1/kv/pilot/workers/bulk",
        json={
            "rows": [
                {"user_id": w1.id, "skills": ["welding"], "city": "Madurai"},
                {"phone": "9876543210", "skills": ["tailoring"], "city": "Dindigul"},
                {"phone": "+911111111111", "skills": ["welding"]},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert (r.json()["created"], r.json()["failed"]) == (2, 1)
    assert r.json()["results"][2]["error"] == "No account with phone number '+911111111111'."
    # Audited.
    actions = [row["action"] for row in users.audit_log(limit=5)]
    assert "kv:pilot_bulk_onboard" in actions


def test_pilot_bulk_endpoint_rejects_worker_and_oversize(client, tmp_path):
    login(client, "worker@example.com")
    r = client.post("/api/v1/kv/pilot/workers/bulk", json={"rows": [{"user_id": "x"}]})
    assert r.status_code == 403
    _as_coordinator(client, tmp_path)
    r = client.post(
        "/api/v1/kv/pilot/workers/bulk",
        json={"rows": [{"user_id": "x"}] * (MAX_BULK_ROWS + 1)},
    )
    assert r.status_code == 422


def test_pilot_review_queue_and_employer_review(client, tmp_path):
    _as_coordinator(client, tmp_path)
    _c, employers, users = _app_stores(tmp_path)
    pending = _employer(employers, "u-emp9", business_name="New Pipes")
    r = client.get("/api/v1/kv/pilot/review-queue")
    assert r.status_code == 200
    assert r.json()["counts"]["employers_pending"] == 1
    assert any(e["business_name"] == "New Pipes" for e in r.json()["employers"])
    r = client.post(
        f"/api/v1/kv/pilot/employers/{pending.id}/review",
        json={"approve": True, "note": "Checked the shop in person."},
    )
    assert r.status_code == 200
    assert r.json()["employer"]["status"] == "verified"
    assert employers.get_employer(pending.id).reviewed_by == "coord@example.com"
    actions = [row["action"] for row in users.audit_log(limit=5)]
    assert "kv:employer_review" in actions
    # A second approve is an illegal transition (verified -> verified).
    r = client.post(f"/api/v1/kv/pilot/employers/{pending.id}/review", json={"approve": True})
    assert r.status_code == 409


def test_pilot_review_listing_requires_verified_employer(client, tmp_path):
    _as_coordinator(client, tmp_path)
    _c, employers, _u = _app_stores(tmp_path)
    pending_emp = _employer(employers, "u-emp9", business_name="New Pipes")
    listing = _listing(employers, pending_emp.id)
    r = client.post(f"/api/v1/kv/pilot/listings/{listing.id}/review", json={"approve": True})
    assert r.status_code == 409  # employer not verified yet
    client.post(f"/api/v1/kv/pilot/employers/{pending_emp.id}/review", json={"approve": True})
    r = client.post(f"/api/v1/kv/pilot/listings/{listing.id}/review", json={"approve": True})
    assert r.status_code == 200
    assert r.json()["listing"]["status"] == "verified"


def test_pilot_endorse_moves_from_admin_to_coordinator(client, tmp_path):
    _as_coordinator(client, tmp_path)
    _c, employers, users = _app_stores(tmp_path)
    employer = employers.set_employer_status(
        _employer(employers, "u-emp1").id, "verified", reviewer="admin@example.com"
    )
    r = client.post(
        f"/api/v1/kv/pilot/employers/{employer.id}/endorse",
        json={
            "endorsed_by": "Govt ITI Madurai",
            "endorsed_by_type": "iti",
            "note": "Verified at the ITI office.",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["employer"]["endorsed_by"] == "Govt ITI Madurai"
    actions = [row["action"] for row in users.audit_log(limit=5)]
    assert "kv:employer_endorse" in actions


def test_pilot_report_review_uphold_flags_listing(client, tmp_path):
    _as_coordinator(client, tmp_path)
    _c, employers, _u = _app_stores(tmp_path)
    employer = employers.set_employer_status(
        _employer(employers, "u-emp1").id, "verified", reviewer="admin@example.com"
    )
    listing = _listing(employers, employer.id, status="verified")
    report, _flagged = employers.report_listing(listing.id, "fake", "Asked for money.")
    r = client.post(
        f"/api/v1/kv/pilot/reports/{report.id}/review",
        json={"action": "uphold", "note": "Confirmed by two workers."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["report"]["status"] == "upheld"
    assert r.json()["listing"]["status"] == "flagged"
    r = client.post(f"/api/v1/kv/pilot/reports/{report.id}/review", json={"action": "bogus"})
    assert r.status_code == 400


def test_pilot_routes_404_when_flag_off(tmp_path, monkeypatch):
    """KV_PILOT=false means the console never mounts (Stage 1 flag rule)."""
    import importlib

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_PILOT", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    try:
        with TestClient(main.app) as client:
            login(client, "boss@example.com")
            assert client.get("/api/v1/kv/pilot/status").status_code == 404
            assert client.get("/api/v1/kv/pilot/metrics").status_code == 404
    finally:
        importlib.reload(main)
