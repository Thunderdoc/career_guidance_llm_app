"""Kaam-Vaani RAG store + retrieval (Stage 2).

Chunks live in the relational DB (migration v12 table ``kv_rag_chunks``)
and are scored in memory by a hybrid retriever: **BM25 (pure Python) +
TF-IDF cosine (scikit-learn, already a dependency)** — zero new
dependencies, works on SQLite and Postgres, no downloads (Stage 0
decision A4). Dense embeddings are an optional second retriever
(``career_guidance.kaamvaani.dense`` — multilingual-e5-small, enabled
with ``KV_DENSE_MODEL``), fused with the hybrid by reciprocal rank
fusion in :meth:`HybridRetriever.search`. ``sentence-transformers`` is
not installed in the build environment; the Step 7A comparison against
glossary translation is measured in ``EVAL_REPORT.md``.

Every chunk carries its full source citation (URL, title, date, licence,
language). The extractive answer is verbatim text from a retrieved chunk
plus its citation — with no LLM configured there is nothing that can
hallucinate, and the citation check in the eval verifies the cited
source is one the gold case expects. The grounded LLM answer (Stage 7)
reuses this retrieval + citation machinery.

Stores go through ``career_guidance.db.connect()`` (ARCHITECTURE §3.2) —
no new direct-``sqlite3`` stores — so the Postgres path works from day
one. SQL uses ``?`` placeholders; the dialect layer translates them.
"""

from __future__ import annotations

import json
import logging
import math
import re
import warnings
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from career_guidance import db as db_layer
from career_guidance.kaamvaani.citations import (
    VerificationResult,
    drop_unsupported,
    verify_answer,
)
from career_guidance.kaamvaani.extract import fix_asr
from career_guidance.kaamvaani.text import estimate_tokens, tokenize
from career_guidance.kaamvaani.trace import Trace, span_for
from career_guidance.kaamvaani.translate import translate_query

logger = logging.getLogger("career_guidance.kaamvaani.rag")

# Hybrid blend: BM25 and TF-IDF contribute equally (tuned on the Stage 2
# gold set; see EVAL_REPORT.md).
BM25_WEIGHT = 0.5
TFIDF_WEIGHT = 0.5
# Reciprocal rank fusion constant for the dense hybrid (Step 7A): the
# standard k=60 (Cormack et al. 2009) — large enough that a rank-1 item
# in one list does not swamp a rank-5 item in both.
RRF_K = 60
# Title-match boost, occupation chunks only: for "what does X do" the
# chunk whose TITLE is X is the answer, and short "Helper" occupations
# otherwise outrank it (their brief text scores higher per term). The
# bonus blends two signals over the ORIGINAL query terms (ASR-fixed,
# before place/synonym expansions — expansion terms must not earn title
# credit, or "Automotive Glass Installers" beats "Automotive Master
# Mechanics" for "car mechanic" on the expansion word "repairer"):
# coverage (fraction of the query's terms the title covers — "Data Entry
# Keyers" covers all of "data entry") and purity (fraction of the title's
# words that match the query — "Brickmasons" is all mason, "Plasterers
# and Stucco Masons" is one-third mason). Pure coverage ties "Nurse
# Practitioners" with "Clinical Nurse Specialists" (both cover "nurse")
# and lets the base scores pick the more comprehensive chunk; pure purity
# over-rewards short titles. Gated to topic == "occupation" or "wages":
# web/wiki page titles are not entity names and boosting them misranks
# scheme/rights questions (measured on the gold set — EVAL_REPORT.md),
# but a wage chunk's title IS its employment name ("Watch and ward
# (security guards)"), exactly like an occupation title — and without
# the bonus a short wage chunk outranks the right one on a construction
# question, and the Security Guards occupation chunk (with its bonus)
# outranks the watch-and-ward wage chunk on a Tamil/Hindi guard
# question, which then refuses on the figure rule (measured Step 7B).
# The scope chunk's title ("Labour Bureau VDA order — scope and
# areas") matches no wage-question term, so it earns no bonus.
# A title word matches a query term when equal, when it ENDS WITH the
# term ("brickmason" ends with "mason" — English compounds put the head
# noun last), or when it STARTS WITH the term plus an agent suffix
# ("farmworker" = "farm" + "worker"). The suffix remainder check is what
# keeps "nursery" (a farm occupation) from matching "nurse".
TITLE_BOOST_WEIGHT = 0.5
TITLE_COVERAGE_WEIGHT = 0.75
TITLE_SUFFIX_MIN_LEN = 4
_COMPOUND_REMAINDERS = frozenset(
    {
        "worker",
        "workers",
        "er",
        "ers",
        "man",
        "men",
        "woman",
        "women",
        "person",
        "people",
        "keeper",
        "keepers",
    }
)
# Subordinate roles ("Helpers--X", "Teacher Assistants", "Home Health
# Aides") are different jobs from X: a query for X (without the
# subordinate word) must not be answered with the subordinate's
# description.
_SUBORDINATE_TITLE_WORDS = frozenset({"helper", "assistant", "aide"})
SUBORDINATE_TITLE_PENALTY = 0.3

