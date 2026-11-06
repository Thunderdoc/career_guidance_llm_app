"""Phase 3 core tests: quizzes, grading, state machine, 90-day plan,
notifications — no HTTP involved."""

from __future__ import annotations

import random

import pytest

from career_guidance import notifications, verify
from career_guidance.migrations import applied_versions, migrate
from career_guidance.roadmap import build_90_day_plan, plan_progress, to_ics_90, to_markdown_90

SECRET = "test-secret"  # noqa: S105 - test-only signing secret


def _answers_for(skill: str, correct_count: int) -> tuple[dict, dict]:
    """Start an attempt and build answers with exactly ``correct_count`` right."""
    attempt = verify.start_attempt(skill, SECRET, rng=random.Random(7))
    quiz = verify.get_quiz(skill)
    answers: dict[str, int] = {}
    remaining = correct_count
    for shown in attempt["questions"]:
        original = next(q for q in quiz.questions if q.id == shown["id"])
        right = shown["options"].index(original.options[original.correct])
        if remaining > 0:
            answers[shown["id"]] = right
            remaining -= 1
        else:
            answers[shown["id"]] = (right + 1) % len(shown["options"])
    return attempt, answers


# --------------------------------------------------------------------- quizzes
def test_exactly_five_quizzes_eight_questions_each():
    quizzes = verify.available_quizzes()
    assert {q["skill"] for q in quizzes} == {
        "python",
        "sql",
        "html-css",
        "excel",
        "communication",
    }
    assert all(q["questions"] == 8 for q in quizzes)
    for meta in quizzes:
        quiz = verify.get_quiz(meta["skill"])
        for question in quiz.questions:
            assert len(question.options) == 4
            assert 0 <= question.correct < 4
            assert question.explanation  # every question explains itself


def test_quiz_payload_never_exposes_answers():
    import json

    attempt = verify.start_attempt("python", SECRET, rng=random.Random(3))
    blob = json.dumps(attempt)
    assert "correct" not in blob
    assert "explanation" not in blob
    for shown in attempt["questions"]:
        assert set(shown) == {"id", "question", "options"}


def test_attempt_is_randomised():
    a = verify.start_attempt("sql", SECRET, rng=random.Random(1))
    b = verify.start_attempt("sql", SECRET, rng=random.Random(2))
    assert [q["id"] for q in a["questions"]] != [q["id"] for q in b["questions"]] or any(
        x["options"] != y["options"] for x, y in zip(a["questions"], b["questions"], strict=True)
    )


def test_unknown_skill_has_no_quiz():
    with pytest.raises(verify.QuizUnavailable):
        verify.get_quiz("astrophysics")
    assert verify.quiz_skill_for("astrophysics") is None
    assert verify.quiz_skill_for("Programming") == "python"


# --------------------------------------------------------------------- grading
def test_grading_pass_fail_boundary():
    # 8 questions: 6/8 = 75% passes, 5/8 = 62.5% fails (pass mark is 70%).
    attempt, answers = _answers_for("python", 6)
    result = verify.grade_attempt(attempt["attempt_token"], answers, SECRET)
    assert result["score_percent"] == 75.0 and result["passed"] is True

    attempt, answers = _answers_for("python", 5)
    result = verify.grade_attempt(attempt["attempt_token"], answers, SECRET)
    assert result["score_percent"] == 62.5 and result["passed"] is False


def test_grading_rejects_tampered_or_wrong_secret_token():
    attempt, answers = _answers_for("excel", 8)
    with pytest.raises(ValueError):
        verify.grade_attempt(attempt["attempt_token"], answers, "other-secret")
    with pytest.raises(ValueError):
        verify.grade_attempt(attempt["attempt_token"][:-6] + "zzzzzz", answers, SECRET)
    with pytest.raises(ValueError):
        verify.grade_attempt("not-a-token", answers, SECRET)


# ---------------------------------------------------------------- state machine
@pytest.fixture()
def store(tmp_path):
    return verify.VerificationStore(str(tmp_path / "app.db"))


def test_quiz_pass_auto_verifies(store):
    attempt, answers = _answers_for("python", 7)
    result = verify.grade_attempt(attempt["attempt_token"], answers, SECRET)
    state = store.record_attempt("u1", "python", result)
    assert state.status == "verified"
    assert state.source == "quiz"
    assert state.self_reported is False
    assert state.best_score == 87.5


