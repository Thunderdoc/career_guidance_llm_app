"""Live Postgres parity tests for the legacy-store port (queue item 7).

Every test runs against BOTH engines: a fresh SQLite file (always) and
the live Postgres 16.2 named by ``KV_SPLITBRAIN_PG_URL`` (skipped when
unset). The Postgres target must be a SCRATCH database — the fixture
drops the whole public schema before each test, then applies migrations
1..14. It is a DIFFERENT variable from ``KV_TEST_POSTGRES_URL`` (the
Step 7C var) on purpose: the 7C live test requires an empty database,
so the two suites must not share one.

Local server recipe: docs/RUNBOOK.md §3.1.
"""

from __future__ import annotations

import os

import pytest

from career_guidance import db as db_layer
from career_guidance.migrations import migrate

PG_URL = os.environ.get("KV_SPLITBRAIN_PG_URL", "")


def _reset_postgres(url: str) -> None:
    """Drop + recreate the public schema (scratch DB only)."""
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


@pytest.fixture(
    params=[
        pytest.param("sqlite"),
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(not PG_URL, reason="KV_SPLITBRAIN_PG_URL not set"),
        ),
    ]
)
def target(request, tmp_path):
    """A fully-migrated, EMPTY database target (path or Postgres URL)."""
    if request.param == "postgres":
        pytest.importorskip("psycopg")
        _reset_postgres(PG_URL)
        migrate(PG_URL)
        return PG_URL
    path = str(tmp_path / "splitbrain.db")
    migrate(path)
    return path


@pytest.fixture()
def dialect(target):
    return "postgres" if db_layer.is_postgres_target(target) else "sqlite"


# --------------------------------------------------------------------------- #
# C1: dialect-layer foundations, live
# --------------------------------------------------------------------------- #


def test_facade_executemany_live(target):
    """executemany inserts every row on both engines (the facade loops
    execute(); sqlite3 has it natively)."""
    conn = db_layer.connect(target)
    with conn:
        conn.executemany(
            "INSERT INTO app_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            [
                ("flags.module.x", "true", "2026-11-22T00:00:00", "test"),
                ("flags.module.y", "false", "2026-11-22T00:00:00", "test"),
            ],
        )
    with db_layer.connect(target) as conn2:
        rows = conn2.execute("SELECT key FROM app_settings ORDER BY key").fetchall()
    assert [r["key"] for r in rows] == ["flags.module.x", "flags.module.y"]


def test_failed_statement_inside_block_does_not_poison_connection(target, dialect):
    """A statement error caught inside the block: the block must exit
    cleanly and the connection must stay usable afterwards. On
    Postgres the transaction is INERROR at exit, so the facade rolls
    back instead of committing (committing would raise
    InFailedSqlTransaction)."""
    import sqlite3

    if dialect == "postgres":
        import psycopg

        error_types = (psycopg.Error,)
    else:
        error_types = (sqlite3.Error,)
    conn = db_layer.connect(target)
    with conn:
        with pytest.raises(error_types):
            conn.execute("INSERT INTO no_such_table (id) VALUES (?)", (1,))
    # The block exited without raising: the connection survived.
    with conn:
        row = conn.execute("SELECT 1 AS one").fetchone()
    assert row["one"] == 1


def test_table_and_column_names_live(target, dialect):
    conn = db_layer.connect(target)
    names = db_layer.table_names(conn, dialect)
    assert "users" in names and "profiles" in names and "kv_rag_chunks" in names
    assert "email" in db_layer.column_names(conn, "users", dialect)
    assert db_layer.column_names(conn, "no_such_table", dialect) == set()


# --------------------------------------------------------------------------- #
# C2: profiles + verification (connect-only ports)
# --------------------------------------------------------------------------- #


def test_profiles_round_trip(target, dialect):
    """Save/get/set_target/clear_target/delete — incl. ``current_role``,
    the Postgres reserved word 7C had to quote in the DDL and upsert."""
    from career_guidance.profiles import ProfileStore

    store = ProfileStore(target)
    assert store.dialect == dialect
    saved = store.save(
        "u1",
        persona="student",
        current_role="tailor",
        skills=["sewing", "cutting"],
        goals="steady income",
        experience_level="beginner",
    )
    assert saved.current_role == "tailor"
    assert saved.skills == ["sewing", "cutting"]
    got = store.get("u1")
    assert got is not None and got.current_role == "tailor"
    assert store.target("u1") is None
    assert store.set_target("u1", "43-9021.00")["career_id"] == "43-9021.00"
    assert store.target("u1")["career_id"] == "43-9021.00"
    store.clear_target("u1")
    assert store.target("u1") is None
    store.delete("u1")
    assert store.get("u1") is None