# Best hybrid score below this → "I don't know / ask your coordinator"
# (tuned on the Stage 2 gold set; see EVAL_REPORT.md).
REFUSAL_THRESHOLD = 0.15
# Absolute TF-IDF cosine floor for an answer. The hybrid score is
# normalised per query (the best hit always scores >= 0.5 whenever ANY
# term matches), so it cannot tell "weak incidental match" (e.g. the
# word "passport" inside a software name) from real grounding. The raw
# cosine is absolute (0-1) and does that job; calibrated on the Stage 2
# golden set (see EVAL_REPORT.md). The floor is split by the top chunk's
# topic: occupation chunks match spuriously through their keyword-soup
# sections (technology lists, alternate titles), so they need a higher
# floor; web/wiki chunks are focused prose, so a lower cosine still
# indicates topical relevance. A weak match (below WEAK_COSINE) also
# needs at least two independent query terms in the top chunk — one
# incidental word ("tell" in "tell me a joke") is not grounding, however
# rare it is. WEAK_COSINE sits below the weakest legitimate match in the
# gold set (a noisy electrician query at 0.127) and above the incidental
# ones, so a single-term topic question with a decent match still
# answers.
REFUSAL_COSINE_THRESHOLD = 0.10
REFUSAL_COSINE_THRESHOLD_WEB = 0.07
WEAK_COSINE = 0.10
# Title-evidence rescue (Step 8.1, for L53): the cosine floors are
# absolute while IDF is corpus-relative, so adding chunks pushed two
# legitimate occupation answers (kv-r013, kv-r039) below the floor —
# their cosines (0.0923, 0.0958) are below 0.10 while their top hits
# are the right chunks. A top hit whose TITLE matches the query
# strongly is grounded by the title itself: the title is the chunk's
# entity name, and a 0.20+ bonus means the query names the entity
# (coverage x purity, max 0.5). Measured on the 189-case gold set: a
# 0.20 threshold rescues exactly kv-r013 (bonus 0.312) and kv-r039
# (0.250) and ZERO refusal cases — the nearest refusal case (kv-x009,
# 0.167) stays refused, and 0.25 rescues the same two. The rescue
# waives the cosine floor AND the weak-match rule for that hit: the
# title match IS the second piece of evidence. It never waives the
# hybrid-score threshold, the out-of-scope patterns or the figure
# rule.
TITLE_RESCUE_THRESHOLD = 0.20

# How much of the top chunk the extractive answer quotes (characters).
ANSWER_MAX_CHARS = 600

# The shared tokenizer (tokenize / estimate_tokens) lives in
# career_guidance.kaamvaani.text and is re-exported here so existing
# importers (matching.py, consent.py, tests) keep working.


# --------------------------------------------------------------------------- #
# Chunks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Chunk:
    """One knowledge-base chunk with its full source citation."""

    source_id: str
    text: str
    source_url: str = ""
    source_title: str = ""
    source_date: str = ""
    licence: str = ""
    language: str = "en"
    topic: str = ""
    state: str = ""
    district: str = ""
    chunk_index: int = 0
    tokens: int = 0
    snapshot_version: str = ""
    id: int | None = None
    created_at: str = ""

    def citation(self) -> dict[str, str]:
        """The citation shown to the user (title + link + source date, so
        a reader can always tell how fresh a figure or claim is)."""
        return {
            "source_id": self.source_id,
            "title": self.source_title or self.source_id,
            "url": self.source_url,
            "date": self.source_date,
        }

    def to_dict(self) -> dict:
        """Snapshot-JSONL shape (no DB id / created_at — those are assigned
        on load)."""
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "source_date": self.source_date,
            "licence": self.licence,
            "language": self.language,
            "topic": self.topic,
            "state": self.state,
            "district": self.district,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "tokens": self.tokens or estimate_tokens(self.text),
            "snapshot_version": self.snapshot_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Chunk:
        """Validate a snapshot record (missing source/text fails loudly —
        a chunk without a citation must never enter the store)."""
        for required in ("source_id", "text"):
            if not str(data.get(required, "")).strip():
                raise ValueError(f"RAG chunk is missing required field {required!r}: {data!r}")
        return cls(
            source_id=str(data["source_id"]),
            text=str(data["text"]),
            source_url=str(data.get("source_url", "")),
            source_title=str(data.get("source_title", "")),
            source_date=str(data.get("source_date", "")),
            licence=str(data.get("licence", "")),
            language=str(data.get("language", "en")),
            topic=str(data.get("topic", "")),
            state=str(data.get("state", "")),
            district=str(data.get("district", "")),
            chunk_index=int(data.get("chunk_index", 0)),
            tokens=int(data.get("tokens", 0)),
            snapshot_version=str(data.get("snapshot_version", "")),
        )


@dataclass
class Hit:
    """One retrieved chunk with its hybrid score and per-scorer parts.
    ``bm25``/``tfidf`` are normalised per query (for ranking); ``raw_bm25``/
    ``raw_tfidf`` are the absolute scores (the cosine gates refusals).
    ``dense``/``raw_dense`` are the dense cosine (normalised / raw) when a
    dense retriever is fused in, else 0. ``title_bonus`` is the title
    bonus this hit earned (0 for non-occupation/wages topics) — the
    title-evidence rescue (Step 8.1) reads it. ``index`` is the chunk's
    position in the retriever's chunk list (used by the RRF fusion)."""

    chunk: Chunk
    score: float
    bm25: float = 0.0
    tfidf: float = 0.0
    raw_bm25: float = 0.0
    raw_tfidf: float = 0.0
    dense: float = 0.0
    raw_dense: float = 0.0
    title_bonus: float = 0.0
    index: int = -1

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "bm25": round(self.bm25, 4),
            "tfidf": round(self.tfidf, 4),
            "raw_tfidf": round(self.raw_tfidf, 4),
            "dense": round(self.dense, 4),
            "raw_dense": round(self.raw_dense, 4),
            "title_bonus": round(self.title_bonus, 4),
            "chunk": self.chunk.to_dict(),
            "citation": self.chunk.citation(),
        }


