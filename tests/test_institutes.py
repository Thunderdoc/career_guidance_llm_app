"""Phase 4 core tests: migration v6, InstituteStore, CSV parsing, cohort."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from career_guidance.institutes import (
    DEFAULT_SEAT_LIMIT,
    InstituteStore,
    cohort_csv,
    cohort_pdf,
    compute_cohort,
    parse_invite_csv,
)
from career_guidance.migrations import applied_versions, migrate
from career_guidance.models import CareerRecommendation
from career_guidance.storage import Database
from career_guidance.users import UserStore


def _users(path: str) -> UserStore:
    migrate(path)
    return UserStore(path)


def _mk_user(store: UserStore, email: str, name: str = "User") -> str:
    return store.upsert_login(email, "magic-link", name).id


# ------------------------------------------------------------------ migrations
def test_migration_v6_applies_and_is_idempotent(tmp_path):
    path = str(tmp_path / "fresh.db")
    assert migrate(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert migrate(path) == []
    assert applied_versions(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"institutes", "institute_invites", "run_reviews"} <= tables
    assert {"institute_id", "institute_role"} <= cols


def test_migration_v5_to_v6_preserves_users(tmp_path, monkeypatch):
    """Upgrading a Phase-3-era (v5) DB adds Phase 4 tables, keeps data."""
    import career_guidance.migrations as migrations

    path = str(tmp_path / "v5.db")
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:5])
    assert migrate(path) == [1, 2, 3, 4, 5]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO users (id, email, name, picture, provider, role, created_at,"
            " last_login_at, handle) VALUES ('u-old', 'old@example.com', 'Old', '',"
            " 'magic-link', 'user', '2026-11-01T00:00:00+00:00',"
            " '2026-11-01T00:00:00+00:00', 'old-user')"
        )
    monkeypatch.undo()
    assert migrate(path) == [6, 7, 8, 9, 10]
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT email, handle, institute_id, institute_role FROM users WHERE id='u-old'"
        ).fetchone()
    assert row == ("old@example.com", "old-user", None, "")
    assert migrate(path) == []


# ------------------------------------------------------------------ store
def test_create_institute_slug_unique_and_branding(tmp_path):
    store = InstituteStore(str(tmp_path / "a.db"))
    a = store.create_institute("Demo College!", "u1", accent_color="#112233")
    b = store.create_institute("Demo College", "u2")
    assert a["slug"] == "demo-college" and b["slug"] == "demo-college-2"
    assert a["seat_limit"] == DEFAULT_SEAT_LIMIT and a["plan"] == "institute"
    with pytest.raises(ValueError):
        store.create_institute("X College", "u1", accent_color="red")
    updated = store.update_branding(a["id"], logo_url="https://x/logo.png")
    assert updated["logo_url"] == "https://x/logo.png"


def test_membership_one_institute_only(tmp_path):
    path = str(tmp_path / "a.db")
    users, store = _users(path), InstituteStore(path)
    uid = _mk_user(users, "a@example.com")
    one = store.create_institute("One College", uid)
    two = store.create_institute("Two College", uid)
    store.set_membership(uid, one["id"], "institute_admin")
    assert store.membership_of(uid)["institute_role"] == "institute_admin"
    with pytest.raises(ValueError):
        store.set_membership(uid, two["id"], "student")
    # The User record exposes the membership without touching global role.
    user = users.get(uid)
    assert user.institute_id == one["id"] and user.role == "user"
    store.clear_membership(uid)
    assert store.membership_of(uid) is None


def test_process_invites_report_and_seats(tmp_path):
    path = str(tmp_path / "a.db")
    users, store = _users(path), InstituteStore(path)
    admin_id = _mk_user(users, "admin@example.com")
    member_id = _mk_user(users, "member@example.com")
    inst = store.create_institute("Seat College", admin_id, seat_limit=3)
    store.set_membership(admin_id, inst["id"], "institute_admin")
    report = store.process_invites(
        inst["id"],
        [
            {"email": "member@example.com", "role": "student"},
            {"email": "ghost@example.com", "role": "counsellor"},
            {"email": "member@example.com", "role": "student"},
            {"email": "bad-email", "role": "student"},
            {"email": "extra@example.com", "role": "student"},
            {"email": "over@example.com", "role": "student"},
        ],
    )
    statuses = [(r["email"], r["status"]) for r in report["results"]]
    assert statuses[0] == ("member@example.com", "invited")
    assert statuses[1] == ("ghost@example.com", "pending")  # reserves a seat
    assert statuses[2][1] == "error" and "Duplicate" in report["results"][2]["error"]
    assert statuses[3][1] == "error"
    # admin(1) + member(1) + pending(1) = seat limit 3 → both later rows fail
    assert statuses[4][1] == "error" and "Seat limit" in report["results"][4]["error"]
    assert store.membership_of(member_id)["institute_role"] == "student"
    assert store.seat_usage(inst["id"])["seats_available"] == 0


def test_claim_pending_invite(tmp_path):
    path = str(tmp_path / "a.db")
    users, store = _users(path), InstituteStore(path)
    admin_id = _mk_user(users, "admin@example.com")
    inst = store.create_institute("Claim College", admin_id)
    store.set_membership(admin_id, inst["id"], "institute_admin")
    store.process_invites(inst["id"], [{"email": "new@example.com", "role": "counsellor"}])
    uid = _mk_user(users, "new@example.com")
    claimed = store.claim_invites(uid, "new@example.com")
    assert claimed["institute_role"] == "counsellor"
    assert store.membership_of(uid)["institute_id"] == inst["id"]
    assert store.claim_invites(uid, "nobody@example.com") is None


# ------------------------------------------------------------------ CSV
def test_parse_invite_csv_valid_and_row_errors():
    rows, errors = parse_invite_csv(
        b"email,name,role\na@b.com,Ada,student\nbad,Bob,student\nc@d.com,,wizard\n\n"
    )
    assert [r["email"] for r in rows] == ["a@b.com"] and rows[0]["_line"] == 2
    assert {e["row"] for e in errors} == {3, 4}


def test_parse_invite_csv_whole_file_errors():
    with pytest.raises(ValueError):
        parse_invite_csv(b"name,role\nAda,student\n")  # no email column
    with pytest.raises(ValueError):
        parse_invite_csv(b"email\n" + b"x" * (5 * 1024 * 1024))
    with pytest.raises(ValueError):
        parse_invite_csv(b"email\n" + b"a@b.com\n" * 501)
    with pytest.raises(ValueError):
        parse_invite_csv(b"\xff\xfe invalid")


# ------------------------------------------------------------------ cohort
def _run(db: Database, user_id: str, title: str, score: float, missing: list[str], when=None):
    rid = db.save_run(
        {"skills": "python"},
        [
            CareerRecommendation(
                title=title,
                match_reason="fit",
                suitability="beginner",
                missing_skills=missing,
                match_score=score,
            )
        ],
        "offline",
        False,
        user_id,
    )
    if when is not None:
        with sqlite3.connect(db._path) as conn:
            conn.execute("UPDATE recommendation_runs SET created_at=? WHERE id=?", (when, rid))
    return rid


def test_compute_cohort_aggregation_and_attention(tmp_path):
    path = str(tmp_path / "a.db")
    users, store, db = _users(path), InstituteStore(path), Database(path)
    admin_id = _mk_user(users, "admin@example.com")
    inst = store.create_institute("Cohort College", admin_id)
    store.set_membership(admin_id, inst["id"], "institute_admin")
    ids = {}
    for email, name in (("s1@example.com", "S One"), ("s2@example.com", "S Two")):
        ids[email] = _mk_user(users, email, name)
        store.set_membership(ids[email], inst["id"], "student")
    now = datetime.now(timezone.utc)
    _run(db, ids["s1@example.com"], "Data Analyst", 0.9, ["SQL", "Excel"])
    old = (now - timedelta(days=40)).isoformat(timespec="seconds")
    _run(db, ids["s2@example.com"], "Data Analyst", 0.4, ["sql"], when=old)
    cohort = compute_cohort(store.members(inst["id"]), db.list_runs(limit=100), now=now)
    assert cohort["member_count"] == 3 and cohort["student_count"] == 2
    assert cohort["runs_count"] == 2
    assert cohort["top_recommended_careers"] == [{"title": "Data Analyst", "count": 2}]
    assert cohort["most_missing_skills"][0] == {"skill": "sql", "count": 2}
    buckets = {b["bucket"]: b["count"] for b in cohort["readiness_distribution"]}
    assert buckets == {"0-49": 1, "50-69": 0, "70-84": 0, "85-100": 1}
    attention = {a["user_id"]: a for a in cohort["needs_attention"]}
    assert ids["s1@example.com"] not in attention
    assert set(attention[ids["s2@example.com"]]["reasons"]) == {
        "no_run_in_30_days",
        "low_top_match",
    }
    assert "example.com" not in str(cohort)  # no e-mails anywhere in cohort


def test_cohort_exports_are_aggregate_only(tmp_path):
    cohort = {
        "member_count": 3,
        "student_count": 2,
        "runs_count": 2,
        "top_recommended_careers": [{"title": "Data Analyst", "count": 2}],
        "most_missing_skills": [{"skill": "sql", "count": 2}],
        "readiness_distribution": [{"bucket": "85-100", "count": 1}],
        "needs_attention": [{"user_id": "u1", "name": "Secret Name"}],
    }
    text = cohort_csv(cohort, {"name": "Demo College"})
    assert "Data Analyst" in text and "Secret Name" not in text and "u1" not in text
    pdf = cohort_pdf(
        cohort,
        {"name": "Demo College", "accent_color": "#112233", "logo_url": "https://x/logo.png"},
    )
    assert pdf.startswith(b"%PDF") and len(pdf) > 500


def test_run_review_payload_label(tmp_path):
    store = InstituteStore(str(tmp_path / "a.db"))
    payload = store.add_review(7, "c1", "counsellor", "Good progress.", True)
    assert payload["label"] == "Reviewed by counsellor"
    assert payload["reviewed"] is True and payload["approved"] is True
    assert store.review_for_run(7)["note"] == "Good progress."
    assert store.reviewed_run_ids([7, 8]) == {7}
