"""Guard the offline matcher quality bar (master plan R2: Hit@5 >= 0.75).

Matcher v2 is evaluated on two suites: the original 50 skill profiles and the
RIASEC-only profiles that exercise the interest term.
"""

import json
from pathlib import Path

from career_guidance.matching import ROLE_ALIASES, get_matcher
from career_guidance.matching2 import MatcherV2
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.json"
GOLDEN_INTERESTS = ROOT / "eval" / "golden_interests.json"
BAR = 0.75


def test_role_aliases_resolve_to_catalog():
    have = {o.id for o in get_matcher().taxonomy.occupations}
    missing = {i for ids in ROLE_ALIASES.values() for i in ids} - have
    assert not missing


def test_golden_hit_at_5_meets_bar():
    matcher = MatcherV2()
    cases = json.loads(GOLDEN.read_text())
    hits = 0
    for case in cases:
        profile = CareerProfile(
            skills=case["skills"],
            goals=case.get("goals", ""),
            experience_level=EXPERIENCE_LEVELS[case.get("level", 0)],
        )
        titles = {r.occupation.title for r in matcher.rank(profile, top_k=5)}
        hits += bool(titles & set(case["expect"]))
    assert hits / len(cases) >= BAR


def test_interest_only_hit_at_5_meets_bar():
    matcher = MatcherV2()
    cases = json.loads(GOLDEN_INTERESTS.read_text())
    hits = 0
    for case in cases:
        profile = CareerProfile(skills="", interests="", goals="")
        titles = {
            r.occupation.title for r in matcher.rank(profile, top_k=5, interests=case["scores"])
        }
        hits += bool(titles & set(case["expect"]))
    assert hits / len(cases) >= BAR


def test_weights_come_from_the_settings_store(tmp_path):
    from career_guidance.settings_store import SettingsStore

    store = SettingsStore(tmp_path / "settings.db")
    assert store.scoring() == {"skills": 0.55, "interests": 0.30, "job_zone": 0.15}
    store.set_many({"scoring.w_skills": 0.8, "scoring.w_interests": 0.1, "scoring.w_job_zone": 0.1})
    weights = store.scoring()
    assert weights["skills"] == 0.8
    assert MatcherV2(weights=weights).weights == weights