class _DenseScorer(Protocol):
    """Anything that scores a query against the chunk list (the dense
    retriever, or a stub in tests). Kept a Protocol so this module does
    not import ``dense.py`` — which imports :class:`Chunk` from here."""

    def scores(self, query: str) -> list[float]: ...


# --------------------------------------------------------------------------- #
# Store (through career_guidance.db.connect — no direct sqlite3)
# --------------------------------------------------------------------------- #

_CHUNK_COLUMNS = (
    "source_id",
    "source_url",
    "source_title",
    "source_date",
    "licence",
    "language",
    "topic",
    "state",
    "district",
    "chunk_index",
    "text",
    "tokens",
    "snapshot_version",
    "created_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RagStore:
    """RAG chunks in the relational DB (migration v12). ``target`` is the
    same path-or-URL the storage layer takes (``settings.database_target``)."""

    def __init__(self, target: str) -> None:
        self.target = target

    def replace_snapshot(self, chunks: list[Chunk], snapshot_version: str) -> int:
        """Replace the whole store with one snapshot version (ingestion is
        a full refresh). Returns the number of chunks stored."""
        conn = db_layer.connect(self.target)
        try:
            with conn:
                conn.execute("DELETE FROM kv_rag_chunks")
                for chunk in chunks:
                    conn.execute(
                        "INSERT INTO kv_rag_chunks ("
                        + ", ".join(_CHUNK_COLUMNS)
                        + ") VALUES ("
                        + ", ".join("?" for _ in _CHUNK_COLUMNS)
                        + ")",
                        (
                            chunk.source_id,
                            chunk.source_url,
                            chunk.source_title,
                            chunk.source_date,
                            chunk.licence,
                            chunk.language,
                            chunk.topic,
                            chunk.state,
                            chunk.district,
                            chunk.chunk_index,
                            chunk.text,
                            chunk.tokens or estimate_tokens(chunk.text),
                            snapshot_version,
                            _now_iso(),
                        ),
                    )
            return len(chunks)
        finally:
            conn.close()

    def count(self) -> int:
        conn = db_layer.connect(self.target)
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM kv_rag_chunks").fetchone()
            return int(row["n"])
        finally:
            conn.close()

    def count_by_topic(self) -> dict[str, int]:
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT topic, COUNT(*) AS n FROM kv_rag_chunks GROUP BY topic"
            ).fetchall()
            return {str(r["topic"]): int(r["n"]) for r in rows}
        finally:
            conn.close()

    def snapshot_versions(self) -> list[str]:
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT DISTINCT snapshot_version FROM kv_rag_chunks ORDER BY 1"
            ).fetchall()
            return [str(r["snapshot_version"]) for r in rows]
        finally:
            conn.close()

    def sources(self) -> list[dict[str, str]]:
        """Distinct sources with their citations + chunk counts."""
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT source_id, source_url, source_title, licence, language,"
                " COUNT(*) AS chunks FROM kv_rag_chunks"
                " GROUP BY source_id, source_url, source_title, licence, language"
                " ORDER BY source_id"
            ).fetchall()
            return [
                {
                    "source_id": str(r["source_id"]),
                    "source_url": str(r["source_url"]),
                    "source_title": str(r["source_title"]),
                    "licence": str(r["licence"]),
                    "language": str(r["language"]),
                    "chunks": int(r["chunks"]),
                }
                for r in rows
            ]
        finally:
            conn.close()

    def all_chunks(self) -> list[Chunk]:
        conn = db_layer.connect(self.target)
        try:
            rows = conn.execute(
                "SELECT id, " + ", ".join(_CHUNK_COLUMNS) + " FROM kv_rag_chunks ORDER BY id"
            ).fetchall()
            return [
                Chunk(
                    id=int(r["id"]),
                    source_id=str(r["source_id"]),
                    source_url=str(r["source_url"]),
                    source_title=str(r["source_title"]),
                    source_date=str(r["source_date"]),
                    licence=str(r["licence"]),
                    language=str(r["language"]),
                    topic=str(r["topic"]),
                    state=str(r["state"]),
                    district=str(r["district"]),
                    chunk_index=int(r["chunk_index"]),
                    text=str(r["text"]),
                    tokens=int(r["tokens"]),
                    snapshot_version=str(r["snapshot_version"]),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]
        finally:
            conn.close()


def load_snapshot_file(path: str | Path) -> tuple[list[Chunk], dict]:
    """Read a snapshot JSONL file (+ its ``.meta.json`` sidecar when
    present). Returns (chunks, meta)."""
    path = Path(path)
    chunks = [
        Chunk.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    meta_path = path.with_suffix("").with_suffix(".meta.json")
    meta: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return chunks, meta


# --------------------------------------------------------------------------- #
# Scorers
# --------------------------------------------------------------------------- #


class BM25Scorer:
    """Pure-Python BM25 (k1=1.2, b=0.75) with an inverted index — only
    documents containing a query term are scored."""

    def __init__(self, documents: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_count = len(documents)
        self.doc_lengths: list[int] = []
        self.avg_length = 0.0
        self._index: dict[str, list[tuple[int, int]]] = {}
        self._doc_freq: dict[str, int] = {}
        total = 0
        for doc_idx, doc in enumerate(documents):
            tokens = tokenize(doc)
            self.doc_lengths.append(len(tokens))
            total += len(tokens)
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            for token, tf in counts.items():
                self._index.setdefault(token, []).append((doc_idx, tf))
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
        self.avg_length = total / max(1, self.doc_count)

    def _idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        return math.log(1 + (self.doc_count - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        """One BM25 score per document (0 for documents with no term)."""
        out = [0.0] * self.doc_count
        for term in set(tokenize(query)):
            idf = self._idf(term)
            for doc_idx, tf in self._index.get(term, []):
                length = self.doc_lengths[doc_idx] or 1
                norm = (
                    tf
                    * (self.k1 + 1)
                    / (tf + self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1)))
                )
                out[doc_idx] += idf * norm
        return out


class TfidfRetriever:
    """TF-IDF cosine over chunk texts (sklearn — already a dependency;
    same vectorizer shape as ``career_guidance.semantic``)."""

    name = "tfidf"

    def __init__(self, documents: list[str]) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        self._cosine = cosine_similarity
        # The shared tokenizer (stopwords + light stemming) so TF-IDF
        # scores the same tokens as BM25; lowercase=False because
        # tokenize() already lower-cases, token_pattern=None because a
        # custom tokenizer makes it unused (sklearn warns otherwise).
        # The "stop_words may be inconsistent" warning is expected here:
        # sklearn tokenizes its own stop-word list with our stemming
        # tokenizer, so a few stemmed forms ("alway", "ourselve") do not
        # match the list — harmless, the words are still filtered by our
        # tokenizer first. Suppressed so eval/CI logs stay readable.
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
            stop_words="english",
            tokenizer=tokenize,
            lowercase=False,
            token_pattern=None,
        )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Your stop_words may be inconsistent.*",
                category=UserWarning,
            )
            self._matrix = self._vectorizer.fit_transform(documents)

    def scores(self, query: str) -> list[float]:
        sims = self._cosine(self._vectorizer.transform([query]), self._matrix)[0]
        return [max(0.0, min(1.0, float(s))) for s in sims]


def _normalise(scores: list[float]) -> list[float]:
    top = max(scores) if scores else 0.0
    if top <= 0:
        return [0.0] * len(scores)
    return [s / top for s in scores]


# --------------------------------------------------------------------------- #
# Query rewriting — ASR noise fixes + local-term expansion (rule-based)
# --------------------------------------------------------------------------- #

# ASR mishearings live in career_guidance.kaamvaani.extract (ASR_FIXES +
# fix_asr) and are shared with the profile extractor, so both paths fix
# the same words the same way.

# District / city name variants that mean the same place.
_PLACE_VARIANTS = {
    "madurai": ("madurai", "madhurai"),
    "trichy": ("trichy", "tiruchirappalli", "tiruchi"),
    "thoothukudi": ("thoothukudi", "tuticorin"),
    "bengaluru": ("bengaluru", "bangalore", "banglore"),
    "chennai": ("chennai", "madras"),
    "coimbatore": ("coimbatore", "kovai"),
    "mysuru": ("mysuru", "mysore"),
    "mangaluru": ("mangaluru", "mangalore"),
    "hubballi": ("hubballi", "hubli"),
    "prayagraj": ("prayagraj", "allahabad"),
    "gurugram": ("gurugram", "gurgaon"),
    "thiruvananthapuram": ("thiruvananthapuram", "trivandrum"),
}


# Query synonyms: everyday words for O*NET's vocabulary ("car" never
# appears in Automotive Body Repairers' text — it says "automotive
# vehicle"; "mechanic" never appears either — O*NET says "Repairers").
# Matched on stemmed query tokens, not substrings ("car" must not fire
# on "card").
_SYNONYM_EXPANSIONS = {
    "car": ("automotive", "vehicle"),
    "mechanic": ("repairer",),
    "house": ("building",),
}


def rewrite_query(
    query: str, expansions: dict[str, list[str]] | None = None
) -> tuple[str, list[str]]:
    """Rewrite a voice transcript for retrieval: fix common ASR
    mishearings, expand place-name variants, and append skill-synonym
    expansions (``expansions`` maps a lower-cased term to extra query
    terms — the eval passes the matcher vocabulary; the router passes the
    same). Returns (rewritten query, list of expansions applied)."""
    rewritten, applied = fix_asr(query.lower())
    extra_terms: list[str] = []
    for canonical, variants in _PLACE_VARIANTS.items():
        if any(v in rewritten for v in variants):
            for variant in variants:
                if variant not in rewritten:
                    extra_terms.append(variant)
            if canonical not in rewritten:
                extra_terms.append(canonical)
    query_terms = set(tokenize(rewritten))
    for term, extras in _SYNONYM_EXPANSIONS.items():
        if term in query_terms:
            for extra in extras:
                if extra not in rewritten:
                    extra_terms.append(extra)
                    applied.append(f"{term}+{extra}")
    if expansions:
        for term, extras in expansions.items():
            if term in rewritten:
                for extra in extras:
                    if extra not in rewritten:
                        extra_terms.append(extra)
                        applied.append(f"{term}+{extra}")
    if extra_terms:
        rewritten = f"{rewritten} {' '.join(sorted(set(extra_terms)))}"
    return rewritten, applied


# --------------------------------------------------------------------------- #
# Hybrid retriever + rerank interface
# --------------------------------------------------------------------------- #


def _title_term_matches(title_word: str, query_term: str) -> bool:
    """Does one title word cover one query term (see TITLE_BOOST_WEIGHT)?"""
    if title_word == query_term:
        return True
    if len(query_term) >= TITLE_SUFFIX_MIN_LEN and title_word.endswith(query_term):
        return True
    if title_word.startswith(query_term):
        return title_word[len(query_term) :] in _COMPOUND_REMAINDERS
    return False


def title_bonus(title: str, query_terms: set[str]) -> float:
    """Title-match bonus for one occupation chunk (0..TITLE_BOOST_WEIGHT):
    coverage of the query's terms blended with purity of the title."""
    title_terms = tokenize(title)
    if not title_terms or not query_terms:
        return 0.0
    covered = sum(1 for q in query_terms if any(_title_term_matches(t, q) for t in title_terms))
    pure = sum(1 for t in title_terms if any(_title_term_matches(t, q) for q in query_terms))
    coverage = covered / len(query_terms)
    purity = pure / len(title_terms)
    blended = TITLE_COVERAGE_WEIGHT * coverage + (1 - TITLE_COVERAGE_WEIGHT) * purity
    return TITLE_BOOST_WEIGHT * blended


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Fuse ranked index lists by reciprocal rank fusion: each list
    contributes 1/(k + rank) (rank 1-based) per item; items in several
    lists sum their contributions. Returns (index, fused score) best
    first. The fusion runs over the FULL rankings (no top-N truncation),
    so a chunk at rank 21 in both lists still outranks a chunk at rank
    1 in one — truncation would misorder exactly those cases."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda pair: pair[1], reverse=True)


class HybridRetriever:
    """BM25 + TF-IDF hybrid over a fixed chunk list. Metadata filters
    (language / topic / state / district) apply BEFORE scoring, so a
    filtered search never returns a chunk outside the filter. With a
    ``dense`` scorer attached (Step 7A), the hybrid ranking is fused
    with the dense ranking by reciprocal rank fusion — the dense side
    scores the ORIGINAL query (the multilingual model reads Tamil/Hindi
    natively), the hybrid side the glossary-translated one."""

    def __init__(self, chunks: list[Chunk], dense: _DenseScorer | None = None) -> None:
        self.chunks = list(chunks)
        self._dense = dense
        documents = [c.text for c in self.chunks]
        self._bm25 = BM25Scorer(documents)
        self._tfidf = TfidfRetriever(documents) if documents else None

    def _fuse_dense(self, query: str, hits: list[Hit], candidates: list[int]) -> list[Hit]:
        """Fuse the hybrid ranking with the dense ranking by reciprocal
        rank fusion. RRF sets the ORDER; each hit keeps its hybrid score
        (the refusal gates still read hybrid evidence) and gains its
        dense cosine (``dense`` normalised per query, ``raw_dense``
        absolute). Metadata filters apply to the dense side too: only
        candidate indices can fuse in."""
        assert self._dense is not None
        dense_scores = self._dense.scores(query)
        candidate_set = set(candidates)
        dense_top = max((dense_scores[i] for i in candidates), default=0.0)
        by_index = {hit.index: hit for hit in hits}
        hybrid_order = [hit.index for hit in hits]
        dense_order = [
            i
            for i, s in sorted(enumerate(dense_scores), key=lambda p: p[1], reverse=True)
            if s > 0 and i in candidate_set
        ]
        out: list[Hit] = []
        for idx, _rrf in reciprocal_rank_fusion([hybrid_order, dense_order]):
            hit = by_index.get(idx)
            if hit is None:
                # Ranked by dense only (hybrid score 0): a real hit with
                # no hybrid evidence — the refusal gates see score 0.
                hit = Hit(chunk=self.chunks[idx], score=0.0, index=idx)
            raw = dense_scores[idx]
            hit.dense = max(0.0, raw / dense_top) if dense_top > 0 else 0.0
            hit.raw_dense = raw
            out.append(hit)
        return out

    def search(
        self,
        query: str,
        top_k: int = 5,
        language: str | None = None,
        topic: str | None = None,
        topics: Collection[str] | None = None,
        state: str | None = None,
        district: str | None = None,
        rewrite: bool = True,
    ) -> list[Hit]:
        """Top-``top_k`` hits by hybrid score (0.5 BM25 + 0.5 TF-IDF, each
        normalised to its own best score for this query). ``topics``
        (Step 9.1) restricts to any of several topics at once — the
        rights assistant searches rights/scam/wages/employment while
        the occupation catalogue stays out. When both ``topic`` and
        ``topics`` are given, both apply (intersection)."""
        if not self.chunks:
            return []
        candidates = [
            i
            for i, chunk in enumerate(self.chunks)
            if (language is None or chunk.language == language)
            and (topic is None or chunk.topic == topic)
            and (topics is None or chunk.topic in topics)
            and (state is None or chunk.state == state)
            and (district is None or chunk.district == district)
        ]
        if not candidates:
            return []
        # Step 7A: translate a Tamil/Hindi query to English before
        # retrieval — the KB is English-only. translate_query is a
        # no-op for English queries, so the English path is unchanged.
        translated = translate_query(query) if rewrite else None
        search_query = translated.text if translated and translated.applied else query
        effective_query = rewrite_query(search_query)[0] if rewrite else query
        bm25_all = self._bm25.scores(effective_query)
        tfidf_all = self._tfidf.scores(effective_query) if self._tfidf else [0.0] * len(self.chunks)
        bm25_norm = _normalise([bm25_all[i] for i in candidates])
        tfidf_norm = _normalise([tfidf_all[i] for i in candidates])
        # Title bonus uses the ORIGINAL query terms (ASR-fixed, before
        # expansions) — see TITLE_BOOST_WEIGHT. For a translated query
        # the "original" is the translation: the terms the scorers saw,
        # since Tamil/Hindi tokens never match English titles.
        bonus_terms = (
            set(tokenize(fix_asr(search_query.lower())[0])) if rewrite else set(tokenize(query))
        )
        hits = []
        for rank, idx in enumerate(candidates):
            chunk = self.chunks[idx]
            score = BM25_WEIGHT * bm25_norm[rank] + TFIDF_WEIGHT * tfidf_norm[rank]
            bonus = 0.0
            if chunk.topic in ("occupation", "wages"):
                bonus = title_bonus(chunk.source_title, bonus_terms)
                score += bonus
            if chunk.topic == "occupation":
                title_terms = set(tokenize(chunk.source_title))
                subordinate = title_terms & _SUBORDINATE_TITLE_WORDS
                if subordinate and not (subordinate & bonus_terms):
                    score -= SUBORDINATE_TITLE_PENALTY
            if score > 0:
                hits.append(
                    Hit(
                        chunk=chunk,
                        score=score,
                        bm25=bm25_norm[rank],
                        tfidf=tfidf_norm[rank],
                        raw_bm25=bm25_all[idx],
                        raw_tfidf=tfidf_all[idx],
                        title_bonus=bonus,
                        index=idx,
                    )
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        if self._dense is not None:
            hits = self._fuse_dense(query, hits, candidates)
        # The reranker (when one plugs in) scores the query the
        # retriever saw — the translation for a Tamil/Hindi query.
        return rerank(search_query, hits, top_k)


def rerank(query: str, hits: list[Hit], top_k: int) -> list[Hit]:
    """Rerank interface (master prompt §5.2). v1 is the identity: hits
    are already ordered by hybrid score. A cross-encoder reranker plugs
    in here behind an env var when one is measured to help."""
    return hits[:top_k]


# --------------------------------------------------------------------------- #
# Refusal + extractive answer (the Stage 7 assistant reuses these)
# --------------------------------------------------------------------------- #

# Questions the assistant must never answer from the KB (medical advice,
# off-topic). Everything else refuses only on a low retrieval score.
_REFUSAL_PATTERNS = (
    re.compile(
        r"\b(cure|disease|medicine|medication|doctor|fever|pain|hospital|clinic"
        r"|diagnos|treatment|symptom|tablet|injection)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(इलाज|दवा|बीमारी|डॉक्टर|बुखार|दर्द|अस्पताल)", re.IGNORECASE),
    re.compile(r"(மருந்து|மருத்துவர்|மருத்துவம்|நோய்|காய்ச்சல்|வலி|மருத்துவமனை)", re.IGNORECASE),
    re.compile(r"\b(astrology|horoscope|lottery|jackpot|cricket score)\b", re.IGNORECASE),
    re.compile(r"(ज्योतिष|राशिफल|लॉटरी|ஜோதிடம்|ராசி பலன்|லாட்டரி)", re.IGNORECASE),
)

REFUSAL_TEXT = "I don't know — please ask your coordinator."

# A question asking for a wage/salary figure ("what is the minimum wage
# in ...") must be answered with a figure, not with framework text: the
# Code on Wages chunk describes the law but carries no wage figure, so
# quoting it would look like an answer while answering nothing. Refuse
# unless the top chunk actually contains a currency figure. (A question
# whose answer is "free" — e.g. "what is the fee?" — has no figure and
# is refused too; acceptable in v1, noted in LIMITATIONS.md.)
# The pattern runs on the ORIGINAL query (answer_question passes the
# untranslated text), so it has a group per language: English + Roman
# use \b (ASCII word boundaries work); Tamil/Hindi use plain substring
# alternation because \b breaks on Indic combining marks (L51) — the
# wage + question-word pairing is distinctive enough without
# boundaries. Step 7B added the Tamil / Hindi / Roman groups with the
# wage chunks.
_FIGURE_QUESTION = re.compile(
    r"\b(what|how much)\b.*\b(wage|salary|pay|paid)\b"
    r"|\b(wage|salary|pay|paid)\b.*\b(what|how much)\b"
    # Tamil: சம்பளம்/கூலி/ஊதியம் + எவ்வளவு/என்ன (how much/what)
    r"|(சம்பளம்|சம்பள|கூலி|ஊதியம்|ஊதிய).*(எவ்வளவு|என்ன)"
    r"|(எவ்வளவு|என்ன).*(சம்பளம்|சம்பள|கூலி|ஊதியம்|ஊதிய)"
    # Hindi: मजदूरी/वेतन/तनख्वाह/सैलरी/पगार + कितना/कितनी/कितने/क्या
    r"|(मजदूरी|वेतन|तनख्वाह|सैलरी|पगार).*(कितना|कितनी|कितने|क्या)"
    r"|(कितना|कितनी|कितने|क्या).*(मजदूरी|वेतन|तनख्वाह|सैलरी|पगार)"
    # Roman: kitna/kitni/evvalavu + wage/salary/sambalam/kooli/...
    r"|\b(kitna|kitni|evvalavu)\b.*\b(wage|salary|pay|paid|sambalam|kooli|vetan|majdoori|mazdoori)\b"
    r"|\b(wage|salary|pay|paid|sambalam|kooli|vetan|majdoori|mazdoori)\b.*\b(kitna|kitni|evvalavu)\b",
    re.IGNORECASE,
)


# A question about the LAW (the Code on Wages, the minimum-wage law)
# asks for an explanation, not a number — it is not a figure question
# even though it pairs a wage word with "what" ("ஊதிய சட்டம் என்றால்
# என்ன?" = "what is the Code on Wages?"). Without this exclusion the
# Tamil/Hindi figure patterns refuse every law question (measured
# Step 7B: kv-r068/kv-r098 refused on the figure rule before it).
# The exclusion only gates the figure rule, so a broad law/code/act
# match is safe: it never fires on a question without a wage word.
_LAW_QUESTION = re.compile(
    r"\b(law|code|act|legislation)\b"
    r"|(சட்டம்|சட்ட)"
    r"|(कानून|संहिता|अधिनियम)",
    re.IGNORECASE,
)
# A currency figure in a chunk: ₹/Rs./rupees next to a number. Two
# traps fixed in Step 7B (measured: the Tailors chunk passed the
# figure rule on the word "Sewers,"): (1) the number must START with
# a digit — "[\d,]+" also matched a bare comma, so "rs," counted as
# a figure; (2) "rs"/"rupees" need a word boundary, or the "rs" at
# the end of "Sewers"/"makers"/"workers" counts as rupees. No
# boundary before ₹ (it is not a word character — "\b₹" never
# matches after a space).
_CURRENCY_FIGURE = re.compile(
    r"(₹|\brs\.?|\brupees?)\s*\d[\d,]*"
    r"|\d[\d,]*\s*(₹|\brs\.?|\brupees?)",
    re.IGNORECASE,
)


def refusal_reason(query: str) -> str | None:
    """A pattern-based refusal reason, or None when no pattern matches."""
    for pattern in _REFUSAL_PATTERNS:
        if pattern.search(query):
            return "out_of_scope"
    return None


def answer_question(
    query: str,
    retriever: HybridRetriever,
    top_k: int = 5,
    threshold: float = REFUSAL_THRESHOLD,
    cosine_threshold: float = REFUSAL_COSINE_THRESHOLD,
    web_cosine_threshold: float = REFUSAL_COSINE_THRESHOLD_WEB,
    trace: Trace | None = None,
    topics: Collection[str] | None = None,
) -> dict:
    """Extractive answer over the RAG base: translate (Tamil/Hindi →
    English glossary translation, a no-op for English) → rewrite →
    retrieve → refuse on an out-of-scope pattern, on no hits, when the
    best chunk's raw TF-IDF cosine is below the floor for its topic, when
    a weak match rests on a single query term, or when a wage/salary-figure
    question's top chunk carries no currency figure → otherwise quote the
    top chunk (verbatim, truncated) with its citation. A top hit with a
    strong title match (title bonus >= TITLE_RESCUE_THRESHOLD) is
    grounded by its title and waives the cosine floor and the weak-match
    rule (Step 8.1, L53) — the score threshold, out-of-scope patterns
    and figure rule still apply. With no LLM configured the answer
    cannot add words the KB never said; the citation check in the eval
    verifies the cited source is expected. The returned dict carries
    the translation (``translated_query`` / ``source_language``, None
    when the query was already English) so the API can show what the
    assistant understood. Step 8.5: the answer is verified against
    its cited chunk before it is returned (``citations.py``) —
    unsupported sentences are dropped, and if nothing grounded
    remains the answer refuses with reason ``"unverified"``; the
    ``verification`` summary reports the check (None when the
    answer was refused before verification ran). Step 8.9: when a
    Trace is passed, the translate / retrieve / verify stages are
    timed as spans (counts and scores only — the trace module
    rejects any raw text). trace=None changes nothing. ``topics`` (Step
    9.1) restricts retrieval to a set of topics — the rights
    assistant passes rights/scam/wages/employment so an occupation
    chunk can never ground a rights answer; None searches
    everything, as before."""
    with span_for(trace, "translate") as span:
        translated = translate_query(query)
        # ``applied`` is the tuple of glossary terms used — the trace
        # records whether translation happened and how many terms,
        # not the terms themselves.
        span.detail["applied"] = bool(translated.applied)
        span.detail["terms"] = len(translated.applied)
        span.detail["source_language"] = translated.source_language or "en"
    scored_query = translated.text if translated.applied else query
    translation_info = {
        "translated_query": scored_query if translated.applied else None,
        "source_language": translated.source_language or None,
    }
    reason = refusal_reason(query)
    if reason is not None:
        return {
            "refused": True,
            "reason": reason,
            "answer": REFUSAL_TEXT,
            "citations": [],
            "top_score": 0.0,
            "top_cosine": 0.0,
            "retrieved": [],
            "verification": None,
            **translation_info,
        }
    hits = []
    with span_for(trace, "retrieve") as span:
        # ``topics`` is passed only when set: a duck-typed retriever
        # implementing the pre-9.1 search() signature (no ``topics``
        # parameter, e.g. the Step 8.1 title-rescue stub) must keep
        # working when no topic restriction is asked for.
        if topics is not None:
            hits = retriever.search(query, top_k=top_k, topics=topics)
        else:
            hits = retriever.search(query, top_k=top_k)
        span.detail["hits"] = len(hits)
        span.detail["top_score"] = round(hits[0].score, 4) if hits else 0.0
        span.detail["top_cosine"] = (
            round(max(hits[0].raw_tfidf, hits[0].raw_dense), 4) if hits else 0.0
        )
        span.detail["title_rescued"] = bool(hits and hits[0].title_bonus >= TITLE_RESCUE_THRESHOLD)
    top_score = hits[0].score if hits else 0.0
    # The cosine gate reads the stronger of the two cosine signals: the
    # hybrid TF-IDF cosine or the dense cosine (0.0 without a dense
    # retriever, so the no-dense path is unchanged). Both are cosines
    # on the same scale, so max() is principled here.
    top_cosine = max(hits[0].raw_tfidf, hits[0].raw_dense) if hits else 0.0
    cosine_floor = (
        web_cosine_threshold if hits and hits[0].chunk.topic != "occupation" else cosine_threshold
    )
    # The weak-match check counts the terms the scorers actually saw:
    # for a translated query those are the English terms, not the Tamil
    # / Hindi originals (which never appear in the chunk text).
    matched_terms = 0
    if hits:
        rewritten_terms = set(tokenize(rewrite_query(scored_query)[0]))
        matched_terms = len(rewritten_terms & set(tokenize(hits[0].chunk.text)))
    weak_ungrounded = top_cosine < WEAK_COSINE and matched_terms < 2
    # Title-evidence rescue (Step 8.1, L53): a top hit whose title
    # matches the query strongly is grounded by the title itself, so
    # the absolute cosine floor and the weak-match rule are waived for
    # it. The score threshold, out-of-scope patterns and figure rule
    # still apply (see TITLE_RESCUE_THRESHOLD).
    title_rescued = bool(hits) and hits[0].title_bonus >= TITLE_RESCUE_THRESHOLD
    # A law question is a framework question, not a figure question
    # (see _LAW_QUESTION): it must not be refused for lacking a figure.
    figure_question = bool(_FIGURE_QUESTION.search(query)) and not _LAW_QUESTION.search(query)
    figure_grounded = bool(hits and _CURRENCY_FIGURE.search(hits[0].chunk.text))
    if (
        not hits
        or top_score < threshold
        or (top_cosine < cosine_floor and not title_rescued)
        or (weak_ungrounded and not title_rescued)
        or (figure_question and not figure_grounded)
    ):
        return {
            "refused": True,
            "reason": "no_grounding",
            "answer": REFUSAL_TEXT,
            "citations": [],
            "top_score": round(top_score, 4),
            "top_cosine": round(top_cosine, 4),
            "retrieved": [h.to_dict() for h in hits],
            "verification": None,
            **translation_info,
        }
    top = hits[0].chunk
    answer = top.text.strip()
    if len(answer) > ANSWER_MAX_CHARS:
        answer = answer[:ANSWER_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    # Citation verification (Step 8.5): every answer sentence must
    # map to the cited chunk. A verbatim quote passes by
    # construction — the check is the guardrail for the future LLM
    # path and the proof for the extractive path. Unsupported
    # sentences are dropped; if nothing grounded remains, the
    # answer refuses instead of speaking ungrounded words.
    verification: VerificationResult
    dropped = 0
    with span_for(trace, "verify") as span:
        verification = verify_answer(answer, top.text)
        if not verification.verified:
            answer, dropped = drop_unsupported(answer, top.text)
            verification = (
                verify_answer(answer, top.text) if answer else VerificationResult((), False)
            )
        span.detail["verified"] = verification.verified
        span.detail["sentences"] = len(verification.sentences)
        span.detail["dropped"] = dropped
    if not answer:
        return {
            "refused": True,
            "reason": "unverified",
            "answer": REFUSAL_TEXT,
            "citations": [],
            "top_score": round(top_score, 4),
            "top_cosine": round(top_cosine, 4),
            "retrieved": [h.to_dict() for h in hits],
            "verification": verification.to_dict(),
            **translation_info,
        }
    return {
        "refused": False,
        "reason": None,
        "answer": answer,
        "citations": [top.citation()],
        "top_score": round(top_score, 4),
        "top_cosine": round(top_cosine, 4),
        "retrieved": [h.to_dict() for h in hits],
        "verification": {**verification.to_dict(), "dropped_sentences": dropped},
        **translation_info,
    }


def check_citation(answer: dict, expected_source_ids: list[str]) -> bool:
    """True when the answer cites at least one expected source (and was
    not refused). This is the Stage 2 faithfulness check: the answer is
    verbatim from a retrieved chunk, so a correct citation means the
    answer is grounded in an expected source."""
    if answer.get("refused"):
        return False
    cited = {c.get("source_id") for c in answer.get("citations", [])}
    return bool(cited & set(expected_source_ids))
