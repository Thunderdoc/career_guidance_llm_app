"""Kaam-Vaani Stage 5: employer portal, listings, verification, scam checker.

Covers: migration v13 (tables + indexes, idempotent), the employer
store (status machines, public-listings-only-verified, duplicate
detection, report auto-flag), the scam rules (each rule fires, the
"no fee" negation does not, score cap + thresholds, LLM advisory
path with mock completers, pay plausibility framework-only), and the
router end to end (register → list → review → verified → worker
visible; fake listings flagged; admin queue; endorsements; reports;
phone verification; flag-off 404).
"""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.kaamvaani.scam import (
    FLAG_THRESHOLD,
    check_listing,
    check_pay_plausibility,
    run_rules,
    score_with_llm,
)
from career_guidance.migrations import LATEST_VERSION, applied_versions, migrate
from tests.conftest import login

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _store(tmp_path, name="kv5.db") -> EmployerStore:
    path = str(tmp_path / name)
    migrate(path)
    return EmployerStore(path)


def _employer(store, user_id="u-emp", **overrides):
    data = {
        "business_name": "Murugan Electricals",
        "contact_name": "Murugan",
        "city": "Madurai",
        "district": "Madurai",
        "business_type": "Electrical shop",
        "description": "House wiring and repair shop in Madurai.",
    }
    data.update(overrides)
    return store.create_employer(user_id, **data)


def _listing(**overrides):
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
    return data


def _fake_listing(**overrides):
    data = {
        "title": "Data entry work from home",
        "role_category": "data entry",
        "description": (
            "Earn 45000 per month from home. Pay 2000 registration fee to "
            "confirm your seat. Limited seats, apply today only!"
        ),
        "city": "Madurai",
        "pay_monthly_min": 45000,
        "pay_monthly_max": 45000,
        "requirements": "Share Aadhaar and bank details to start.",
        "contact_info": "WhatsApp only: 98765 43210",
    }
    data.update(overrides)
    return data


class _MockCompleter:
    """A ChatCompleter stand-in returning a fixed reply (or raising)."""

    def __init__(self, reply: str | None = None, error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_content: str) -> str:
        self.calls.append((system_prompt, user_content))
        if self.error is not None:
            raise self.error
        assert self.reply is not None
        return self.reply


# --------------------------------------------------------------------------- #
# Migration v13
# --------------------------------------------------------------------------- #


def test_latest_version_is_14():
    assert LATEST_VERSION == 14


def test_migration_v13_creates_tables_and_indexes(tmp_path):
    path = str(tmp_path / "v13.db")
    applied = migrate(path)
    assert applied == list(range(1, LATEST_VERSION + 1))
    # Idempotent: a second run applies nothing.
    assert migrate(path) == []
    assert applied_versions(path) == list(range(1, LATEST_VERSION + 1))
    conn = sqlite3.connect(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"kv_employers", "kv_listings", "kv_listing_reports"} <= tables
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "idx_kv_employers_user",
        "idx_kv_employers_status",
        "idx_kv_listings_employer",
        "idx_kv_listings_status",
        "idx_kv_listings_city",
        "idx_kv_listings_sample",
        "idx_kv_listing_reports_listing",
        "idx_kv_listing_reports_status",
    } <= indexes
    conn.close()


# --------------------------------------------------------------------------- #
# Employer store: employers
# --------------------------------------------------------------------------- #


