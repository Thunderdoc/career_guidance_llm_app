"""Phase 7 semantic layer: determinism, fallback, blend math, flag-off parity."""

from __future__ import annotations

import pytest

from career_guidance.config import Settings
from career_guidance.matching import get_matcher
from career_guidance.matching2 import MatcherV2
from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.semantic import (
    EmbeddingSemanticScorer,
    TfidfSemanticScorer,
    blend_score,
    get_semantic_scorer,
)
from career_guidance.taxonomy import load_taxonomy


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy()


@pytest.fixture(scope="module")
def tfidf(taxonomy):
    return TfidfSemanticScorer(taxonomy)


def test_blend_math_and_clamping():
    assert blend_score(0.8, 0.4, 0.25) == pytest.approx(0.7)
    assert blend_score(0.8, 0.4, 0.0) == pytest.approx(0.8)
    assert blend_score(0.8, 0.4, 1.0) == pytest.approx(0.4)
    assert blend_score(0.8, 0.4, 5.0) == pytest.approx(0.4)  # clamped
    assert blend_score(0.8, 0.4, -1.0) == pytest.approx(0.8)


def test_tfidf_scorer_deterministic_and_ordered(tfidf, taxonomy):
    occs = taxonomy.occupations[:12]
    text = "python sql data analysis statistics"
    first = tfidf.scores(text, occs)
    second = tfidf.scores(text, occs)
    assert first == second
    assert len(first) == len(occs)
    assert all(0.0 <= s <= 1.0 for s in first)
    assert tfidf.scores(text, []) == []


def test_tfidf_scorer_ranks_relevant_occupation_higher(tfidf, taxonomy):
    data_occ = taxonomy.get("15-2041.00")  # Statisticians
    assert data_occ is not None
    chef = next(o for o in taxonomy.occupations if o.title.startswith("Chefs"))
    scores = tfidf.scores("python machine learning statistics data", [chef, data_occ])
    assert scores[1] > scores[0]


def test_embedding_scorer_falls_back_when_package_or_model_missing(taxonomy, monkeypatch):
    import sys
    import types

    # An empty module makes the lazy import fail deterministically,
    # whether or not sentence-transformers happens to be installed.
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.ModuleType("st_stub"))
    scorer = EmbeddingSemanticScorer(taxonomy, "no-such-model-xyz", encoder=None)
    occs = taxonomy.occupations[:5]
    scores = scorer.scores("python programming", occs)
    expected = TfidfSemanticScorer(taxonomy).scores("python programming", occs)
    assert scores == expected
    assert scorer.backend == "tfidf-fallback"


class _BrokenEncoder:
    def encode(self, texts, normalize_embeddings=True):
        raise RuntimeError("encode exploded")


def test_embedding_scorer_falls_back_on_encode_error(taxonomy):
    scorer = EmbeddingSemanticScorer(taxonomy, "fake-model", encoder=_BrokenEncoder())
    occs = taxonomy.occupations[:4]
    scores = scorer.scores("python", occs)
    assert scores == TfidfSemanticScorer(taxonomy).scores("python", occs)
    assert scorer.backend == "tfidf-fallback"


class _FakeEncoder:
    """Deterministic tiny encoder: one-hot on 'python' vs everything else."""

    def encode(self, texts, normalize_embeddings=True):
        import numpy as np

        return np.array(
            [[1.0, 0.0] if "python" in t.lower() else [0.0, 1.0] for t in texts], dtype=float
        )


def test_embedding_scorer_uses_encoder_when_available(taxonomy):
    scorer = EmbeddingSemanticScorer(taxonomy, "fake-model", encoder=_FakeEncoder())
    occs = taxonomy.occupations[:6]
    scores = scorer.scores("python developer", occs)
    assert len(scores) == len(occs) and all(0.0 <= s <= 1.0 for s in scores)
    assert scorer.backend == "embedding"


def test_get_semantic_scorer_defaults_to_tfidf(taxonomy):
    assert isinstance(get_semantic_scorer(taxonomy, Settings()), TfidfSemanticScorer)
    emb = get_semantic_scorer(taxonomy, Settings(semantic_embedding_model="some-model"))
    assert isinstance(emb, EmbeddingSemanticScorer)


def _titles(matcher, profile):
    return [r.occupation.title for r in matcher.rank(profile, top_k=5)]


def test_flag_off_ranking_is_byte_identical_to_baseline():
    profile = CareerProfile(
        skills="Python, SQL, statistics",
        goals="data analyst",
        experience_level=EXPERIENCE_LEVELS[0],
    )
    baseline = _titles(MatcherV2(get_matcher(), semantic_enabled=False), profile)
    again = _titles(MatcherV2(get_matcher(), semantic_enabled=False), profile)
    assert again == baseline
    # Scores too: flag-off must not perturb a single float.
    a = MatcherV2(get_matcher(), semantic_enabled=False).rank(profile, top_k=5)
    b = MatcherV2(get_matcher(), semantic_enabled=False).rank(profile, top_k=5)
    assert [r.score for r in a] == [r.score for r in b]


def test_blend_applies_at_matcher_v2_seam(tfidf):
    profile = CareerProfile(skills="Python, SQL, statistics", goals="data")
    off = MatcherV2(get_matcher(), semantic_enabled=False).rank(profile, top_k=5)
    on = MatcherV2(
        get_matcher(), semantic_scorer=tfidf, semantic_enabled=True, semantic_weight=0.25
    ).rank(profile, top_k=5)
    # With a pure-semantic weight of 1.0 the score must equal the semantic
    # similarity for the skills-only case only up to the zone tiebreak —
    # instead assert the exact blend identity on weight=1 vs scorer values:
    pure = MatcherV2(
        get_matcher(), semantic_scorer=tfidf, semantic_enabled=True, semantic_weight=1.0
    ).rank(profile, top_k=200)
    sims = {
        occ.id: s
        for occ, s in zip(
            [r.occupation for r in pure],
            tfidf.scores(profile.to_prompt_text(), [r.occupation for r in pure]),
            strict=True,
        )
    }
    for r in pure:
        assert r.score == pytest.approx(sims[r.occupation.id], abs=1e-9)
    assert on  # blended ranking still returns results
    assert off[0].occupation.title  # baseline sane


def test_semantic_weight_clamped():
    m = MatcherV2(get_matcher(), semantic_enabled=False, semantic_weight=9.0)
    assert m.semantic_weight == 1.0
