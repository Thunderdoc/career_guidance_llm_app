"""Query translation for multilingual retrieval (Kaam-Vaani Step 7A).

The knowledge base is English-only, so a Tamil/Hindi question retrieves
nothing on its own (LIMITATIONS.md L16): the Tamil/Hindi tokens never
appear in the English chunks. This module translates the question's
content words to English with a static bilingual glossary
(``data/kv_glossary.yaml``) — occupation, skill and trade terms — and the
retriever scores the translation. It is a retrieval aid, not a general
translator: answers still come verbatim from the English KB, and the
assistant still answers in English (L16 stays open for answer language).

Matching: the query is split into whole words by a glossary-local
tokenizer (see :func:`_glossary_tokens`) and scanned left to right,
longest phrase first (3-gram, 2-gram, 1-gram). The tokenizer is
deliberately NOT the retriever's shared one: the shared tokenizer splits
on ``[^\\w]+``, and ``\\w`` does not cover Indic combining marks (Tamil
vowel signs, the pulli, Devanagari matras), so it shreds Tamil/Hindi
words into fragments — different words then collapse onto the same
fragments and match the wrong glossary entries (measured 21 Nov 2026:
"மின் பணியாளர்" translated to "security guard"). The glossary tokenizer
splits only on whitespace and punctuation, so Indic words stay whole.
Latin tokens pass through unchanged (PMKVY, NSDC, "free online course");
unmatched non-Latin tokens are dropped — they cannot match English text.
A small Tamil suffix strip (locative -இல்/-யில், dative -க்கு, ...)
retries a token that did not match, so "ஐடிஐயில்" still finds "ஐடிஐ";
the stripped form must itself be a glossary key, so stripping can never
invent a translation.

English queries are returned unchanged (no non-Latin script, no glossary
phrase), so the English retrieval path is byte-identical to before.
Complexity: O(n * w) token lookups for an n-token query with max phrase
width w=3, plus one YAML load cached for the process lifetime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.kaamvaani.cache import translation_cache

GLOSSARY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "kv_glossary.yaml"

_TAMIL_RE = re.compile(r"[\u0b80-\u0bff]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")

# Whole-word split for glossary matching: whitespace, ASCII punctuation
# and the Devanagari danda. Indic combining marks are NOT split points
# (unlike the retriever's [^\w]+ tokenizer — see the module docstring),
# so Tamil/Hindi words stay whole. No stopword dropping, no stemming,
# no length filter: multi-word keys ("बिजली का काम") must match exactly,
# including their function words.
_SPLIT_RE = re.compile(r"[\s.,;:!?()\"'«»\-–—/\\|@#$%^&*+=<>\[\]{}~`।]+")


def _glossary_tokens(text: str) -> list[str]:
    """Lower-cased whole-word tokens for glossary matching."""
    return [token for token in _SPLIT_RE.split(text.lower()) if token]


# Tamil case suffixes stripped (one at a time) when a token does not
# match the glossary — the stripped form must itself be a glossary key.
# Longest first: "உக்கு"/"ுக்கு" must be tried before "க்கு" (its tail)
# and "யில்" before "இல்", or "தொழிலாளர்களுக்கு" strips to the non-word
# "தொழிலாளர்களு" instead of "தொழிலாளர்கள்". "ுக்கு" (u-vowel-sign +
# kku) is the plural-dative ending: "கள்" + "உக்கு" becomes "களுக்கு",
# with the pulli replaced by the vowel sign.
_TAMIL_SUFFIXES = ("உக்கு", "ுக்கு", "யில்", "உடன்", "க்கு", "இல்", "ஓடு", "ஐ")

_MAX_PHRASE_TOKENS = 3


@dataclass(frozen=True)
class TranslatedQuery:
    """A query after glossary translation.

    ``text`` is the English query the retriever scores (the original
    query when nothing was translated). ``applied`` lists the glossary
    keys used, in order. ``source_language`` is "ta" / "hi" / "roman"
    when the query was translated, else "".
    """

    text: str
    applied: tuple[str, ...] = ()
    source_language: str = ""


@lru_cache(maxsize=1)
def _load_glossary() -> dict[tuple[str, ...], str]:
    """Glossary as token-tuple -> English terms (loaded once). Keys are
    tokenised with the glossary tokenizer, so a key and a query token
    are always compared in the same form."""
    data = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))
    entries: dict[tuple[str, ...], str] = {}
    for section in ("tamil", "hindi", "roman"):
        for source, english in (data.get(section) or {}).items():
            key = tuple(_glossary_tokens(str(source)))
            if key:
                entries[key] = str(english)
    return entries


def _strip_tamil_suffix(token: str, entries: dict[tuple[str, ...], str]) -> str | None:
    """Strip one Tamil case suffix and return the English for the
    stripped form, or None when no suffix leaves a glossary key.
    Every suffix is tried (longest first) — the first whose remainder
    is a key wins — so stripping can never invent a translation. The
    remainder is also tried with the pulli (்) restored: the plural
    dative "களுக்கு" loses the "கள்" pulli to the u-vowel sign, so
    "தொழிலாளர்களுக்கு" strips to "தொழிலாளர்கள" and only
    "தொழிலாளர்கள" + "்" is the glossary key."""
    for suffix in _TAMIL_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            stripped = token[: -len(suffix)]
            english = entries.get((stripped,))
            if english is None:
                english = entries.get((stripped + "்",))
            if english is not None:
                return english
    return None


def translate_query(query: str) -> TranslatedQuery:
    """Translate a Tamil/Hindi/Roman query to English for retrieval.

    English queries come back unchanged (``applied`` empty): no
    non-Latin script and no glossary phrase means there is nothing to
    translate, so the English retrieval path is unaffected. Results
    are cached (Step 8.6, ``cache.translation_cache``): the glossary
    is process-lifetime, so translation is a pure function of the
    query and a cached result is identical to a fresh one.
    ``TranslatedQuery`` is frozen, so sharing the cached instance is
    safe.
    """
    cached = translation_cache.get(query)
    if cached is not None:
        return cached
    result = _translate_query_uncached(query)
    translation_cache.put(query, result)
    return result


def _translate_query_uncached(query: str) -> TranslatedQuery:
    """The translation itself (see :func:`translate_query`)."""
    entries = _load_glossary()
    tokens = _glossary_tokens(query)
    if not tokens:
        return TranslatedQuery(query)
    has_tamil = bool(_TAMIL_RE.search(query))
    has_devanagari = bool(_DEVANAGARI_RE.search(query))
    out: list[str] = []
    applied: list[str] = []
    i = 0
    while i < len(tokens):
        matched = False
        for width in range(min(_MAX_PHRASE_TOKENS, len(tokens) - i), 0, -1):
            key = tuple(tokens[i : i + width])
            english = entries.get(key)
            if english is None and width == 1:
                english = _strip_tamil_suffix(tokens[i], entries)
            if english is not None:
                out.append(english)
                applied.append(" ".join(key))
                i += width
                matched = True
                break
        if matched:
            continue
        if tokens[i].isascii():
            out.append(tokens[i])  # Latin tokens pass through.
        # Unmatched non-Latin tokens are dropped: they cannot match
        # English text.
        i += 1
    if not applied and not has_tamil and not has_devanagari:
        return TranslatedQuery(query)
    language = "ta" if has_tamil else "hi" if has_devanagari else "roman"
    return TranslatedQuery(" ".join(out), tuple(applied), language)
