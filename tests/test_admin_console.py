"""S4 admin console: every endpoint answers 401 / 403 / 200 (or 422/404).

The console is the only place that writes to the catalogue, the synonym table,
the templates and the settings, so each write route is exercised for real and
the audit trail is checked afterwards.
"""

from __future__ import annotations

import io
import json

import pytest

CAREER = "15-1199.08"

READ_ROUTES = [
    "/api/v1/admin/overview",
    "/api/v1/admin/users",
    "/api/v1/admin/users.csv",
    "/api/v1/admin/runs",
    "/api/v1/admin/runs.csv",
    "/api/v1/admin/runs.json",
    "/api/v1/admin/careers?limit=5",
    "/api/v1/admin/careers.csv",
    "/api/v1/admin/synonyms",
    "/api/v1/admin/unmatched",
    "/api/v1/admin/resources",
    "/api/v1/admin/resources.yaml",
    "/api/v1/admin/resource-overrides",
    "/api/v1/admin/assessment-items",
    "/api/v1/admin/weights",
    "/api/v1/admin/settings",
    "/api/v1/admin/templates",
    "/api/v1/admin/interview-templates",
    "/api/v1/admin/feedback",
    "/api/v1/admin/announcements",
    "/api/v1/admin/system",
    "/api/v1/admin/audit",
    "/api/v1/admin/backup.db",
]


def test_admin_routes_refuse_anonymous_and_plain_users(app_module, auth_client):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as anonymous:
        for path in READ_ROUTES:
            assert anonymous.get(path).status_code == 401, path
    for path in READ_ROUTES:
        response = auth_client.get(path)
        assert response.status_code == 403, path
    assert auth_client.get("/api/v1/admin/system").json()["detail"]


def test_admin_read_routes_answer_200_with_data(admin_client):
    for path in READ_ROUTES:
        response = admin_client.get(path)
        assert response.status_code == 200, (path, response.text[:200])
    overview = admin_client.get("/api/v1/admin/overview").json()
    assert overview["users"]["total"] >= 1
    assert overview["system"]["occupations"] > 900
    assert overview["system"]["db_bytes"] > 0 and "uptime_s" in overview["system"]
    assert admin_client.get("/api/v1/admin/backup.db").content[:15] == b"SQLite format 3"


def test_admin_careers_editing_round_trip(admin_client):
    listing = admin_client.get("/api/v1/admin/careers?q=Business%20Intelligence&limit=5").json()
    assert listing["careers"] and listing["total"] >= 1
    assert any(row["id"] == CAREER for row in listing["careers"])

    patched = admin_client.patch(
        f"/api/v1/admin/careers/{CAREER}",
        json={"salary_p50": 1234567, "trend": "rising", "remote": True, "notes": "QA check"},
    )
    assert patched.status_code == 200
    assert patched.json()["override"]["salary_p50"] == 1234567

    # India override shows up on the public career page.
    detail = admin_client.get(f"/api/v1/careers/{CAREER}").json()
    assert detail["market"]["salary_p50"] == 1234567
    assert detail["market"]["trend"] in {"up", "rising"}

    hidden = admin_client.patch(f"/api/v1/admin/careers/{CAREER}", json={"hidden": True})
    assert hidden.status_code == 200
    assert admin_client.get(f"/api/v1/careers/{CAREER}").status_code == 404
    assert (
        admin_client.patch(f"/api/v1/admin/careers/{CAREER}", json={"hidden": False}).status_code
        == 200
    )

    created = admin_client.post(
        "/api/v1/admin/careers",
        json={
            "id": "TEST-0001",
            "title": "QA Test Role",
            "description": "Created by the test suite.",
            "job_zone": 3,
            "skills": ["Testing"],
        },
    )
    assert created.status_code == 200 and created.json()["id"] == "TEST-0001"
    assert admin_client.get("/api/v1/careers/TEST-0001").status_code == 200
    assert admin_client.delete("/api/v1/admin/careers/TEST-0001").status_code == 200
    assert admin_client.get("/api/v1/careers/TEST-0001").status_code == 404

    csv_body = "id,title,description,job_zone,skills\nTEST-0002,CSV Role,Imported,2,Testing\n"
    imported = admin_client.post(
        "/api/v1/admin/careers/import",
        files={"file": ("careers.csv", csv_body, "text/csv")},
    )
    assert imported.status_code == 200 and imported.json()["imported"] == 1
    assert admin_client.get("/api/v1/careers/TEST-0002").status_code == 200
    admin_client.delete("/api/v1/admin/careers/TEST-0002")

    assert (
        admin_client.patch("/api/v1/admin/careers/nope", json={"hidden": True}).status_code == 404
    )