def test_verification_round_trip(target, dialect):
    """Quiz pass -> verified; project submit -> review -> verified;
    failed attempt -> cooldown."""
    from career_guidance.verify import VerificationStore

    store = VerificationStore(target)
    assert store.dialect == dialect
    assert store.get("u1", "sewing").status == "unverified"
    passed = store.record_attempt(
        "u1", "sewing", {"score_percent": 85, "passed": True, "total": 10, "correct": 9}
    )
    assert passed.status == "verified"
    assert passed.source == "quiz"
    assert passed.best_score == 85
    assert store.get("u1", "sewing").source == "quiz"

    project = store.submit_project(
        "u1",
        "tailoring",
        "Stitched a shirt",
        "https://example.com/shirt",
        "First shirt",
        ["hem", "seam"],
    )
    assert project.status == "project_submitted"
    approved = store.review_project("u1", "tailoring", True)
    assert approved.status == "verified"
    assert approved.source == "project"

    store.record_attempt(
        "u1", "cutting", {"score_percent": 20, "passed": False, "total": 10, "correct": 2}
    )
    assert store.get("u1", "cutting").status == "unverified"
    assert store.cooldown_remaining("u1", "cutting") > 0


# --------------------------------------------------------------------------- #
# C3: sharing + legacy consent + institute API keys (RETURNING id ports)
# --------------------------------------------------------------------------- #


def test_sharing_round_trip(target, dialect):
    """Create (RETURNING id on Postgres) -> by_token -> revoke."""
    from career_guidance.sharing import ShareStore

    store = ShareStore(target)
    assert store.dialect == dialect
    record, token = store.create(1, "u1")
    assert record.id > 0
    assert record.run_id == 1
    assert record.status() == "active"
    assert token
    assert store.by_token(token).id == record.id
    assert store.get(record.id).id == record.id
    assert [r.id for r in store.list_for_run(1)] == [record.id]
    revoked = store.revoke(record.id)
    assert revoked.status() == "revoked"
    assert store.by_token(token).status() == "revoked"


def test_legacy_consent_round_trip(target, dialect):
    """Create (RETURNING id) -> supersede -> decide -> revoke."""
    from career_guidance.consent import ConsentStore

    store = ConsentStore(target)
    assert store.dialect == dialect
    first, token1 = store.create_request("u1", "guardian@example.com")
    assert first.id > 0
    assert first.status == "pending"
    assert store.by_token(token1).id == first.id
    # A second request supersedes the first pending one.
    second, token2 = store.create_request("u1", "guardian@example.com")
    assert second.id > first.id
    assert store.latest("u1").id == second.id
    assert store.by_token(token1).status == "revoked"
    with pytest.raises(ValueError, match="already_decided"):
        store.decide(token1, True)
    granted = store.decide(token2, True)
    assert granted.status == "granted"
    assert store.effective_status("u1") == "granted"
    assert store.has_granted_consent("u1") is True
    revoked = store.revoke("u1")
    assert revoked.status == "revoked"
    assert store.effective_status("u1") == "revoked"


def test_institute_api_keys_round_trip(target, dialect):
    """Create (RETURNING id) -> authenticate -> revoke -> auth fails."""
    from career_guidance.api_keys import KEY_PREFIX, InstituteApiKeyStore

    store = InstituteApiKeyStore(target)
    assert store.dialect == dialect
    created = store.create_key(1, "test key", "admin1")
    assert created["id"] > 0
    assert created["api_key"].startswith(KEY_PREFIX)
    assert created["active"] is True
    authed = store.authenticate(created["api_key"])
    assert authed is not None
    assert authed["id"] == created["id"]
    assert authed["last_used_at"]
    assert [k["id"] for k in store.list_keys(1)] == [created["id"]]
    assert store.revoke_key(1, created["id"]) is True
    assert store.revoke_key(1, created["id"]) is False  # already revoked
    assert store.authenticate(created["api_key"]) is None


# --------------------------------------------------------------------------- #
# C4: institutes (RETURNING id port)
# --------------------------------------------------------------------------- #


