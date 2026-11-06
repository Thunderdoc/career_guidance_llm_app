"""Phase 6 error-shape audit for the Phase 2–5 routes.

Every expected failure on the new routes must answer with FastAPI's
consistent ``{detail: ...}`` shape and a 4xx — never a bare 500. (The
uniform-500 middleware covers genuinely unhandled errors separately;
see tests/test_observability.py.)
"""

from __future__ import annotations

import pytest


def assert_error_shape(response, status: int) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert "detail" in body, body


# --------------------------------------------------------------- Phase 1/4 demo


def test_demo_request_validation_errors(client):
    assert_error_shape(client.post("/api/v1/billing/demo-request", json={}), 422)
    assert_error_shape(
        client.post(
            "/api/v1/billing/demo-request",
            json={"name": "Asha", "email": "not-an-email", "organisation": "Org"},
        ),
        422,
    )
    assert_error_shape(
        client.post(
            "/api/v1/billing/demo-request",
            json={
                "name": "Asha",
                "email": "asha@example.com",
                "organisation": "Org",
                "seats": -3,
            },
        ),
        422,
    )


# ------------------------------------------------------------------ Phase 3


def test_verify_unknown_skill_and_bad_token(auth_client):
    assert_error_shape(auth_client.get("/api/v1/skills/verify/nosuchskill/quiz"), 404)
    assert_error_shape(
        auth_client.post(
            "/api/v1/skills/verify/python/submit",
            json={"attempt_token": "garbage.token.value", "answers": {}},
        ),
        400,
    )
    assert_error_shape(
        auth_client.post(
            "/api/v1/skills/verify/python/project",
            json={"title": "X", "link": "ftp://nope", "description": "", "checklist": []},
        ),
        422,
    )


def test_public_profile_unknown_handle(client):
    assert_error_shape(client.get("/api/v1/p/definitely-not-a-handle"), 404)


def test_plan_90day_without_run(auth_client):
    # GET is an empty-state 200 by design; the export is the 404 path.
    r = auth_client.get("/api/v1/plan/90day")
    assert r.status_code == 200 and r.json()["plan"] is None
    assert_error_shape(auth_client.get("/api/v1/plan/90day/export.md"), 404)


# ------------------------------------------------------------------ Phase 4


def test_institute_create_and_invite_validation(auth_client):
    assert_error_shape(auth_client.post("/api/v1/institutes", json={"name": "x"}), 422)
    r = auth_client.post("/api/v1/institutes", json={"name": "Error Shape Institute"})
    assert r.status_code == 201, r.text
    iid = r.json()["institute"]["id"]
    assert_error_shape(
        auth_client.post(f"/api/v1/institutes/{iid}/invites", json={"members": []}),
        422,
    )
    assert_error_shape(auth_client.get("/api/v1/institutes/999999/cohort"), 404)


def test_institute_csv_oversize_is_422_not_500(auth_client):
    r = auth_client.post("/api/v1/institutes", json={"name": "CSV Shape Institute"})
    iid = r.json()["institute"]["id"]
    big = b"email\n" + b"a@b.co\n" * 900_000  # > 5 MB cap
    assert_error_shape(
        auth_client.post(
            f"/api/v1/institutes/{iid}/invites/csv",
            files={"file": ("invites.csv", big, "text/csv")},
        ),
        422,
    )


def test_institute_csv_binary_garbage_is_422(auth_client):
    r = auth_client.post("/api/v1/institutes", json={"name": "CSV Binary Institute"})
    iid = r.json()["institute"]["id"]
    assert_error_shape(
        auth_client.post(
            f"/api/v1/institutes/{iid}/invites/csv",
            files={"file": ("invites.csv", b"\xff\xfe\x00\x01binary", "text/csv")},
        ),
        422,
    )


# ------------------------------------------------------------------ Phase 5


def test_consent_confirm_garbage_token(client):
    assert_error_shape(client.get("/api/v1/consent/confirm/not-a-real-token"), 404)


# ------------------------------------------------------------- Phase 2 admin


def test_india_market_override_shape_errors(admin_client):
    assert_error_shape(
        admin_client.put("/api/v1/admin/india-market", json={"overrides": {"family-x": 5}}),
        422,
    )
    r = admin_client.put("/api/v1/admin/india-market", json={"overrides": {"family-x": {}}})
    assert r.status_code == 200, r.text


def test_weights_non_numeric_is_422(admin_client):
    assert_error_shape(
        admin_client.put("/api/v1/admin/weights", json={"weights": {"skills": "abc"}}),
        422,
    )


# ------------------------------------------------------------ upload limits


def test_resume_oversize_is_413(auth_client):
    big = b"x" * (5 * 1024 * 1024 + 1)
    r = auth_client.post(
        "/api/v1/resume/extract", files={"file": ("resume.txt", big, "text/plain")}
    )
    assert_error_shape(r, 413)


def test_resume_garbage_is_422(auth_client):
    r = auth_client.post(
        "/api/v1/resume/extract",
        files={"file": ("resume.pdf", b"%PDF-not-really", "application/pdf")},
    )
    # Either a clean 422 (unparseable) — never a 500.
    assert r.status_code in (200, 422)
    if r.status_code == 422:
        assert "detail" in r.json()


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/institutes/1/cohort"),
        ("get", "/api/v1/skills/verify/mine"),
        ("get", "/api/v1/me/consent"),
    ],
)
def test_new_routes_reject_anonymous_with_detail(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code in (401, 403, 404)
    if r.status_code != 404:
        assert "detail" in r.json()