def test_failed_attempt_stays_unverified_and_starts_cooldown(store):
    attempt, answers = _answers_for("sql", 2)
    result = verify.grade_attempt(attempt["attempt_token"], answers, SECRET)
    state = store.record_attempt("u1", "sql", result)
    assert state.status == "unverified"
    remaining = store.cooldown_remaining("u1", "sql")
    assert 23.0 < remaining <= 24.0
    with pytest.raises(verify.CooldownActive):
        store.assert_can_attempt("u1", "sql")
    # A different skill is unaffected; a passing user is never cooled down.
    assert store.cooldown_remaining("u1", "excel") == 0.0
    store.record_attempt("u2", "sql", {"score_percent": 100.0, "passed": True})
    assert store.cooldown_remaining("u2", "sql") == 0.0


def test_cooldown_expires(store, tmp_path):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    store.record_attempt("u1", "sql", {"score_percent": 10.0, "passed": False})
    assert store.cooldown_remaining("u1", "sql") > 0
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
    with sqlite3.connect(str(tmp_path / "app.db")) as conn:
        conn.execute("UPDATE quiz_attempts SET created_at = ?", (old,))
    assert store.cooldown_remaining("u1", "sql") == 0.0
    store.assert_can_attempt("u1", "sql")  # must not raise


def test_project_path_is_self_reported_until_reviewed(store):
    state = store.submit_project(
        "u1", "python", "Marks CLI", "https://github.com/example/marks", "desc", ["has tests"]
    )
    assert state.status == "project_submitted"
    assert state.self_reported is True
    assert state.source == "project"

    state = store.review_project("u1", "python", approve=True)
    assert state.status == "verified"
    assert state.self_reported is False


def test_project_review_rejection_returns_to_unverified(store):
    store.submit_project("u1", "excel", "Budget sheet", "https://example.com/sheet", "", [])
    state = store.review_project("u1", "excel", approve=False)
    assert state.status == "unverified"


def test_review_without_submission_is_an_error(store):
    with pytest.raises(ValueError):
        store.review_project("ghost", "python", approve=True)


def test_verified_projection_for_public_profile(store):
    store.record_attempt("u1", "python", {"score_percent": 90.0, "passed": True})
    store.submit_project("u1", "sql", "ETL demo", "https://github.com/example/etl", "", [])
    verified = store.verified_skills("u1")
    assert verified == [
        {"skill": "python", "method": "quiz", "verified_at": verified[0]["verified_at"]}
    ]
    projects = store.public_projects("u1")
    assert projects[0]["title"] == "ETL demo"
    assert projects[0]["verified"] is False  # submitted ≠ reviewed


# ------------------------------------------------------------------ migrations
def test_migration_v5_applies_and_is_idempotent(tmp_path):
    path = str(tmp_path / "fresh.db")
    assert migrate(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert migrate(path) == []
    assert applied_versions(path) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_migration_from_phase1_era_db_preserves_users(tmp_path, monkeypatch):
    """Industry-Ready §6.3: a v4 (Phase 1/2-era) DB upgrades in place."""
    import sqlite3

    import career_guidance.migrations as migrations

    path = str(tmp_path / "old.db")
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:4])
    assert migrate(path) == [1, 2, 3, 4]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO users (id, email, name, picture, provider, role, created_at, "
            "last_login_at) VALUES ('u-old', 'old@example.com', 'Old User', '', 'magic-link', "
            "'user', '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00')"
        )
    monkeypatch.undo()
    assert migrate(path) == [5, 6, 7, 8, 9, 10]
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT email, handle, public_profile, is_minor FROM users WHERE id = 'u-old'"
        ).fetchone()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert row == ("old@example.com", "", 0, 0)  # data intact, safe defaults
    assert {"skill_verifications", "quiz_attempts", "skill_projects", "plans_90day"} <= tables
    assert migrate(path) == []  # still idempotent after the upgrade


# ------------------------------------------------------------------ 90-day plan
def test_plan_has_13_weeks_and_scales_with_hours():
    low = build_90_day_plan(["python", "sql"], {"hours_per_week": 2})
    high = build_90_day_plan(["python", "sql"], {"hours_per_week": 10})
    assert len(low["weeks"]) == 13 and len(high["weeks"]) == 13
    assert len(low["weeks"][0]["tasks"]) == 1
    assert len(high["weeks"][0]["tasks"]) == 3
    assert low["hours_per_week"] == 2 and high["hours_per_week"] == 10


def test_plan_defaults_without_constraints():
    plan = build_90_day_plan(["excel"], None)
    assert plan["hours_per_week"] == 6
    assert len(plan["weeks"][0]["tasks"]) == 2


