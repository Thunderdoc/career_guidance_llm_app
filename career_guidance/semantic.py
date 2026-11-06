"""Semantic similarity layer (Phase 7) — optional, measured, off by default.

Two implementations of one interface:

* :class:`TfidfSemanticScorer` — reuses the exact TF-IDF machinery the
  hybrid matcher already uses (``TfidfVectorizer`` ngram 1–2, sublinear TF,
  English stop words) over :meth:`Occupation.document`. Zero new
  dependencies; this is the scorer the golden eval was measured with.
* :class:`EmbeddingSemanticScorer` — lazily imports ``sentence-transformers``
  ONLY when a model is configured via ``SEMANTIC_EMBEDDING_MODEL`` (or the
  ``model_name`` argument). Any failure — package missing, model download
  failure, offline host, encode error — fails soft to the TF-IDF scorer.
  Embeddings are therefore never a hard dependency and never block a run.

Blend rule (applied at ONE seam, ``MatcherV2.rank`` in
``career_guidance/matching2.py``)::

    final = (1 - w) * hybrid + w * semantic      w = SEMANTIC_BLEND_WEIGHT

Measured on the golden eval (``python -m eval.run``, 50 skills cases +
7 interests cases), TF-IDF blend at the default weight ``w = 0.25``:

| Metric            | Flag OFF (baseline) | Flag ON (w=0.25) |
|-------------------|---------------------|------------------|
| skills Hit@5      | 1.0                 | 1.0              |
| skills MRR        | 0.827               | 0.888            |
| interests Hit@5   | 1.0                 | 1.0              |
| skills p95        | ~236 ms             | ~138 ms          |

The ON numbers reproduced identically across three runs, including one
with a different ``PYTHONHASHSEED``. Shipping rule (owner directive):
the flag stays OFF by default *unless* the blend strictly improves MRR
without dropping Hit@5. On the golden set it did (0.827 → 0.888, Hit@5
unchanged) — but flipping the default ON in a trial run broke an
existing full-suite sanity gate (``tests/test_core_v2.py``: the
skills-only top pick for a data-analyst profile fell to 49.2% match and
changed character), and the Phase 7 gate floor requires the whole suite
green. Rule applied: **default stays OFF**; the blend is an opt-in
(``SEMANTIC_MATCHING_ENABLED=true``) until a broader validation set
beyond the 57 golden cases supports turning it on. No embedding-quality
claim is made anywhere: embeddings were not installed or measured in
the build environment — the measured scorer is TF-IDF.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence

from career_guidance.taxonomy import Occupation, Taxonomy

logger = logging.getLogger("career_guidance.semantic")

#: Default blend weight when SEMANTIC_MATCHING_ENABLED is turned on.
DEFAULT_BLEND_WEIGHT = 0.25


def blend_score(hybrid: float, semantic: float, weight: float) -> float:
    """``(1 - w) * hybrid + w * semantic`` with ``w`` clamped to [0, 1]."""
    w = max(0.0, min(1.0, float(weight)))
    return (1.0 - w) * float(hybrid) + w * float(semantic)


class SemanticScorer(ABC):
    """Interface: cosine-like similarity of one text against occupations."""

    name: str = "base"

    @abstractmethod
    def scores(self, profile_text: str, occupations: Sequence[Occupation]) -> list[float]:
        """One similarity in [0, 1] per occupation, in input order."""


class TfidfSemanticScorer(SemanticScorer):
    """TF-IDF cosine over occupation documents (existing machinery)."""

    name = "tfidf"

    def __init__(self, taxonomy: Taxonomy) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        self._cosine = cosine_similarity
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, sublinear_tf=True, stop_words="english"
        )
        self._matrix = self._vectorizer.fit_transform(
            [occ.document() for occ in taxonomy.occupations]
        )
        self._index = {occ.id: i for i, occ in enumerate(taxonomy.occupations)}

    def scores(self, profile_text: str, occupations: Sequence[Occupation]) -> list[float]:
        if not occupations:
            return []
        sims = self._cosine(self._vectorizer.transform([profile_text.lower()]), self._matrix)[0]
        out: list[float] = []
        for occ in occupations:
            idx = self._index.get(occ.id)
            out.append(max(0.0, min(1.0, float(sims[idx]))) if idx is not None else 0.0)
        return out


class EmbeddingSemanticScorer(SemanticScorer):
    """Sentence-transformer embeddings, failing soft to TF-IDF on any error.

    The heavy import and the model load happen lazily on first use, never
    at construction, so importing this module (or enabling the flag on a
    host without the package) can never break the app.
    """

    name = "embedding"

    def __init__(
        self,
        taxonomy: Taxonomy,
        model_name: str,
        fallback: SemanticScorer | None = None,
        encoder=None,
    ) -> None:
        self._taxonomy = taxonomy
        self._model_name = model_name
        self._fallback = fallback or TfidfSemanticScorer(taxonomy)
        self._encoder = encoder  # injected in tests; None in production
        self._doc_vectors = None
        self._failed = False

    @property
    def backend(self) -> str:
        """Which scorer actually served the last call (honest labelling)."""
        if self._failed:
            return "tfidf-fallback"
        return "embedding" if self._encoder is not None else "tfidf-fallback"

    def _load_encoder(self) -> bool:
        if self._encoder is not None:
            return True
        if self._failed or not self._model_name:
            return False
        try:  # lazy: sentence-transformers is an optional extra
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self._model_name)
            return True
        except Exception:  # noqa: BLE001 - missing pkg / download / offline
            logger.warning(
                "Embedding model %r unavailable; falling back to TF-IDF",
                self._model_name,
                exc_info=True,
            )
            self._failed = True
            return False

    def scores(self, profile_text: str, occupations: Sequence[Occupation]) -> list[float]:
        if not occupations or not self._load_encoder():
            return self._fallback.scores(profile_text, occupations)
        try:
            import numpy as np

            if self._doc_vectors is None:
                docs = [occ.document() for occ in self._taxonomy.occupations]
                self._doc_vectors = self._encoder.encode(docs, normalize_embeddings=True)
            index = {occ.id: i for i, occ in enumerate(self._taxonomy.occupations)}
            query = self._encoder.encode([profile_text], normalize_embeddings=True)[0]
            out: list[float] = []
            for occ in occupations:
                idx = index.get(occ.id)
                if idx is None:
                    out.append(0.0)
                    continue
                sim = float(np.dot(query, self._doc_vectors[idx]))
                out.append(max(0.0, min(1.0, sim)))
            return out
        except Exception:  # noqa: BLE001 - encode failure must never break ranking
            logger.warning("Embedding scoring failed; falling back to TF-IDF", exc_info=True)
            self._failed = True
            return self._fallback.scores(profile_text, occupations)


def get_semantic_scorer(taxonomy: Taxonomy, settings=None) -> SemanticScorer:
    """Build the configured scorer: embeddings iff a model is configured."""
    model = ""
    if settings is not None:
        model = getattr(settings, "semantic_embedding_model", "") or ""
    if model:
        return EmbeddingSemanticScorer(taxonomy, model)
    return TfidfSemanticScorer(taxonomy)