def _insert_user(target, user_id: str, email: str) -> None:
    """Minimal user row via raw SQL — UserStore is not ported yet (C11),
    so live tests that need a user insert one directly. Every column
    not listed here has a migration default or is nullable."""
    with db_layer.connect(target) as conn:
        conn.execute(
            "INSERT INTO users (id, email, provider, created_at, last_login_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, email, "google", "2026-11-22T00:00:00", "2026-11-22T00:00:00"),
        )


def test_institutes_round_trip(target, dialect):
    """Create (RETURNING id, slug dedup) -> branding/schedule ->
    membership -> invites -> run reviews."""
    from career_guidance.institutes import InstituteStore

    store = InstituteStore(target)
    assert store.dialect == dialect
    first = store.create_institute("Kalasalingam Academy", "admin1")
    assert first["id"] > 0
    assert first["slug"] == "kalasalingam-academy"
    second = store.create_institute("Kalasalingam Academy", "admin1")
    assert second["slug"] == "kalasalingam-academy-2"
    assert store.get_institute(first["id"])["name"] == "Kalasalingam Academy"
    assert store.set_report_schedule(first["id"], "weekly")["report_schedule"] == "weekly"
    branded = store.update_branding(
        first["id"], logo_url="https://example.com/logo.png", accent_color="#0f766e"
    )
    assert branded["accent_color"] == "#0f766e"

    _insert_user(target, "u1", "student@example.com")
    assert store.membership_of("u1") is None
    store.set_membership("u1", first["id"], "student")
    assert store.membership_of("u1") == {
        "institute_id": first["id"],
        "institute_role": "student",
    }
    assert store.member_count(first["id"]) == 1
    assert store.user_by_email("student@example.com")["id"] == "u1"

    result = store.process_invites(
        first["id"], [{"email": "new@example.com", "name": "New", "role": "student"}]
    )
    assert result["pending"] == 1 and result["errors"] == 0
    assert store.pending_invite_count(first["id"]) == 1
    assert store.seat_usage(first["id"])["seats_used"] == 2  # 1 member + 1 pending
    assert [i["email"] for i in store.list_invites(first["id"])] == ["new@example.com"]

    review = store.add_review(7, "c1", "counsellor", "Good fit", True)
    assert review["reviewed"] is True
    assert store.review_for_run(7) is not None
    assert store.reviewed_run_ids([7, 8]) == {7}


# --------------------------------------------------------------------------- #
# C5: coupons + billing (the shared-transaction pair)
# --------------------------------------------------------------------------- #


def test_coupons_and_referrals_round_trip(target, dialect):
    """Coupon create (RETURNING id) -> validate -> deactivate; referral
    code stable across calls; summary counts."""
    from career_guidance.coupons import CouponStore, ReferralStore

    coupons = CouponStore(target)
    referrals = ReferralStore(target)
    assert coupons.dialect == dialect
    assert referrals.dialect == dialect
    coupon = coupons.create("WELCOME10", "percent", 10, max_redemptions=5, created_by="admin1")
    assert coupon["id"] > 0
    assert coupon["code"] == "WELCOME10"
    assert coupons.get_by_code("welcome10")["id"] == coupon["id"]
    found, reason = coupons.validate_for("WELCOME10", "u1")
    assert found is not None and reason is None
    assert coupons.redemption_count(coupon["id"]) == 0
    assert [c["code"] for c in coupons.list()] == ["WELCOME10"]

    code = referrals.code_for("u1")
    assert code.startswith("CG-")
    assert referrals.code_for("u1") == code  # stable after first mint
    assert referrals.owner_of(code) == "u1"
    assert referrals.summary("u1") == {"code": code, "referrals": 0, "pending_rewards": 0}

    assert coupons.deactivate("WELCOME10") is True
    assert coupons.get_by_code("WELCOME10")["active"] == 0
    found, reason = coupons.validate_for("WELCOME10", "u1")
    assert found is None and reason is not None


