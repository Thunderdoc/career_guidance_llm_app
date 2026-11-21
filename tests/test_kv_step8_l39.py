"""Kaam-Vaani Step 8A, inherited item L39: the central-sphere wage
tables wired into the scam check's pay-plausibility framework.

Covers: the tables load (7 employments, provenance), the monthly
bands (pinned rupee figures from the VDA order), employment
matching (longest phrase wins, word boundaries — "mines" must not
match "determines"), the four verdicts (below_minimum /
above_range / within_central_range / unknown, including the
piece-rate exclusion), the advisory-only contract (the verdict
never flags a listing and never changes the score), and the
router end to end (status endpoint + check preview carrying the
pay verdict).
"""

from __future__ import annotations

from career_guidance.kaamvaani.scam import check_listing, check_pay_plausibility
from career_guidance.kaamvaani.wages import (
    find_employment,
    load_wage_tables,
    wage_band,
)
from tests.conftest import login


def _listing(**overrides):
    data = {
        "title": "Mason helper",
        "role_category": "construction",
        "description": "Help masons with building work on a construction site.",
        "city": "Madurai",
        "pay_monthly_min": 15000,
        "pay_monthly_max": 20000,
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# Tables + bands
# --------------------------------------------------------------------------- #


def test_tables_load_with_provenance():
    tables = load_wage_tables()
    assert len(tables["employments"]) == 7
    assert tables["provenance"]["order"] == "File No. 6/1/2026-VDA, dated 30 September 2026"
    assert tables["provenance"]["effective_from"] == "2026-10-01"


def test_monthly_bands():
    # Pinned rupee figures: lowest/highest daily total x 26 days.
    by_id = {e["id"]: e for e in load_wage_tables()["employments"]}
    band = wage_band(by_id["construction"])
    assert (band.floor_monthly, band.ceiling_monthly) == (14690, 28886)
    band = wage_band(by_id["agriculture"])
    assert (band.floor_monthly, band.ceiling_monthly) == (12636, 18330)
    band = wage_band(by_id["watch-ward"])
    assert (band.floor_monthly, band.ceiling_monthly) == (20644, 28886)
    band = wage_band(by_id["mines"])
    assert (band.floor_monthly, band.ceiling_monthly) == (14690, 28470)
    band = wage_band(by_id["sweeping-cleaning"])
    assert (band.floor_monthly, band.ceiling_monthly) == (14690, 21840)
    # Piece rates cannot convert to monthly.
    assert wage_band(by_id["stone-mines-piece"]) is None


# --------------------------------------------------------------------------- #
# Employment matching
# --------------------------------------------------------------------------- #


def test_find_employment_longest_phrase_wins():
    # Each case carries its own description AND role category: the
    # default _listing text is construction, and the longest-phrase
    # rule would (correctly) let "building work" / "construction"
    # beat "farm worker".
    assert (
        find_employment(
            _listing(
                title="Security guard",
                description="Night security guard duty.",
                role_category="security",
            )
        )["id"]
        == "watch-ward"
    )
    assert (
        find_employment(
            _listing(
                title="Farm worker",
                description="Farm labour and harvesting.",
                role_category="agriculture",
            )
        )["id"]
        == "agriculture"
    )
    assert find_employment(_listing(title="Mason helper"))["id"] == "construction"
    # "guard" alone still matches watch-ward, but the longer phrase
    # wins when both are present (the band is the same either way —
    # this pins the matching rule, not the outcome).
    assert (
        find_employment(
            _listing(
                title="Night guard",
                description="Watchman duty.",
                role_category="security",
            )
        )["id"]
        == "watch-ward"
    )


def test_find_employment_word_boundaries():
    # "mines" as a substring of "determines" must NOT match.
    assert (
        find_employment(
            _listing(
                title="Quality checker",
                description="Determines whether garments pass inspection.",
                role_category="quality",
            )
        )
        is None
    )
    # No scheduled employment matches an electrician listing.
    assert (
        find_employment(
            _listing(
                title="Electrician helper",
                description="Help with house wiring work.",
                role_category="electrician",
            )
        )
        is None
    )


# --------------------------------------------------------------------------- #
# Verdicts
# --------------------------------------------------------------------------- #


def test_below_minimum():
    result = check_pay_plausibility(_listing(pay_monthly_min=12000, pay_monthly_max=14000))
    assert result["status"] == "below_minimum"
    assert result["checked_against"]["employment"] == "construction"
    assert result["checked_against"]["floor_monthly"] == 14690
    assert result["checked_against"]["scope"] == "central sphere only"
    assert "central-sphere" in result["reason"]
    # Only the max matters for below_minimum: a max below the floor
    # with no min is still below_minimum.
    result = check_pay_plausibility(_listing(pay_monthly_min=None, pay_monthly_max=14000))
    assert result["status"] == "below_minimum"


def test_within_central_range():
    result = check_pay_plausibility(_listing(pay_monthly_min=15000, pay_monthly_max=20000))
    assert result["status"] == "within_central_range"
    assert result["checked_against"]["ceiling_monthly"] == 28886
    # Only a min below the floor cannot prove below_minimum (the
    # max might be above it) — within range, honestly.
    result = check_pay_plausibility(_listing(pay_monthly_min=12000, pay_monthly_max=None))
    assert result["status"] == "within_central_range"


def test_above_range():
    result = check_pay_plausibility(_listing(pay_monthly_min=30000, pay_monthly_max=35000))
    assert result["status"] == "above_range"
    assert "not a wage violation" in result["reason"]


def test_unknown_cases():
    # No pay figures: unknown, but the employment was matched.
    result = check_pay_plausibility(_listing(pay_monthly_min=None, pay_monthly_max=None))
    assert result["status"] == "unknown"
    assert result["checked_against"]["employment"] == "construction"
    # No employment match: unknown, nothing checked against.
    result = check_pay_plausibility(
        _listing(
            title="Electrician helper",
            description="Help with house wiring work.",
            role_category="electrician",
        )
    )
    assert result["status"] == "unknown"
    assert result["checked_against"] is None
    # Piece-rate employment: unknown with the piece-rate reason.
    result = check_pay_plausibility(
        _listing(
            title="Stone breaking helper",
            description="Stone breaking and crushing work at a stone quarry.",
            role_category="mining",
        )
    )
    assert result["status"] == "unknown"
    assert "piece rates" in result["reason"]
    assert result["checked_against"]["employment"] == "stone-mines-piece"


# --------------------------------------------------------------------------- #
# Advisory-only contract
# --------------------------------------------------------------------------- #


def test_pay_verdict_never_flags_and_never_scores():
    below = check_listing(
        _listing(pay_monthly_min=12000, pay_monthly_max=14000),
        {"business_name": "X"},
    )
    within = check_listing(
        _listing(pay_monthly_min=15000, pay_monthly_max=20000),
        {"business_name": "X"},
    )
    assert below.pay["status"] == "below_minimum"
    assert within.pay["status"] == "within_central_range"
    assert below.score == within.score
    assert below.flags == within.flags
    assert below.recommended_status == within.recommended_status


# --------------------------------------------------------------------------- #
# Router end to end
# --------------------------------------------------------------------------- #


def test_status_endpoint_reports_central_sphere(client):
    r = client.get("/api/v1/kv/employers/status")
    assert r.status_code == 200, r.text
    pay = r.json()["pay_plausibility"]
    assert pay["status"] == "central_sphere"
    assert pay["employments"] == 7
    assert "6/1/2026-VDA" in pay["order"]
    assert pay["effective_from"] == "2026-10-01"


def test_check_preview_carries_pay_verdict(client):
    login(client, "shop@example.com")
    r = client.post(
        "/api/v1/kv/employers/register",
        json={"business_name": "Buildwell", "city": "Madurai"},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/kv/employers/listings/check",
        json=_listing(pay_monthly_min=12000, pay_monthly_max=14000),
    )
    assert r.status_code == 200, r.text
    assert r.json()["check"]["pay"]["status"] == "below_minimum"
