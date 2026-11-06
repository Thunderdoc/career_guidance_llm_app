"""Phase 5 core tests: migration v7, age declaration, consent store /
provider, notice-version invalidation, minor rules, delete + export."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import career_guidance.consent as consent
from career_guidance.consent import (
    ConsentStore,
    ManualEmailConsentProvider,
    derive_is_minor,
    is_unconsented_minor,
    restrictions_for,
    validate_age_declaration,
)
from career_guidance.journey import JourneyStore
from career_guidance.migrations import applied_versions, migrate
from career_guidance.users import UserStore
from career_guidance.verify import VerificationStore


def _user(store: UserStore, email: str = "kid@example.com") -> str:
    return store.upsert_login(email, "magic-link", "Kid").id


# ------------------------------------------------------------------ migrations
def test_migration_v7_applies_and_is_idempotent(tmp_path):
    path = str(tmp_path / "fresh.db")
    assert migrate(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert migrate(path) == []
    assert applied_versions(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert "consent_records" in tables
    assert {"age_band", "birth_year"} <= cols


def test_migration_v6_to_v7_preserves_users(tmp_path, monkeypatch):
    """Industry-Ready §6.3: a Phase-4-era (v6) DB upgrades in place."""
    import career_guidance.migrations as migrations

    path = str(tmp_path / "v6.db")
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:6])
    assert migrate(path) == [1, 2, 3, 4, 5, 6]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO users (id, email, name, picture, provider, role, created_at,"
            " last_login_at, handle, is_minor) VALUES ('u-old', 'old@example.com', 'Old', '',"
            " 'magic-link', 'user', '2026-11-01T00:00:00+00:00',"
            " '2026-11-01T00:00:00+00:00', 'old-user', 1)"
        )
    monkeypatch.undo()
    assert migrate(path) == [7, 8, 9, 10]
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT email, handle, is_minor, age_band, birth_year FROM users WHERE id='u-old'"
        ).fetchone()
    assert row == ("old@example.com", "old-user", 1, "", None)  # data intact, safe defaults
    assert migrate(path) == []


# ------------------------------------------------------------- age declaration
@pytest.mark.parametrize(
    "band,year,expected",
    [
        ("adult", None, False),
        ("minor", None, True),
        ("", 2015, True),  # year alone implies under-18
        ("", 1990, False),
        ("adult", 2015, True),  # fail-safe: a young birth year wins over the band
        ("minor", 1990, True),  # the band itself says minor
        ("", None, False),
    ],
)
def test_derive_is_minor(band, year, expected):
    assert derive_is_minor(band, year) is expected


def test_validate_age_declaration_rejects_bad_input():
    with pytest.raises(ValueError):
        validate_age_declaration("teen")
    with pytest.raises(ValueError):
        validate_age_declaration("", 1800)
    with pytest.raises(ValueError):
        validate_age_declaration("", datetime.now(timezone.utc).year + 1)
    with pytest.raises(ValueError):
        validate_age_declaration("", None)
    assert validate_age_declaration(" Minor ", None) == ("minor", None)


def test_user_store_age_declaration_roundtrip(tmp_path):
    store = UserStore(str(tmp_path / "u.db"))
    uid = _user(store)
    updated = store.set_age_declaration(uid, "minor", 2013)
    assert updated.is_minor and updated.age_band == "minor" and updated.birth_year == 2013
    updated = store.set_age_declaration(uid, "adult", 2000)
    assert not updated.is_minor and updated.age_band == "adult"


# ---------------------------------------------------------------- consent flow
def test_consent_store_grant_flow_and_token_single_use(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    record, token = store.create_request("u1", "Mum@Example.com")
    assert record.status == "pending" and record.guardian_email == "mum@example.com"
    assert store.effective_status("u1") == "pending"
    decided = store.decide(token, True)
    assert decided.status == "granted" and decided.decided_at
    assert store.has_granted_consent("u1")
    # The decision token is cleared: deciding again is an error, not a flip.
    with pytest.raises(ValueError, match="unknown_token"):
        store.decide(token, False)
    with pytest.raises(ValueError, match="unknown_token"):
        store.decide("not-a-token", True)


def test_consent_store_deny_and_revoke(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    _, token = store.create_request("u1", "mum@example.com")
    assert store.decide(token, False).status == "denied"
    assert not store.has_granted_consent("u1")
    _, token2 = store.create_request("u1", "mum@example.com")
    store.decide(token2, True)
    assert store.has_granted_consent("u1")
    store.revoke("u1")
    assert store.effective_status("u1") == "revoked"
    assert not store.has_granted_consent("u1")


def test_consent_new_request_supersedes_pending(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    _, old = store.create_request("u1", "a@example.com")
    _, new = store.create_request("u1", "b@example.com")
    with pytest.raises(ValueError):  # old token's record is no longer pending
        store.decide(old, True)
    assert store.decide(new, True).status == "granted"


def test_consent_token_expiry_72h(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    record, token = store.create_request("u1", "mum@example.com", ttl_hours=72)
    expires = datetime.fromisoformat(record.token_expires_at)
    requested = datetime.fromisoformat(record.requested_at)
    assert expires - requested == timedelta(hours=72)
    _, stale = store.create_request("u2", "mum@example.com", ttl_hours=-1)
    with pytest.raises(ValueError, match="expired_token"):
        store.decide(stale, True)


def test_notice_version_bump_forces_reconsent(tmp_path, monkeypatch):
    store = ConsentStore(str(tmp_path / "c.db"))
    _, token = store.create_request("u1", "mum@example.com")
    store.decide(token, True)
    assert store.effective_status("u1") == "granted"
    monkeypatch.setattr(consent, "NOTICE_VERSION", "2027-01-v2")
    assert store.effective_status("u1") == "needs_reconsent"
    assert not store.has_granted_consent("u1")
    record = store.latest("u1")
    assert record.status == "granted"  # stored status untouched; computed only
    assert record.effective_status == "needs_reconsent"


def test_consent_record_rejects_bad_guardian_email(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    with pytest.raises(ValueError):
        store.create_request("u1", "not-an-email")


class _StubNotifier:
    def __init__(self):
        self.sent = []

    def send(self, user, subject, body):
        self.sent.append((user, subject, body))
        return True


def test_manual_email_provider_flow(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    notifier = _StubNotifier()
    provider = ManualEmailConsentProvider(store, base_url="http://testserver", notifier=notifier)
    payload = provider.request_consent({"id": "u1", "email": "kid@example.com"}, "mum@example.com")
    assert payload["status"] == "pending" and payload["delivered"] is True
    assert "dev_link" not in payload
    assert len(notifier.sent) == 1 and notifier.sent[0][0]["email"] == "mum@example.com"
    body = notifier.sent[0][2]
    assert "/api/v1/consent/confirm/" in body and "decision=grant" in body
    # Extract the token from the e-mailed link and confirm through the provider.
    link = [w for w in body.split() if "/consent/confirm/" in w][0]
    token = link.split("/consent/confirm/")[1].split("?")[0]
    assert provider.confirm(token, True).status == "granted"


def test_provider_log_fallback_surfaces_dev_link(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))

    class _Dead:
        def send(self, user, subject, body):
            return False

    provider = ManualEmailConsentProvider(store, notifier=_Dead())
    payload = provider.request_consent({"id": "u1", "email": "k@example.com"}, "mum@example.com")
    assert payload["delivered"] is False and payload["dev_link"].startswith("/api/v1/consent/")


def test_guardian_revoke_via_action_token(tmp_path):
    store = ConsentStore(str(tmp_path / "c.db"))
    _, token = store.create_request("u1", "mum@example.com")
    store.decide(token, True)
    action = store.issue_action_token("u1")
    assert store.revoke_by_token(action).status == "revoked"


# ------------------------------------------------------------------ rules
def test_restrictions_for_minor_adult_and_consented(tmp_path):
    path = str(tmp_path / "r.db")
    users = UserStore(path)
    consents = ConsentStore(path)
    minor_id = _user(users, "kid@example.com")
    users.set_age_declaration(minor_id, "minor", 2014)
    minor = users.get(minor_id)
    rules = restrictions_for(minor, consents)
    assert rules["restricted"] is True
    assert rules["core_guidance_allowed"] is True
    assert rules["public_profile_allowed"] is False
    assert rules["behavioural_analytics_allowed"] is False
    assert rules["streak_nudges_allowed"] is False
    assert rules["needs_attention_individual_allowed"] is False
    assert is_unconsented_minor(minor, consents) is True

    _, token = consents.create_request(minor_id, "mum@example.com")
    consents.decide(token, True)
    rules = restrictions_for(minor, consents)
    assert rules["restricted"] is False
    assert rules["behavioural_analytics_allowed"] is True
    assert rules["public_profile_allowed"] is False  # minors: always off (Phase 3)

    adult_id = _user(users, "adult@example.com")
    users.set_age_declaration(adult_id, "adult", 1999)
    rules = restrictions_for(users.get(adult_id), consents)
    assert rules["restricted"] is False and rules["public_profile_allowed"] is True


# ------------------------------------------------------- delete / export (store)
def test_delete_user_removes_all_personal_data(tmp_path):
    path = str(tmp_path / "d.db")
    users = UserStore(path)
    uid = _user(users, "gone@example.com")
    other = _user(users, "stays@example.com")
    journey = JourneyStore(path)
    verif = VerificationStore(path)
    consents = ConsentStore(path)

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO recommendation_runs (created_at, provider, is_demo, profile_json,"
            " recommendations_json, user_id) VALUES ('2026-11-01', 'offline', 0, '{}', '[]', ?)",
            (uid,),
        )
        run_id = conn.execute("SELECT MAX(id) FROM recommendation_runs").fetchone()[0]
        conn.execute(
            "INSERT INTO run_reviews (run_id, reviewer_id, note, created_at)"
            " VALUES (?, ?, 'seen', '2026-11-01')",
            (run_id, other),
        )
        conn.execute(
            "INSERT INTO skill_projects (user_id, skill, title, link, description,"
            " checklist_json, self_reported, created_at) VALUES (?, 'python', 'Proj',"
            " 'https://example.com', '', '[]', 1, '2026-11-01')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO plans_90day (user_id, run_id, created_at, hours_per_week, plan_json)"
            " VALUES (?, NULL, '2026-11-01', 6, '{}')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO payments (user_id, provider_order_id, amount_paise, created_at,"
            " updated_at) VALUES (?, 'order_x', 100, '2026-11-01', '2026-11-01')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO tool_events (created_at, user_id, tool) VALUES ('2026-11-01', ?, 'recommend')",  # noqa: E501
            (uid,),
        )
        conn.execute(
            "INSERT INTO feedback (created_at, user_id, career_title, rating)"
            " VALUES ('2026-11-01', ?, 'Analyst', 5)",
            (uid,),
        )
    verif.get(uid, "python")  # creates nothing; submit a real project row instead
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO skill_verifications (user_id, skill, status, source, updated_at)"
            " VALUES (?, 'python', 'verified', 'quiz', '2026-11-01')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO quiz_attempts (user_id, skill, score_percent, passed, created_at)"
            " VALUES (?, 'python', 90, 1, '2026-11-01')",
            (uid,),
        )
    consents.create_request(uid, "guardian@example.com")
    users.audit("gone@example.com", "profile:update", "profile")
    users.create_magic_link("gone@example.com")

    users.delete_user(uid)

    with sqlite3.connect(path) as conn:

        def count(sql, params=(uid,)):
            return conn.execute(sql, params).fetchone()[0]

        assert count("SELECT COUNT(*) FROM users WHERE id = ?") == 0
        for table in (
            "recommendation_runs",
            "skill_verifications",
            "quiz_attempts",
            "skill_projects",
            "plans_90day",
            "payments",
            "tool_events",
            "consent_records",
        ):
            assert count(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?") == 0, table
        assert count("SELECT COUNT(*) FROM run_reviews WHERE reviewer_id = ?", (other,)) == 0
        # Feedback is anonymised, not deleted (rating is product data).
        row = conn.execute("SELECT user_id, rating FROM feedback").fetchone()
        assert row == (None, 5)
        # Audit keeps the action, loses the e-mail.
        actors = [r[0] for r in conn.execute("SELECT actor FROM audit_log")]
        assert "gone@example.com" not in actors
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM magic_links WHERE email = 'gone@example.com'"
            ).fetchone()[0]
            == 0
        )
    # The other user is untouched.
    assert users.get(other) is not None
    assert journey.export_user(other)["runs"] == []


def test_export_user_includes_phase5_sections(tmp_path):
    path = str(tmp_path / "e.db")
    users = UserStore(path)
    uid = _user(users, "me@example.com")
    journey = JourneyStore(path)
    consents = ConsentStore(path)
    consents.create_request(uid, "guardian@example.com")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO skill_verifications (user_id, skill, status, source, updated_at)"
            " VALUES (?, 'python', 'verified', 'quiz', '2026-11-01')",
            (uid,),
        )
    payload = journey.export_user(uid)
    assert payload["skill_verifications"][0]["skill"] == "python"
    assert payload["consent_records"][0]["guardian_email"] == "guardian@example.com"
    assert "token_hash" not in payload["consent_records"][0]  # credential, not data
    for key in ("plans_90day", "quiz_attempts", "skill_projects", "payments"):
        assert key in payload
