"""Phase 2: crosswalk, india market, Reality Score, report API fields."""

from __future__ import annotations

import copy

from career_guidance.india import india_market_for, load_crosswalk, lookup_crosswalk
from career_guidance.reality import WEIGHTS, compute_reality
from career_guidance.taxonomy import Occupation, load_taxonomy


def _occ(**kw):
    base = dict(
        id="15-1132.00",
        title="Software Developers, Applications",
        description="Build software applications.",
        job_zone=4,
        skills=["Programming"],
        knowledge=["Computers and Electronics"],
    )
    base.update(kw)
    return Occupation(**base)


def test_crosswalk_known_mapping_resolves():
    tax = load_taxonomy()
    entry = lookup_crosswalk(tax.get("15-1132.00"))
    assert entry and entry["nco_code"] == "2512" and entry["isco_code"] == "2512"
    assert entry["confidence"] in {"high", "medium", "low"}
    assert len(load_crosswalk()) >= 40


def test_crosswalk_unknown_returns_empty():
    fake = Occupation(
        id="99-9999.00", title="Nonexistent Occupation XYZ", description="", job_zone=3
    )
    assert lookup_crosswalk(fake) is None
    assert lookup_crosswalk(onet_code="00-0000.00", title="Nope") is None


def test_india_market_is_labelled_estimate():
    tax = load_taxonomy()
    m = india_market_for(tax.get("15-1132.00"))
    assert m and m["kind"] == "estimate"
    assert "not official" in m["source"]
    assert m["source_url"] == ""
    assert len(m["fresher_salary_inr"]) == 2 and len(m["salary_7yr_inr"]) == 2
    assert m["fresher_salary_inr"][1] <= m["salary_7yr_inr"][1]


def test_reality_bounds_and_structure():
    r = compute_reality(_occ())
    assert r["score"] is not None and 0 <= r["score"] <= 100
    assert 0 < r["confidence"] <= 1
    assert {c["key"] for c in r["components"]} == set(WEIGHTS)
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert r["india"]["crosswalk"]["nco_code"] == "2512"


def test_reality_missing_data_excluded_and_confidence_drops():
    full = compute_reality(_occ())
    bare = compute_reality(_occ(), india={"crosswalk": {}, "market": None})
    assert "salary_ladder" in bare["missing_components"]
    assert "entry_demand" in bare["missing_components"]
    assert bare["confidence"] < full["confidence"]
    comp = {c["key"]: c for c in bare["components"]}
    assert (
        comp["salary_ladder"]["status"] == "insufficient_data"
        and comp["salary_ladder"]["value"] is None
    )
    # score is averaged over available components only, still bounded
    assert bare["score"] is not None and 0 <= bare["score"] <= 100


def test_reality_monotonic_demand():
    occ = _occ()
    from career_guidance.india import india_payload

    base = india_payload(occ)
    low = copy.deepcopy(base)
    low["market"]["demand"] = 1
    low["market"]["entry_demand_trend"] = "declining"
    high = copy.deepcopy(base)
    high["market"]["demand"] = 5
    high["market"]["entry_demand_trend"] = "rising"
    assert compute_reality(occ, high)["score"] >= compute_reality(occ, low)["score"]


def test_reality_monotonic_barrier():
    low_barrier = compute_reality(_occ(job_zone=2))
    high_barrier = compute_reality(_occ(job_zone=5))
    assert low_barrier["score"] >= high_barrier["score"]


def test_report_api_has_reality_why_not_alternatives(client):
    r = client.post(
        "/api/v1/recommend", json={"skills": "Python, SQL, Excel", "goals": "data analyst"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # additive: old fields unchanged
    for key in ("run_id", "provider", "recommendations", "priority_skills", "weights", "source"):
        assert key in body
    assert "why_not" in body and "alternatives" in body
    assert isinstance(body["why_not"], list) and isinstance(body["alternatives"], list)
    for w in body["why_not"]:
        assert w["match_percent"] is not None and "matcher" in w["source"]
    rec = body["recommendations"][0]
    assert rec["reality"] and 0 <= rec["reality"]["score"] <= 100
    assert rec["reality"]["india"]["market"]["kind"] == "estimate"
    assert any("india_market" in s for s in body.get("provenance_sources", []))


def test_admin_india_market_anonymous_locked(client):
    assert client.get("/api/v1/admin/india-market").status_code == 401


def test_admin_india_market_non_admin_forbidden(auth_client):
    assert auth_client.get("/api/v1/admin/india-market").status_code in (401, 403)


def test_admin_india_market_roundtrip_and_auth(admin_client):
    got = admin_client.get("/api/v1/admin/india-market")
    assert got.status_code == 200 and got.json()["entries"]
    put = admin_client.put(
        "/api/v1/admin/india-market",
        json={"overrides": {"software-engineering": {"demand": 5, "top_cities": ["Bengaluru"]}}},
    )
    assert put.status_code == 200, put.text
    again = admin_client.get("/api/v1/admin/india-market").json()
    assert again["overrides"]["software-engineering"]["demand"] == 5
    audit = admin_client.get("/api/v1/admin/audit").json()["log"]
    assert any("india-market:update" in row["action"] for row in audit)
