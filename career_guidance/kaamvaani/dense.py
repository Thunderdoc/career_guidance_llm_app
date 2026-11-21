"""Dense (embedding) retriever for Kaam-Vaani RAG (Step 7A).

Optional second retriever: multilingual sentence embeddings
(``intfloat/multilingual-e5-small`` by default) scored by cosine
similarity against pre-computed chunk embeddings, fused with the BM25 +
TF-IDF hybrid by reciprocal rank fusion (RRF, k=60) in
:class:`career_guidance.kaamvaani.rag.HybridRetriever`.

Optional and lazy: ``sentence-transformers`` + ``torch`` are NOT
installed in the build environment. Importing this module is safe
without them; the model loads only when a :class:`DenseRetriever` is
constructed, and construction raises a clear error naming the missing
package. The default path (no dense retriever) is byte-identical to
before. Enable with ``KV_DENSE_MODEL=intfloat/multilingual-e5-small``
or the eval's ``--dense-model`` flag.

E5 usage: queries are prefixed ``"query: "`` and passages ``"passage: "``
(the model's instruction format — without the prefixes the embeddings
are measurably worse). Chunk embeddings are computed once at
construction and cached in memory: 1,040 chunks x 384 dims x 4 bytes
~= 1.6 MB. Model weights ~= 470 MB (fp32) plus the torch runtime — see
EVAL_REPORT.md for the measured memory/latency and the comparison
against glossary translation (Step 7A decision).

Complexity: construction O(C) embedding forward passes (C = chunks,
batched); per query one embedding forward pass + O(C x d) dot products
(d = 384). Space: O(C x d) floats for the index + O(P) for the model
(P ~= 118M parameters).
"""

from __future__ import annotations

import logging

from career_guidance.kaamvaani.rag import Chunk

logger = logging.getLogger("career_guidance.kaamvaani.dense")

DEFAULT_DENSE_MODEL = "intfloat/multilingual-e5-small"

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


class DenseRetriever:
    """Multilingual embedding retriever over a fixed chunk list.

    The model is loaded lazily at construction (downloading from
    HuggingFace on first use, then cached). ``scores`` returns raw
    cosine similarities in [-1, 1] — embeddings are L2-normalised, so
    the dot product IS the cosine.
    """

    def __init__(self, chunks: list[Chunk], model_name: str = DEFAULT_DENSE_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - missing optional dep
            raise RuntimeError(
                "Dense retrieval needs sentence-transformers + torch, which are "
                "not installed. Install them (pip install sentence-transformers "
                "torch) or leave KV_DENSE_MODEL unset to use the glossary-only "
                "path."
            ) from exc
        self.model_name = model_name
        self.chunks = list(chunks)
        logger.info("loading dense model %s (%d chunks)", model_name, len(self.chunks))
        self.model = SentenceTransformer(model_name)
        texts = [PASSAGE_PREFIX + chunk.text for chunk in self.chunks]
        self.embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        self.dim = self.embeddings.shape[1] if len(self.embeddings) else 0

    def scores(self, query: str) -> list[float]:
        """Cosine similarity of ``query`` against every chunk, in chunk
        order. The query is embedded as-is (the model is multilingual,
        so a Tamil/Hindi query needs no translation on this side)."""
        if not self.chunks:
            return []
        query_vec = self.model.encode(
            [QUERY_PREFIX + query],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )[0]
        return [float(s) for s in (self.embeddings @ query_vec)]

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """Top-``top_k`` (chunk index, cosine) pairs, best first."""
        scored = sorted(
            ((i, s) for i, s in enumerate(self.scores(query))),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return scored[:top_k]