def test_billing_payment_with_coupon_and_referral(target, dialect):
    """create_payment writes the payment + redemption + attribution in
    ONE transaction on both engines (the coupon functions run on the
    live facade connection); webhook replay returns False."""
    from career_guidance.billing import (
        BillingStore,
        DemoRequestStore,
        SubscriptionStore,
    )
    from career_guidance.coupons import CouponStore, ReferralStore

    coupons = CouponStore(target)
    referrals = ReferralStore(target)
    billing = BillingStore(target)
    subscriptions = SubscriptionStore(target)
    demos = DemoRequestStore(target)
    assert billing.dialect == dialect

    coupon = coupons.create("SAVE20", "flat_inr", 50, max_redemptions=5, created_by="admin1")
    referrer_code = referrals.code_for("referrer1")
    assert referrer_code.startswith("CG-")

    payment_id = billing.create_payment(
        "buyer1",
        "order_123",
        "pro",
        49900,
        discount_paise=5000,
        coupon=coupon,
        coupon_code="SAVE20",
        referral_code=referrer_code,
        referrer_user_id="referrer1",
    )
    assert payment_id > 0
    payment = billing.payment_by_order("order_123")
    assert payment["id"] == payment_id
    assert payment["status"] == "created"
    assert payment["discount_paise"] == 5000
    assert payment["coupon_code"] == "SAVE20"
    assert coupons.redemption_count(coupon["id"]) == 1
    summary = referrals.summary("referrer1")
    assert summary["referrals"] == 1
    assert summary["pending_rewards"] == 1

    captured = billing.mark_captured("order_123")
    assert captured["status"] == "captured"

    sub = subscriptions.create("buyer1", "pro", "sub_razorpay_1")
    assert sub["razorpay_subscription_id"] == "sub_razorpay_1"
    assert subscriptions.by_razorpay_id("sub_razorpay_1")["user_id"] == "buyer1"
    assert subscriptions.for_user("buyer1")["plan"] == "pro"
    assert subscriptions.update("sub_razorpay_1", status="active")["status"] == "active"
    assert subscriptions.record_webhook_event("evt_1", "subscription.activated") is True
    assert subscriptions.record_webhook_event("evt_1", "subscription.activated") is False

    demo_id = demos.create("Dana", "dana@example.com", "KARE", 50, "Show us around")
    assert demo_id > 0
    assert [d["id"] for d in demos.list()] == [demo_id]


# --------------------------------------------------------------------------- #
# C6: journey
# --------------------------------------------------------------------------- #


def test_journey_round_trip(target, dialect):
    """Ratings -> rebuild_plan (RETURNING id) -> saved/done resources ->
    interview (RETURNING id) -> export -> purge."""
    from career_guidance.journey import JourneyStore

    store = JourneyStore(target)
    assert store.dialect == dialect
    assert store.set_ratings("u1", "43-9021.00", {"typing": 4, "excel": 2}) == {
        "typing": 4,
        "excel": 2,
    }
    assert store.ratings("u1", "43-9021.00")["typing"] == 4

    plan = store.rebuild_plan("u1", "43-9021.00", 6)
    assert plan["plan_id"] > 0
    latest = store.latest_plan("u1")
    assert latest["plan_id"] == plan["plan_id"]
    assert latest["readiness"] is not None  # merged from the plans row
    assert store.plan_by_id("u1", plan["plan_id"])["plan_id"] == plan["plan_id"]

    # set_item_done marks the item in the RETURNED payload; done_items
    # reads xp_events by the "plan:<id>:<item>" detail, which
    # set_item_done never writes (pre-existing bug, ported faithfully —
    # see the queue-item-7 audit note). Both engines agree.
    items = plan.get("items") or []
    assert items, "rebuild_plan produced no items to mark done"
    first_id = items[0]["id"]
    marked = store.set_item_done("u1", plan["plan_id"], first_id, True)
    assert marked is not None
    assert [i for i in marked["items"] if i["id"] == first_id][0]["done"] is True
    assert store.done_items("u1", plan["plan_id"]) == set()

    assert store.toggle_saved("u1", 5, True) is True
    assert store.toggle_saved("u1", 5, True) is True  # idempotent (ON CONFLICT)
    assert store.saved_resources("u1") == [5]
    assert store.toggle_saved("u1", 5, False) is False
    assert store.saved_resources("u1") == []

    store.mark_resource("u1", 7, True)
    assert store.done_resources("u1") == [7]
    store.mark_resource("u1", 7, False)
    assert store.done_resources("u1") == []

    interview_id = store.save_interview("u1", "43-9021.00", 300, {"q1": "Tell me about yourself"})
    assert interview_id > 0
    sessions = store.interview_sessions("u1")
    assert [s["id"] for s in sessions] == [interview_id]
    assert sessions[0]["notes"] == {"q1": "Tell me about yourself"}

    exported = store.export_user("u1")
    assert len(exported["plans"]) == 1
    assert len(exported["interview_sessions"]) == 1
    assert exported["ratings"], "export must include the ratings rows"

    store.purge_user("u1")
    assert store.ratings("u1", "43-9021.00") == {}
    assert store.latest_plan("u1") is None
    assert store.interview_sessions("u1") == []
    assert store.export_user("u1")["plans"] == []


