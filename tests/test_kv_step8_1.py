"""Step 8.1 tests: the separate ranker component (config + injectable
comparator), the score-identical KVScorer refactor, fairness, and the
title-evidence rescue gate (L53).

The refactor regression pins the PRE-refactor top-5 (titles + scores)
for the five Stage 4 probe profiles, captured before matching.py was
touched (~/workspace/tmp/kv81_probe_before.py). The ranker changes
where the weights live and who orders the list — not a single score.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.matching import KVScorer
from career_guidance.kaamvaani.profile import extract_profile_guided
from career_guidance.kaamvaani.rag import (
    TITLE_RESCUE_THRESHOLD,
    Chunk,
    Hit,
    HybridRetriever,
    answer_question,
)
from career_guidance.kaamvaani.ranker import (
    LIVE_FEATURES,
    MultiCriteriaRanker,
    RankerConfig,
    ScoredItem,
    default_comparator,
    load_ranker_config,
)
from career_guidance.matching2 import education_zone
from career_guidance.taxonomy import Taxonomy

ROOT = Path(__file__).resolve().parent.parent

DEMO_ANSWERS = {
    "skills": "farming and basic computer work, and I can type",
    "education": "12th pass",
    "city": "Madurai",
    "income": "15000 rupees a month",
    "goal": "I need a job",
}


def _profile(**overrides) -> VoiceProfile:
    base = {
        "skills": ["attention to detail", "computer literacy", "agricultural science"],
        "interests": "farming and basic computer work, and I can type. Madurai. I need a job",
        "education": "12th pass",
        "city": "Madurai",
        "income_text": "₹15,000 / month",
        "income_monthly": 15000,
        "goal_type": "job_6_months",
        "raw_text": "farming and basic computer work, and I can type. 12th pass. Madurai. "
        "15000 rupees a month. I need a job",
    }
    base.update(overrides)
    return VoiceProfile(**base)


def _demo_profile() -> VoiceProfile:
    profile, _ = extract_profile_guided(DEMO_ANSWERS, None)
    return profile


def _electrician_profile() -> VoiceProfile:
    return _profile(
        skills=["electrical technician"],
        interests="I am an electrician, house wiring and fan repair",
        education="ITI",
        city="Salem",
        income_monthly=20000,
        income_text="₹20,000 / month",
        raw_text="I am an electrician, house wiring and fan repair. ITI. Salem. "
        "20000 rupees a month. I need a job",
    )


def _tailor_profile() -> VoiceProfile:
    return _profile(
        skills=["fashion design"],
        interests="tailoring and stitching clothes",
        education="10th pass",
        city="Tiruppur",
        income_monthly=12000,
        income_text="₹12,000 / month",
        raw_text="tailoring and stitching clothes. 10th pass. Tiruppur. "
        "12000 rupees a month. I need a job",
    )


def _driver_profile() -> VoiceProfile:
    return _profile(
        skills=["driving"],
        interests="I drive a bus, heavy vehicle licence",
        education="10th pass",
        city="Madurai",
        income_monthly=18000,
        income_text="₹18,000 / month",
        raw_text="I drive a bus, heavy vehicle licence. 10th pass. Madurai. "
        "18000 rupees a month. I need a job",
    )


def _btech_profile() -> VoiceProfile:
    return _profile(
        skills=["computer literacy"],
        interests="computer programming and data work",
        education="B.Tech",
        city="Chennai",
        income_monthly=40000,
        income_text="₹40,000 / month",
        raw_text="computer programming and data work. B.Tech. Chennai. "
        "40000 rupees a month. I need a job",
    )


# Pre-refactor top-5 (title, score) per probe profile — captured before
# the refactor; the refactor must reproduce them exactly.
#
# Re-baselined in Step 8B (L55 fix): dropping the raw income text from
# the base matcher's goals string changed scores by up to 0.0058
# (btech / Computer Programmers — a semantic-scorer renormalisation
# effect) and <= 0.0004 elsewhere. The ORDER is identical in all five
# profiles; only the pinned scores moved. Any future change to this
# table needs the same justification: order unchanged, deltas small
# and explained.
EXPECTED_TOP5: dict[str, list[tuple[str, float]]] = {
    "demo": [
        ("Data Entry Keyers", 0.508827),
        ("Computer Operators", 0.468499),
        ("Agricultural Technicians", 0.454499),
        ("Agricultural Inspectors", 0.426745),
        ("Computer Programmers", 0.393103),
    ],
    "electrician": [
        ("Electricians", 0.765369),
        ("Electrical Engineering Technicians", 0.572977),
        ("Watch Repairers", 0.54012),
        ("Helpers--Electricians", 0.536722),
        ("Avionics Technicians", 0.534209),
    ],
    "tailor": [
        ("Fashion Designers", 0.611854),
        ("Floral Designers", 0.472281),
        ("Dental Laboratory Technicians", 0.329307),
        ("Glass Blowers, Molders, Benders, and Finishers", 0.329196),
        ("Fine Artists, Including Painters, Sculptors, and Illustrators", 0.28938),
    ],
    "driver": [
        ("Pile-Driver Operators", 0.367359),
        ("Driver/Sales Workers", 0.364259),
        ("Taxi Drivers and Chauffeurs", 0.364176),
        ("Bus Drivers, Transit and Intercity", 0.341809),
        ("Bus Drivers, School or Special Client", 0.319642),
    ],
    "btech": [
        ("Computer Operators", 0.433328),
        ("Computer Programmers", 0.410665),
        ("Clinical Data Managers", 0.347799),
        ("Computer Systems Analysts", 0.347799),
        ("Data Warehousing Specialists", 0.347799),
    ],
}

PROFILES = {
    "demo": _demo_profile,
    "electrician": _electrician_profile,
    "tailor": _tailor_profile,
    "driver": _driver_profile,
    "btech": _btech_profile,
}


@pytest.fixture(scope="module")
def scorer() -> KVScorer:
    return KVScorer()


# --------------------------------------------------------------------------- #
# RankerConfig
# --------------------------------------------------------------------------- #


def test_default_config_sums_to_one():
    config = RankerConfig.default()
    config.validate()
    assert abs(sum(config.weights.values()) - 1.0) < 1e-9
    assert config.weights["skill"] == 0.30
    assert config.weights["title"] == 0.40
    assert config.weights["distance"] == 0.0


def test_yaml_config_matches_default():
    config = load_ranker_config()
    default = RankerConfig.default()
    assert config.weights == default.weights
    assert config.zone_filter_slack == default.zone_filter_slack
    assert config.zone_gap_penalty == default.zone_gap_penalty
    assert config.zone_gap_penalty_cap == default.zone_gap_penalty_cap


def test_config_rejects_bad_sum():
    weights = {"skill": 0.5, "title": 0.4, "base": 0.1, "zone": 0.1, "income": 0.1}
    config = RankerConfig(weights=weights)
    with pytest.raises(ValueError, match="sum to"):
        config.validate()


def test_config_rejects_negative_weight():
    weights = dict(RankerConfig.default().weights)
    weights["skill"] = -0.1
    weights["title"] = 0.8
    with pytest.raises(ValueError, match="negative"):
        RankerConfig(weights=weights).validate()


def test_config_rejects_unknown_feature():
    weights = dict(RankerConfig.default().weights)
    weights["caste"] = 0.0
    with pytest.raises(ValueError, match="unknown"):
        RankerConfig(weights=weights).validate()


def test_config_rejects_missing_live_feature():
    weights = {k: v for k, v in RankerConfig.default().weights.items() if k != "title"}
    weights["skill"] = 0.7
    with pytest.raises(ValueError, match="missing"):
        RankerConfig(weights=weights).validate()


def test_config_rejects_bad_zone_params():
    base = RankerConfig.default()
    with pytest.raises(ValueError, match="zone_filter_slack"):
        RankerConfig(weights=base.weights, zone_filter_slack=-1.0).validate()
    with pytest.raises(ValueError, match="zone_gap_penalty"):
        RankerConfig(weights=base.weights, zone_gap_penalty=1.5).validate()
    with pytest.raises(ValueError, match="zone_gap_penalty_cap"):
        RankerConfig(weights=base.weights, zone_gap_penalty_cap=2.0).validate()


def test_config_weight_lookup():
    config = RankerConfig.default()
    assert config.weight("title") == 0.40
    assert config.weight("distance") == 0.0
    assert config.weight("not_a_feature") == 0.0


def test_load_rejects_invalid_yaml(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("weights:\n  skill: 0.5\n  title: 0.4\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_ranker_config(bad)


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ranker_config(tmp_path / "nope.yaml")


# --------------------------------------------------------------------------- #
# MultiCriteriaRanker
# --------------------------------------------------------------------------- #


def test_combine_weighted_sum_and_contributions():
    ranker = MultiCriteriaRanker()
    score, contributions = ranker.combine(
        {"skill": 0.5, "title": 1.0, "base": 0.0, "zone": 0.8, "income": 1.0}
    )
    assert score == pytest.approx(0.30 * 0.5 + 0.40 * 1.0 + 0.10 * 0.8 + 0.10 * 1.0)
    assert contributions["title"] == pytest.approx(0.40)
    assert contributions["skill"] == pytest.approx(0.15)
    # Zero-weight and unknown features never contribute.
    assert "distance" not in contributions
    score2, _ = ranker.combine({"skill": 0.5, "distance": 1.0, "surprise": 1.0})
    assert score2 == pytest.approx(0.30 * 0.5)


def test_combine_uses_injected_config_weights():
    config = RankerConfig(
        weights={"skill": 1.0, "title": 0.0, "base": 0.0, "zone": 0.0, "income": 0.0}
    )
    ranker = MultiCriteriaRanker(config)
    score, _ = ranker.combine({"skill": 0.5, "title": 1.0})
    assert score == pytest.approx(0.5)


def test_default_comparator_orders_score_desc_title_asc():
    items = [
        ScoredItem(item="b", score=0.5, tiebreak="Beta"),
        ScoredItem(item="a", score=0.5, tiebreak="Alpha"),
        ScoredItem(item="c", score=0.9, tiebreak="Gamma"),
    ]
    ranked = MultiCriteriaRanker().rank(items)
    assert [i.item for i in ranked] == ["c", "a", "b"]
    # Input untouched.
    assert [i.item for i in items] == ["b", "a", "c"]


def test_injected_comparator_replaces_order():
    """The comparator is really injected: ascending-score order is the
    reverse of the default."""
    items = [
        ScoredItem(item="low", score=0.2, tiebreak="Low"),
        ScoredItem(item="high", score=0.9, tiebreak="High"),
    ]
    ascending = lambda a, b: -default_comparator(a, b)  # noqa: E731
    ranked = MultiCriteriaRanker(comparator=ascending).rank(items)
    assert [i.item for i in ranked] == ["low", "high"]


def test_default_comparator_is_a_total_order():
    """Antisymmetric, reflexive on equals, transitive on a small set."""
    items = [
        ScoredItem(item="a", score=0.5, tiebreak="Alpha"),
        ScoredItem(item="b", score=0.5, tiebreak="Beta"),
        ScoredItem(item="c", score=0.9, tiebreak="Gamma"),
    ]
    for x in items:
        assert default_comparator(x, x) == 0
    for x in items:
        for y in items:
            assert default_comparator(x, y) == -default_comparator(y, x)
    # c > b > a in rank order (c first): transitivity via the sort.
    ranked = MultiCriteriaRanker().rank(list(reversed(items)))
    assert [i.item for i in ranked] == ["c", "a", "b"]


def test_score_item_bundles_score_and_contributions():
    ranker = MultiCriteriaRanker()
    entry = ranker.score_item("x", {"skill": 1.0}, tiebreak="X")
    assert entry.score == pytest.approx(0.30)
    assert entry.components["skill"] == pytest.approx(0.30)
    assert entry.tiebreak == "X"


# --------------------------------------------------------------------------- #
# Refactor regression: identical ranking on the five probe profiles
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_refactor_reproduces_pre_refactor_top5(scorer, name):
    ranked, _ = scorer.rank(PROFILES[name](), top_k=5)
    got = [(m.occupation.title, round(m.score, 6)) for m in ranked]
    assert got == EXPECTED_TOP5[name]


def test_scorer_loads_yaml_config_by_default(scorer):
    assert scorer.config.weights == RankerConfig.default().weights
    assert scorer.config.zone_filter_slack == 1.0


def test_scorer_accepts_injected_comparator(scorer):
    """An injected comparator reaches the scorer's ordering: ascending
    scores put the weakest match first."""
    ascending = lambda a, b: -default_comparator(a, b)  # noqa: E731
    reversed_scorer = KVScorer(
        taxonomy=scorer.taxonomy,
        matcher=scorer.matcher,
        seed=scorer.seed,
        normalizer=scorer.normalizer,
        comparator=ascending,
    )
    ranked, _ = reversed_scorer.rank(_demo_profile(), top_k=5)
    scores = [m.score for m in ranked]
    assert scores == sorted(scores)


# --------------------------------------------------------------------------- #
# Fairness: determinism, order-independence, input isolation, no protected
# attributes
# --------------------------------------------------------------------------- #


def test_ranking_is_deterministic(scorer):
    profile = _demo_profile()
    first, _ = scorer.rank(profile, top_k=5)
    second, _ = scorer.rank(profile, top_k=5)
    assert [(m.occupation.id, m.score) for m in first] == [
        (m.occupation.id, m.score) for m in second
    ]


def test_ranking_is_order_independent(scorer):
    """Shuffling the taxonomy must not change the top-5 — the ranking
    depends on scores + titles, never on input order."""
    shuffled = list(scorer.taxonomy.occupations)
    random.Random(8).shuffle(shuffled)
    shuffled_scorer = KVScorer(
        taxonomy=Taxonomy(shuffled),
        matcher=scorer.matcher,
        seed=scorer.seed,
        normalizer=scorer.normalizer,
    )
    for name in ("demo", "btech"):  # btech has a 3-way exact tie
        expected, _ = scorer.rank(PROFILES[name](), top_k=5)
        got, _ = shuffled_scorer.rank(PROFILES[name](), top_k=5)
        assert [(m.occupation.id, m.score) for m in got] == [
            (m.occupation.id, m.score) for m in expected
        ]


def test_city_does_not_change_scores(scorer):
    """City is not a scoring input: changing it must leave every score
    untouched. (The free-text income string is NOT isolated: it feeds
    the base matcher through the goals field — see LIMITATIONS.md L55.
    Only the parsed ``income_monthly`` number is a scoring input.)"""
    base = _demo_profile()
    changed = _profile(
        skills=base.skills,
        interests=base.interests,
        education=base.education,
        city="Coimbatore",
        income_text=base.income_text,
        income_monthly=base.income_monthly,
        goal_type=base.goal_type,
        raw_text=base.raw_text,
    )
    first, _ = scorer.rank(base, top_k=5)
    second, _ = scorer.rank(changed, top_k=5)
    assert [(m.occupation.id, m.score) for m in first] == [
        (m.occupation.id, m.score) for m in second
    ]


def test_match_features_are_exactly_the_five_live_features(scorer):
    ranked, _ = scorer.rank(_demo_profile(), top_k=5)
    for match in ranked:
        assert sorted(match.components) == sorted(LIVE_FEATURES)


def test_contributions_are_weight_times_component(scorer):
    """Per-feature contributions (spec 8.1): each contribution is its
    config weight times the raw feature value, and they sum to the
    pre-penalty score — score == sum(contributions) x the
    zone-penalty factor."""
    config = scorer.config
    profile = _demo_profile()
    ranked, _ = scorer.rank(profile, top_k=5)
    # The unrounded target zone (meta rounds it to 2dp, which would
    # skew the penalty factor beyond approx's tolerance).
    target_zone = education_zone(profile.education, "Student / No experience")
    for match in ranked:
        assert sorted(match.contributions) == sorted(LIVE_FEATURES)
        for name in LIVE_FEATURES:
            assert match.contributions[name] == pytest.approx(
                config.weights[name] * match.components[name]
            )
        gap = max(0.0, match.occupation.job_zone - target_zone)
        factor = max(
            1.0 - config.zone_gap_penalty_cap,
            1.0 - config.zone_gap_penalty * gap,
        )
        assert match.score == pytest.approx(sum(match.contributions.values()) * factor)


def test_match_dict_carries_contributions(scorer):
    ranked, _ = scorer.rank(_demo_profile(), top_k=1)
    data = ranked[0].to_dict()
    assert sorted(data["contributions"]) == sorted(LIVE_FEATURES)
    assert data["contributions"]["title"] == pytest.approx(
        ranked[0].contributions["title"], abs=0.0001
    )


def test_no_protected_attribute_names_in_ranker_or_matching():
    """No protected-attribute name anywhere in the ranker or the
    scorer source (the ranker can only see the feature dict it is
    handed — and the feature set is the five live features)."""
    protected = ("caste", "religion", "gender", "community", "creed", "tribe", "sect")
    for module in ("ranker.py", "matching.py"):
        source = (
            (ROOT / "career_guidance" / "kaamvaani" / module).read_text(encoding="utf-8").lower()
        )
        for word in protected:
            assert word not in source, f"{word!r} appears in {module}"


# --------------------------------------------------------------------------- #
# Title-evidence rescue gate (L53)
# --------------------------------------------------------------------------- #


def _chunk(source_id: str, text: str, title: str, topic: str = "occupation") -> Chunk:
    return Chunk(
        source_id=source_id,
        source_url=f"https://example.com/{source_id}",
        source_title=title,
        source_date="2026-11-06",
        licence="test",
        language="en",
        topic=topic,
        text=text,
    )


class _StubRetriever:
    """A retriever returning one hand-built hit, so the answer gate
    itself is tested without depending on scorer internals."""

    def __init__(self, hit: Hit) -> None:
        self._hit = hit

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        return [self._hit]


def _rescue_hit(*, title_bonus: float, raw_tfidf: float = 0.05, score: float = 1.0) -> Hit:
    chunk = _chunk(
        "onet:47-2111.00",
        "Electricians install, maintain, and repair electrical wiring, equipment, and fixtures.",
        "Electricians",
    )
    return Hit(chunk=chunk, score=score, raw_tfidf=raw_tfidf, title_bonus=title_bonus)


def test_search_stores_title_bonus_on_hits():
    retriever = HybridRetriever(
        [
            _chunk(
                "onet:47-2111.00",
                "Electricians install, maintain, and repair electrical wiring.",
                "Electricians",
            ),
            _chunk(
                "onet:47-3013.00",
                "Helpers--Electricians help electricians by performing duties "
                "requiring less skill.",
                "Helpers--Electricians",
            ),
        ]
    )
    hits = retriever.search("what do electricians do")
    assert hits
    assert hits[0].title_bonus > 0
    assert hits[0].to_dict()["title_bonus"] == pytest.approx(hits[0].title_bonus)


def test_title_rescue_waives_cosine_floor():
    """A top hit below the cosine floor (0.05 < 0.10) but with a strong
    title match (0.30 >= 0.20) is grounded by its title and answers."""
    assert TITLE_RESCUE_THRESHOLD == 0.20
    result = answer_question(
        "what do electricians do",
        _StubRetriever(_rescue_hit(title_bonus=0.30)),
    )
    assert result["refused"] is False
    assert "Electricians install" in result["answer"]


def test_title_rescue_waives_weak_match_rule():
    """The same hit also fails the weak-match rule (cosine 0.05, one
    matched term) — the title match IS the second piece of evidence."""
    result = answer_question(
        "electricians",
        _StubRetriever(_rescue_hit(title_bonus=0.25, raw_tfidf=0.05)),
    )
    assert result["refused"] is False


def test_below_threshold_title_bonus_still_refuses():
    """A 0.167 bonus (kv-x009, the nearest refusal case) stays refused
    when the cosine is below the floor."""
    result = answer_question(
        "what do electricians do",
        _StubRetriever(_rescue_hit(title_bonus=0.167)),
    )
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"


def test_title_rescue_does_not_waive_score_threshold():
    result = answer_question(
        "what do electricians do",
        _StubRetriever(_rescue_hit(title_bonus=0.30, score=0.05)),
    )
    assert result["refused"] is True


def test_title_rescue_does_not_waive_figure_rule():
    """A wage-figure question still refuses when the top chunk carries
    no currency figure, however strong its title match."""
    result = answer_question(
        "what is the minimum wage for electricians",
        _StubRetriever(_rescue_hit(title_bonus=0.30)),
    )
    assert result["refused"] is True
    assert result["reason"] == "no_grounding"
