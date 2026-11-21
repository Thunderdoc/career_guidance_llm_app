"""Step 9.4 — hardening: rate limits, data deletion, L50 verification.

Rate-limit tests hammer each newly limited endpoint past its
budget and assert the 429. The limiter check runs BEFORE the
endpoint's own validation, so the state-machine endpoints
(/confirm, /matches, /gap-learning) are driven with bodies that
fail validation (400) — the point is the limiter, not the
transition, and 30 fast 400s prove the wiring without 30 slow
scoring runs.
"""

from __future__ import annotations

from career_guidance import db as db_layer
from career_guidance.kaamvaani.consent import (
    ConsentStore,
    delete_all_kv_data,
)
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.profile import new_session
from career_guidance.migrations import migrate
from tests.conftest import login

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _profile_dict() -> dict:
    profile = VoiceProfile(
        skills=["welding"],
        interests="welding work",
        education="12th pass",
        city="Madurai",
        income_text="₹15,000 / month",
        income_monthly=15000,
        goal_type="job_6_months",
        raw_text="welding work. 12th pass. Madurai. 15000 rupees a month.",
    )
    return profile.model_dump(mode="json")


def _session_dict() -> dict:
    # A fresh session (state "start") — /matches and /gap-learning
    # reject it with a 400, which is exactly what the rate-limit
    # tests want: the limiter runs before the state check.
    return new_session("en").model_dump(mode="json")


def _stores(tmp_path, name="kv94.db"):
    path = str(tmp_path / name)
    migrate(path)
    return path, ConsentStore(path), EmployerStore(path)


def _verified_employer(employers, user_id="u-emp"):
    employer = employers.create_employer(
        user_id,
        business_name="Murugan Electricals",
        contact_name="Murugan",
        city="Madurai",
        district="Madurai",
        business_type="Electrical shop",
        description="House wiring and repair shop in Madurai.",
    )
    return employers.set_employer_status(employer.id, "verified", reviewer="admin@example.com")


def _verified_listing(employers, employer_id):
    return employers.create_listing(
        employer_id,
        status="verified",
        title="Electrician helper",
        role_category="electrician",
        description="Help with house wiring work. 10th pass. Full-time, day shift.",
        city="Madurai",
        district="Madurai",
        pay_monthly_min=12000,
        pay_monthly_max=15000,
        work_type="full-time",
        openings=2,
        requirements="Basic wiring knowledge.",
        contact_info="Murugan, 98430 12345, 12 Main Road, Madurai.",
    )


def _worker(store, user_id="u-worker"):
    return store.save_worker_profile(
        user_id,
        skills=["electrical technician"],
        education="12th pass",
        city="Madurai",
        district="Madurai",
        income_monthly=12000,
        goal_type="job",
    )


def _seed_worker_world(tmp_path):
    """One worker + one verified employer + listing + consent +
    shortlist + contact request + worker-reported outcome."""
    path, store, employers = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    _worker(store)
    consent = store.grant_consent("u-worker", employer.id, ["skills", "contact"])
    store.add_shortlist(employer.id, listing.id, "u-worker")
    store.create_contact_request(employer.id, listing.id, "u-worker", "Please call.")
    outcome = store.report_outcome(
        employer.id,
        listing.id,
        "u-worker",
        "hired",
        reported_by_user_id="u-worker",
        reporter_role="worker",
        note="Started Monday, call me at 98430 99999.",
    )
    return path, store, employers, employer, listing, consent, outcome


# --------------------------------------------------------------------------- #
# Rate limits — anonymous endpoints (30/min per IP)
# --------------------------------------------------------------------------- #


def test_rag_ask_rate_limited(client):
    body = {"question": "What is the minimum wage for an unskilled worker?"}
    for _ in range(30):
        assert client.post("/api/v1/kv/rag/ask", json=body).status_code == 200
    assert client.post("/api/v1/kv/rag/ask", json=body).status_code == 429


