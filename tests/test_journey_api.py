"""S3 endpoints: onboarding → discover → plan → learn → résumé → interview.

Every route requires a session (401 without one); the tests drive the full
journey through the HTTP layer so the payloads the front end consumes are
checked end to end.
"""

from __future__ import annotations

from career_guidance.profile import EXPERIENCE_LEVELS

CAREER = "15-1199.08"  # Business Intelligence Analysts (2012-era SOC, present in the catalog)


def test_journey_routes_require_a_session(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as client:
        for method, path in [
            ("get", "/api/v1/profile"),
            ("get", "/api/v1/discover/items"),
            ("get", "/api/v1/plan"),
            ("get", "/api/v1/learn"),
            ("get", "/api/v1/careers"),
            ("get", f"/api/v1/careers/{CAREER}"),
            ("get", "/api/v1/compare?ids=a,b"),
            ("get", f"/api/v1/transitions?from={CAREER}&to=15-2041.00"),
            ("get", f"/api/v1/interview/questions?career_id={CAREER}"),
            ("get", "/api/v1/gamification"),
            ("get", "/api/v1/announcements"),
            ("get", "/api/v1/me/dashboard"),
            ("get", "/api/v1/me/export"),
            ("get", "/api/v1/me/report.pdf"),
        ]:
            assert getattr(client, method)(path).status_code == 401, path


def test_profile_and_onboarding_flow(auth_client):
    client = auth_client
    options = client.get("/api/v1/profile").json()["options"]
    assert options["personas"] and options["education_levels"]

    saved = client.put(
        "/api/v1/profile",
        json={
            "persona": "Student",
            "education": "Bachelor's degree",
            "experience_level": EXPERIENCE_LEVELS[1],
            "skills": ["sql", "excel"],
            "goals": "become a data analyst",
            "hours_per_week": 8,
            "language": "ta",
        },
    )
    assert saved.status_code == 200, saved.text
    profile = saved.json()["profile"]
    assert profile["persona"] == "Student" and profile["hours_per_week"] == 8
    assert profile["skills"] == ["sql", "excel"]

    onboarded = client.post(
        "/api/v1/onboarding",
        json={
            "persona": "Student",
            "experience_level": EXPERIENCE_LEVELS[1],
            "skills": ["sql"],
            "set_target": CAREER,
        },  # noqa: E501
    ).json()
    assert onboarded["profile"]["onboarded"] is True
    assert onboarded["target"]["career_id"] == CAREER

    assert client.post("/api/v1/onboarding", json={"set_target": "nope"}).status_code == 404
    # hours are clamped to the documented range
    assert (
        client.put("/api/v1/profile", json={"hours_per_week": 999}).json()["profile"][
            "hours_per_week"
        ]
        == 40
    )


def test_discover_scoring_and_history(auth_client):
    client = auth_client
    items = client.get("/api/v1/discover/items").json()
    assert items["total"] == 36
    answers = {item["id"]: 5 if item["dim"] == "I" else 2 for item in items["items"]}
    result = client.post("/api/v1/discover", json={"answers": answers}).json()
    assert result["holland_code"].startswith("I")
    assert len(result["top_careers"]) == 15
    assert result["top_careers"][0]["why"]
    assert result["history_id"] > 0

    history = client.get("/api/v1/discover/history").json()["runs"]
    assert history and history[0]["holland_code"] == result["holland_code"]
    assert client.get("/api/v1/assessment/history").json()["runs"]

    # the assessment also feeds the gamification counters
    assert client.get("/api/v1/gamification").json()["counts"]["assessments"] == 1


def test_plan_readiness_roadmap_and_exports(auth_client):
    client = auth_client
    readiness = client.get(f"/api/v1/plan/readiness?career_id={CAREER}").json()
    assert readiness["readiness"] == 0
    assert readiness["counts"]["missing"] == len(readiness["skills"])
    assert readiness["template"]

    rated = client.post(
        "/api/v1/plan/ratings",
        json={"career_id": CAREER, "ratings": {readiness["skills"][0]["skill"]: 5}},
    ).json()
    assert rated["counts"]["strong"] == 1
    assert rated["readiness"] > 0

    plan = client.post("/api/v1/plan", json={"career_id": CAREER, "hours_per_week": 6}).json()[
        "plan"
    ]
    assert plan["plan_id"] > 0
    assert plan["weeks"] >= 1 and plan["eta"]
    assert plan["items"] and all(item["hours"] > 0 for item in plan["items"])
    assert plan["readiness_before"] < plan["readiness_after"] <= 100
    assert plan["items"][0]["resources"] is not None

    item_id = plan["items"][0]["id"]
    updated = client.patch(
        f"/api/v1/plan/{plan['plan_id']}/items", json={"item_id": item_id, "done": True}
    ).json()["plan"]  # noqa: E501
    assert next(i for i in updated["items"] if i["id"] == item_id)["done"] is True
    assert client.get("/api/v1/gamification").json()["counts"]["plan_items"] == 1
    client.patch(f"/api/v1/plan/{plan['plan_id']}/items", json={"item_id": item_id, "done": False})

    latest = client.get("/api/v1/plan").json()
    assert latest["plan"]["plan_id"] == plan["plan_id"]
    assert latest["ratings"]

    for fmt, marker in [("md", b"# "), ("json", b"{"), ("ics", b"BEGIN:VCALENDAR")]:
        response = client.get(f"/api/v1/plan/{plan['plan_id']}.{fmt}")
        assert response.status_code == 200 and response.content.startswith(marker), fmt
    pdf = client.get(f"/api/v1/plan/{plan['plan_id']}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/v1/plan/9999.md").status_code == 404
    assert client.get("/api/v1/plan/readiness?career_id=nope").status_code == 404


def test_learn_save_done_and_filters(auth_client):
    client = auth_client
    listing = client.get("/api/v1/learn?limit=5").json()
    assert listing["total"] > 0 and listing["filters"]["skills"]
    resource = listing["results"][0]

    assert client.post(f"/api/v1/learn/{resource['id']}/save").json()["saved"] is True
    saved = client.get("/api/v1/learn/saved").json()["results"]
    assert [r["id"] for r in saved] == [resource["id"]]
    assert client.delete(f"/api/v1/learn/{resource['id']}/save").json()["saved"] is False

    done = client.post(f"/api/v1/learn/{resource['id']}/done", json={"done": True}).json()
    assert done["done"] is True and done["xp"]["counts"]["courses"] == 1
    assert client.post("/api/v1/learn/999999/done", json={"done": True}).status_code == 404

    filtered = client.get("/api/v1/learn?skill=python&free=true").json()
    assert all(r["skill"] == "python" and r["free"] for r in filtered["results"])


def test_resume_score_reports_signals(auth_client):
    client = auth_client
    body = {
        "resume_text": (
            "Data analyst with 3 years of experience. Built SQL dashboards and automated "
            "Excel reports for 12 clients, cutting reporting time by 40%.\n"
            "Skills: python, sql, tableau, excel"
        ),
        "target_career_id": CAREER,
    }
    result = client.post("/api/v1/resume/score", json=body).json()
    assert 0 <= result["score"] <= 100 and result["grade"]
    assert result["keyword_coverage"]["matched"]
    assert result["target_career"]["id"] == CAREER
    assert result["summary"]
    assert result["source"].startswith("Source:")
    assert client.post("/api/v1/resume/score", json={"resume_text": "too short"}).status_code == 422
    assert (
        client.post("/api/v1/resume/score", json={**body, "target_career_id": "nope"}).status_code
        == 404
    )


def test_interview_kit_is_deterministic_and_saveable(auth_client):
    client = auth_client
    first = client.get(f"/api/v1/interview/questions?career_id={CAREER}").json()
    again = client.get(f"/api/v1/interview/questions?career_id={CAREER}").json()
    assert [q["question"] for q in first["questions"]] == [
        q["question"] for q in again["questions"]
    ]
    assert len([q for q in first["questions"] if q["kind"] == "behavioural"]) == 10
    assert len([q for q in first["questions"] if q["kind"] == "technical"]) == 10
    assert first["source"].startswith("Source:")

    other = client.get("/api/v1/interview/questions?career_id=15-2041.00").json()
    assert [q["question"] for q in other["questions"]] != [
        q["question"] for q in first["questions"]
    ]

    saved = client.post(
        "/api/v1/interview/sessions",
        json={"career_id": CAREER, "seconds": 90, "notes": {"q1": "STAR answer"}},
    ).json()
    assert saved["id"] > 0
    sessions = client.get("/api/v1/interview/sessions").json()["sessions"]
    assert sessions[0]["notes"]["q1"] == "STAR answer"
    assert client.get("/api/v1/interview/questions?career_id=nope").status_code == 404


def test_compare_and_transitions(auth_client):
    client = auth_client
    compare = client.get(f"/api/v1/compare?ids={CAREER},15-2041.00").json()
    assert len(compare["careers"]) == 2
    assert compare["table"] and compare["template"]
    assert compare["careers"][0]["market"]["source"]
    assert compare["careers"][0]["salary_band_in"]
    assert client.get(f"/api/v1/compare?ids={CAREER}").status_code == 422
    assert client.get(f"/api/v1/compare?ids={CAREER},nope").status_code == 404

    path = client.get(f"/api/v1/transitions?from={CAREER}&to=15-2041.00").json()
    assert {"from", "to", "hops", "found", "path", "template"} <= set(path)
    assert client.get("/api/v1/transitions?from=nope&to=nope").status_code == 404


def test_careers_browse_and_detail(auth_client):
    client = auth_client
    listing = client.get("/api/v1/careers?limit=10").json()
    assert listing["total"] > 900 and len(listing["results"]) == 10
    assert listing["source"].startswith("Source:")
    assert listing["results"][0]["salary_p50"] is None or listing["results"][0]["salary_p50"] >= 0

    detail = client.get(f"/api/v1/careers/{CAREER}").json()
    assert detail["title"]
    assert detail["tasks"] and detail["tasks"][0]["source"].startswith("Source:")
    assert detail["education_path"]
    assert detail["skill_importance"]
    assert detail["market"]["salary_p50"]
    assert detail["market_us"]["currency"] == "USD"
    assert detail["transitions_in"]
    assert detail["family"]
    assert client.get("/api/v1/careers/nope").status_code == 404
    assert client.get("/api/v1/careers/search?q=data").json()["results"]


def test_gamification_feedback_and_dashboard(auth_client):
    client = auth_client
    client.post("/api/v1/plan/target", json={"career_id": CAREER})
    client.post(
        "/api/v1/recommend", json={"skills": "sql excel", "experience_level": EXPERIENCE_LEVELS[0]}
    )

    dashboard = client.get("/api/v1/me/dashboard").json()
    assert dashboard["target"]["career_id"] == CAREER
    assert dashboard["readiness"]["readiness"] == 0
    assert dashboard["xp"]["xp"] > 0
    assert dashboard["recent_runs"] and dashboard["recent_runs"][0]["recommendations"]
    assert "streak" in dashboard

    event = client.post("/api/v1/gamification/event", json={"kind": "run"}).json()
    assert event["counts"]["runs"] >= 1
    assert client.post("/api/v1/gamification/event", json={"kind": "nonsense"}).status_code == 422

    assert (
        client.post(
            "/api/v1/feedback", json={"rating": 5, "comment": "great", "tool": "recommend"}
        ).json()["id"]
        > 0
    )
    assert client.get("/api/v1/announcements").json()["announcements"] == []

    exported = client.get("/api/v1/me/export").json()
    assert exported["profile"] and exported["account"]["email"]
    assert "plans" in exported and "xp_events" in exported

    report = client.get("/api/v1/me/report.pdf")
    assert report.status_code == 200 and report.content.startswith(b"%PDF")


def test_recommend_response_is_explainable(auth_client):
    client = auth_client
    response = client.post(
        "/api/v1/recommend",
        json={
            "skills": "sql, excel, python, tally",
            "goals": "data analyst",
            "experience_level": EXPERIENCE_LEVELS[1],
            "education": "Bachelor's degree",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "matcher-v2"
    assert body["weights"] == {"skills": 0.55, "interests": 0.3, "job_zone": 0.15}
    assert body["run_id"]
    rec = body["recommendations"][0]
    assert rec["why"] and all(isinstance(line, str) for line in rec["why"])
    assert rec["market"]["source"].startswith("Source:")
    assert rec["score_parts"]["skills"] >= 0
    assert rec["provenance"]["ids"] == [rec["career_id"]]
    assert any("O*NET" in s or "template" in s for s in rec["provenance"]["sources"])


def test_recommend_uses_stored_interests(auth_client):
    """An interests-only user still gets ranked careers (interest term active)."""
    client = auth_client
    items = client.get("/api/v1/discover/items").json()["items"]
    client.post("/api/v1/discover", json={"answers": {i["id"]: 3 for i in items}})
    body = client.post(
        "/api/v1/recommend",
        json={"skills": "communication", "experience_level": EXPERIENCE_LEVELS[0]},
    ).json()
    assert body["recommendations"]
    assert all(rec["score_parts"]["interests"] >= 0 for rec in body["recommendations"])


def test_pathway_answers_the_qualification_question(auth_client):
    """The flagship flow: “I want to be a doctor but I did B.Tech.”"""
    client = auth_client
    signals = client.get("/api/v1/pathway/signals").json()
    assert signals["experience_levels"] and signals["education_levels"]

    doctor = client.post(
        "/api/v1/pathway",
        json={
            "career_id": "29-1069.03",  # Hospitalists — an MBBS-gated role
            "resume_text": (
                "B.Tech Information Technology, 3 years experience as a business analyst. "
                "SQL, Excel, Tableau, Python."
            ),
            "hours_per_week": 8,
        },
    ).json()
    assert doctor["verdict"]["verdict"] == "blocked"
    assert doctor["verdict"]["hard_blockers"]
    assert doctor["verdict"]["profession"]["label"].startswith("Doctor")
    assert doctor["bridges"], "a blocked verdict must offer real bridge programmes"
    titles = " ".join(bridge["title"] for bridge in doctor["bridges"])
    assert "Nursing" in titles or "Physiotherapy" in titles or "Health" in titles
    assert all(bridge["duration"] for bridge in doctor["bridges"])
    assert doctor["verdict"]["requirements"] and doctor["plan"]["phases"]
    assert doctor["plan"]["weeks"] >= 1 and doctor["plan"]["eta"]
    assert doctor["open_doors"], "blocked paths must list doors open to any degree"
    assert doctor["sources"]["pathways"].startswith("Source:")

    # A role any graduate can enter: the verdict is reachable, with a plan.
    law = client.post(
        "/api/v1/pathway",
        json={
            "career_id": "23-1011.00",
            "resume_text": "B.Tech IT, 3 years experience. SQL, Excel, Tableau.",
            "hours_per_week": 6,
        },
    ).json()
    assert law["verdict"]["verdict"] in {"reachable", "blocked"}
    assert law["bridges"] and any("LLB" in b["title"] for b in law["bridges"])
    assert law["signals"]["experience_level"] == "Mid-level (2-5 years)"
    assert law["plan"]["phases"][0]["focus_skills"]

    # Resumé parsing is best-effort and always reported back to the user.
    parsed = client.post(
        "/api/v1/pathway",
        json={
            "career_id": CAREER,
            "resume_text": "M.Sc Statistics, 6 years experience with SQL and Python",
        },
    ).json()
    assert parsed["signals"]["education"] == "Master's degree"
    assert parsed["signals"]["experience_years"] == 6.0

    assert client.post("/api/v1/pathway", json={"career_id": "nope"}).status_code == 404
    assert (
        client.post(
            "/api/v1/pathway", json={"career_id": CAREER, "experience_level": "nope"}
        ).status_code
        == 422
    )


def test_ladder_lists_real_rungs(auth_client):
    client = auth_client
    client.post("/api/v1/plan/target", json={"career_id": CAREER})
    ladder = client.get("/api/v1/ladder").json()
    assert ladder["current"]["id"] == CAREER
    assert ladder["step_across"] or ladder["step_up"]
    rung = (ladder["step_up"] or ladder["step_across"])[0]
    assert rung["title"] and 0 <= rung["coverage"] <= 100
    assert rung["weeks_at_your_pace"] >= 1 and rung["source"].startswith("Source:")
    assert rung["family"] and rung["demand_label"]
    assert client.get("/api/v1/ladder?career_id=nope").status_code == 404

    detail = client.get(f"/api/v1/careers/{CAREER}").json()
    assert detail["ladder"]["step_up"] or detail["ladder"]["step_across"]
