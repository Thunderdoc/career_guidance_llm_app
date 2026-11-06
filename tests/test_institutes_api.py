"""Phase 4 API tests: permission matrix, CSV import, cohort privacy,
counsellor review loop, project-review extension, DEMO end-to-end."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture()
def world(app_module, client):
    """Two institutes with staff/students + one outsider + platform admin.

    DEMO seed data — created only inside this test fixture.
    """
    w = {}
    w["iadmin"] = _client(app_module, "iadmin@demo.example")
    w["counsellor"] = _client(app_module, "counsellor@demo.example")
    w["student"] = _client(app_module, "student@demo.example")
    w["student2"] = _client(app_module, "student2@demo.example")
    w["other_admin"] = _client(app_module, "other@demo.example")
    w["outsider"] = _client(app_module, "outsider@demo.example")
    w["platform_admin"] = _client(app_module, "boss@example.com")
    for key in ("iadmin", "counsellor", "student", "student2", "other_admin", "outsider"):
        w[f"{key}_id"] = _me(w[key])["id"]

    r = w["iadmin"].post("/api/v1/institutes", json={"name": "DEMO Institute One"})
    assert r.status_code == 201, r.text
    w["iid"] = r.json()["institute"]["id"]
    r = w["iadmin"].post(
        f"/api/v1/institutes/{w['iid']}/invites",
        json={
            "members": [
                {"email": "counsellor@demo.example", "role": "counsellor"},
                {"email": "student@demo.example", "role": "student"},
                {"email": "student2@demo.example", "role": "student"},
            ]
        },
    )
    assert r.json()["invited"] == 3, r.text
    r = w["other_admin"].post("/api/v1/institutes", json={"name": "DEMO Institute Two"})
    assert r.status_code == 201, r.text
    w["iid2"] = r.json()["institute"]["id"]
    w["run_id"] = _seed_run(app_module, w["student_id"])
    w["run2_id"] = _seed_run(app_module, w["student2_id"], score=0.3, missing=("excel",))
    return w


# ------------------------------------------------------------- permission matrix
MATRIX_PATHS = [
    ("get", "/cohort"),
    ("get", "/students"),
    ("get", "/review-queue"),
    ("get", "/cohort/report.csv"),
    ("get", "/cohort/report.pdf"),
]


@pytest.mark.parametrize("method, suffix", MATRIX_PATHS)
def test_cohort_routes_permission_matrix(world, client, method, suffix):
    iid = world["iid"]
    path = f"/api/v1/institutes/{iid}{suffix}"
    assert getattr(client, method)(path).status_code == 401  # anonymous
    assert getattr(world["student"], method)(path).status_code == 403  # own student
    assert getattr(world["outsider"], method)(path).status_code == 403  # no institute
    assert getattr(world["other_admin"], method)(path).status_code == 403  # other institute
    assert getattr(world["platform_admin"], method)(path).status_code == 403  # not a member
    assert getattr(world["counsellor"], method)(path).status_code == 200
    assert getattr(world["iadmin"], method)(path).status_code == 200


def test_member_management_permission_matrix(world, client):
    iid = world["iid"]
    members = f"/api/v1/institutes/{iid}/members"
    assert client.get(members).status_code == 401
    assert world["student"].get(members).status_code == 403
    assert world["other_admin"].get(members).status_code == 403
    assert world["counsellor"].get(members).status_code == 200  # staff can view
    assert world["iadmin"].get(members).status_code == 200
    # Removal + invites: institute_admin only.
    target = world["student2_id"]
    assert world["counsellor"].delete(f"{members}/{target}").status_code == 403
    assert world["student"].delete(f"{members}/{target}").status_code == 403
    invite = {"members": [{"email": "x@demo.example", "role": "student"}]}
    assert (
        world["counsellor"].post(f"/api/v1/institutes/{iid}/invites", json=invite).status_code
        == 403
    )
    assert world["iadmin"].delete(f"{members}/{target}").status_code == 200
    assert (
        world["iadmin"].get(f"/api/v1/institutes/{iid}/cohort").json()["cohort"]["member_count"]
        == 3
    )


def test_create_institute_rules(world, client):
    assert client.post("/api/v1/institutes", json={"name": "Anon College"}).status_code == 401
    # Already a member → 409 (one institute per user in v1).
    r = world["student"].post("/api/v1/institutes", json={"name": "Second College"})
    assert r.status_code == 409
    # Platform admin may create; they become that institute's admin.
    r = world["platform_admin"].post(
        "/api/v1/institutes", json={"name": "DEMO Platform College", "accent_color": "#123456"}
    )
    assert r.status_code == 201 and r.json()["my_role"] == "institute_admin"
    assert r.json()["seat_usage"]["seat_limit"] == 50  # documented default


def test_mine_and_detail(world):
    mine = world["student"].get("/api/v1/institutes/mine").json()
    assert mine["institute"]["id"] == world["iid"] and mine["my_role"] == "student"
    assert world["outsider"].get("/api/v1/institutes/mine").json()["institute"] is None
    assert world["outsider"].get(f"/api/v1/institutes/{world['iid']}").status_code == 403
    assert world["student"].get(f"/api/v1/institutes/{world['iid']}").status_code == 200
    assert world["iadmin"].get("/api/v1/institutes/99999").status_code == 404


# ------------------------------------------------------------- CSV import
def _csv_upload(client, iid, data: bytes, name="invites.csv"):
    return client.post(
        f"/api/v1/institutes/{iid}/invites/csv",
        files={"file": (name, data, "text/csv")},
    )


def test_csv_import_valid_malformed_duplicates(world, app_module):
    iid = world["iid"]
    _client(app_module, "csv1@demo.example")
    data = (
        b"email,name,role\n"
        b"csv1@demo.example,CSV One,student\n"
        b"not-an-email,Bad,student\n"
        b"student@demo.example,Dup,student\n"
        b"csv1@demo.example,Again,student\n"
        b"ghost@demo.example,Ghost,counsellor\n"
    )
    r = _csv_upload(world["iadmin"], iid, data)
    assert r.status_code == 200, r.text
    by_row = {row["row"]: row for row in r.json()["results"]}
    assert by_row[2]["status"] == "invited"  # csv1, first occurrence
    assert by_row[3]["status"] == "error" and by_row[3]["email"] == "not-an-email"
    assert by_row[4]["status"] == "error"  # student@ is already a member
    assert by_row[5]["status"] == "error"  # csv1 again — duplicate in this import
    assert by_row[6]["status"] == "pending"  # ghost has no account yet


def test_csv_import_whole_file_errors_are_422_not_500(world):
    iid = world["iid"]
    r = _csv_upload(world["iadmin"], iid, b"name,role\nAda,student\n")
    assert r.status_code == 422 and "email" in str(r.json())
    r = _csv_upload(world["iadmin"], iid, b"\xff\xfe\x00bad")
    assert r.status_code == 422
    r = _csv_upload(world["iadmin"], iid, b"email\n" + b"a@b.com\n" * 501)
    assert r.status_code == 422
    r = _csv_upload(world["counsellor"], iid, b"email\na@b.com\n")
    assert r.status_code == 403  # counsellor cannot invite


def test_invite_seat_limit_overflow(world, app_module):
    # Shrink the DEMO institute to its current usage, then invite → error row.
    iid = world["iid"]
    with sqlite3.connect(app_module.settings.database_path) as conn:
        conn.execute("UPDATE institutes SET seat_limit=4 WHERE id=?", (iid,))
    r = world["iadmin"].post(
        f"/api/v1/institutes/{iid}/invites",
        json={"emails": ["one-more@demo.example"]},
    )
    assert r.json()["results"][0]["status"] == "error"
    assert "Seat limit" in r.json()["results"][0]["error"]


def test_pending_invite_claim_flow(world, app_module):
    iid = world["iid"]
    r = world["iadmin"].post(
        f"/api/v1/institutes/{iid}/invites", json={"emails": ["late@demo.example"]}
    )
    assert r.json()["results"][0]["status"] == "pending"
    late = _client(app_module, "late@demo.example")
    r = late.post("/api/v1/institutes/invites/claim")
    assert r.status_code == 200 and r.json()["institute_id"] == iid
    assert late.get("/api/v1/institutes/mine").json()["my_role"] == "student"
    assert late.post("/api/v1/institutes/invites/claim").status_code == 404


# ------------------------------------------------------------- cohort privacy
def test_cohort_payload_has_no_emails_and_aggregates(world):
    r = world["counsellor"].get(f"/api/v1/institutes/{world['iid']}/cohort")
    assert r.status_code == 200
    cohort = r.json()["cohort"]
    assert cohort["member_count"] == 4 and cohort["runs_count"] == 2
    assert cohort["top_recommended_careers"][0] == {"title": "Data Analyst", "count": 2}
    assert {a["user_id"] for a in cohort["needs_attention"]} == {world["student2_id"]}
    assert "@" not in r.text  # no e-mail addresses anywhere in the payload
    csv_text = world["iadmin"].get(f"/api/v1/institutes/{world['iid']}/cohort/report.csv").text
    assert "Data Analyst" in csv_text and "student2" not in csv_text and "@" not in csv_text
    pdf = world["iadmin"].get(f"/api/v1/institutes/{world['iid']}/cohort/report.pdf")
    assert pdf.content.startswith(b"%PDF")


def test_student_detail_is_staff_only(world):
    iid = world["iid"]
    path = f"/api/v1/institutes/{iid}/students"
    rows = world["counsellor"].get(path).json()["students"]
    by_id = {row["user_id"]: row for row in rows}
    assert by_id[world["student_id"]]["runs_count"] == 1
    assert by_id[world["student_id"]]["latest_top_career"] == "Data Analyst"
    runs_path = f"{path}/{world['student_id']}/runs"
    assert world["student"].get(runs_path).status_code == 403
    assert world["other_admin"].get(runs_path).status_code == 403
    assert world["iadmin"].get(runs_path).json()["runs"][0]["id"] == world["run_id"]


# ------------------------------------------------------------- review loop
def test_counsellor_review_reaches_student_payload(world):
    iid, run_id = world["iid"], world["run_id"]
    queue = world["counsellor"].get(f"/api/v1/institutes/{iid}/review-queue").json()["queue"]
    assert {q["run_id"] for q in queue} == {world["run_id"], world["run2_id"]}
    assert (
        world["student"]
        .post(
            f"/api/v1/institutes/{iid}/runs/{run_id}/review",
            json={"note": "self", "approved": True},
        )
        .status_code
        == 403
    )
    assert (
        world["other_admin"]
        .post(f"/api/v1/institutes/{iid}/runs/{run_id}/review", json={"note": "x"})
        .status_code
        == 403
    )
    r = world["counsellor"].post(
        f"/api/v1/institutes/{iid}/runs/{run_id}/review",
        json={"note": "Strong plan — keep going.", "approved": True},
    )
    assert r.status_code == 200, r.text
    review = r.json()["counsellor_review"]
    assert review["label"] == "Reviewed by counsellor"
    assert review["reviewer_role"] == "counsellor"
    # Student's own run payload (history powers /report/[runId]).
    runs = world["student"].get("/api/v1/history").json()["runs"]
    mine = next(run for run in runs if run["id"] == run_id)
    assert mine["counsellor_review"]["note"] == "Strong plan — keep going."
    assert mine["counsellor_review"]["label"] == "Reviewed by counsellor"
    mine_reviews = world["student"].get("/api/v1/institutes/reviews/mine").json()["reviews"]
    assert mine_reviews and mine_reviews[0]["run_id"] == run_id


def test_counsellor_can_verify_own_institute_projects(world):
    r = world["student"].post(
        "/api/v1/skills/verify/python/project",
        json={
            "title": "ETL demo",
            "link": "https://example.com/etl",
            "description": "demo",
            "checklist": ["tests"],
        },
    )
    assert r.status_code == 200, r.text
    body = {"user_id": world["student_id"], "skill": "python", "approve": True}
    # A student cannot review; an other-institute admin cannot either.
    assert (
        world["student2"].post("/api/v1/skills/verify/admin/review", json=body).status_code == 403
    )
    assert (
        world["other_admin"].post("/api/v1/skills/verify/admin/review", json=body).status_code
        == 403
    )
    r = world["counsellor"].post("/api/v1/skills/verify/admin/review", json=body)
    assert r.status_code == 200 and r.json()["verification"]["status"] == "verified"


def test_platform_admin_project_review_still_works(world):
    world["student2"].post(
        "/api/v1/skills/verify/sql/project",
        json={
            "title": "SQL demo",
            "link": "https://example.com/sql",
            "description": "demo",
            "checklist": [],
        },
    )
    r = world["platform_admin"].post(
        "/api/v1/skills/verify/admin/review",
        json={"user_id": world["student2_id"], "skill": "sql", "approve": True},
    )
    assert r.status_code == 200 and r.json()["verification"]["status"] == "verified"


# ------------------------------------------------------------- DEMO e2e
def test_DEMO_institute_end_to_end(world):
    """DEMO: create → invite → run → cohort → review → export, seeded data."""
    iid = world["iid"]
    assert world["iadmin"].get(f"/api/v1/institutes/{iid}").json()["seat_usage"]["members"] == 4
    cohort = world["iadmin"].get(f"/api/v1/institutes/{iid}/cohort").json()["cohort"]
    assert cohort["most_missing_skills"][0]["skill"] in ("sql", "excel")
    world["counsellor"].post(
        f"/api/v1/institutes/{iid}/runs/{world['run2_id']}/review",
        json={"note": "DEMO review", "approved": False},
    )
    runs = world["student2"].get("/api/v1/history").json()["runs"]
    assert runs[0]["counsellor_review"]["note"] == "DEMO review"
    assert world["iadmin"].get(f"/api/v1/institutes/{iid}/cohort/report.pdf").status_code == 200
