"""Kaam-Vaani Stage 6: consent system, audit log, employer matching, hire outcomes.

Covers: migration v14 (tables + indexes, idempotent), the worker
profile store (skill normalisation, contact rules), consent grants /
revokes / lazy expiry (one active consent per pair), the append-only
audit log (source + behaviour proof), field-level filtering, the
candidate scorer (probe ranking, explainable contributions, fairness
— no protected attribute is an input), the matching gates (verified
employer + verified listing + active consent, or no data), shortlists,
contact requests, hire outcomes + the 30/90-day retention metric,
and the router end to end (worker saves profile → grants → employer
matches → shortlists → contacts → reports outcome → worker revokes
→ employer sees nothing; flag-off 404).
"""

from __future__ import annotations

import importlib
import inspect
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career_guidance.kaamvaani.consent import (
    CANDIDATE_WEIGHT_CITY,
    CANDIDATE_WEIGHT_INCOME,
    CANDIDATE_WEIGHT_SKILL,
    CANDIDATE_WEIGHT_TITLE,
    CONSENT_FIELDS,
    ConsentConflict,
    ConsentNotFound,
    ConsentStore,
    ConsentValidationError,
    clean_worker_skills,
    consent_explanation,
    filter_profile,
    required_skills_for_listing,
    score_candidate,
)
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.migrations import LATEST_VERSION, applied_versions, migrate
from career_guidance.users import UserStore
from tests.conftest import login

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _stores(tmp_path, name="kv6.db"):
    path = str(tmp_path / name)
    migrate(path)
    return path, ConsentStore(path), EmployerStore(path), UserStore(path)


def _verified_employer(employers, user_id="u-emp", **overrides):
    data = {
        "business_name": "Murugan Electricals",
        "contact_name": "Murugan",
        "city": "Madurai",
        "district": "Madurai",
        "business_type": "Electrical shop",
        "description": "House wiring and repair shop in Madurai.",
    }
    data.update(overrides)
    employer = employers.create_employer(user_id, **data)
    return employers.set_employer_status(employer.id, "verified", reviewer="admin@example.com")


def _verified_listing(employers, employer_id, **overrides):
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
    return employers.create_listing(employer_id, status="verified", **data)


def _worker(store, user_id="u-worker", **overrides):
    data = {
        "skills": ["electrical technician"],
        "education": "12th pass",
        "city": "Madurai",
        "district": "Madurai",
        "income_monthly": 12000,
        "goal_type": "job",
    }
    data.update(overrides)
    return store.save_worker_profile(user_id, **data)


def _backdate_expiry(path, consent_id, when="2020-01-01T00:00:00+00:00"):
    conn = sqlite3.connect(path)
    try:
        conn.execute("UPDATE kv_consents SET expires_at = ? WHERE id = ?", (when, consent_id))
        conn.commit()
    finally:
        conn.close()


def _audit_count(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM kv_consent_audit").fetchone()[0]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Migration v14
# --------------------------------------------------------------------------- #


def test_latest_version_is_14():
    assert LATEST_VERSION == 14


def test_migration_v14_creates_tables_and_indexes(tmp_path):
    path = str(tmp_path / "v14.db")
    applied = migrate(path)
    assert 14 in applied
    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table in (
            "kv_worker_profiles",
            "kv_consents",
            "kv_consent_audit",
            "kv_shortlists",
            "kv_contact_requests",
            "kv_hire_outcomes",
        ):
            assert table in tables, table
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        for index in (
            "idx_kv_consents_pair",
            "idx_kv_consents_expiry",
            "idx_kv_consent_audit_worker",
            "idx_kv_hire_outcomes_listing",
        ):
            assert index in indexes, index
        versions = applied_versions(path)
        assert versions[-1] == 14
    finally:
        conn.close()
    # Idempotent: a second migrate applies nothing new.
    assert migrate(path) == []


def test_migration_v14_worker_profile_has_no_protected_columns(tmp_path):
    """Fairness (6.4), schema half: the worker profile table cannot
    hold a protected attribute — there is no column for one."""
    path = str(tmp_path / "v14cols.db")
    migrate(path)
    conn = sqlite3.connect(path)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(kv_worker_profiles)").fetchall()
        }
    finally:
        conn.close()
    for forbidden in ("caste", "religion", "gender", "origin"):
        assert forbidden not in columns
    assert {"skills_json", "education", "city", "income_monthly"} <= columns


# --------------------------------------------------------------------------- #
# Worker profile
# --------------------------------------------------------------------------- #


def test_clean_worker_skills_normalises_to_taxonomy_canonicals():
    assert clean_worker_skills(["electrical technician"]) == ["electrical"]
    assert clean_worker_skills("electrical technician, computer literacy") == [
        "electrical",
        "computer literacy",
    ]
    assert clean_worker_skills(None) == []
    assert clean_worker_skills([]) == []


def test_clean_worker_skills_keeps_unknown_trade_terms_verbatim():
    # A local trade term the taxonomy does not know is preserved, not
    # silently dropped.
    assert clean_worker_skills(["palm jaggery making"]) == ["palm jaggery making"]
    assert clean_worker_skills(["electrical", "electrical"]) == ["electrical"]