def test_rag_search_rate_limited(client):
    body = {"query": "minimum wage", "top_k": 3}
    for _ in range(30):
        assert client.post("/api/v1/kv/rag/search", json=body).status_code == 200
    assert client.post("/api/v1/kv/rag/search", json=body).status_code == 429


def test_rights_ask_rate_limited(client):
    body = {"question": "Is this job a scam?"}
    for _ in range(30):
        assert client.post("/api/v1/kv/rights/ask", json=body).status_code == 200
    assert client.post("/api/v1/kv/rights/ask", json=body).status_code == 429


def test_voice_extract_rate_limited(client):
    body = {"text": "I am a carpenter in Madurai, 10th pass, need a job"}
    for _ in range(30):
        assert client.post("/api/v1/kv/voice/extract", json=body).status_code == 200
    assert client.post("/api/v1/kv/voice/extract", json=body).status_code == 429


def test_voice_confirm_rate_limited(client):
    # Illegal transition (fresh session) → 400; the limiter still
    # counts the call, so the 31st is a 429.
    body = {"session": _session_dict(), "profile": _profile_dict(), "confirmed": True}
    for _ in range(30):
        assert client.post("/api/v1/kv/voice/confirm", json=body).status_code == 400
    assert client.post("/api/v1/kv/voice/confirm", json=body).status_code == 429


def test_matches_rate_limited(client):
    body = {"session": _session_dict(), "profile": _profile_dict(), "top_k": 5}
    for _ in range(30):
        assert client.post("/api/v1/kv/matches", json=body).status_code == 400
    assert client.post("/api/v1/kv/matches", json=body).status_code == 429


def test_gap_learning_rate_limited(client):
    body = {
        "session": _session_dict(),
        "profile": _profile_dict(),
        "occupation_id": "electrician",
    }
    for _ in range(30):
        assert client.post("/api/v1/kv/gap-learning", json=body).status_code == 400
    assert client.post("/api/v1/kv/gap-learning", json=body).status_code == 429


# --------------------------------------------------------------------------- #
# Rate limits — reports (10/min per IP) + signed-in mutations (60/min/user)
# --------------------------------------------------------------------------- #