# --------------------------------------------------------------------------- #
# C7: settings store
# --------------------------------------------------------------------------- #


def test_settings_round_trip(target, dialect):
    """Overrides + flags + events/counts (7-day window, named-column
    counts) + announcements + jobs — on BOTH engines."""
    from career_guidance.settings_store import SettingsStore

    store = SettingsStore(target)
    assert store.dialect == dialect
    assert store.get("scoring.w_skills") == 0.55  # default
    assert store.module_enabled("plan") is True
    store.set_many({"scoring.w_skills": 0.6, "flags.module.plan": False}, actor="admin1")
    assert store.get("scoring.w_skills") == 0.6
    assert store.overrides()["scoring.w_skills"] == 0.6
    assert store.module_enabled("plan") is False
    assert store.scoring()["skills"] > 0.5
    store.set_feature_flag("demo_mode", True)
    assert store.feature_flags()["demo_mode"] is True
    # reset(keys) exercises the facade's executemany on Postgres.
    store.reset(["scoring.w_skills", "flags.module.plan", "flags.demo_mode"])
    assert store.get("scoring.w_skills") == 0.55
    assert store.module_enabled("plan") is True

    store.record_event("startup", "cold start")
    store.record_error("/api/v1/x", "boom")
    store.record_tool("resume", "u1", "scored")
    store.record_tool("resume", "u2")
    counts = store.counts()
    assert counts["tools"] == 2
    assert counts["tools_7d"] == 2  # recorded today, inside the window
    assert counts["errors"] == 1
    assert counts["cold_starts"] == 1
    assert [t for t, _ in store.tool_usage()] == ["resume"]
    assert len(store.events("startup")) == 1

    aid = store.add_announcement("Hello", "World", level="info", pinned=True, actor="admin1")
    assert aid > 0
    assert [a["id"] for a in store.announcements()] == [aid]
    store.update_announcement(aid, title="Hello again", active=False)
    assert store.announcements() == []
    assert [a["title"] for a in store.announcements(active_only=False)] == ["Hello again"]
    store.delete_announcement(aid)
    assert store.announcements(active_only=False) == []

    job_id = store.start_job("import", "csv import")
    assert job_id > 0
    store.finish_job(job_id, status="done")
    jobs = store.jobs()
    assert [j["id"] for j in jobs] == [job_id]
    assert jobs[0]["status"] == "done"


# --------------------------------------------------------------------------- #
# C8: content store
# --------------------------------------------------------------------------- #