def test_save_and_get_worker_profile_round_trip(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    profile = _worker(store)
    assert profile.user_id == "u-worker"
    assert profile.skills == ["electrical"]
    assert profile.city == "Madurai"
    assert profile.income_monthly == 12000
    assert profile.is_sample is False
    again = store.get_worker_profile("u-worker")
    assert again is not None and again.to_dict() == profile.to_dict()
    assert store.get_worker_profile("nobody") is None


def test_save_worker_profile_upserts(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    _worker(store)
    updated = _worker(store, skills=["driving"], city="Chennai", district="Chennai")
    assert updated.skills == ["driving"]
    assert updated.city == "Chennai"
    assert store.get_worker_profile("u-worker").city == "Chennai"


def test_save_worker_profile_rejects_negative_income(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    with pytest.raises(ConsentValidationError, match="Monthly income"):
        _worker(store, income_monthly=-1)


def test_save_worker_profile_normalises_language(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    assert _worker(store, language="ta").language == "ta"
    assert _worker(store, user_id="u2", language="fr").language == "en"


def test_delete_worker_profile(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    _worker(store)
    assert store.delete_worker_profile("u-worker") is True
    assert store.get_worker_profile("u-worker") is None
    assert store.delete_worker_profile("u-worker") is False


def test_contact_for_shares_phone_only_when_verified(tmp_path):
    path, store, _, users = _stores(tmp_path)
    user = users.upsert_login("w@example.com", "seed", "W")
    contact = store.contact_for(user.id)
    assert contact["email"] == "w@example.com"
    assert contact["phone_verified"] is False
    assert contact["phone_e164"] == ""
    # An unverified number on the row is still not shared.
    conn = sqlite3.connect(path)
    try:
        conn.execute("UPDATE users SET phone_e164 = '+919843012345' WHERE id = ?", (user.id,))
        conn.commit()
    finally:
        conn.close()
    contact = store.contact_for(user.id)
    assert contact["phone_verified"] is False
    assert contact["phone_e164"] == ""
    users.set_phone_verified(user.id, "+919843012345")
    contact = store.contact_for(user.id)
    assert contact["phone_verified"] is True
    assert contact["phone_e164"] == "+919843012345"
    assert store.contact_for("ghost")["email"] == ""


# --------------------------------------------------------------------------- #
# Consent: grant / revoke / expiry
# --------------------------------------------------------------------------- #


def test_grant_consent_happy_path(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    _worker(store)
    consent = store.grant_consent(
        "u-worker",
        employer.id,
        ["skills", "city"],
        30,
        listing_id=listing.id,
        actor="w@example.com",
    )
    assert consent.status == "granted"
    assert consent.fields == ["skills", "city"]
    assert consent.duration_days == 30
    assert consent.listing_id == listing.id
    assert consent.is_active is True
    assert consent.granted_at < consent.expires_at
    events = store.list_audit(worker_user_id="u-worker")
    assert len(events) == 1
    assert events[0].action == "granted"
    assert events[0].actor == "w@example.com"
    assert events[0].detail["fields"] == ["skills", "city"]


def test_grant_consent_defaults_to_all_fields(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    consent = store.grant_consent("u-worker", employer.id, None)
    assert consent.fields == list(CONSENT_FIELDS)


def test_grant_consent_validates_fields_and_duration(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    with pytest.raises(ConsentValidationError, match="at least one field"):
        store.grant_consent("u-worker", employer.id, [])
    with pytest.raises(ConsentValidationError, match="Unknown shareable field"):
        store.grant_consent("u-worker", employer.id, ["skills", "aadhaar"])
    with pytest.raises(ConsentValidationError, match="days"):
        store.grant_consent("u-worker", employer.id, ["skills"], 45)


def test_grant_consent_needs_a_saved_profile(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    with pytest.raises(ConsentConflict, match="Save your work profile"):
        store.grant_consent("u-worker", employer.id, ["skills"])


def test_grant_consent_one_active_per_pair(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    other = _verified_employer(employers, user_id="u-emp2", business_name="Other Shop")
    _worker(store)
    store.grant_consent("u-worker", employer.id, ["skills"])
    with pytest.raises(ConsentConflict, match="already sharing"):
        store.grant_consent("u-worker", employer.id, ["skills"])
    # A different employer is a different pair — allowed.
    second = store.grant_consent("u-worker", other.id, ["skills"])
    assert second.is_active is True


def test_grant_consent_after_revoke_and_after_expiry(tmp_path):
    path, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    first = store.grant_consent("u-worker", employer.id, ["skills"])
    store.revoke_consent(first.id, "u-worker")
    second = store.grant_consent("u-worker", employer.id, ["skills"])
    assert second.is_active is True
    _backdate_expiry(path, second.id)
    third = store.grant_consent("u-worker", employer.id, ["skills"])
    assert third.is_active is True
    assert store.get_consent(second.id).status == "expired"


def test_revoke_consent_happy_path_and_errors(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    consent = store.grant_consent("u-worker", employer.id, ["skills"], actor="w@example.com")
    revoked = store.revoke_consent(consent.id, "u-worker", actor="w@example.com")
    assert revoked.status == "revoked"
    assert revoked.revoked_at != ""
    assert revoked.is_active is False
    events = store.list_audit(consent_id=consent.id)
    assert [e.action for e in events] == ["revoked", "granted"]
    with pytest.raises(ConsentConflict, match="already revoked"):
        store.revoke_consent(consent.id, "u-worker")
    with pytest.raises(ConsentNotFound):
        store.revoke_consent(99999, "u-worker")
    with pytest.raises(ConsentNotFound):
        store.revoke_consent(consent.id, "someone-else")


def test_revoke_expired_consent_is_a_conflict(tmp_path):
    path, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    consent = store.grant_consent("u-worker", employer.id, ["skills"])
    _backdate_expiry(path, consent.id)
    with pytest.raises(ConsentConflict, match="already expired"):
        store.revoke_consent(consent.id, "u-worker")


def test_lazy_expiry_flips_status_and_audits(tmp_path):
    path, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    consent = store.grant_consent("u-worker", employer.id, ["skills"])
    _backdate_expiry(path, consent.id)
    expired = store.expire_overdue_consents()
    assert expired == [consent.id]
    assert store.get_consent(consent.id).status == "expired"
    events = store.list_audit(consent_id=consent.id)
    assert events[0].action == "expired"
    assert events[0].actor == "system"
    # Second call is a no-op — expiry is idempotent.
    assert store.expire_overdue_consents() == []


def test_has_active_consent_and_record(tmp_path):
    path, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    _worker(store)
    assert store.has_active_consent("u-worker", employer.id) is None
    assert store.has_consent_record("u-worker", employer.id) is False
    consent = store.grant_consent("u-worker", employer.id, ["skills"])
    assert store.has_active_consent("u-worker", employer.id).id == consent.id
    assert store.has_consent_record("u-worker", employer.id) is True
    _backdate_expiry(path, consent.id)
    assert store.has_active_consent("u-worker", employer.id) is None
    assert store.has_consent_record("u-worker", employer.id) is True


def test_list_consents_scoped_to_worker_and_employer(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    other = _verified_employer(employers, user_id="u-emp2", business_name="Other Shop")
    _worker(store)
    _worker(store, user_id="u-worker2", skills=["driving"])
    store.grant_consent("u-worker", employer.id, ["skills"])
    store.grant_consent("u-worker", other.id, ["skills"])
    store.grant_consent("u-worker2", employer.id, ["skills"])
    assert len(store.list_consents_for_worker("u-worker")) == 2
    assert len(store.list_consents_for_worker("u-worker2")) == 1
    assert len(store.list_consents_for_employer(employer.id)) == 2
    assert len(store.list_consents_for_employer(other.id)) == 1
    assert store.list_consents_for_worker("ghost") == []


def test_consent_explanation_states_exactly_what_is_shared():
    text = consent_explanation("Murugan Electricals", ["skills", "city"], 30)
    assert "Murugan Electricals" in text
    assert "30 days" in text
    assert "the work you can do (your skills)" in text
    assert "where you live (your city and district)" in text
    assert "They will NOT see" in text
    assert "how much you need to earn each month" in text  # not shared
    assert "Revoke" in text
    full = consent_explanation("Shop", list(CONSENT_FIELDS), 7)
    assert "They will NOT see" not in full


# --------------------------------------------------------------------------- #
# Field filtering
# --------------------------------------------------------------------------- #


def test_filter_profile_returns_only_consented_fields(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    profile = _worker(store, interests="computers")
    contact = {"email": "w@example.com", "phone_e164": "+919843012345", "phone_verified": True}
    filtered = filter_profile(profile, ["skills", "city"], contact)
    assert filtered["skills"] == ["electrical"]
    assert filtered["city"] == "Madurai"
    assert filtered["district"] == "Madurai"
    assert "education" not in filtered
    assert "income_monthly" not in filtered
    assert "interests" not in filtered
    assert "contact" not in filtered
    assert filtered["fields_shared"] == ["skills", "city"]
    assert filtered["worker_user_id"] == "u-worker"
    full = filter_profile(profile, list(CONSENT_FIELDS), contact)
    assert full["contact"] == contact
    assert full["education"] == "12th pass"
    assert full["income_monthly"] == 12000
    assert full["interests"] == "computers"


def test_filter_profile_ignores_unknown_fields(tmp_path):
    _, store, _, _ = _stores(tmp_path)
    profile = _worker(store)
    filtered = filter_profile(profile, ["skills", "aadhaar", "caste"])
    assert filtered["fields_shared"] == ["skills"]
    assert "aadhaar" not in filtered


# --------------------------------------------------------------------------- #
# Candidate scoring (probes)
# --------------------------------------------------------------------------- #


def _probe_setup(tmp_path):
    """Electrician listing + three consented candidates: a matching
    electrician (Madurai), a tailor (Madurai), a driver (Chennai,
    need above the pay ceiling). Returns (store, employers, listing,
    {email: user_id})."""
    _, store, employers, users = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    ids = {}
    probes = [
        ("sparky@example.com", ["electrical technician"], "Madurai", "Madurai", 12000),
        ("tailor@example.com", ["fashion design", "stitching"], "Madurai", "Madurai", 12000),
        ("driver@example.com", ["driving"], "Chennai", "Chennai", 25000),
    ]
    for email, skills, city, district, need in probes:
        user = users.upsert_login(email, "seed", email.split("@")[0])
        ids[email] = user.id
        store.save_worker_profile(
            user.id,
            skills=skills,
            education="12th pass",
            city=city,
            district=district,
            income_monthly=need,
            goal_type="job",
        )
        store.grant_consent(user.id, employer.id, None, 30, listing_id=listing.id, actor=email)
    return store, employers, listing, ids


def test_candidate_weights_sum_to_one():
    total = (
        CANDIDATE_WEIGHT_SKILL
        + CANDIDATE_WEIGHT_TITLE
        + CANDIDATE_WEIGHT_CITY
        + CANDIDATE_WEIGHT_INCOME
    )
    assert total == pytest.approx(1.0)


def test_probe_ranking_electrician_first(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    result = store.rank_candidates_for_listing(listing.id)
    assert result["count"] == 3
    ordered = [c["worker_user_id"] for c in result["candidates"]]
    assert ordered == [
        ids["sparky@example.com"],
        ids["tailor@example.com"],
        ids["driver@example.com"],
    ]
    top, middle, bottom = result["candidates"]
    # Measured probe scores (weights 0.35/0.30/0.20/0.15): the
    # electrician matches on skill + city + income; the tailor only
    # on city + income; the driver on neither city nor income.
    assert top["score"] == pytest.approx(0.70, abs=0.001)
    assert top["components"] == {"skill": 1.0, "title": 0.0, "city": 1.0, "income": 1.0}
    assert top["matched_skills"] == ["electrical"]
    assert top["missing_skills"] == []
    assert {r["kind"] for r in top["reasons"]} == {"skill", "city", "income"}
    assert middle["score"] == pytest.approx(0.35, abs=0.001)
    assert middle["missing_skills"] == ["electrical"]
    assert bottom["score"] == pytest.approx(0.06, abs=0.001)
    assert bottom["components"]["income"] == 0.4
    assert bottom["components"]["city"] == 0.0


def test_ranking_returns_only_consented_fields(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    result = store.rank_candidates_for_listing(listing.id)
    top = result["candidates"][0]
    # The probe grants shared ALL fields — narrow one worker's consent
    # and re-rank: only the narrowed fields come back.
    consent = store.has_active_consent(ids["sparky@example.com"], listing.employer_id)
    store.revoke_consent(consent.id, ids["sparky@example.com"])
    store.grant_consent(
        ids["sparky@example.com"],
        listing.employer_id,
        ["skills"],
        30,
        listing_id=listing.id,
    )
    result = store.rank_candidates_for_listing(listing.id)
    top = result["candidates"][0]
    assert top["profile"]["fields_shared"] == ["skills"]
    assert "city" not in top["profile"]
    assert "income_monthly" not in top["profile"]
    assert "contact" not in top["profile"]


def test_ranking_city_filter(tmp_path):
    store, _, listing, _ = _probe_setup(tmp_path)
    result = store.rank_candidates_for_listing(listing.id, city="Madurai")
    assert result["count"] == 2
    result = store.rank_candidates_for_listing(listing.id, city="Chennai")
    assert result["count"] == 1
    result = store.rank_candidates_for_listing(listing.id, city="Salem")
    assert result["count"] == 0


def test_score_candidate_district_and_missing_income(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(
        employers,
        employer.id,
        title="General helper",
        role_category="",
        requirements="",
        city="Dindigul",
        district="Dindigul",
        pay_monthly_min=None,
        pay_monthly_max=None,
    )
    worker = _worker(store, city="Oddanchatram", district="Dindigul", income_monthly=None)
    match = score_candidate(worker, listing)
    assert match.components["skill"] == 0.0
    assert match.components["city"] == 0.5  # same district, different city
    assert match.components["income"] == 1.0  # no data never punishes
    assert match.missing_skills == ["general helper"]


def test_score_candidate_no_extractable_requirements(tmp_path):
    """A listing whose title/role/requirements extract to no skills
    scores 0 on skill for everyone and says so (the reason exists
    for robustness — the API requires a title, so this needs a
    title of pure filler)."""
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(
        employers,
        employer.id,
        title="a",
        role_category="",
        requirements="",
    )
    assert required_skills_for_listing(listing) == []
    worker = _worker(store)
    match = score_candidate(worker, listing)
    assert match.components["skill"] == 0.0
    assert {"kind": "no_requirements"} in match.reasons


def test_required_skills_for_listing(tmp_path):
    _, _, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    assert "electrical" in required_skills_for_listing(listing)


# --------------------------------------------------------------------------- #
# Matching gates: no consent, no data
# --------------------------------------------------------------------------- #


def test_ranking_needs_verified_employer_and_listing(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    pending = employers.create_employer("u-pending", business_name="Pending Shop")
    listing = _verified_listing(employers, pending.id)
    with pytest.raises(ConsentConflict, match="verified employer"):
        store.rank_candidates_for_listing(listing.id)
    employer = _verified_employer(employers)
    draft = employers.create_listing(employer.id, title="Draft job", status="pending")
    with pytest.raises(ConsentConflict, match="verified listing"):
        store.rank_candidates_for_listing(draft.id)
    with pytest.raises(ConsentNotFound):
        store.rank_candidates_for_listing(99999)


def test_unconsented_worker_is_invisible(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    # A fourth worker with a profile but NO consent.
    store.save_worker_profile(
        "u-stranger",
        skills=["electrical technician"],
        education="12th pass",
        city="Madurai",
        district="Madurai",
        income_monthly=12000,
        goal_type="job",
    )
    result = store.rank_candidates_for_listing(listing.id)
    assert result["count"] == 3
    assert "u-stranger" not in [c["worker_user_id"] for c in result["candidates"]]
    # And a worker whose profile was deleted after consenting vanishes too.
    store.delete_worker_profile(ids["driver@example.com"])
    result = store.rank_candidates_for_listing(listing.id)
    assert result["count"] == 2


def test_revoked_and_expired_consent_cut_access(tmp_path):
    path, store, employers, users = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    worker = users.upsert_login("w@example.com", "seed", "W")
    _worker(store, user_id=worker.id)
    consent = store.grant_consent(worker.id, employer.id, None, 30, listing_id=listing.id)
    assert store.rank_candidates_for_listing(listing.id)["count"] == 1
    store.revoke_consent(consent.id, worker.id)
    assert store.rank_candidates_for_listing(listing.id)["count"] == 0
    second = store.grant_consent(worker.id, employer.id, None, 30, listing_id=listing.id)
    assert store.rank_candidates_for_listing(listing.id)["count"] == 1
    _backdate_expiry(path, second.id)
    assert store.rank_candidates_for_listing(listing.id)["count"] == 0


def test_ranking_writes_one_access_event_per_candidate(tmp_path):
    store, _, listing, _ = _probe_setup(tmp_path)
    before = _audit_count(store.target)
    result = store.rank_candidates_for_listing(listing.id)
    assert result["count"] == 3
    after = _audit_count(store.target)
    assert after - before == 3
    events = store.list_audit(employer_id=result["listing"]["employer_id"])
    accessed = [e for e in events if e.action == "accessed"]
    assert len(accessed) == 3
    assert accessed[0].detail["listing_id"] == result["listing"]["id"]
    assert accessed[0].detail["fields_returned"]


def test_ranking_marks_shortlisted_and_sample(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    store.add_shortlist(listing.employer_id, listing.id, ids["sparky@example.com"])
    result = store.rank_candidates_for_listing(listing.id)
    top = result["candidates"][0]
    assert top["shortlisted"] is True
    assert result["candidates"][1]["shortlisted"] is False
    assert result["sample_data"] is False
    # A sample worker flips the sample flag.
    store.save_worker_profile(
        "u-sample",
        skills=["electrical technician"],
        education="12th pass",
        city="Madurai",
        district="Madurai",
        income_monthly=12000,
        goal_type="job",
        is_sample=True,
    )
    store.grant_consent("u-sample", listing.employer_id, None, 30, listing_id=listing.id)
    result = store.rank_candidates_for_listing(listing.id)
    assert result["sample_data"] is True


# --------------------------------------------------------------------------- #
# Shortlists
# --------------------------------------------------------------------------- #


def test_shortlist_needs_consent_and_is_unique(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    with pytest.raises(ConsentConflict, match="has not shared"):
        store.add_shortlist(listing.employer_id, listing.id, "u-stranger")
    entry = store.add_shortlist(listing.employer_id, listing.id, ids["sparky@example.com"])
    assert entry.worker_user_id == ids["sparky@example.com"]
    with pytest.raises(ConsentConflict, match="already shortlisted"):
        store.add_shortlist(listing.employer_id, listing.id, ids["sparky@example.com"])
    sparky = ids["sparky@example.com"]
    assert store.remove_shortlist(listing.employer_id, listing.id, sparky) is True
    assert store.remove_shortlist(listing.employer_id, listing.id, sparky) is False


def test_shortlist_view_hides_profile_after_revoke(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    store.add_shortlist(listing.employer_id, listing.id, ids["sparky@example.com"])
    view = store.shortlist_view(listing.employer_id, listing.id)
    assert len(view) == 1
    assert view[0]["consent_status"] == "granted"
    assert view[0]["profile"] is not None
    consent = store.has_active_consent(ids["sparky@example.com"], listing.employer_id)
    store.revoke_consent(consent.id, ids["sparky@example.com"])
    view = store.shortlist_view(listing.employer_id, listing.id)
    assert len(view) == 1  # the entry survives
    assert view[0]["consent_status"] == "revoked"
    assert view[0]["profile"] is None  # ...but the data does not


# --------------------------------------------------------------------------- #
# Contact requests
# --------------------------------------------------------------------------- #


def test_contact_request_needs_consent(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    with pytest.raises(ConsentConflict, match="has not shared"):
        store.create_contact_request(listing.employer_id, listing.id, "u-stranger")
    created = store.create_contact_request(
        listing.employer_id,
        listing.id,
        ids["sparky@example.com"],
        message="Can you come for a trial on Monday?",
    )
    assert created.message.startswith("Can you come")
    assert len(store.list_contact_requests(employer_id=listing.employer_id)) == 1
    assert len(store.list_contact_requests(worker_user_id=ids["sparky@example.com"])) == 1
    assert len(store.list_contact_requests(worker_user_id=ids["tailor@example.com"])) == 0
    assert len(store.list_contact_requests(listing_id=listing.id)) == 1


# --------------------------------------------------------------------------- #
# Hire outcomes + retention
# --------------------------------------------------------------------------- #


def test_report_outcome_happy_path_and_stranger_block(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    outcome = store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["sparky@example.com"],
        "hired",
        "u-emp",
        "employer",
        note="Joined Monday",
    )
    assert outcome.outcome == "hired"
    assert outcome.reporter_role == "employer"
    worker_report = store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["tailor@example.com"],
        "interviewed",
        ids["tailor@example.com"],
        "worker",
    )
    assert worker_report.reporter_role == "worker"
    with pytest.raises(ConsentConflict, match="No consent record"):
        store.report_outcome(
            listing.employer_id, listing.id, "u-stranger", "hired", "u-emp", "employer"
        )
    with pytest.raises(ConsentValidationError, match="Outcome must be"):
        store.report_outcome(
            listing.employer_id,
            listing.id,
            ids["sparky@example.com"],
            "ghosted",
            "u-emp",
            "employer",
        )


def test_report_outcome_after_revoke_still_allowed(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    consent = store.has_active_consent(ids["sparky@example.com"], listing.employer_id)
    store.revoke_consent(consent.id, ids["sparky@example.com"])
    outcome = store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["sparky@example.com"],
        "hired",
        "u-emp",
        "employer",
    )
    assert outcome.outcome == "hired"


def test_followup_and_retention_summary(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    first = store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["sparky@example.com"],
        "hired",
        "u-emp",
        "employer",
    )
    second = store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["tailor@example.com"],
        "hired",
        "u-emp",
        "employer",
    )
    store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["driver@example.com"],
        "not_hired",
        "u-emp",
        "employer",
    )
    summary = store.retention_summary(listing.employer_id)
    assert summary["hired"] == 2
    assert summary["day30"] == {
        "reported": 0,
        "still_employed": 0,
        "left": 0,
        "unknown": 0,
        "rate": None,
    }
    store.record_followup(first.id, 30, "still_employed")
    store.record_followup(second.id, 30, "left")
    store.record_followup(first.id, 90, "still_employed")
    summary = store.retention_summary(listing.employer_id)
    assert summary["day30"]["reported"] == 2
    assert summary["day30"]["rate"] == 0.5
    assert summary["day90"]["reported"] == 1
    assert summary["day90"]["rate"] == 1.0
    with pytest.raises(ConsentValidationError, match="30 or 90"):
        store.record_followup(first.id, 60, "still_employed")
    with pytest.raises(ConsentValidationError, match="Retention status"):
        store.record_followup(first.id, 30, "maybe")
    with pytest.raises(ConsentNotFound):
        store.record_followup(99999, 30, "still_employed")
    not_hired = store.list_outcomes(worker_user_id=ids["driver@example.com"])[0]
    with pytest.raises(ConsentConflict, match="hires only"):
        store.record_followup(not_hired.id, 30, "still_employed")


def test_outcome_counts_latest_wins(tmp_path):
    store, _, listing, ids = _probe_setup(tmp_path)
    store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["sparky@example.com"],
        "interviewed",
        "u-emp",
        "employer",
    )
    store.report_outcome(
        listing.employer_id,
        listing.id,
        ids["sparky@example.com"],
        "hired",
        "u-emp",
        "employer",
    )
    counts = store.outcome_counts(listing.employer_id, listing_id=listing.id)
    assert counts == {"hired": 1, "interviewed": 0, "not_hired": 0, "total": 1}
    assert store.outcome_counts(listing.employer_id)["total"] == 1


# --------------------------------------------------------------------------- #
# Audit log: append-only (execution prompt 6.2)
# --------------------------------------------------------------------------- #


def test_audit_log_has_no_update_or_delete_code_path():
    """The audit log is append-only: no UPDATE or DELETE statement
    against kv_consent_audit exists anywhere in the consent module.
    The only audit write is the INSERT in _append_audit."""
    source = Path("career_guidance/kaamvaani/consent.py").read_text(encoding="utf-8")
    assert "UPDATE kv_consent_audit" not in source
    assert "DELETE FROM kv_consent_audit" not in source
    assert "update kv_consent_audit" not in source.lower()
    assert "delete from kv_consent_audit" not in source.lower()


def test_audit_log_has_no_mutating_method():
    """The only ConsentStore methods touching the audit table are
    the private INSERT-only writer and the read — there is no
    update/delete/remove method for audit rows."""
    methods = [name for name, _ in inspect.getmembers(ConsentStore, inspect.isfunction)]
    audit_methods = sorted(m for m in methods if "audit" in m)
    assert audit_methods == ["_append_audit", "list_audit"]
    writer_source = inspect.getsource(ConsentStore._append_audit)
    assert "INSERT INTO kv_consent_audit" in writer_source
    assert "UPDATE" not in writer_source
    assert "DELETE" not in writer_source
    for name in methods:
        assert not (name.startswith(("delete_", "update_", "remove_")) and "audit" in name)


def test_audit_log_only_grows(tmp_path):
    path, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    _worker(store)
    assert _audit_count(path) == 0
    consent = store.grant_consent("u-worker", employer.id, None, 30, listing_id=listing.id)
    assert _audit_count(path) == 1
    store.rank_candidates_for_listing(listing.id)
    assert _audit_count(path) == 2  # +1 accessed
    store.revoke_consent(consent.id, "u-worker")
    assert _audit_count(path) == 3  # +1 revoked
    # Nothing in the store can shrink it: the count never goes down.
    store.delete_sample_data()
    assert _audit_count(path) == 3


# --------------------------------------------------------------------------- #
# Fairness (execution prompt 6.4)
# --------------------------------------------------------------------------- #


def test_scorer_ignores_language_and_identity(tmp_path):
    """Two workers with identical scoring inputs but different
    languages (and different user ids) rank identically — the score
    cannot see anything but skills, city, district and income."""
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    first = _worker(store, user_id="u-en", language="en")
    second = _worker(store, user_id="u-ta", language="ta")
    assert score_candidate(first, listing).score == score_candidate(second, listing).score
    assert score_candidate(first, listing).components == score_candidate(second, listing).components


def test_scorer_source_has_no_protected_inputs():
    """The scorer functions never mention a protected attribute —
    the inputs are exactly skills, city, district, income (worker)
    and title, role, requirements, city, district, pay (listing)."""
    sources = "".join(
        inspect.getsource(fn)
        for fn in (
            score_candidate,
            required_skills_for_listing,
            ConsentStore.rank_candidates_for_listing,
        )
    )
    for forbidden in ("caste", "religion", "gender", "origin"):
        assert forbidden not in sources.lower()


# --------------------------------------------------------------------------- #
# Seed cleanup
# --------------------------------------------------------------------------- #


def test_delete_sample_data_removes_sample_workers_only(tmp_path):
    _, store, employers, _ = _stores(tmp_path)
    employer = _verified_employer(employers)
    listing = _verified_listing(employers, employer.id)
    _worker(store, user_id="u-real")
    store.save_worker_profile(
        "u-sample",
        skills=["driving"],
        education="10th pass",
        city="Madurai",
        district="Madurai",
        income_monthly=10000,
        goal_type="job",
        is_sample=True,
    )
    store.grant_consent("u-real", employer.id, ["skills"], 30, listing_id=listing.id)
    store.grant_consent("u-sample", employer.id, ["skills"], 30, listing_id=listing.id)
    assert store.count_sample_workers() == 1
    removed = store.delete_sample_data()
    assert removed["sample_workers"] == 1
    assert removed["kv_consents"] == 1
    assert store.count_sample_workers() == 0
    assert store.get_worker_profile("u-sample") is None
    assert store.get_worker_profile("u-real") is not None
    assert store.has_active_consent("u-real", employer.id) is not None
    assert store.has_active_consent("u-sample", employer.id) is None
    assert store.delete_sample_data()["sample_workers"] == 0


# --------------------------------------------------------------------------- #
# Router: helpers
# --------------------------------------------------------------------------- #


def _register_employer(client, email="shop@example.com"):
    login(client, email)
    r = client.post(
        "/api/v1/kv/employers/register",
        json={"business_name": "Murugan Electricals", "city": "Madurai"},
    )
    assert r.status_code == 200, r.text
    return r.json()["employer"]


def _admin_review(client, path, approve=True, note=""):
    login(client, "boss@example.com")
    r = client.post(path, json={"approve": approve, "note": note})
    assert r.status_code == 200, r.text
    return r.json()


def _verified_listing_via_api(client, email="shop@example.com"):
    """Register an employer, post a listing, verify both via the
    admin queue. Returns (employer, listing_id). Leaves the client
    logged in as the employer."""
    employer = _register_employer(client, email)
    r = client.post(
        "/api/v1/kv/employers/listings",
        json={
            "title": "Electrician helper",
            "role_category": "electrician",
            "description": "Help with house wiring work. 10th pass.",
            "city": "Madurai",
            "district": "Madurai",
            "pay_monthly_min": 12000,
            "pay_monthly_max": 15000,
            "requirements": "Basic wiring knowledge.",
        },
    )
    assert r.status_code == 200, r.text
    listing_id = r.json()["listing"]["id"]
    _admin_review(client, f"/api/v1/kv/admin/employers/{employer['id']}/review")
    _admin_review(client, f"/api/v1/kv/admin/listings/{listing_id}/review")
    login(client, email)
    return employer, listing_id


def _worker_profile_body(**overrides):
    body = {
        "skills": ["electrical technician"],
        "education": "12th pass",
        "city": "Madurai",
        "district": "Madurai",
        "income_monthly": 12000,
        "goal_type": "job",
        "interests": "machines",
    }
    body.update(overrides)
    return body


def _save_profile(client, email="worker@example.com", **overrides):
    login(client, email)
    r = client.put("/api/v1/kv/worker-profile", json=_worker_profile_body(**overrides))
    assert r.status_code == 200, r.text
    return r.json()["profile"]


# --------------------------------------------------------------------------- #
# Router: status + worker profile
# --------------------------------------------------------------------------- #


def test_consent_status_is_public(client):
    r = client.get("/api/v1/kv/consent/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert [f["name"] for f in body["fields"]] == list(CONSENT_FIELDS)
    assert body["durations_days"] == [7, 30, 90]
    assert body["default_duration_days"] == 30
    assert body["outcomes"] == ["hired", "interviewed", "not_hired"]


def test_worker_profile_save_get_and_validation(client):
    login(client, "worker@example.com")
    assert client.get("/api/v1/kv/worker-profile").status_code == 404
    profile = _save_profile(client)
    assert profile["skills"] == ["electrical"]
    assert profile["city"] == "Madurai"
    # interests is a plain string in the store contract (like the voice
    # profile) — a list here would 422.
    assert profile["interests"] == "machines"
    got = client.get("/api/v1/kv/worker-profile").json()["profile"]
    assert got == profile
    # Negative income is a 422 (pydantic), not a 500.
    r = client.put("/api/v1/kv/worker-profile", json=_worker_profile_body(income_monthly=-5))
    assert r.status_code == 422
    # A second save replaces the first.
    r = client.put("/api/v1/kv/worker-profile", json=_worker_profile_body(city="Chennai"))
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["city"] == "Chennai"


def test_worker_profile_requires_login_and_user_role(client):
    assert client.get("/api/v1/kv/worker-profile").status_code == 401
    assert client.put("/api/v1/kv/worker-profile", json=_worker_profile_body()).status_code == 401
    _register_employer(client)
    r = client.put("/api/v1/kv/worker-profile", json=_worker_profile_body())
    assert r.status_code == 400
    assert "worker account" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Router: full consent flow end to end
# --------------------------------------------------------------------------- #


def test_full_consent_flow_end_to_end(client):
    # Worker saves a profile; employer posts + verifies a listing.
    _save_profile(client)
    employer, listing_id = _verified_listing_via_api(client)
    # Worker grants a NARROW consent (skills + city only).
    login(client, "worker@example.com")
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={
            "employer_id": employer["id"],
            "fields": ["skills", "city"],
            "duration_days": 30,
            "listing_id": listing_id,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    consent_id = body["consent"]["id"]
    assert body["consent"]["fields"] == ["skills", "city"]
    assert body["employer_name"] == "Murugan Electricals"
    assert "Murugan Electricals" in body["explanation"]
    assert "the work you can do (your skills)" in body["explanation"]
    assert body["consent"]["employer_name"] == "Murugan Electricals"
    assert body["consent"]["listing_title"] == "Electrician helper"
    # Employer matches: exactly one candidate, only consented fields.
    login(client, "shop@example.com")
    r = client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["count"] == 1
    candidate = result["candidates"][0]
    worker_user_id = candidate["worker_user_id"]
    assert candidate["profile"]["fields_shared"] == ["skills", "city"]
    assert candidate["profile"]["skills"] == ["electrical"]
    assert candidate["profile"]["city"] == "Madurai"
    assert "income_monthly" not in candidate["profile"]
    assert "contact" not in candidate["profile"]
    assert candidate["score"] > 0
    assert set(candidate["components"]) == {"skill", "title", "city", "income"}
    assert candidate["consent_id"] == consent_id
    # Enriched shape the UI renders: worker_name ("" for a nameless
    # magic-link worker), match_percent, shortlisted, is_sample.
    assert candidate["worker_name"] == ""
    assert candidate["match_percent"] == round(candidate["score"] * 100, 1)
    assert candidate["shortlisted"] is False
    assert candidate["is_sample"] is False
    assert result["sample_data"] is False
    assert result["listing"]["id"] == listing_id
    # Reasons are structured (kind + payload), not free text — the UI
    # renders one line per reason. Title is 0.0 for this electrician
    # case (no shared-stem matching), so no title reason appears.
    assert [r["kind"] for r in candidate["reasons"]] == ["skill", "city", "income"]
    assert candidate["reasons"][0]["skills"] == ["electrical"]
    assert candidate["reasons"][1]["city"] == "Madurai"
    # The worker's audit shows the grant AND the access.
    login(client, "worker@example.com")
    events = client.get("/api/v1/kv/consent/audit").json()["events"]
    assert [e["action"] for e in events] == ["accessed", "granted"]
    mine = client.get("/api/v1/kv/consent/mine").json()["consents"]
    assert len(mine) == 1 and mine[0]["active"] is True
    # Employer shortlists + contacts; the worker sees the request.
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/employers/matching/shortlist",
        json={"listing_id": listing_id, "worker_user_id": worker_user_id},
    )
    assert r.status_code == 200, r.text
    view = client.get(f"/api/v1/kv/employers/matching/shortlist?listing_id={listing_id}").json()[
        "shortlist"
    ]
    assert len(view) == 1
    assert view[0]["consent_status"] == "granted"
    assert view[0]["profile"] is not None
    # The shortlist view is FLAT (not nested under "shortlist") with
    # the worker's name and the consent expiry the UI shows.
    assert view[0]["worker_user_id"] == worker_user_id
    assert view[0]["worker_name"] == ""
    assert view[0]["consent_expires_at"] != ""
    assert "shortlist" not in view[0]
    r = client.post(
        "/api/v1/kv/employers/matching/contact-request",
        json={
            "listing_id": listing_id,
            "worker_user_id": worker_user_id,
            "message": "Can you come for a trial on Monday?",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["request"]["employer_name"] == "Murugan Electricals"
    login(client, "worker@example.com")
    requests = client.get("/api/v1/kv/consent/contact-requests").json()["requests"]
    assert len(requests) == 1
    assert requests[0]["listing_title"] == "Electrician helper"
    # Employer reports hired; retention starts with no follow-ups.
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={
            "listing_id": listing_id,
            "worker_user_id": worker_user_id,
            "outcome": "hired",
            "note": "Joined Monday",
        },
    )
    assert r.status_code == 200, r.text
    outcome_id = r.json()["outcome"]["id"]
    # Magic-link users have no name set — the field is honestly empty,
    # not invented from the email.
    assert r.json()["outcome"]["worker_name"] == ""
    assert r.json()["outcome"]["listing_title"] == "Electrician helper"
    summary = client.get(f"/api/v1/kv/employers/hire-outcomes?listing_id={listing_id}").json()
    assert summary["counts"] == {"hired": 1, "interviewed": 0, "not_hired": 0, "total": 1}
    assert summary["retention"]["hired"] == 1
    assert summary["retention"]["day30"]["rate"] is None
    login(client, "worker@example.com")
    assert len(client.get("/api/v1/kv/hire-outcomes/mine").json()["outcomes"]) == 1
    # Day-30 follow-up: still employed → rate 1.0.
    login(client, "shop@example.com")
    r = client.post(
        f"/api/v1/kv/hire-outcomes/{outcome_id}/followup",
        json={"day": 30, "status": "still_employed"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["day30_status"] == "still_employed"
    summary = client.get(f"/api/v1/kv/employers/hire-outcomes?listing_id={listing_id}").json()
    assert summary["retention"]["day30"]["rate"] == 1.0
    # Worker revokes: the employer sees NOTHING from the next call on.
    login(client, "worker@example.com")
    r = client.post(f"/api/v1/kv/consent/{consent_id}/revoke")
    assert r.status_code == 200, r.text
    assert r.json()["consent"]["status"] == "revoked"
    login(client, "shop@example.com")
    result = client.post(
        "/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id}
    ).json()
    assert result["count"] == 0
    view = client.get(f"/api/v1/kv/employers/matching/shortlist?listing_id={listing_id}").json()[
        "shortlist"
    ]
    assert len(view) == 1  # entry survives
    assert view[0]["consent_status"] == "revoked"
    assert view[0]["profile"] is None  # ...but the data does not
    # Outcomes can still be reported after revoke (consent record exists).
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={
            "listing_id": listing_id,
            "worker_user_id": worker_user_id,
            "outcome": "hired",
            "note": "Confirmed after revoke",
        },
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# Router: grant / revoke errors
# --------------------------------------------------------------------------- #


def test_grant_errors(client):
    _save_profile(client)
    employer, listing_id = _verified_listing_via_api(client)
    login(client, "worker@example.com")
    # Unknown employer / listing → 404.
    r = client.post("/api/v1/kv/consent/grant", json={"employer_id": 99999})
    assert r.status_code == 404
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": 99999},
    )
    assert r.status_code == 404
    # Bad field / bad duration → 400.
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "fields": ["skills", "aadhaar"]},
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "duration_days": 45},
    )
    assert r.status_code == 400
    # Duplicate active grant → 409.
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": listing_id},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": listing_id},
    )
    assert r.status_code == 409
    # An employer account cannot grant as a worker.
    login(client, "shop@example.com")
    r = client.post("/api/v1/kv/consent/grant", json={"employer_id": employer["id"]})
    assert r.status_code == 400


def test_grant_without_profile_is_409(client):
    employer, _ = _verified_listing_via_api(client)
    login(client, "worker@example.com")
    r = client.post("/api/v1/kv/consent/grant", json={"employer_id": employer["id"]})
    assert r.status_code == 409
    assert "work profile" in r.json()["detail"]


def test_revoke_errors(client):
    _save_profile(client)
    employer, listing_id = _verified_listing_via_api(client)
    login(client, "worker@example.com")
    r = client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": listing_id},
    )
    consent_id = r.json()["consent"]["id"]
    assert client.post("/api/v1/kv/consent/99999/revoke").status_code == 404
    # Another worker's consent 404s (never 403 — no id leak).
    login(client, "other-worker@example.com")
    assert client.post(f"/api/v1/kv/consent/{consent_id}/revoke").status_code == 404
    # Double revoke → 409.
    login(client, "worker@example.com")
    assert client.post(f"/api/v1/kv/consent/{consent_id}/revoke").status_code == 200
    assert client.post(f"/api/v1/kv/consent/{consent_id}/revoke").status_code == 409


# --------------------------------------------------------------------------- #
# Router: matching negative cases
# --------------------------------------------------------------------------- #


def test_matching_negative_cases(client):
    _save_profile(client)
    # Unverified employer cannot match at all.
    employer = _register_employer(client)
    r = client.post(
        "/api/v1/kv/employers/listings",
        json={"title": "Electrician helper", "city": "Madurai"},
    )
    listing_id = r.json()["listing"]["id"]
    r = client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    assert r.status_code == 409
    assert "verified employer" in r.json()["detail"]
    # Verified employer, pending listing → 409.
    _admin_review(client, f"/api/v1/kv/admin/employers/{employer['id']}/review")
    login(client, "shop@example.com")
    r = client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    assert r.status_code == 409
    assert "verified listing" in r.json()["detail"]
    # Verify the listing: now matching works — but with no consent
    # the worker is invisible (0 candidates, not an error).
    _admin_review(client, f"/api/v1/kv/admin/listings/{listing_id}/review")
    login(client, "shop@example.com")
    r = client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0
    # Explicit empty-string city also validates ("" = no filter; the
    # frontend sends "" when the city box is blank — null 422s).
    r = client.post(
        "/api/v1/kv/employers/matching/candidates",
        json={"listing_id": listing_id, "city": ""},
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0
    # Another employer's listing 404s.
    _register_employer(client, "shop-b@example.com")
    r = client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    assert r.status_code == 404
    # A worker calling the employer endpoint gets 403.
    login(client, "worker@example.com")
    r = client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    assert r.status_code == 403


def test_shortlist_and_contact_require_consent(client):
    _save_profile(client)
    _, listing_id = _verified_listing_via_api(client)
    # The worker has a profile but has NOT consented: shortlist and
    # contact both refuse with 409.
    login(client, "worker@example.com")
    me = client.get("/api/v1/auth/me").json()["user"]
    worker_id = me["id"]
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/employers/matching/shortlist",
        json={"listing_id": listing_id, "worker_user_id": worker_id},
    )
    assert r.status_code == 409
    r = client.post(
        "/api/v1/kv/employers/matching/contact-request",
        json={"listing_id": listing_id, "worker_user_id": worker_id},
    )
    assert r.status_code == 409


def test_outcome_permissions_and_validation(client):
    _save_profile(client)
    employer, listing_id = _verified_listing_via_api(client)
    login(client, "worker@example.com")
    me = client.get("/api/v1/auth/me").json()["user"]
    worker_id = me["id"]
    client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": listing_id},
    )
    # A third user (neither employer nor worker) gets 403.
    login(client, "third@example.com")
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={"listing_id": listing_id, "worker_user_id": worker_id, "outcome": "hired"},
    )
    assert r.status_code == 403
    # A stranger worker (no consent record) gets 409 from the store.
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={"listing_id": listing_id, "worker_user_id": "u-stranger", "outcome": "hired"},
    )
    assert r.status_code == 409
    # Bad outcome value → 400.
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={"listing_id": listing_id, "worker_user_id": worker_id, "outcome": "ghosted"},
    )
    assert r.status_code == 400
    # Unknown listing → 404.
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={"listing_id": 99999, "worker_user_id": worker_id, "outcome": "hired"},
    )
    assert r.status_code == 404
    # The worker can report their own outcome.
    login(client, "worker@example.com")
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={"listing_id": listing_id, "worker_user_id": worker_id, "outcome": "interviewed"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["reporter_role"] == "worker"


def test_followup_permissions_and_validation(client):
    _save_profile(client)
    employer, listing_id = _verified_listing_via_api(client)
    login(client, "worker@example.com")
    me = client.get("/api/v1/auth/me").json()["user"]
    worker_id = me["id"]
    client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": listing_id},
    )
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={
            "listing_id": listing_id,
            "worker_user_id": worker_id,
            "outcome": "interviewed",
        },
    )
    outcome_id = r.json()["outcome"]["id"]
    # Follow-ups apply to hires only.
    r = client.post(
        f"/api/v1/kv/hire-outcomes/{outcome_id}/followup",
        json={"day": 30, "status": "still_employed"},
    )
    assert r.status_code == 409
    # Unknown outcome → 404; third user → 403.
    assert (
        client.post(
            "/api/v1/kv/hire-outcomes/99999/followup",
            json={"day": 30, "status": "still_employed"},
        ).status_code
        == 404
    )
    login(client, "third@example.com")
    assert (
        client.post(
            f"/api/v1/kv/hire-outcomes/{outcome_id}/followup",
            json={"day": 30, "status": "still_employed"},
        ).status_code
        == 403
    )
    # Bad day / bad status → 400 (as the employer, on a real hire).
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/hire-outcomes",
        json={"listing_id": listing_id, "worker_user_id": worker_id, "outcome": "hired"},
    )
    hired_id = r.json()["outcome"]["id"]
    assert (
        client.post(
            f"/api/v1/kv/hire-outcomes/{hired_id}/followup",
            json={"day": 60, "status": "still_employed"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/v1/kv/hire-outcomes/{hired_id}/followup",
            json={"day": 30, "status": "maybe"},
        ).status_code
        == 400
    )


def test_employer_audit_and_outcomes_views(client):
    _save_profile(client)
    employer, listing_id = _verified_listing_via_api(client)
    login(client, "worker@example.com")
    client.post(
        "/api/v1/kv/consent/grant",
        json={"employer_id": employer["id"], "listing_id": listing_id},
    )
    login(client, "shop@example.com")
    client.post("/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id})
    events = client.get("/api/v1/kv/employers/matching/audit").json()["events"]
    assert [e["action"] for e in events] == ["accessed", "granted"]
    assert events[0]["employer_id"] == employer["id"]
    # Empty outcomes view is honest (no invented zeros beyond counts).
    summary = client.get("/api/v1/kv/employers/hire-outcomes").json()
    assert summary["outcomes"] == []
    assert summary["counts"]["total"] == 0
    assert summary["retention"]["hired"] == 0
    assert summary["retention"]["day30"]["rate"] is None


# --------------------------------------------------------------------------- #
# Router: flag off
# --------------------------------------------------------------------------- #


@pytest.fixture()
def app_module_kv_consent_off(tmp_path, monkeypatch):
    """backend.main reloaded with KV_CONSENT=false (dev otherwise)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_CONSENT", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_consent_routes_404_when_flag_off(app_module_kv_consent_off):
    with TestClient(app_module_kv_consent_off.app) as c:
        assert c.get("/api/v1/kv/consent/status").status_code == 404
        assert c.get("/api/v1/kv/worker-profile").status_code == 404
        assert c.get("/api/v1/kv/consent/mine").status_code == 404
        assert c.post(
            "/api/v1/kv/employers/matching/candidates", json={"listing_id": 1}
        ).status_code in (404, 405)
        # The rest of the app is unaffected by the flag being off.
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/api/v1/kv/voice/status").status_code == 200
        assert c.get("/api/v1/kv/employers/status").status_code == 200