def test_create_employer_pending_and_unique(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    assert employer.status == "pending"
    assert employer.state == "Tamil Nadu"
    assert store.get_employer_by_user("u-emp").id == employer.id
    with pytest.raises(ValueError, match="already has an employer profile"):
        _employer(store)


def test_employer_status_machine(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    # pending -> verified -> flagged -> verified is legal.
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    assert store.get_employer(employer.id).status == "verified"
    store.set_employer_status(employer.id, "flagged", reviewer="admin")
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    # verified -> pending is illegal; rejected -> pending is the re-apply path.
    with pytest.raises(ValueError, match="Cannot move employer"):
        store.set_employer_status(employer.id, "pending", reviewer="admin")
    store.set_employer_status(employer.id, "rejected", reviewer="admin")
    store.set_employer_status(employer.id, "pending", reviewer="admin")
    with pytest.raises(ValueError, match="Unknown employer status"):
        store.set_employer_status(employer.id, "bogus", reviewer="admin")
    with pytest.raises(ValueError, match="Unknown employer"):
        store.set_employer_status(999, "verified", reviewer="admin")


def test_employer_edit_resets_verified_to_pending(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    updated = store.update_employer(employer.id, city="Salem")
    assert updated.city == "Salem"
    assert updated.status == "pending"
    assert "re-review" in updated.review_note


def test_endorsement_badge(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    assert employer.endorsed is False
    endorsed = store.set_endorsement(
        employer.id, "Govt ITI Madurai", "iti", "Verified training partner."
    )
    assert endorsed.endorsed is True
    assert endorsed.to_dict()["endorsed"] is True
    cleared = store.set_endorsement(employer.id, "", "")
    assert cleared.endorsed is False


def test_delete_employer(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    assert store.delete_employer(employer.id) is True
    assert store.get_employer(employer.id) is None
    assert store.delete_employer(employer.id) is False


# --------------------------------------------------------------------------- #
# Employer store: listings
# --------------------------------------------------------------------------- #


def test_create_listing_and_public_visibility(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    listing = store.create_listing(employer.id, **_listing())
    assert listing.status == "pending"
    assert store.list_public_listings() == []
    # Verify is blocked while the employer is unverified.
    with pytest.raises(ValueError, match="employer is verified"):
        store.set_listing_status(listing.id, "verified", reviewer="admin")
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    store.set_listing_status(listing.id, "verified", reviewer="admin")
    public = store.list_public_listings()
    assert [item.id for item in public] == [listing.id]
    # The public shape hides review internals but keeps the sample label.
    assert "review_note" not in public[0].public_dict()
    assert public[0].public_dict()["is_sample"] is False


def test_rejected_employer_cannot_list(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    store.set_employer_status(employer.id, "rejected", reviewer="admin")
    with pytest.raises(ValueError, match="rejected employer cannot create listings"):
        store.create_listing(employer.id, **_listing())
    with pytest.raises(ValueError, match="Unknown employer"):
        store.create_listing(999, **_listing())


def test_listing_status_machine(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    listing = store.create_listing(employer.id, **_listing())
    with pytest.raises(ValueError, match="Cannot move listing"):
        store.set_listing_status(listing.id, "pending", reviewer="admin")
    store.set_listing_status(listing.id, "flagged", reviewer="admin")
    store.set_listing_status(listing.id, "pending", reviewer="admin")
    store.set_listing_status(listing.id, "rejected", reviewer="admin")
    store.set_listing_status(listing.id, "pending", reviewer="admin")


def test_listing_edit_resets_verified_to_pending(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    listing = store.create_listing(employer.id, **_listing())
    store.set_listing_status(listing.id, "verified", reviewer="admin")
    updated = store.update_listing(listing.id, pay_monthly_max=16000)
    assert updated.status == "pending"


def test_duplicate_detection(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    other = _employer(store, user_id="u-emp2", business_name="Other Shop")
    data = _listing()
    listing = store.create_listing(employer.id, **data)
    desc = data["description"]
    # Same employer, same title (case/space-insensitive), same city,
    # same description: an exact duplicate.
    assert store.find_duplicate(employer.id, "  electrician HELPER ", "Madurai", desc) is not None
    # A reworded title with the same description is a near-duplicate.
    assert (
        store.find_duplicate(employer.id, "Electrician helper needed", "Madurai", desc) is not None
    )
    # Different city, different employer, or excluded id: no match.
    assert store.find_duplicate(employer.id, "Electrician helper", "Salem", desc) is None
    assert store.find_duplicate(other.id, "Electrician helper", "Madurai", desc) is None
    assert (
        store.find_duplicate(
            employer.id, "Electrician helper", "Madurai", desc, exclude_id=listing.id
        )
        is None
    )
    # Step 8.4 behaviour change: the same title with a DIFFERENT
    # description is a new opening reusing a title, not a duplicate.
    assert (
        store.find_duplicate(
            employer.id,
            "Electrician helper",
            "Madurai",
            "Night-shift warehouse packing work. Load and unload trucks.",
        )
        is None
    )


def test_delete_listing_and_sample_counts(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    one = store.create_listing(employer.id, **_listing())
    two = store.create_listing(employer.id, is_sample=True, **_listing(title="Tailor"))
    assert store.count_sample_listings() == 1
    assert store.delete_listing(one.id) is True
    assert store.get_listing(one.id) is None
    assert store.delete_listing(one.id) is False
    assert store.delete_sample_listings() == 1
    assert store.get_listing(two.id) is None
    assert store.count_sample_listings() == 0


# --------------------------------------------------------------------------- #
# Employer store: reports
# --------------------------------------------------------------------------- #


def test_reports_auto_flag_after_three(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    listing = store.create_listing(employer.id, **_listing())
    store.set_listing_status(listing.id, "verified", reviewer="admin")
    for i in range(2):
        _, auto = store.report_listing(listing.id, "fake", f"report {i}")
        assert auto is False
        assert store.get_listing(listing.id).status == "verified"
    _, auto = store.report_listing(listing.id, "fee_demanded", "asked for money")
    assert auto is True
    assert store.get_listing(listing.id).status == "flagged"
    # A fourth report on an already-flagged listing does not re-flag.
    _, auto = store.report_listing(listing.id, "fake")
    assert auto is False
    assert store.count_open_reports(listing.id) == 4


def test_report_review_uphold_and_dismiss(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    listing = store.create_listing(employer.id, **_listing())
    report, _ = store.report_listing(listing.id, "other", "details")
    with pytest.raises(ValueError, match="Unknown report outcome"):
        store.set_report_status(report.id, "bogus")
    reviewed = store.set_report_status(report.id, "dismissed", reviewer="admin")
    assert reviewed.status == "dismissed"
    with pytest.raises(ValueError, match="already dismissed"):
        store.set_report_status(report.id, "upheld", reviewer="admin")
    with pytest.raises(ValueError, match="Unknown report reason"):
        store.report_listing(listing.id, "bogus")
    with pytest.raises(ValueError, match="Unknown listing"):
        store.report_listing(999, "fake")


def test_review_queue_counts(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    listing = store.create_listing(employer.id, **_listing())
    store.report_listing(listing.id, "fake")
    counts = store.review_queue_counts()
    assert counts["employers_pending"] == 1
    assert counts["listings_pending"] == 1
    assert counts["reports_open"] == 1
    assert counts["listings_flagged"] == 0


# --------------------------------------------------------------------------- #
# Scam rules
# --------------------------------------------------------------------------- #


def test_legit_listing_scores_zero():
    score, flags = run_rules(_listing(), {"business_name": "Murugan Electricals"})
    assert score == 0
    assert flags == []


def test_fee_rule_and_no_fee_negation():
    score, flags = run_rules(
        _listing(description="Pay 2000 registration fee to join."),
        {"business_name": "X"},
    )
    assert score >= 45
    assert "fee_demanded" in [f.id for f in flags]
    # "No fee to apply" must NOT fire the fee rule.
    score, flags = run_rules(
        _listing(description="Help with wiring. No fee to apply. We never ask for money."),
        {"business_name": "X"},
    )
    assert "fee_demanded" not in [f.id for f in flags]


def test_advance_and_personal_info_rules():
    _, flags = run_rules(
        _listing(description="Pay 5000 in advance to confirm."),
        {"business_name": "X"},
    )
    assert "advance_payment" in [f.id for f in flags]
    _, flags = run_rules(
        _listing(requirements="Share Aadhaar and OTP to start."),
        {"business_name": "X"},
    )
    assert "personal_info_harvest" in [f.id for f in flags]


def test_whatsapp_only_rule():
    _, flags = run_rules(
        _listing(contact_info="WhatsApp only, message us on Telegram."),
        {"business_name": "X"},
    )
    assert "whatsapp_only" in [f.id for f in flags]
    # WhatsApp plus a real phone number is not WhatsApp-only.
    _, flags = run_rules(
        _listing(contact_info="WhatsApp 98430 12345 or call the shop."),
        {"business_name": "X"},
    )
    assert "whatsapp_only" not in [f.id for f in flags]


def test_urgency_needs_two_signals():
    _, flags = run_rules(_listing(description="Urgent requirement."), {"business_name": "X"})
    assert "urgency_pressure" not in [f.id for f in flags]
    _, flags = run_rules(
        _listing(description="Urgent! Limited seats, apply today only! Immediate joining."),
        {"business_name": "X"},
    )
    assert "urgency_pressure" in [f.id for f in flags]


def test_company_details_vague_and_pay_rules():
    _, flags = run_rules(_listing(contact_info=""), {"business_name": ""})
    assert "no_company_details" in [f.id for f in flags]
    _, flags = run_rules(_listing(description="Work.", requirements=""), {"business_name": "X"})
    assert "vague_job" in [f.id for f in flags]
    _, flags = run_rules(
        _listing(pay_monthly_min=20000, pay_monthly_max=10000), {"business_name": "X"}
    )
    assert "pay_inverted" in [f.id for f in flags]
    _, flags = run_rules(_listing(pay_monthly_min=500), {"business_name": "X"})
    assert "pay_absurd_low" in [f.id for f in flags]
    _, flags = run_rules(_listing(pay_monthly_max=200000), {"business_name": "X"})
    assert "pay_absurd_high" in [f.id for f in flags]
    _, flags = run_rules(_listing(), {"business_name": "X"}, duplicate=True)
    assert "duplicate" in [f.id for f in flags]


def test_fake_listing_scores_at_flag_threshold():
    check = check_listing(_fake_listing(), {"business_name": "Quick Jobs"}, duplicate=False)
    assert check.score >= FLAG_THRESHOLD
    assert check.recommended_status == "flagged"
    assert check.score <= 100
    assert {"fee_demanded", "personal_info_harvest"} <= {f.id for f in check.flags}
    assert check.llm_status == "not_configured"
    assert check.driven_by == "rules"


def test_pay_plausibility_unknown_without_match():
    # Step 8A (L39): the check is wired to the central-sphere wage
    # tables now — the framework-only test is replaced. An
    # electrician listing matches no scheduled employment, so it
    # is still unknown (the verdicts live in test_kv_step8_l39.py).
    result = check_pay_plausibility(_listing())
    assert result["status"] == "unknown"
    assert result["checked_against"] is None
    assert "No central-sphere scheduled employment matches" in result["reason"]


def test_llm_score_paths():
    text = "Data entry work from home."
    # No completer: not configured, score None.
    assert score_with_llm(text, None) == (None, [], "not_configured")
    # A well-formed LLM reply parses.
    good = _MockCompleter(json.dumps({"risk_score": 80, "reasons": ["fee demanded"]}))
    score, reasons, status = score_with_llm(text, good)
    assert (score, reasons, status) == (80, ["fee demanded"], "configured")
    # The LLM can drive the final score above the rules score.
    check = check_listing(_listing(), {"business_name": "X"}, completer=good)
    assert check.score == 80
    assert check.driven_by == "llm"
    assert check.llm_score == 80
    # Garbage, out-of-range and raising completers all degrade to failed.
    assert score_with_llm(text, _MockCompleter("not json"))[2] == "failed"
    assert score_with_llm(text, _MockCompleter(json.dumps({"risk_score": 150})))[2] == "failed"
    assert score_with_llm(text, _MockCompleter(json.dumps({"no_score": 1})))[2] == "failed"
    assert score_with_llm(text, _MockCompleter(error=RuntimeError("boom")))[2] == "failed"
    # A failed LLM leaves the rules score standing.
    check = check_listing(
        _listing(), {"business_name": "X"}, completer=_MockCompleter(error=RuntimeError("boom"))
    )
    assert check.score == check.rules_score
    assert check.llm_status == "failed"


# --------------------------------------------------------------------------- #
# Router: status + registration
# --------------------------------------------------------------------------- #


def test_employers_status(client):
    r = client.get("/api/v1/kv/employers/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["phone_otp"]["firebase_configured"] is False
    assert body["llm_risk_score"]["configured"] is False
    assert body["pay_plausibility"]["status"] == "central_sphere"
    assert body["pay_plausibility"]["employments"] == 7


def test_register_sets_employer_role_and_blocks_second_registration(client):
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/employers/register",
        json={"business_name": "Murugan Electricals", "city": "Madurai"},
    )
    assert r.status_code == 200, r.text
    employer = r.json()["employer"]
    assert employer["status"] == "pending"
    assert employer["business_name"] == "Murugan Electricals"
    me = client.get("/api/v1/auth/me").json()["user"]
    assert me["role"] == "employer"
    # A second registration is refused: the account is now an employer,
    # so the role guard fires first (the store-level 409 duplicate only
    # shows if an admin demotes the account back to "user" first).
    r = client.post(
        "/api/v1/kv/employers/register",
        json={"business_name": "Second Shop", "city": "Madurai"},
    )
    assert r.status_code == 400
    # The employer can read their own profile; a plain user with no
    # profile gets 404 — the UI shows the register form. NOT 403:
    # gating the read on the employer role broke onboarding for
    # fresh users (found by the Stage 5 live check).
    r = client.get("/api/v1/kv/employers/mine")
    assert r.status_code == 200
    assert r.json()["employer"]["phone_verified"] is False
    login(client, "worker@example.com")
    r = client.get("/api/v1/kv/employers/mine")
    assert r.status_code == 404


def test_register_requires_user_role(client):
    login(client, "boss@example.com")  # ADMIN_EMAILS in the fixture
    r = client.post("/api/v1/kv/employers/register", json={"business_name": "Boss Shop"})
    assert r.status_code == 400
    r = client.post("/api/v1/kv/employers/register", json={"business_name": "x"})
    assert r.status_code in (400, 422)


def test_register_requires_login(client):
    r = client.post("/api/v1/kv/employers/register", json={"business_name": "No Auth Shop"})
    assert r.status_code == 401


def test_fresh_user_reads_404_but_actions_stay_role_gated(client):
    """A signed-in user who has not registered yet reads their own
    (nonexistent) profile/listings as 404 — the UI treats that as
    'show the register form'. Employer ACTIONS stay role-gated
    (403), and logged-out reads stay 401. Regression test for the
    onboarding break found by the Stage 5 live check."""
    assert client.get("/api/v1/kv/employers/mine").status_code == 401
    assert client.get("/api/v1/kv/employers/listings").status_code == 401
    login(client, "fresh@example.com")
    assert client.get("/api/v1/kv/employers/mine").status_code == 404
    assert client.get("/api/v1/kv/employers/listings").status_code == 404
    assert client.get("/api/v1/kv/employers/listings/1").status_code == 404
    listing = {"title": "Helper", "description": "Help wanted.", "city": "Madurai"}
    r = client.post("/api/v1/kv/employers/listings/check", json=listing)
    assert r.status_code == 403
    r = client.post("/api/v1/kv/employers/listings", json=listing)
    assert r.status_code == 403
    r = client.put("/api/v1/kv/employers/mine", json={"city": "Madurai"})
    assert r.status_code == 403
    r = client.put("/api/v1/kv/employers/listings/1", json={"title": "Helper 2"})
    assert r.status_code == 403
    r = client.delete("/api/v1/kv/employers/listings/1")
    assert r.status_code == 403
    r = client.post(
        "/api/v1/kv/employers/mine/verify-phone", json={"id_token": "long-enough-dummy-token"}
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Router: full lifecycle (register → list → review → verified → visible)
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


def test_full_lifecycle_register_list_review_visible(client):
    employer = _register_employer(client)
    # Create a listing: pending, scam check attached.
    r = client.post("/api/v1/kv/employers/listings", json=_listing())
    assert r.status_code == 200, r.text
    listing = r.json()["listing"]
    assert listing["status"] == "pending"
    assert r.json()["check"]["score"] == 0
    listing_id = listing["id"]
    # Workers see nothing yet; the detail 404s.
    assert client.get("/api/v1/kv/listings").json()["listings"] == []
    assert client.get(f"/api/v1/kv/listings/{listing_id}").status_code == 404
    # Approving the listing before the employer is verified is a 409.
    login(client, "boss@example.com")
    r = client.post(f"/api/v1/kv/admin/listings/{listing_id}/review", json={"approve": True})
    assert r.status_code == 409
    # Verify the employer, then the listing.
    _admin_review(client, f"/api/v1/kv/admin/employers/{employer['id']}/review")
    _admin_review(client, f"/api/v1/kv/admin/listings/{listing_id}/review")
    # Now workers see it, with the employer name attached.
    public = client.get("/api/v1/kv/listings").json()
    assert public["count"] == 1
    assert public["listings"][0]["employer_name"] == "Murugan Electricals"
    assert public["listings"][0]["employer_endorsed"] is False
    assert public["sample_data"] is False
    detail = client.get(f"/api/v1/kv/listings/{listing_id}").json()["listing"]
    assert detail["title"] == "Electrician helper"
    # Editing a verified listing sends it back to pending (hidden again).
    login(client, "shop@example.com")
    r = client.put(
        f"/api/v1/kv/employers/listings/{listing_id}",
        json={"pay_monthly_max": 16000},
    )
    assert r.status_code == 200, r.text
    assert r.json()["listing"]["status"] == "pending"
    assert client.get("/api/v1/kv/listings").json()["listings"] == []


def test_fake_listing_flagged_on_create(client):
    _register_employer(client)
    r = client.post("/api/v1/kv/employers/listings", json=_fake_listing())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["listing"]["status"] == "flagged"
    assert body["check"]["score"] >= FLAG_THRESHOLD
    assert body["listing"]["risk_score"] == body["check"]["score"]
    # Flagged listings never reach workers.
    assert client.get("/api/v1/kv/listings").json()["listings"] == []


def test_check_preview_endpoint_stores_nothing(client):
    _register_employer(client)
    r = client.post("/api/v1/kv/employers/listings/check", json=_fake_listing())
    assert r.status_code == 200, r.text
    assert r.json()["check"]["score"] >= FLAG_THRESHOLD
    assert client.get("/api/v1/kv/employers/listings").json()["listings"] == []


def test_employer_cannot_touch_others_listings(client):
    _register_employer(client, "shop-a@example.com")
    r = client.post("/api/v1/kv/employers/listings", json=_listing())
    listing_id = r.json()["listing"]["id"]
    _register_employer(client, "shop-b@example.com")
    # Another employer's listing 404s (never 403 — ids must not leak).
    assert client.get(f"/api/v1/kv/employers/listings/{listing_id}").status_code == 404
    assert (
        client.put(
            f"/api/v1/kv/employers/listings/{listing_id}", json={"title": "Hijacked"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/kv/employers/listings/{listing_id}").status_code == 404
    assert client.get("/api/v1/kv/employers/listings").json()["listings"] == []
    # The owner can still delete it.
    login(client, "shop-a@example.com")
    r = client.delete(f"/api/v1/kv/employers/listings/{listing_id}")
    assert r.status_code == 200


def test_create_listing_requires_employer_role(client):
    login(client, "worker@example.com")
    r = client.post("/api/v1/kv/employers/listings", json=_listing())
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Router: admin queue, endorsements, reports
# --------------------------------------------------------------------------- #


def test_admin_queue_and_endorsement(client):
    employer = _register_employer(client)
    r = client.post("/api/v1/kv/employers/listings", json=_listing())
    listing_id = r.json()["listing"]["id"]
    # Non-admins cannot see the queue.
    r = client.get("/api/v1/kv/admin/review-queue")
    assert r.status_code == 403
    login(client, "boss@example.com")
    queue = client.get("/api/v1/kv/admin/review-queue").json()
    assert queue["counts"]["employers_pending"] == 1
    assert queue["counts"]["listings_pending"] == 1
    assert [e["id"] for e in queue["employers"]] == [employer["id"]]
    assert [item["id"] for item in queue["listings"]] == [listing_id]
    # Endorsement badge on, then cleared.
    r = client.post(
        f"/api/v1/kv/admin/employers/{employer['id']}/endorse",
        json={"endorsed_by": "Govt ITI Madurai", "endorsed_by_type": "iti"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["employer"]["endorsed"] is True
    r = client.post(
        f"/api/v1/kv/admin/employers/{employer['id']}/endorse",
        json={"endorsed_by": "", "endorsed_by_type": ""},
    )
    assert r.json()["employer"]["endorsed"] is False
    # Rejecting the employer, then re-reviewing to pending (re-apply path).
    r = client.post(
        f"/api/v1/kv/admin/employers/{employer['id']}/review",
        json={"approve": False, "note": "No business proof."},
    )
    assert r.json()["employer"]["status"] == "rejected"
    # A rejected employer's listing cannot be verified.
    r = client.post(f"/api/v1/kv/admin/listings/{listing_id}/review", json={"approve": True})
    assert r.status_code == 409


def test_reports_auto_flag_and_admin_review(client):
    employer = _register_employer(client)
    r = client.post("/api/v1/kv/employers/listings", json=_listing())
    listing_id = r.json()["listing"]["id"]
    _admin_review(client, f"/api/v1/kv/admin/employers/{employer['id']}/review")
    _admin_review(client, f"/api/v1/kv/admin/listings/{listing_id}/review")
    assert client.get("/api/v1/kv/listings").json()["count"] == 1
    # Guests can report (no login needed).
    guest = TestClient(client.app)
    for i in range(3):
        r = guest.post(
            f"/api/v1/kv/listings/{listing_id}/report",
            json={"reason": "fake", "details": f"report {i}"},
        )
        assert r.status_code == 200, r.text
    assert r.json()["auto_flagged"] is True
    assert client.get("/api/v1/kv/listings").json()["listings"] == []
    # Bad reason / unknown listing.
    assert (
        guest.post(f"/api/v1/kv/listings/{listing_id}/report", json={"reason": "bogus"}).status_code
        == 400
    )
    assert (
        guest.post("/api/v1/kv/listings/99999/report", json={"reason": "fake"}).status_code == 404
    )
    # Admin sees the reports and can dismiss one; re-reviewing it is a 409.
    login(client, "boss@example.com")
    reports = client.get("/api/v1/kv/admin/reports?status=open").json()["reports"]
    assert len(reports) == 3
    r = client.post(
        f"/api/v1/kv/admin/reports/{reports[0]['id']}/review",
        json={"action": "dismiss", "note": "Not substantiated."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["report"]["status"] == "dismissed"
    r = client.post(
        f"/api/v1/kv/admin/reports/{reports[0]['id']}/review",
        json={"action": "dismiss"},
    )
    assert r.status_code == 409
    r = client.post(
        f"/api/v1/kv/admin/reports/{reports[1]['id']}/review",
        json={"action": "bogus"},
    )
    assert r.status_code == 400


def test_report_uphold_flags_verified_listing(client):
    employer = _register_employer(client)
    r = client.post("/api/v1/kv/employers/listings", json=_listing())
    listing_id = r.json()["listing"]["id"]
    _admin_review(client, f"/api/v1/kv/admin/employers/{employer['id']}/review")
    _admin_review(client, f"/api/v1/kv/admin/listings/{listing_id}/review")
    guest = TestClient(client.app)
    r = guest.post(
        f"/api/v1/kv/listings/{listing_id}/report",
        json={"reason": "fee_demanded", "details": "They asked for money."},
    )
    report_id = r.json()["report"]["id"]
    assert r.json()["auto_flagged"] is False  # only one report
    login(client, "boss@example.com")
    r = client.post(
        f"/api/v1/kv/admin/reports/{report_id}/review",
        json={"action": "uphold", "note": "Fee demand confirmed."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["report"]["status"] == "upheld"
    assert r.json()["listing"]["status"] == "flagged"
    assert client.get("/api/v1/kv/listings").json()["listings"] == []


# --------------------------------------------------------------------------- #
# Router: phone verification
# --------------------------------------------------------------------------- #


def test_verify_phone_503_when_firebase_not_configured(client):
    _register_employer(client)
    r = client.post("/api/v1/kv/employers/mine/verify-phone", json={"id_token": "any-token-here"})
    assert r.status_code == 503


class _StubFirebase:
    """A FirebaseVerifier stand-in: enabled, returns fixed claims."""

    enabled = True

    def __init__(self, claims=None, error=None):
        self.claims = claims or {}
        self.error = error

    def verify(self, id_token):
        if self.error is not None:
            raise self.error
        return dict(self.claims)


def test_verify_phone_with_stubbed_firebase(app_module, monkeypatch):
    import backend.main as main

    claims = {"email": "shop@example.com", "email_verified": True, "phone_number": "+919876543210"}
    monkeypatch.setattr(main._auth, "firebase", _StubFirebase(claims))
    with TestClient(main.app) as c:
        _register_employer(c)
        r = c.post("/api/v1/kv/employers/mine/verify-phone", json={"id_token": "stub-token"})
        assert r.status_code == 200, r.text
        assert r.json()["phone_e164"] == "+919876543210"
        assert r.json()["phone_verified"] is True
        mine = c.get("/api/v1/kv/employers/mine").json()["employer"]
        assert mine["phone_verified"] is True
        assert mine["phone_e164"] == "+919876543210"


def test_verify_phone_rejects_wrong_account_and_missing_phone(app_module, monkeypatch):
    import backend.main as main

    with TestClient(main.app) as c:
        _register_employer(c)
        # Token for a different account.
        monkeypatch.setattr(
            main._auth,
            "firebase",
            _StubFirebase({"email": "someone-else@example.com", "phone_number": "+911111111111"}),
        )
        r = c.post("/api/v1/kv/employers/mine/verify-phone", json={"id_token": "stub-token"})
        assert r.status_code == 400
        # Token with no phone number.
        claims = {"email": "shop@example.com", "email_verified": True}
        monkeypatch.setattr(main._auth, "firebase", _StubFirebase(claims))
        r = c.post("/api/v1/kv/employers/mine/verify-phone", json={"id_token": "stub-token"})
        assert r.status_code == 400
        # Token whose e-mail Firebase has not verified (claim match is
        # not a verified-identity match).
        claims = {
            "email": "shop@example.com",
            "email_verified": False,
            "phone_number": "+919876543210",
        }
        monkeypatch.setattr(main._auth, "firebase", _StubFirebase(claims))
        r = c.post("/api/v1/kv/employers/mine/verify-phone", json={"id_token": "stub-token"})
        assert r.status_code == 400
        # Token that fails verification.
        monkeypatch.setattr(main._auth, "firebase", _StubFirebase(error=ValueError("bad token")))
        r = c.post("/api/v1/kv/employers/mine/verify-phone", json={"id_token": "stub-token"})
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Router: flag off
# --------------------------------------------------------------------------- #


@pytest.fixture()
def app_module_kv_employers_off(tmp_path, monkeypatch):
    """backend.main reloaded with KV_EMPLOYERS=false (dev otherwise)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_EMPLOYERS", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_employers_routes_404_when_flag_off(app_module_kv_employers_off):
    with TestClient(app_module_kv_employers_off.app) as c:
        assert c.get("/api/v1/kv/employers/status").status_code == 404
        assert c.get("/api/v1/kv/listings").status_code == 404
        # The rest of the app is unaffected by the flag being off.
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/api/v1/kv/voice/status").status_code == 200


# --------------------------------------------------------------------------- #
# Seed script
# --------------------------------------------------------------------------- #


def test_seed_script_loads_and_flags_fakes(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    db_path = str(tmp_path / "seed.db")
    script = str(root / "scripts" / "seed_kv_listings.py")
    result = subprocess.run(
        [sys.executable, script, "--db", db_path],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    store = EmployerStore(db_path)
    assert len(store.list_employers()) == 7
    assert store.count_sample_listings() == 45
    assert len(store.list_public_listings()) == 37
    assert len(store.list_listings(status="pending")) == 3
    flagged = store.list_listings(status="flagged")
    assert len(flagged) == 5
    assert all(item.risk_score >= FLAG_THRESHOLD for item in flagged)
    assert all(item.is_sample for item in store.list_listings())
    # Idempotent: a second run changes nothing.
    result = subprocess.run(
        [sys.executable, script, "--db", db_path],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=120,
    )
    assert result.returncode == 0
    assert "Already seeded" in result.stdout
    assert store.count_sample_listings() == 45
    # --force re-seeds cleanly (same counts, no duplicates).
    result = subprocess.run(
        [sys.executable, script, "--db", db_path, "--force"],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(store.list_employers()) == 7
    assert store.count_sample_listings() == 45