def test_content_round_trip(target, dialect):
    """Overrides (ON CONFLICT insert) -> custom careers + CSV import
    (duplicate skipped via the IntegrityError catch) -> resources
    (seed idempotency, case-insensitive search, executemany bump) ->
    interview templates."""
    from career_guidance.content_store import ContentStore

    store = ContentStore(target)
    assert store.dialect == dialect
    store.update_career("43-9021.00", hidden=True, salary_p50=300000, notes="test")
    overrides = store.career_overrides()
    assert overrides["43-9021.00"]["hidden"] == 1
    assert overrides["43-9021.00"]["salary_p50"] == 300000
    assert "43-9021.00" in store.hidden_ids()
    store.update_career("43-9021.00", hidden=False)
    assert "43-9021.00" not in store.hidden_ids()

    store.add_custom_career("custom-1", "Tailor Master", job_zone=2, skills=["sewing"])
    assert [c.id for c in store.custom_careers()] == ["custom-1"]
    csv_text = (
        "id,title,description,job_zone,skills,knowledge,technology\n"
        "custom-2,Weaver,Weaves cloth,2,weaving,,,\n"
        "custom-1,Duplicate,Should skip,2,,,\n"
        ",No id,Skipped,2,,,\n"
    )
    imported, skipped = store.import_careers_csv(csv_text)
    assert (imported, skipped) == (1, 2)
    assert store.catalog().get("custom-2") is not None
    store.delete_custom_career("custom-1")
    store.delete_custom_career("custom-2")
    assert store.custom_careers() == []

    seed = {
        "python": [
            {
                "title": "Python Basics",
                "url": "https://example.com/py",
                "provider": "Coursera",
            }
        ]
    }
    assert store.seed_resources(seed) == 1
    assert store.seed_resources(seed) == 0  # idempotent
    assert [r["title"] for r in store.resources(q="PYTHON")] == ["Python Basics"]
    assert [r["title"] for r in store.resources(provider="coursera")] == ["Python Basics"]

    rid = store.upsert_resource(
        {
            "skill": "sewing",
            "title": "Sewing 101",
            "url": "https://example.com/sew",
            "provider": "Khan",
        }
    )
    assert rid > 0
    assert store.resource(rid)["title"] == "Sewing 101"
    store.bump_uses([rid, rid])  # executemany on the facade
    assert store.resource(rid)["uses"] == 2
    store.mark_link_status(rid, "dead")
    assert store.resource(rid)["status"] == "dead"
    assert all(r["id"] != rid for r in store.resources())  # dead excluded
    filters = store.filters()
    assert "python" in filters["skills"]
    assert "Coursera" in filters["providers"]
    store.delete_resource(rid)
    assert store.resource(rid) is None

    tid = store.add_interview_template("technical", "Explain a hash map.", skill="python")
    assert tid > 0
    assert [t["id"] for t in store.interview_templates()] == [tid]
    store.delete_interview_template(tid)
    assert store.interview_templates() == []


# --------------------------------------------------------------------------- #
# C9: synonyms + gamification
# --------------------------------------------------------------------------- #


def test_synonyms_round_trip(target, dialect):
    """Upsert -> case-insensitive search (LOWER LIKE) -> unmatched loop
    (log, map, dismiss) -> stats -> delete."""
    from career_guidance.synonyms import SynonymStore

    store = SynonymStore(target)
    assert store.dialect == dialect
    store.upsert("ms excel", "microsoft excel")
    store.upsert("py", "python")
    assert [r["alias"] for r in store.all(q="PY")] == ["py"]
    assert [r["alias"] for r in store.all(q="EXCEL")] == ["ms excel"]
    assert {r["alias"] for r in store.all()} >= {"ms excel", "py"}
    entries = store.as_entries()
    assert any(e.canonical == "python" and "py" in e.aliases for e in entries)

    store.log_unmatched(["quxterm", "quxterm", "otherterm"])
    assert {r["term"]: r["count"] for r in store.unmatched()} == {
        "quxterm": 1,
        "otherterm": 1,
    }
    store.log_unmatched(["quxterm"])
    assert {r["term"]: r["count"] for r in store.unmatched()} == {
        "quxterm": 2,
        "otherterm": 1,
    }
    store.map_unmatched("quxterm", "python")
    assert {r["term"] for r in store.unmatched()} == {"otherterm"}
    assert store.all(q="quxterm")
    store.dismiss_unmatched("otherterm")
    assert store.unmatched() == []
    stats = store.stats()
    assert stats["open"] == 0 and stats["mapped"] == 1
    store.delete("py")
    store.delete("quxterm")
    assert store.all(q="py") == []


def test_gamification_round_trip(target, dialect):
    """Award -> xp/counts/daily/streak -> badge grant (the INSERT ...
    ON CONFLICT DO NOTHING statement runs on both engines) -> status."""
    from career_guidance.gamification import GamificationStore

    store = GamificationStore(target)
    assert store.dialect == dialect
    assert store.award("u-1", "run") == 10
    store.award("u-1", "assessment")
    assert store.xp("u-1") == 30
    counts = store.counts("u-1")
    assert counts["runs"] == 1 and counts["assessments"] == 1
    assert store.daily_xp("u-1")[-1][1] == 30
    assert store.streak("u-1")["current"] == 1
    # Pre-existing quirk, pinned as parity (not a port regression):
    # badge events are named "assessment"/"plan"/"interview" but
    # counts() keys them "assessments"/"plans"/"interviews", so
    # those badges never fire. The "learned" badge does fire — it
    # exercises the INSERT ... ON CONFLICT DO NOTHING statement
    # on both engines.
    assert {b["id"] for b in store.badges("u-1") if b["earned_at"]} == set()
    for _ in range(10):
        store.award("u-1", "plan_item")
    assert store.counts("u-1")["learned"] == 10
    earned = {b["id"] for b in store.badges("u-1") if b["earned_at"]}
    assert earned == {"skills-10"}
    # A further award must not duplicate the badge row.
    store.award("u-1", "plan_item")
    assert {b["id"] for b in store.badges("u-1") if b["earned_at"]} == {"skills-10"}
    assert store.evaluate_badges("u-1") == []
    status = store.status("u-1")
    assert status["xp"] == 30 + 11 * 15
    assert status["level"] >= 1
    assert len(status["recent"]) == 10