def test_admin_synonyms_and_unmatched_mapping(admin_client):
    created = admin_client.post(
        "/api/v1/admin/synonyms",
        json={"alias": "qa test alias", "canonical": "sql", "locale": "en"},
    )
    assert created.status_code == 200
    listing = admin_client.get("/api/v1/admin/synonyms?q=qa test").json()
    assert any(row["alias"] == "qa test alias" for row in listing["synonyms"])
    assert (
        admin_client.post(
            "/api/v1/admin/synonyms", json={"alias": "qa test alias", "canonical": "python"}
        ).status_code
        == 200
    )  # upsert, not a duplicate
    assert admin_client.delete("/api/v1/admin/synonyms/qa test alias").status_code == 200

    # An unmatched term is logged by /recommend and can be mapped from the console.
    admin_client.post(
        "/api/v1/recommend",
        json={"skills": "zorbatrix widget", "experience_level": "Junior (0-2 years)"},
    )
    unmatched = admin_client.get("/api/v1/admin/unmatched").json()["unmatched"]
    assert unmatched, "unmatched skills must be logged for the mapping table"
    assert (
        admin_client.post(
            "/api/v1/admin/unmatched/map", json={"term": unmatched[0]["term"], "canonical": "sql"}
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            "/api/v1/admin/unmatched/dismiss", json={"term": unmatched[0]["term"]}
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            "/api/v1/admin/unmatched/map", json={"term": "", "canonical": ""}
        ).status_code
        == 422
    )


def test_admin_resources_crud_and_link_check(admin_client):
    created = admin_client.post(
        "/api/v1/admin/resources",
        json={
            "skill": "sql",
            "title": "QA resource",
            "url": "https://example.org/qa",
            "provider": "QA Provider",
            "level": "beginner",
            "language": "en",
            "free": True,
        },
    )
    assert created.status_code == 200
    resource_id = created.json()["id"]
    assert any(
        row["title"] == "QA resource"
        for row in admin_client.get("/api/v1/admin/resources?q=QA resource").json()["resources"]
    )
    assert (
        admin_client.put(
            f"/api/v1/admin/resources/{resource_id}",
            json={
                "skill": "sql",
                "title": "QA resource v2",
                "url": "https://example.org/qa2",
                "free": False,
            },
        ).status_code
        == 200
    )
    assert admin_client.post("/api/v1/admin/resources/check").status_code == 200
    assert admin_client.delete(f"/api/v1/admin/resources/{resource_id}").status_code == 200
    assert admin_client.delete(f"/api/v1/admin/resources/{resource_id}").status_code == 404
    assert (
        admin_client.post(
            "/api/v1/admin/resources", json={"skill": "", "title": "", "url": ""}
        ).status_code
        == 422
    )

    # Legacy skill → resource override table still works and feeds /learn.
    assert (
        admin_client.put(
            "/api/v1/admin/resource-overrides/sql",
            json={
                "resources": [
                    {
                        "title": "Override course",
                        "url": "https://example.org/o",
                        "provider": "X",
                        "free": True,
                    }
                ]
            },
        ).status_code
        == 200
    )
    overrides = admin_client.get("/api/v1/admin/resource-overrides?q=sql").json()["skills"]
    entry = next(row for row in overrides if row["skill"] == "sql")
    assert entry["overridden"] is True
    assert admin_client.delete("/api/v1/admin/resource-overrides/sql").status_code == 200


def test_admin_assessment_items_and_templates(admin_client):
    items = admin_client.get("/api/v1/admin/assessment-items").json()["items"]
    assert len(items) >= 36
    assert (
        admin_client.post(
            "/api/v1/admin/assessment-items",
            json={"id": "qa1", "dim": "I", "text": "QA statement about research", "weight": 1.5},
        ).status_code
        == 200
    )
    assert any(
        row["id"] == "qa1"
        for row in admin_client.get("/api/v1/admin/assessment-items").json()["items"]
    )
    assert admin_client.delete("/api/v1/admin/assessment-items/qa1").status_code == 200
    assert admin_client.post(
        "/api/v1/admin/assessment-items", json={"id": "bad", "dim": "Z", "text": "x"}
    ).status_code in {200, 422}

    templates = admin_client.get("/api/v1/admin/templates").json()
    assert templates["templates"] and templates["rendered"]
    key = sorted(templates["templates"])[0]
    assert (
        admin_client.put(
            "/api/v1/admin/templates",
            json={"locale": "en", "templates": {key: "QA override {matched_count}"}},
        ).status_code
        == 200
    )
    assert (
        admin_client.get("/api/v1/admin/templates")
        .json()["templates"][key]
        .startswith("QA override")
    )

    assert (
        admin_client.post(
            "/api/v1/admin/interview-templates",
            json={"kind": "behavioural", "template": "Tell me about {skill}.", "career_id": CAREER},
        ).status_code
        == 200
    )
    rows = admin_client.get("/api/v1/admin/interview-templates").json()["templates"]
    assert (
        rows
        and admin_client.delete(f"/api/v1/admin/interview-templates/{rows[-1]['id']}").status_code
        == 200
    )
    assert admin_client.delete("/api/v1/admin/interview-templates/99999").status_code == 404


