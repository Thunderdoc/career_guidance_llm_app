"""Phase 9 tests: institute analytics v2.

- Term = CALENDAR QUARTER. Term-over-term: current vs previous quarter
  cohorts + deltas over real stored runs only (empty period → honest
  zeros, never fabricated).
- report_schedule is a PREFERENCE record (none|weekly|monthly) with a
  nominal next_run — no scheduler exists or is claimed.
- Review queue v2: unreviewed only, oldest first, paginated; the Phase 4
  review endpoint marks items off the queue.
- Phase 4 privacy binds throughout: aggregates only, no e-mails.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from career_guidance.institutes import (
    compute_cohort_comparison,
    quarter_bounds,
    report_schedule_payload,
)
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


def _set_run_time(app_module, run_id: int, when: datetime) -> None:
    with sqlite3.connect(app_module.settings.database_path) as conn:
        conn.execute(
            "UPDATE recommendation_runs SET created_at=? WHERE id=?",
            (when.isoformat(timespec="seconds"), run_id),
        )


@pytest.fixture()
def world(app_module, client):
    w = {}
    w["iadmin"] = _client(app_module, "iadmin@demo.example")
    w["counsellor"] = _client(app_module, "counsellor@demo.example")
    w["student"] = _client(app_module, "student@demo.example")
    w["student_id"] = _me(w["student"])["id"]
    r = w["iadmin"].post("/api/v1/institutes", json={"name": "DEMO Analytics Institute"})
    assert r.status_code == 201, r.text
    w["iid"] = r.json()["institute"]["id"]
    r = w["iadmin"].post(
        f"/api/v1/institutes/{w['iid']}/invites",
        json={
            "members": [
                {"email": "counsellor@demo.example", "role": "counsellor"},
                {"email": "student@demo.example", "role": "student"},
            ]
        },
    )
    assert r.json()["invited"] == 2, r.text
    return w


# ---------------------------------------------------------------- core


def test_quarter_bounds():
    start, end = quarter_bounds(datetime(2026, 11, 6, tzinfo=timezone.utc))
    assert (start.month, start.day) == (10, 1) and (end.year, end.month) == (2027, 1)
    start, end = quarter_bounds(datetime(2026, 2, 15, tzinfo=timezone.utc))
    assert (start.month, end.month) == (1, 4)


def _fake_run(user_id: str, created_at: str, title: str, score: float, missing: list[str]):
    rec = CareerRecommendation(
        title=title,
        match_reason="fit",
        suitability="beginner",
        missing_skills=missing,
        match_score=score,
    )
    return SimpleNamespace(user_id=user_id, created_at=created_at, recommendations=[rec], id=1)


def test_comparison_core_deltas_and_empty_previous():
    members = [{"user_id": "s1", "name": "S", "institute_role": "student"}]
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)  # Q4 2026
    runs = [_fake_run("s1", "2026-10-10T00:00:00+00:00", "Data Analyst", 0.9, ["sql"])]
    out = compute_cohort_comparison(members, runs, now=now)
    assert out["term"]["kind"] == "calendar_quarter"
    assert out["term"]["current"]["label"] == "2026-Q4"
    assert out["term"]["previous"]["label"] == "2026-Q3"
    assert out["current"]["runs_count"] == 1
    # Empty previous period → honest zeros, not fabricated numbers.
    assert out["previous"]["runs_count"] == 0
    assert out["previous"]["top_recommended_careers"] == []
    assert out["deltas"]["runs_count"] == 1
    careers = {d["title"]: d for d in out["deltas"]["top_recommended_careers"]}
    assert careers["Data Analyst"] == {
        "title": "Data Analyst",
        "current": 1,
        "previous": 0,
        "delta": 1,
    }
    readiness = {d["bucket"]: d for d in out["deltas"]["readiness_distribution"]}
    assert readiness["85-100"]["delta"] == 1 and readiness["0-49"]["delta"] == 0


def test_report_schedule_payload_next_run():
    base = {"report_schedule": "none", "report_schedule_updated_at": "2026-11-01T00:00:00+00:00"}
    assert report_schedule_payload(base) == {"schedule": "none", "next_run": None}
    weekly = report_schedule_payload({**base, "report_schedule": "weekly"})
    assert weekly["next_run"].startswith("2026-11-08")
    monthly = report_schedule_payload({**base, "report_schedule": "monthly"})
    assert monthly["next_run"].startswith("2026-12-01")
    assert report_schedule_payload({})["schedule"] == "none"


# ---------------------------------------------------------------- API


def test_cohort_term_over_term_api(world, app_module):
    now = datetime.now(timezone.utc)
    cur_start, _ = quarter_bounds(now)
    prev_start, _ = quarter_bounds(cur_start - timedelta(days=1))
    _seed_run(app_module, world["student_id"], title="Data Analyst", score=0.9)
    previous_run = _seed_run(
        app_module, world["student_id"], title="Web Developer", score=0.6, missing=("css",)
    )
    _set_run_time(app_module, previous_run, prev_start + timedelta(days=2))
    iid = world["iid"]
    r = world["counsellor"].get(f"/api/v1/institutes/{iid}/cohort?period=current")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cohort"]["runs_count"] == 1
    comparison = body["comparison"]
    assert comparison["current"]["runs_count"] == 1
    assert comparison["previous"]["runs_count"] == 1
    assert comparison["deltas"]["runs_count"] == 0
    careers = {d["title"]: d for d in comparison["deltas"]["top_recommended_careers"]}
    assert careers["Data Analyst"]["delta"] == 1
    assert careers["Web Developer"]["delta"] == -1
    assert "@" not in r.text  # aggregates only — no e-mails anywhere
    r = world["iadmin"].get(f"/api/v1/institutes/{iid}/cohort?period=previous")
    assert r.json()["cohort"]["runs_count"] == 1
    assert r.json()["cohort"]["top_recommended_careers"][0]["title"] == "Web Developer"
    # All-time cohort (no period) is unchanged Phase 4 behaviour.
    assert (
        world["iadmin"].get(f"/api/v1/institutes/{iid}/cohort").json()["cohort"]["runs_count"] == 2
    )
    # Bad period + role gates.
    assert world["iadmin"].get(f"/api/v1/institutes/{iid}/cohort?period=yearly").status_code == 422
    assert (
        world["student"].get(f"/api/v1/institutes/{iid}/cohort?period=current").status_code == 403
    )


def test_cohort_comparison_empty_previous_is_honest(world, app_module):
    _seed_run(app_module, world["student_id"])  # current quarter only
    body = world["iadmin"].get(f"/api/v1/institutes/{world['iid']}/cohort?period=current").json()
    previous = body["comparison"]["previous"]
    assert previous["runs_count"] == 0
    assert previous["top_recommended_careers"] == []
    assert previous["most_missing_skills"] == []
    assert all(d["count"] == 0 for d in previous["readiness_distribution"])
    assert body["comparison"]["deltas"]["runs_count"] == 1


def test_report_schedule_patch(world):
    iid = world["iid"]
    detail = world["iadmin"].get(f"/api/v1/institutes/{iid}").json()
    assert detail["report_schedule"] == {"schedule": "none", "next_run": None}
    # Counsellor cannot set it (institute_admin only, via the PATCH route).
    r = world["counsellor"].patch(f"/api/v1/institutes/{iid}", json={"report_schedule": "weekly"})
    assert r.status_code == 403
    r = world["iadmin"].patch(f"/api/v1/institutes/{iid}", json={"report_schedule": "weekly"})
    assert r.status_code == 200, r.text
    schedule = r.json()["report_schedule"]
    assert schedule["schedule"] == "weekly" and schedule["next_run"]
    r = world["iadmin"].patch(f"/api/v1/institutes/{iid}", json={"report_schedule": "daily"})
    assert r.status_code == 422


def test_review_queue_v2_unreviewed_oldest_first_paginated(world, app_module):
    iid = world["iid"]
    older = _seed_run(app_module, world["student_id"], title="Older Run")
    newer = _seed_run(app_module, world["student_id"], title="Newer Run")
    now = datetime.now(timezone.utc)
    _set_run_time(app_module, older, now - timedelta(days=2))
    _set_run_time(app_module, newer, now - timedelta(days=1))
    queue_url = f"/api/v1/institutes/{iid}/review-queue"
    body = world["counsellor"].get(queue_url).json()
    assert body["total"] == 2
    assert [q["run_id"] for q in body["queue"]] == [older, newer]  # oldest first
    assert all(q["reviewed"] is False for q in body["queue"])
    page = world["counsellor"].get(f"{queue_url}?limit=1&offset=1").json()
    assert page["total"] == 2 and [q["run_id"] for q in page["queue"]] == [newer]
    assert world["student"].get(queue_url).status_code == 403
    # The Phase 4 review endpoint marks the item off the queue.
    r = world["counsellor"].post(
        f"/api/v1/institutes/{iid}/runs/{older}/review",
        json={"note": "Seen.", "approved": True},
    )
    assert r.status_code == 200
    body = world["counsellor"].get(queue_url).json()
    assert body["total"] == 1 and body["queue"][0]["run_id"] == newer
