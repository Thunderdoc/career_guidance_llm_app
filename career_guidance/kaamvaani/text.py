"""Shared text helpers for Kaam-Vaani retrieval (moved from ``rag.py`` in
Step 7A so the modules that share the tokenizer have a clean home).

The tokenizer is the single shared definition for retrieval scoring:
BM25, TF-IDF, the title bonus and the matcher all tokenise the same
way, so a term that matches in one place matches everywhere. Known
limitation: it splits on ``[^\\w]+``, and ``\\w`` does not cover Indic
combining marks (Tamil vowel signs, the pulli, Devanagari matras), so
Tamil/Hindi words are shredded into fragments. That is harmless for
scoring (Tamil/Hindi tokens never appear in the English KB, so they
score 0 whole or shredded) but it means the query translator
(``translate.py``) uses its own whole-word tokenizer — it must match
glossary keys against whole Indic words.
"""

from __future__ import annotations

import re

# Small English stopword set for the BM25 tokenizer (sklearn applies its
# own for TF-IDF). Tamil/Hindi tokens are never stopwords here.
# The second block is KB template noise + voice-query filler, measured on
# snapshot v1: "also"/"known" come from the "Also known as:" header
# (df 98%/95%) and "zone"/"preparation"/"level" from the preparation-level
# line — template words, never a query's subject. "work" is the generic
# filler of voice queries ("plumber work", "data entry work", "farm work")
# and carries no discrimination. Deliberately NOT stopwords: "job" (a real
# word again once the "Job Zone" header was reworded — it separates the
# NCS jobs portal from the myScheme schemes portal), "skill" ("Skill
# India" is a proper noun), "knowledge"/"tool"/"technology" (real query
# subjects). Both singular and plural forms are listed: the stopword
# check runs before stemming, so "skills" would otherwise survive.
_STOPWORDS = frozenset(
    """
    a an the and or but if then else when at by for with about against
    between into through during before after above below to from up down
    in out on off over under again further once here there all any both
    each few more most other some such no nor not only own same so than
    too very can could may might must shall should will would do does did
    is am are was were be been being have has had having i me my we our
    you your he him his she her it its they them their this that these
    those what which who whom how why when where is are was were
    also known zone zones preparation level levels work works
    """.split()
)

_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)


def _stem(token: str) -> str:
    """Light English plural stemming (ASCII words only): electricians →
    electrician, courses → course, cities → city. Without it a query for
    "electrician" misses a chunk that only says "Electricians" (both
    scorers tokenise the same way, so the stem must live in the shared
    tokenizer). Guards: words of ≤3 letters and endings -ss/-us/-is are
    never stripped (gas, business, analysis)."""
    if len(token) <= 3 or not token.isascii():
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens (unicode-aware); drops stopwords and tokens
    shorter than 2 characters, then light-stems English plurals.
    Tamil/Devanagari tokens pass through unstemmed."""
    tokens = []
    for raw in _TOKEN_RE.split(text.lower()):
        token = raw.strip()
        if len(token) < 2 or token in _STOPWORDS:
            continue
        tokens.append(_stem(token))
    return tokens


def estimate_tokens(text: str) -> int:
    """Rough token count for chunk sizing (whitespace words; documented as
    approximate — the chunker targets 300–500 by this measure)."""
    return len(text.split())