def test_admin_weights_settings_and_feature_flags(admin_client):
    assert admin_client.get("/api/v1/admin/weights").json()["weights"].keys() == {
        "skills",
        "interests",
        "job_zone",
    }
    updated = admin_client.put(
        "/api/v1/admin/weights",
        json={"weights": {"skills": 0.5, "interests": 0.3, "job_zone": 0.2}},
    )
    assert updated.status_code == 200
    assert admin_client.post(
        "/api/v1/recommend",
        json={"skills": "sql excel", "experience_level": "Junior (0-2 years)"},
    ).json()["weights"] == {"skills": 0.5, "interests": 0.3, "job_zone": 0.2}
    assert admin_client.put("/api/v1/admin/weights", json={"weights": {}}).status_code == 422
    assert (
        admin_client.put(
            "/api/v1/admin/weights", json={"weights": {"skills": 0, "interests": 0, "job_zone": 0}}
        ).status_code
        == 422
    )

    settings = admin_client.get("/api/v1/admin/settings").json()
    assert settings["settings"] and "flags" in settings
    patched = admin_client.put(
        "/api/v1/admin/settings",
        json={"values": {"flags.discover": False, "roadmap.hours_per_week": 8}},
    )
    assert patched.status_code == 200
    # The feature flag really switches the module off for users.
    assert admin_client.get("/api/v1/discover/items").status_code == 503
    assert (
        admin_client.put(
            "/api/v1/admin/settings", json={"values": {"flags.discover": True}}
        ).status_code
        == 200
    )
    assert admin_client.get("/api/v1/discover/items").status_code == 200
    assert (
        admin_client.put("/api/v1/admin/settings", json={"values": {"nope.nope": 1}}).status_code
        == 422
    )


def test_admin_users_feedback_and_announcements(admin_client, app_module):
    from fastapi.testclient import TestClient

    from tests.conftest import login

    # A second, ordinary account so role/disable/delete act on someone else.
    with TestClient(app_module.app) as member:
        login(member, email="qa-member@example.org")
        member.post(
            "/api/v1/recommend", json={"skills": "sql", "experience_level": "Junior (0-2 years)"}
        )
    users = admin_client.get("/api/v1/admin/users").json()
    assert users["total"] >= 2
    other = next(row for row in users["users"] if row["email"] == "qa-member@example.org")
    profile = admin_client.get(f"/api/v1/admin/users/{other['id']}").json()
    assert profile["user"]["email"] == other["email"]

    assert (
        admin_client.patch(
            f"/api/v1/admin/users/{other['id']}/role", json={"role": "admin"}
        ).status_code
        == 200
    )
    assert (
        admin_client.patch(
            f"/api/v1/admin/users/{other['id']}/disabled", json={"disabled": True}
        ).status_code
        == 200
    )
    assert (
        admin_client.patch(
            f"/api/v1/admin/users/{other['id']}/role", json={"role": "nope"}
        ).status_code
        == 422
    )
    assert admin_client.get("/api/v1/admin/users/missing-user").status_code == 404
    assert admin_client.delete(f"/api/v1/admin/users/{other['id']}").status_code == 200
    assert admin_client.get(f"/api/v1/admin/users/{other['id']}").status_code == 404

    feedback = admin_client.post(
        "/api/v1/feedback", json={"rating": 4, "comment": "QA feedback", "tool": "recommend"}
    ).json()
    flagged = admin_client.patch(
        f"/api/v1/admin/feedback/{feedback['id']}", json={"status": "seen", "note": "ok"}
    )
    assert flagged.status_code == 200
    assert any(
        row["comment"] == "QA feedback"
        for row in admin_client.get("/api/v1/admin/feedback").json()["feedback"]
    )
    assert (
        admin_client.patch("/api/v1/admin/feedback/99999", json={"status": "new"}).status_code
        == 404
    )
    assert (
        admin_client.patch(
            f"/api/v1/admin/feedback/{feedback['id']}", json={"status": "bogus"}
        ).status_code
        == 422
    )

    created = admin_client.post(
        "/api/v1/admin/announcements",
        json={"title": "QA announcement", "body": "Hello", "level": "warning", "pinned": True},
    )
    assert created.status_code == 200
    announcement_id = created.json()["id"]
    assert any(
        row["title"] == "QA announcement"
        for row in admin_client.get("/api/v1/announcements").json()["announcements"]
    )
    assert (
        admin_client.patch(
            f"/api/v1/admin/announcements/{announcement_id}", json={"active": False}
        ).status_code
        == 200
    )
    assert admin_client.delete(f"/api/v1/admin/announcements/{announcement_id}").status_code == 200
    assert (
        admin_client.patch("/api/v1/admin/announcements/99999", json={"active": False}).status_code
        == 404
    )


