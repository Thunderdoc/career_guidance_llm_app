"""Answer-language rendering for Kaam-Vaani (L16 fix).

The knowledge base is English-only, so a Tamil/Hindi question gets a
correct, cited answer in English. This module renders the grounded
English answer in the question's language — with only verified
material, never an invented translation.

Two translators, in priority order:

* **Glossary** (always available, the default): the bilingual glossary
  (``data/kv_glossary.yaml``) inverted — English term -> Tamil/Hindi
  term — substituted into the answer, longest phrase first. Measured
  on the 189-case gold set (22 Nov 2026): the glossary covers 11.8%
  of answer words, and the title line carries a glossary term in
  46/68 Tamil/Hindi answers. The result is code-mixed, not a full
  translation — the occupation/scheme/figure terms read in the
  user's language and the detail stays English. Substitution is
  meaning-preserving BY CONSTRUCTION: every substituted term is a
  verified glossary pair, so no new claim can enter the answer
  (unlike LLM translation, which can hallucinate). The worst case
  is awkward grammar, never a wrong fact. Numbers, rupee figures,
  dates and proper nouns pass through untouched.
* **Argos** (optional, MT): full machine translation via
  argos-translate (opus-mt), behind ``KV_ANSWER_MT=argos`` — see
  :mod:`career_guidance.kaamvaani.answer_mt`. Not installed in CI;
  when it is unavailable the glossary path is used with a warning.

The local LLM (Qwen2.5-0.5B) was MEASURED for translation and
rejected (22 Nov 2026): 76.8 s for a Tamil answer it did not
translate at all (it echoed the English input, then degenerated
into repeating "Tools and Materials:"), and 89.8 s for a Hindi
answer of looped gibberish — see EVAL_REPORT.md. It is not a
translation path.

Language rules: only native-script questions (``source_language``
"ta"/"hi") are rendered — a Roman-script question ("roman") stays
English, because a user who writes in Latin script may not read
Tamil/Devanagari script, and transliteration is a separate,
unmeasured step. Refusals use fixed translated strings
(``REFUSAL_TEXT_LOCAL``) — simple sentences, agent-written,
unreviewed like the other Tamil/Hindi UI strings (LIMITATIONS.md
L5, flagged for native-speaker review before any pilot).

The citation verifier (Step 8.5) always checks the ENGLISH quote
(``answer_en``): verification proves the quote is grounded in its
cited chunk, and the rendered answer is a term-substitution (or
MT translation) of that verified quote — the ``verification``
field in the result describes the English source, never the
rendered text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from career_guidance.kaamvaani.translate import GLOSSARY_PATH

logger = logging.getLogger("career_guidance.kaamvaani.answer_lang")

# Translation methods reported on every answer (``translation_method``).
METHOD_NONE = "none"  # English — no translation attempted or possible.
METHOD_GLOSSARY = "glossary"  # Deterministic glossary term substitution.
METHOD_FIXED = "fixed"  # Fixed translated string (refusals only).
METHOD_ARGOS = "argos"  # Full MT via argos-translate (optional).

# Languages with a rendered answer. "roman" is deliberately absent:
# a Roman-script question stays English (see the module docstring).
RENDER_LANGUAGES = ("ta", "hi")

# Fixed refusal strings in the user's language (agent-written,
# unreviewed — L5). English is REFUSAL_TEXT in rag.py; these are its
# equivalents, kept as short standard sentences.
REFUSAL_TEXT_LOCAL = {
    "ta": "எனக்குத் தெரியாது — உங்கள் ஒருங்கிணைப்பாளரிடம் கேளுங்கள்.",
    "hi": "मुझे नहीं पता — कृपया अपने समन्वयक से पूछें।",
}

# English terms NEVER substituted, even when the glossary inverts to
# them: "card" is the L17 homonym — the glossary maps it from the ID-card
# sense ("அட்டை"/"कार्ड"), but an answer about playing cards (Gaming
# Dealers) would get the wrong word. A wrong substitution is worse
# than an untranslated word.
_DENYLIST = frozenset({"card"})

# The glossary's longest English value is 3 words ("Code on Wages",
# "National Career Service"), so 3-gram matching covers every entry.
_MAX_PHRASE_WORDS = 3

# Word characters for the English side of the substitution: ASCII
# letters only. Numbers, currency, punctuation and non-Latin script
# are separators and pass through untouched.
_WORD_RE = re.compile(r"[A-Za-z]+")
_TAMIL_RE = re.compile(r"[\u0b80-\u0bff]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")


@dataclass(frozen=True)
class TranslatedAnswer:
    """A rendered answer plus honest metadata.

    ``text`` is what the user reads. ``language`` is "ta"/"hi" when
    at least one term was rendered in that script, else "en".
    ``method`` is one of the METHOD_* labels. ``terms_translated``
    counts the glossary substitutions (0 for the English path).
    ``translated_share`` is the fraction of the answer's words in
    the target script (0.0 for English) — the honest measure of
    how much of the answer the user can read in their language.
    """

    text: str
    language: str
    method: str
    terms_translated: int = 0
    translated_share: float = 0.0


def _plural_forms(word: str) -> list[str]:
    """Plural forms of one English word (mirrors text._stem in
    reverse: "worker" -> "workers", "city" -> "cities"). Words of
    <=3 letters and -ss/-us/-is endings never pluralise — the same
    guards as the stemmer, so a plural key can never collide with
    a different word."""
    if len(word) <= 3 or word.endswith(("ss", "us", "is")):
        return []
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return [word[:-1] + "ies"]
    return [word + "s"]


@lru_cache(maxsize=2)
def load_inverted_glossary(language: str) -> dict[str, str]:
    """The glossary inverted for one language: English phrase (lower
    case) -> Tamil/Hindi term. First listed wins when several source
    terms share one English phrase (the glossary lists the most
    common form first). Plural forms are added as keys, so
    "Electricians" matches the "electrician" entry. Denied terms
    (``_DENYLIST``) are dropped. Cached per language for the
    process lifetime — the glossary file is static."""
    data = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8"))
    section = "tamil" if language == "ta" else "hindi"
    inverted: dict[str, str] = {}
    for source, english in (data.get(section) or {}).items():
        phrase = str(english).strip().lower()
        if not phrase or phrase in _DENYLIST:
            continue
        inverted.setdefault(phrase, str(source))
    # Plural keys for single-word entries (multi-word phrases
    # pluralise on their last word — "farm workers" is already
    # plural in the glossary, so only single words need forms).
    for phrase, term in list(inverted.items()):
        if " " in phrase:
            continue
        for plural in _plural_forms(phrase):
            inverted.setdefault(plural, term)
    return inverted


def _script_share(text: str, language: str) -> float:
    """Fraction of the text's words in the target script (Tamil /
    Devanagari). Words are whitespace-separated tokens; a token
    counts when it contains at least one character of the script."""
    pattern = _TAMIL_RE if language == "ta" else _DEVANAGARI_RE
    words = [w for w in text.split() if w.strip()]
    if not words:
        return 0.0
    in_script = sum(1 for w in words if pattern.search(w))
    return in_script / len(words)


def translate_answer_glossary(answer_en: str, language: str) -> TranslatedAnswer:
    """Render an English answer by glossary term substitution.

    Longest phrase first (3-gram, 2-gram, 1-gram) over the answer's
    English words, whole-word, case-insensitive. Separators (spaces,
    punctuation, numbers, currency) are preserved exactly, so a
    figure like "₹840" or a date survives untouched. When nothing
    matches, the English text is returned unchanged with method
    "none" — an untranslated answer must not claim a language it
    does not speak."""
    entries = load_inverted_glossary(language)
    # Split into alternating word / separator runs so the text
    # rebuilds byte-identically apart from the substitutions.
    parts = re.split(r"([A-Za-z]+)", answer_en)
    words = [(i, part) for i, part in enumerate(parts) if _WORD_RE.fullmatch(part)]
    terms = 0
    i = 0
    while i < len(words):
        matched = False
        for width in range(min(_MAX_PHRASE_WORDS, len(words) - i), 0, -1):
            phrase = " ".join(w.lower() for _, w in words[i : i + width])
            term = entries.get(phrase)
            if term is None:
                continue
            first_idx = words[i][0]
            parts[first_idx] = term
            for idx, _ in words[i + 1 : i + width]:
                parts[idx] = ""
            terms += 1
            i += width
            matched = True
            break
        if not matched:
            i += 1
    if terms == 0:
        return TranslatedAnswer(answer_en, "en", METHOD_NONE, 0, 0.0)
    text = "".join(parts)
    # A substituted phrase leaves empty word slots behind; collapse
    # the doubled spaces they leave (but keep newlines — the answer
    # is multi-line: title, then body).
    text = re.sub(r"[ \t]{2,}", " ", text)
    return TranslatedAnswer(
        text=text,
        language=language,
        method=METHOD_GLOSSARY,
        terms_translated=terms,
        translated_share=round(_script_share(text, language), 4),
    )


def translate_refusal(source_language: str | None) -> tuple[str, str, str]:
    """The refusal text in the question's language.

    Returns (text, language, method): the fixed translated refusal
    for Tamil/Hindi, else the English REFUSAL_TEXT (imported lazily
    to avoid a rag -> answer_lang -> rag import cycle — rag.py
    imports this module)."""
    if source_language in REFUSAL_TEXT_LOCAL:
        return REFUSAL_TEXT_LOCAL[source_language], source_language, METHOD_FIXED
    from career_guidance.kaamvaani.rag import REFUSAL_TEXT

    return REFUSAL_TEXT, "en", METHOD_NONE


def render_answer(
    answer_en: str,
    source_language: str | None,
    translator=None,
) -> TranslatedAnswer:
    """Render a verified English answer in the question's language.

    ``translator`` is an optional callable ``(text, language) ->
    TranslatedAnswer`` (the Argos MT path injects one; tests inject
    stubs). Without one, the glossary renderer is used. English and
    Roman-script questions return the English text unchanged
    (method "none"). A translator failure never breaks the answer:
    it falls back to the glossary path with a warning, and if that
    fails too, to English — the user always gets the grounded
    answer, in English at worst."""
    if source_language not in RENDER_LANGUAGES:
        return TranslatedAnswer(answer_en, "en", METHOD_NONE, 0, 0.0)
    if translator is not None:
        try:
            return translator(answer_en, source_language)
        except Exception as exc:  # noqa: BLE001 - fall back, never fail the answer
            logger.warning("answer translator failed (%s); using glossary", exc)
    return translate_answer_glossary(answer_en, source_language)