def test_plan_tasks_only_from_curated_catalogue():
    from career_guidance.learning import resources_for

    plan = build_90_day_plan(["python"], {"hours_per_week": 6})
    known_urls = {r.url for s in ("python", "programming") for r in resources_for(s, 10)}
    for week in plan["weeks"]:
        for task in week["tasks"]:
            assert task["resource"]["url"] in known_urls


def test_plan_verification_check_names_quiz_only_when_one_exists():
    plan = build_90_day_plan(["python", "xyzzy-nonsense-skill"], {"hours_per_week": 6})
    assert "Python basics" in plan["weeks"][0]["verification_check"]
    assert plan["weeks"][1]["verification_check"] == ""
    assert plan["weeks"][1]["tasks"] == []  # no curated resources → honest empty
    assert "No curated resource" in plan["weeks"][1]["note"]


def test_plan_exports():
    plan = build_90_day_plan(["sql"], {"hours_per_week": 6})
    md = to_markdown_90(plan)
    assert "# 90-day plan" in md and "Week 13" in md and "SQLBolt" in md
    ics = to_ics_90(plan)
    assert ics.count("BEGIN:VEVENT") == 13
    progress = plan_progress(plan, {plan["weeks"][0]["tasks"][0]["id"]})
    assert progress["tasks_done"] == 1 and progress["tasks_total"] == 26


# ---------------------------------------------------------------- notifications
class FakeProvider(notifications.NotificationProvider):
    name = "fake"

    def __init__(self):
        self.sent: list[tuple[dict, str, str]] = []

    def send(self, user, subject, body):
        self.sent.append((user, subject, body))
        return True


def test_send_plan_reminder_with_fake_provider():
    fake = FakeProvider()
    week = {
        "week": 3,
        "skill": "python",
        "tasks": [{"title": "Work through: Python for Everybody"}],
        "verification_check": "Verification check: take the quiz.",
    }
    assert notifications.send_plan_reminder({"email": "a@b.c"}, week, provider=fake) is True
    assert len(fake.sent) == 1
    assert "Week 3" in fake.sent[0][2] and "Python for Everybody" in fake.sent[0][2]


def test_send_plan_reminder_noops_gracefully():
    assert notifications.send_plan_reminder({}, {}) is False
    assert notifications.send_plan_reminder({"email": "a@b.c"}, None) is False
    # WhatsApp stub raises NotImplementedError; the helper must swallow it.
    week = {"week": 1, "skill": "sql", "tasks": []}
    assert (
        notifications.send_plan_reminder(
            {"email": "a@b.c"}, week, provider=notifications.WhatsAppNotificationProvider()
        )
        is False
    )
    with pytest.raises(NotImplementedError):
        notifications.WhatsAppNotificationProvider().send({}, "s", "b")
    # Log provider is the safe default when SMTP is unconfigured.
    assert notifications.LogNotificationProvider().send({"email": "a@b.c"}, "s", "b") is True


class _FakeSMTP:
    """Stand-in for smtplib.SMTP that records the outgoing message."""

    instances: list[_FakeSMTP] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.message = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        self.message = msg


def test_smtp_provider_sends_via_stubbed_smtplib(monkeypatch):
    import smtplib

    _FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    config = notifications.SmtpConfig(host="mail.example.com", port=587, user="u", sender="f@x.y")
    provider = notifications.SmtpNotificationProvider(config)
    assert provider.send({"email": "a@b.c"}, "Subject", "Body") is True
    sent = _FakeSMTP.instances[0].message
    assert sent["To"] == "a@b.c" and sent["Subject"] == "Subject"


def test_smtp_provider_degrades_without_config_or_address():
    provider = notifications.SmtpNotificationProvider(notifications.SmtpConfig(host=""))
    assert provider.send({"email": "a@b.c"}, "s", "b") is False
    configured = notifications.SmtpNotificationProvider(
        notifications.SmtpConfig(host="mail.example.com")
    )
    assert configured.send({}, "s", "b") is False  # no recipient address


def test_smtp_config_from_env_and_default_provider(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert notifications.SmtpConfig.from_env().enabled is False
    assert isinstance(notifications.default_provider(), notifications.LogNotificationProvider)
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    config = notifications.SmtpConfig.from_env()
    assert config.enabled and config.port == 2525
    assert isinstance(notifications.default_provider(), notifications.SmtpNotificationProvider)
