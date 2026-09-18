"""Guard the offline matcher quality bar (master plan R2: Hit@5 >= 0.70)."""

import json
from pathlib import Path

from career_guidance.matching import ROLE_ALIASES, get_matcher
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden.json"


def test_role_aliases_resolve_to_catalog():
    have = {o.id for o in get_matcher().taxonomy.occupations}
    missing = {i for ids in ROLE_ALIASES.values() for i in ids} - have
    assert not missing


def test_golden_hit_at_5_meets_bar():
    matcher = get_matcher()
    cases = json.loads(GOLDEN.read_text())
    hits = 0
    for case in cases:
        profile = CareerProfile(
            skills=case["skills"],
            goals=case.get("goals", ""),
            experience_level=EXPERIENCE_LEVELS[case.get("level", 0)],
        )
        titles = {m.occupation.title for m in matcher.rank(profile)}
        hits += bool(titles & set(case["expect"]))
    assert hits / len(cases) >= 0.70