# --------------------------------------------------------------------------- #
# C10: RIASEC + 90-day plans
# --------------------------------------------------------------------------- #


def test_riasec_round_trip(target, dialect):
    """Save (RETURNING id) -> history/latest for a user and for
    anonymous runs (the IS NULL branch) -> admin item overrides."""
    from career_guidance.riasec import AssessmentStore

    store = AssessmentStore(target)
    assert store.dialect == dialect
    result = {
        "scores": {"R": 5.0, "I": 4.0, "A": 3.0, "S": 2.0, "E": 1.0, "C": 6.0},
        "holland_code": "RIC",
    }
    run_id = store.save("u-1", {"R1": 5, "I1": 4}, result)
    assert run_id > 0
    anon_id = store.save(None, {"R1": 3}, result)
    assert anon_id > 0
    history = store.history("u-1")
    assert [h["id"] for h in history] == [run_id]
    assert history[0]["holland_code"] == "RIC"
    assert history[0]["scores"]["R"] == 5.0
    assert store.latest("u-1")["id"] == run_id
    assert [h["id"] for h in store.history(None)] == [anon_id]
    assert store.latest(None)["id"] == anon_id

    store.upsert_item("R99", "R", "I like fixing engines.", weight=1.5)
    overrides = store.item_overrides()
    assert any(r["id"] == "R99" and r["text"] == "I like fixing engines." for r in overrides)
    items = store.merged_items()
    assert any(i.id == "R99" and i.weight == 1.5 for i in items)
    store.delete_item("R99")
    assert all(r["id"] != "R99" for r in store.item_overrides())


def test_plan90_round_trip(target, dialect):
    """Save (RETURNING id) -> latest -> mark_task toggle -> misses."""
    from career_guidance.roadmap import Plan90Store

    store = Plan90Store(target)
    assert store.dialect == dialect
    plan = {
        "run_id": 7,
        "hours_per_week": 6,
        "weeks": [{"week": 1, "tasks": [{"id": "t1", "title": "Learn Python", "done": False}]}],
    }
    saved = store.save("u-1", plan)
    assert saved["plan_id"] > 0
    assert saved["created_at"]
    latest = store.latest("u-1")
    assert latest["plan_id"] == saved["plan_id"]
    assert latest["weeks"][0]["tasks"][0]["done"] is False
    updated = store.mark_task("u-1", saved["plan_id"], "t1", True)
    assert updated["weeks"][0]["tasks"][0]["done"] is True
    assert store.latest("u-1")["weeks"][0]["tasks"][0]["done"] is True
    assert store.mark_task("u-1", saved["plan_id"], "missing", True) is None
    assert store.latest("nobody") is None


# --------------------------------------------------------------------------- #
# C11: users
# --------------------------------------------------------------------------- #