def test_report_rate_limited(client, tmp_path):
    # Seed one verified listing directly in the app's test DB.
    path = str(tmp_path / "app.db")
    employers = EmployerStore(path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    body = {"reason": "fee_demanded", "details": "They asked for ₹2,000 upfront."}
    for _ in range(10):
        assert client.post(f"/api/v1/kv/listings/{listing.id}/report", json=body).status_code == 200
    assert client.post(f"/api/v1/kv/listings/{listing.id}/report", json=body).status_code == 429


def test_consent_grant_rate_limited(client):
    login(client, "worker-rl@example.com")
    # No such employer — the grant fails (404/400) AFTER the
    # limiter counts the call, so the 61st is a 429.
    body = {"employer_id": 999999, "fields": ["skills"], "duration_days": 30}
    for _ in range(60):
        assert client.post("/api/v1/kv/consent/grant", json=body).status_code != 429
    assert client.post("/api/v1/kv/consent/grant", json=body).status_code == 429


def test_verify_phone_rate_limited(client, tmp_path):
    """The OTP endpoint is strict: 5/hour per user. Firebase is
    disabled in tests, so every call fails AFTER the limiter
    counts it — the 6th is a 429, not the Firebase error."""
    from career_guidance.users import UserStore

    me = login(client, "emp-rl@example.com")
    users = UserStore(str(tmp_path / "app.db"))
    users.set_role(me["id"], "employer")
    body = {"id_token": "not-a-real-token"}
    for _ in range(5):
        assert client.post("/api/v1/kv/employers/mine/verify-phone", json=body).status_code != 429
    assert client.post("/api/v1/kv/employers/mine/verify-phone", json=body).status_code == 429


# --------------------------------------------------------------------------- #
# Data deletion — store level
# --------------------------------------------------------------------------- #


def test_delete_worker_data(tmp_path):
    path, store, employers, employer, listing, consent, outcome = _seed_worker_world(tmp_path)
    audit_before = store.list_audit(worker_user_id="u-worker")
    assert audit_before  # the grant + shortlist wrote audit rows
    counts = store.delete_worker_data("u-worker")
    assert counts["kv_worker_profiles"] == 1
    assert counts["kv_consents"] == 1
    assert counts["kv_shortlists"] == 1
    assert counts["kv_contact_requests"] == 1
    assert counts["kv_hire_outcomes_anonymised"] == 1
    # The worker's data is gone…
    assert store.get_worker_profile("u-worker") is None
    assert store.list_consents_for_worker("u-worker") == []
    # …the outcome row survives, anonymised: the worker link is a
    # one-way tombstone, the reporter link and the note are gone.
    kept = store.get_outcome(outcome.id)
    assert kept is not None
    assert kept.worker_user_id.startswith("deleted-")
    assert len(kept.worker_user_id) == len("deleted-") + 12
    assert kept.reported_by_user_id == ""
    assert kept.note == ""
    assert kept.outcome == "hired"  # aggregate stats stay valid
    # …and the audit trail is untouched (append-only).
    assert len(store.list_audit(worker_user_id="u-worker")) == len(audit_before)


def test_delete_worker_data_is_idempotent(tmp_path):
    _, store, _, _, _, _, _ = _seed_worker_world(tmp_path)
    store.delete_worker_data("u-worker")
    counts = store.delete_worker_data("u-worker")
    assert all(value == 0 for value in counts.values())


def test_delete_employer_data_keeps_reports(tmp_path):
    _, store, employers, employer, listing, consent, _ = _seed_worker_world(tmp_path)
    report, _ = employers.report_listing(
        listing.id, "fee_demanded", "Asked for money.", reporter_user_id="u-worker"
    )
    counts, employer_ids = employers.delete_employer_data("u-emp")
    assert counts["kv_employers"] == 1
    assert counts["kv_listings"] == 1
    assert employer_ids == [employer.id]
    assert employers.get_employer_by_user("u-emp") is None
    assert employers.get_listing(listing.id) is None
    # The worker's safety report survives the employer's deletion.
    assert employers.get_report(report.id) is not None
    # The consent side is a separate call (ConsentStore's job).
    consent_counts = store.delete_employer_consents(employer_ids, "u-emp")
    assert consent_counts["kv_consents"] == 1
    assert consent_counts["kv_shortlists"] == 1
    assert consent_counts["kv_contact_requests"] == 1
    assert store.list_consents_for_worker("u-worker") == []


def test_delete_employer_data_unknown_user(tmp_path):
    _, _, employers = _stores(tmp_path)
    counts, employer_ids = employers.delete_employer_data("nobody")
    assert counts == {"kv_employers": 0, "kv_listings": 0}
    assert employer_ids == []


def test_delete_all_kv_data_both_sides(tmp_path):
    """One user who is BOTH a worker and an employer loses both
    sides in a single call."""
    path, store, employers = _stores(tmp_path)
    employer = _verified_employer(employers, user_id="u-both")
    _verified_listing(employers, employer.id)
    _worker(store, user_id="u-both")
    store.grant_consent("u-both", employer.id, ["skills"])
    result = delete_all_kv_data(path, "u-both")
    assert result["deleted"]["worker_profiles"] == 1
    assert result["deleted"]["consents"] == 1
    assert result["deleted"]["employers"] == 1
    assert result["deleted"]["listings"] == 1
    assert employers.get_employer_by_user("u-both") is None
    assert store.get_worker_profile("u-both") is None


# --------------------------------------------------------------------------- #
# Data deletion — endpoints
# --------------------------------------------------------------------------- #


def test_delete_my_kv_data_requires_login(client):
    assert client.request("DELETE", "/api/v1/kv/me/data").status_code == 401


def test_delete_my_kv_data_endpoint(client, tmp_path):
    me = login(client, "worker-del@example.com")
    path = str(tmp_path / "app.db")
    store = ConsentStore(path)
    employers = EmployerStore(path)
    employer = _verified_employer(employers, user_id="u-other-emp")
    store.save_worker_profile(
        me["id"],
        skills=["welding"],
        education="12th pass",
        city="Madurai",
        district="Madurai",
        income_monthly=12000,
        goal_type="job",
    )
    store.grant_consent(me["id"], employer.id, ["skills"])
    r = client.request("DELETE", "/api/v1/kv/me/data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"]["worker_profiles"] == 1
    assert body["deleted"]["consents"] == 1
    assert "never deleted" in body["retained"]["consent_audit_rows"]
    assert store.get_worker_profile(me["id"]) is None
    # A second delete is a no-op (idempotent).
    r2 = client.request("DELETE", "/api/v1/kv/me/data")
    assert r2.status_code == 200
    assert all(v == 0 for v in r2.json()["deleted"].values())


def test_account_self_delete_erases_kv_data(client, tmp_path):
    """DELETE /api/v1/me erases Kaam-Vaani data too — before Step
    9.4 it left every KV row behind."""
    me = login(client, "worker-selfdel@example.com")
    path = str(tmp_path / "app.db")
    store = ConsentStore(path)
    employers = EmployerStore(path)
    employer = _verified_employer(employers, user_id="u-other-emp2")
    listing = _verified_listing(employers, employer.id)
    store.save_worker_profile(
        me["id"],
        skills=["welding"],
        education="12th pass",
        city="Madurai",
        district="Madurai",
        income_monthly=12000,
        goal_type="job",
    )
    store.grant_consent(me["id"], employer.id, ["skills"])
    outcome = store.report_outcome(
        employer.id,
        listing.id,
        me["id"],
        "hired",
        reported_by_user_id=me["id"],
        reporter_role="worker",
        note="My phone is 98430 11111.",
    )
    r = client.request("DELETE", "/api/v1/me")
    assert r.status_code == 200, r.text
    assert store.get_worker_profile(me["id"]) is None
    assert store.list_consents_for_worker(me["id"]) == []
    kept = store.get_outcome(outcome.id)
    assert kept is not None
    assert kept.worker_user_id.startswith("deleted-")
    assert kept.note == ""


# --------------------------------------------------------------------------- #
# Security headers — the voice flow needs the mic
# --------------------------------------------------------------------------- #


def test_permissions_policy_allows_microphone_on_own_origin(client):
    """Step 9.4: the Phase 6 `microphone=()` blocked the Kaam-Vaani
    voice flow (Web Speech Recognition) on the Render-served
    origin. The policy now allows the mic on the app's own origin
    only; camera and geolocation stay blocked."""
    r = client.get("/api/v1/health")
    policy = r.headers["permissions-policy"]
    assert "microphone=(self)" in policy
    assert "camera=()" in policy
    assert "geolocation=()" in policy


# --------------------------------------------------------------------------- #
# L50 — lazy expiry uses the (status, expires_at) index
# --------------------------------------------------------------------------- #


def test_expiry_query_uses_index(tmp_path):
    """L50 CLOSED: v14 already ships idx_kv_consents_expiry on
    (status, expires_at), and the expiry query matches it exactly
    — this test proves the planner uses it (no full table scan)."""
    path = str(tmp_path / "l50.db")
    migrate(path)
    conn = db_layer.connect(path)
    try:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM kv_consents"
            " WHERE status = 'granted' AND expires_at <= ?",
            ("2026-11-21T00:00:00",),
        ).fetchall()
    finally:
        conn.close()
    detail = " ".join(str(row[3]) for row in plan)
    assert "idx_kv_consents_expiry" in detail, detail
    assert "SCAN kv_consents" not in detail, detail
