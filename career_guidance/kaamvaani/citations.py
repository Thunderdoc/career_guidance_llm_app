"""Citation verifier for Kaam-Vaani answers (Step 8.5).

Every answer sentence must map to its cited chunk. The verifier
checks that mapping with token overlap: a sentence is supported
when at least ``SENTENCE_SUPPORT_THRESHOLD`` of its content
tokens appear in the cited chunk's text (tokens come from the
repo's ``tokenize`` — stopwords dropped, light stemming — so
"helpers" and "helper" count as the same word).

What this proves — and what it does not
----------------------------------------
Kaam-Vaani answers are verbatim quotes of the top chunk, so the
verifier should pass on (nearly) every answer — it PROVES the
extractive guarantee on every response instead of assuming it,
and it is the guardrail the future LLM path will need (when a
model generates words, unsupported sentences get dropped or the
answer refuses). What it does NOT prove is relevance: the 6
still-unfaithful gold cases (kv-r015, kv-r033, kv-r056, kv-r059,
kv-r086, kv-r089) are all wrong-chunk citations — the answer is
verbatim from its cited chunk, but the chunk is the wrong one
for the question. Those answers PASS verification, because
verification checks grounding in the cited chunk, not whether
the cited chunk answers the question. That distinction is
LIMITATIONS.md L58, and the gold-set measurement reports both
numbers separately.

Truncation: answers are cut at 600 characters (``rag.py``) at a
word boundary with a trailing "…", so the last sentence may be
a fragment. A trailing "…" marks the final sentence truncated:
it is reported but excluded from the verified requirement (an
incomplete sentence must not fail verification for being
incomplete — the "…" already tells the reader).

Complexity: O(S x T) for S sentences and T chunk tokens (token
sets, so each sentence is a set intersection); negligible next
to retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from career_guidance.kaamvaani.text import tokenize

__all__ = [
    "SENTENCE_SUPPORT_THRESHOLD",
    "SentenceVerdict",
    "VerificationResult",
    "drop_unsupported",
    "split_sentences",
    "verify_answer",
    "verify_answer_dict",
]

# A sentence is supported when this fraction of its content tokens
# appear in the cited chunk. 0.8 (not 1.0) leaves room for
# stemming edge cases and the truncation cut; verbatim sentences
# score 1.0, so the threshold is not doing the work — the quote is.
SENTENCE_SUPPORT_THRESHOLD = 0.8

_SENTENCE_END = re.compile(r"[^.!?]+[.!?]+")


@dataclass(frozen=True)
class SentenceVerdict:
    """One answer sentence against its cited chunk."""

    text: str
    overlap: float
    supported: bool
    truncated: bool


@dataclass(frozen=True)
class VerificationResult:
    """The verification of one answer against one chunk."""

    sentences: tuple[SentenceVerdict, ...] = ()
    verified: bool = False

    @property
    def supported_count(self) -> int:
        return sum(1 for s in self.sentences if s.supported)

    @property
    def truncated_count(self) -> int:
        return sum(1 for s in self.sentences if s.truncated)

    @property
    def support_rate(self) -> float:
        complete = [s for s in self.sentences if not s.truncated]
        if not complete:
            return 1.0 if self.sentences else 0.0
        return sum(1 for s in complete if s.supported) / len(complete)

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "sentences": len(self.sentences),
            "supported": self.supported_count,
            "truncated": self.truncated_count,
            "support_rate": round(self.support_rate, 4),
        }


def split_sentences(text: str) -> list[str]:
    """Split text into sentences on ``.`` / ``!`` / ``?`` (the
    terminator stays attached). A trailing "…" is stripped before
    splitting — the caller marks the last sentence truncated.
    Text with no terminator is one sentence."""
    stripped = text.rstrip().removesuffix("…").rstrip()
    if not stripped:
        return []
    sentences = [m.group(0).strip() for m in _SENTENCE_END.finditer(stripped)]
    consumed = sum(len(m.group(0)) for m in _SENTENCE_END.finditer(stripped))
    remainder = stripped[consumed:].strip()
    if remainder:
        sentences.append(remainder)
    return [s for s in sentences if s]


def _overlap(sentence: str, chunk_tokens: set[str]) -> float:
    tokens = tokenize(sentence)
    if not tokens:
        return 1.0  # no content words — nothing to ground (e.g. "Rs. 500.")
    return len(set(tokens) & chunk_tokens) / len(set(tokens))


def verify_answer(answer_text: str, chunk_text: str) -> VerificationResult:
    """Verify every sentence of ``answer_text`` against ``chunk_text``.

    The answer is verified when every complete (non-truncated)
    sentence is supported and the answer has at least one
    sentence. An empty answer is not verified.
    """
    truncated = answer_text.rstrip().endswith("…")
    sentences = split_sentences(answer_text)
    if not sentences:
        return VerificationResult((), False)
    chunk_tokens = set(tokenize(chunk_text))
    verdicts: list[SentenceVerdict] = []
    for i, sentence in enumerate(sentences):
        is_truncated = truncated and i == len(sentences) - 1
        overlap = _overlap(sentence, chunk_tokens)
        verdicts.append(
            SentenceVerdict(
                text=sentence,
                overlap=round(overlap, 4),
                supported=overlap >= SENTENCE_SUPPORT_THRESHOLD,
                truncated=is_truncated,
            )
        )
    verified = all(v.supported for v in verdicts if not v.truncated)
    return VerificationResult(tuple(verdicts), verified)


def drop_unsupported(answer_text: str, chunk_text: str) -> tuple[str, int]:
    """Rebuild the answer from supported sentences only.

    Returns ``(cleaned_text, dropped_count)``. A truncated final
    sentence is kept when its fragment is grounded (its overlap
    is computed like any other sentence) — the "…" is re-attached
    only then, so the reader still sees the cut. An empty result
    means nothing was grounded.
    """
    result = verify_answer(answer_text, chunk_text)
    kept = [v for v in result.sentences if v.supported]
    cleaned = " ".join(v.text for v in kept)
    if any(v.truncated for v in kept) and cleaned and not cleaned.endswith("…"):
        cleaned += "…"
    return cleaned, len(result.sentences) - len(kept)


def verify_answer_dict(answer: dict) -> VerificationResult | None:
    """Verify an ``answer_question`` result dict against its cited
    chunk. Returns None for a refused answer (nothing to verify)
    or when the cited chunk is not among the retrieved hits (the
    verifier refuses to guess — no chunk, no verdict)."""
    if answer.get("refused"):
        return None
    citations = answer.get("citations") or []
    if not citations:
        return None
    cited_id = citations[0].get("source_id")
    for hit in answer.get("retrieved") or []:
        chunk = hit.get("chunk") or {}
        if chunk.get("source_id") == cited_id:
            return verify_answer(answer.get("answer", ""), chunk.get("text", ""))
    return None