def test_users_round_trip(target, dialect):
    """Login/get/phone -> case-insensitive list -> roles/prefs/profile/
    age -> magic links -> plan/trial -> progress -> feedback (RETURNING
    id, AVG as float) -> resource overrides -> audit -> full delete."""
    from career_guidance.users import UserStore

    store = UserStore(target)
    assert store.dialect == dialect
    user = store.upsert_login("Ada@Example.com", "google", name="Ada Lovelace")
    assert user.email == "ada@example.com" and user.role == "user"
    assert store.get(user.id).name == "Ada Lovelace"
    again = store.upsert_login("ada@example.com", "google", name="Ada L.")
    assert again.id == user.id and again.name == "Ada L."
    store.set_phone_verified(user.id, "+919876543210")
    assert store.get_by_phone("+919876543210").id == user.id
    assert store.get_by_phone("+910000000000") is None

    # Case-insensitive search (LOWER LIKE).
    assert [u["email"] for u in store.list_users("ADA")] == ["ada@example.com"]
    assert [u["email"] for u in store.list_users("lovelace")] == []
    assert store.count_users()["total"] == 1

    store.set_role(user.id, "coordinator")
    assert store.get(user.id).role == "coordinator"
    store.set_prefs(user.id, {"locale": "ta"})
    assert store.get(user.id).prefs == {"locale": "ta"}
    store.set_public_profile(user.id, "ada-l", True)
    assert store.get_by_handle("ada-l").id == user.id
    store.set_minor(user.id, False)
    declared = store.set_age_declaration(user.id, "adult", 2005)
    assert declared.age_band == "adult" and declared.is_minor is False

    token = store.create_magic_link("ada@example.com")
    assert store.consume_magic_link(token) == "ada@example.com"
    assert store.consume_magic_link(token) is None  # single use
    assert store.consume_magic_link("no-such-token") is None

    assert store.plan_of(user.id) == {"plan": "free", "trial_ends_at": ""}
    store.set_plan(user.id, "pro")
    store.start_trial(user.id, "2027-01-01")
    assert store.plan_of(user.id) == {"plan": "pro", "trial_ends_at": "2027-01-01"}

    store.set_progress(user.id, "Python", True)
    store.set_progress(user.id, "SQL", False)
    assert store.progress(user.id) == ["python"]

    fid = store.add_feedback(5, "Great tool", user.id, None, "Data Analyst", tool="recommend")
    assert fid > 0
    store.add_feedback(3, "Okay", None, None, "Teacher")
    feedback = store.list_feedback()
    assert [f["id"] for f in feedback] == sorted((f["id"] for f in feedback), reverse=True)
    stats = store.feedback_stats()
    assert stats["total"] == 2 and stats["open"] == 2
    assert stats["avg_rating"] == 4.0
    assert isinstance(stats["avg_rating"], float)  # Postgres AVG returns Decimal
    store.set_feedback_status(fid, "seen")
    assert store.feedback_stats()["open"] == 1

    store.set_resources("python", [{"title": "Py 101"}], actor="admin")
    assert store.resource_overrides()["python"][0]["title"] == "Py 101"
    store.delete_resources("python")
    assert store.resource_overrides() == {}

    store.audit("ada@example.com", "test:action", "target")
    assert any(r["action"] == "test:action" for r in store.audit_log())

    # Full delete: user gone, feedback anonymised, audit actor anonymised.
    store.delete_user(user.id)
    assert store.get(user.id) is None
    assert store.list_users() == []
    assert all(f["user_id"] is None for f in store.list_feedback())
    assert all(r["actor"] != "ada@example.com" for r in store.audit_log())


# --------------------------------------------------------------------------- #
# C12: admin console
# --------------------------------------------------------------------------- #


def test_admin_console_dialect(target, dialect):
    """_applied_map on both engines; the admin router against the
    target: /system reports the database healthy, file backup/restore
    work on SQLite and answer 501 on Postgres."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.admin_console import _applied_map, build_router
    from career_guidance.storage import Database
    from career_guidance.users import UserStore

    applied = _applied_map(target)
    assert set(applied) >= set(range(1, 15))  # migrations 1..14
    assert all(v for v in applied.values())

    users = UserStore(target)
    db = Database(target)
    admin = users.upsert_login("admin@example.com", "google", name="Admin")
    users.set_role(admin.id, "admin")
    settings = SimpleNamespace(database_path=target, database_target=target)
    app = FastAPI()
    app.include_router(build_router(settings, users, db, lambda: admin))
    with TestClient(app) as client:
        system = client.get("/api/v1/admin/system").json()
        assert system["health"]["db"] == "ok"
        assert len(system["migrations"]) == 14
        assert all(m["applied_at"] for m in system["migrations"])
        if dialect == "postgres":
            assert system["disk"]["db_bytes"] == 0
            assert client.get("/api/v1/admin/backup.db").status_code == 501
            response = client.post(
                "/api/v1/admin/restore",
                files={"file": ("x.db", b"SQLite format 3" + b"\0" * 200)},
            )
            assert response.status_code == 501
        else:
            assert system["disk"]["db_bytes"] > 0
            backup = client.get("/api/v1/admin/backup.db")
            assert backup.status_code == 200
            assert backup.content[:15] == b"SQLite format 3"