def test_admin_runs_export_and_system_tools(admin_client):
    run = admin_client.post(
        "/api/v1/recommend",
        json={"skills": "sql excel", "experience_level": "Junior (0-2 years)"},
    ).json()
    runs = admin_client.get("/api/v1/admin/runs?q=sql").json()
    assert runs["total"] >= 1
    assert (
        admin_client.patch(
            f"/api/v1/admin/runs/{run['run_id']}/flag", json={"flagged": True}
        ).status_code
        == 200
    )
    assert admin_client.get("/api/v1/admin/runs?flagged=true").json()["total"] >= 1
    assert (
        admin_client.patch("/api/v1/admin/runs/999999/flag", json={"flagged": True}).status_code
        == 404
    )

    csv_export = admin_client.get("/api/v1/admin/runs.csv")
    assert csv_export.text.splitlines()[0].startswith("id,created_at")
    assert admin_client.get("/api/v1/admin/runs.xml").status_code == 404
    assert admin_client.get("/api/v1/admin/users.csv").text.splitlines()[0].startswith("id,email")
    assert admin_client.get("/api/v1/admin/careers.csv").text.splitlines()[0].startswith("id,title")

    system = admin_client.get("/api/v1/admin/system").json()
    assert system["disk"]["db_bytes"] > 0 and system["migrations"]
    assert system["env"] and all(set(row) == {"name", "value"} for row in system["env"])
    assert system["health"]["status"] == "ok"
    assert admin_client.post("/api/v1/admin/cache/clear").json()["cleared"] is True

    backup = admin_client.get("/api/v1/admin/backup.db").content
    assert admin_client.post("/api/v1/admin/restore", json={}).status_code == 422  # file required

    audit = admin_client.get("/api/v1/admin/audit").json()["log"]
    actions = {row["action"] for row in audit}
    assert "system:cache-clear" in actions
    assert any(row["actor"] for row in audit)
    assert backup  # keep the reference so the assertion above cannot be optimised away

    assert admin_client.delete(f"/api/v1/admin/runs/{run['run_id']}").status_code == 200


def test_admin_restore_accepts_an_uploaded_database(admin_client):
    """Restore replaces the working database with the uploaded SQLite file."""
    backup = admin_client.get("/api/v1/admin/backup.db").content
    restored = admin_client.post(
        "/api/v1/admin/restore",
        files={"file": ("backup.db", io.BytesIO(backup), "application/octet-stream")},
    )
    assert restored.status_code == 200
    assert restored.json()["restored"] is True and "migrations" in restored.json()
    assert admin_client.get("/api/v1/admin/overview").status_code == 200

    bad = admin_client.post(
        "/api/v1/admin/restore",
        files={"file": ("bad.db", io.BytesIO(b"not a database"), "application/octet-stream")},
    )
    assert bad.status_code == 422


def test_admin_console_writes_are_audited(admin_client):
    admin_client.put(
        "/api/v1/admin/weights",
        json={"weights": {"skills": 0.55, "interests": 0.3, "job_zone": 0.15}},
    )
    entries = admin_client.get("/api/v1/admin/audit?limit=50").json()["log"]
    assert any(entry["action"].startswith("settings:weights") for entry in entries)
    assert all("actor" in entry and "created_at" in entry for entry in entries)
    assert any(entry["action"].startswith("settings:weights") for entry in entries)
    # The audit log is append-only through the API.
    assert admin_client.delete("/api/v1/admin/audit").status_code in {404, 405}


@pytest.mark.parametrize(
    "path",
    ["/api/v1/admin/overview", "/api/v1/admin/users", "/api/v1/admin/settings"],
)
def test_admin_401_body_is_json(app_module, path):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as anonymous:
        response = anonymous.get(path)
    assert response.status_code == 401
    assert json.loads(response.text)["detail"]


def test_admin_overview_aggregates_existing_runs(admin_client):
    """Regression: overview crashed with AttributeError once runs existed."""
    admin_client.post(
        "/api/v1/recommend",
        json={
            "skills": "sql, excel, tableau",
            "goals": "data analyst",
            "experience_level": "Junior (0-2 years)",
            "education": "Bachelor's degree",
        },
    )
    overview = admin_client.get("/api/v1/admin/overview").json()
    assert overview["runs"]["total"] >= 1
    assert overview["runs"]["per_day"]
    assert overview["top_requested_skills"], "requested skills must be counted from the runs"
    assert all(isinstance(row, list) and len(row) == 2 for row in overview["top_requested_skills"])
    assert overview["averages"]["match"] >= 0
    assert "top_missing_skills" in overview and "errors" in overview
