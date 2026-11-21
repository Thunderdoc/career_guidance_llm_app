"""Deterministic profile extraction (Kaam-Vaani Stage 2).

Server-side mirror of the frontend voice extractor
(``frontend/lib/voice-profile.ts``): turns a spoken/typed free-text
answer ("I finished 12th in Madurai, I know farming and basic computers,
I need about fifteen thousand a month") into the structured profile the
recommendation engine takes. This is the OFFLINE fallback the master
prompt §4.2 requires — it runs with no LLM and no key. Stage 3 adds LLM
structured-output extraction in front of it (with a repair prompt on
invalid output) and the confirmation flow; the deterministic path stays
as the fallback and as the thing the Stage 2 eval measures.

Both paths agree by construction: skills come from the same vocabulary
(``data/skill_synonyms.yaml`` + ``data/voice_aliases.yaml`` — the single
source of truth shared with ``scripts/gen_voice_vocab.py``), cities from
``data/kv_cities.yaml`` (same English list as the frontend, plus
native-script aliases). Two deliberate extensions over the frontend
extractor, recorded in ``ASSUMPTIONS.md`` (A16): Devanagari/Tamil-script
education patterns and income words (₹/रुपये/ரூபாய், हजार/ஆயிரம்,
लाख/லட்சம்), and Devanagari/Tamil digit normalisation — the frontend
patterns are English-only, so a Hindi/Tamil transcript would lose the
education and income fields there. Stage 3 ports the parity to the
frontend.

Everything extracted is shown to the user for confirmation before use
(Stage 3); the extractor never invents a field — anything not recognised
stays in the free-text ``interests`` field.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_YAML = ROOT / "data" / "skill_synonyms.yaml"
VOICE_ALIASES_YAML = ROOT / "data" / "voice_aliases.yaml"
CITIES_YAML = ROOT / "data" / "kv_cities.yaml"

# Devanagari (०-९) and Tamil (௦-௯) digits → ASCII. Chrome's hi-IN / ta-IN
# recognition usually returns Latin digits, but normalising costs nothing
# and saves the income parser when it does not.
_DIGIT_MAP = str.maketrans(
    "".join(chr(c) for c in range(0x966, 0x970)) + "".join(chr(c) for c in range(0xBE6, 0xBF0)),
    "0123456789" * 2,
)


def normalise_digits(text: str) -> str:
    """Map Devanagari/Tamil digits to ASCII digits (other text unchanged)."""
    return text.translate(_DIGIT_MAP)


class VoiceProfile(BaseModel):
    """Structured profile extracted from one transcript (Stage 3 reuses
    this schema for LLM structured output)."""

    skills: list[str] = []
    interests: str = ""
    education: str = ""
    city: str = ""
    income_text: str = ""
    income_monthly: int | None = None
    goal_type: str = "explore"
    raw_text: str = ""


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Vocabulary:
    """Skill aliases (longest first) + cities, loaded once and cached."""

    skill_aliases: tuple[tuple[str, str], ...] = ()
    # (canonical city, (aliases incl. the English name, lower-cased))
    cities: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def canonical_skills(self) -> set[str]:
        return {canon for _, canon in self.skill_aliases}


def _load_skill_aliases() -> list[tuple[str, str]]:
    data = yaml.safe_load(SKILL_YAML.read_text(encoding="utf-8"))
    skills = data["skills"]
    pairs: dict[str, str] = {}
    for canonical, entry in skills.items():
        canon = str(canonical).strip().lower()
        aliases = [canon, *[str(a).strip().lower() for a in entry.get("aliases", [])]]
        for alias in aliases:
            if len(alias) >= 2 and not alias.isdigit():
                pairs.setdefault(alias, canon)
    extra = yaml.safe_load(VOICE_ALIASES_YAML.read_text(encoding="utf-8"))["extra_aliases"]
    for alias, canon in extra.items():
        alias, canon = str(alias).strip().lower(), str(canon).strip().lower()
        if canon not in {str(c).strip().lower() for c in skills}:
            raise ValueError(f"voice_aliases.yaml: {alias!r} maps to unknown canonical {canon!r}")
        pairs.setdefault(alias, canon)
    return sorted(pairs.items(), key=lambda kv: (-len(kv[0]), kv[0]))


def _load_cities() -> list[tuple[str, tuple[str, ...]]]:
    data = yaml.safe_load(CITIES_YAML.read_text(encoding="utf-8"))
    out = []
    for entry in data["cities"]:
        name = str(entry["name"])
        aliases = tuple([name.lower(), *[str(a).lower() for a in entry.get("aliases", [])]])
        out.append((name, aliases))
    return out


@lru_cache(maxsize=1)
def load_vocabulary() -> Vocabulary:
    """Load (and cache) the skill + city vocabulary from the data files."""
    return Vocabulary(
        skill_aliases=tuple(_load_skill_aliases()),
        cities=tuple(_load_cities()),
    )


# --------------------------------------------------------------------------- #
# Matching helpers — unicode-aware (the TS extractor's containsPhrase logic)
# --------------------------------------------------------------------------- #


def _is_word_char(char: str) -> bool:
    """Letter/mark/number/_ — marks (category M) count as word characters
    so Indic-script words do not split at vowel signs: without this, the
    alias "कर" (tax) would match inside "नौकरी" (job), because the vowel
    sign ौ before it is a mark, not a letter. (The frontend TS check is
    letters/numbers only — see ASSUMPTIONS.md A16.)"""
    return char == "_" or unicodedata.category(char)[0] in ("L", "M", "N")


def contains_phrase(haystack: str, phrase: str) -> bool:
    """True when ``phrase`` occurs in ``haystack`` at a word boundary.

    ``\\b`` fails for non-Latin scripts, so boundaries are checked by
    hand: the characters immediately before/after the match must not be
    word characters. Used for Latin-script phrases; native-script city
    names use plain substring matching (agglutinative suffixes such as
    Tamil -இல் defeat boundary checks) — see :func:`extract_city`.
    """
    start = 0
    while True:
        idx = haystack.find(phrase, start)
        if idx == -1:
            return False
        before = haystack[idx - 1] if idx > 0 else " "
        after = haystack[idx + len(phrase)] if idx + len(phrase) < len(haystack) else " "
        if not _is_word_char(before) and not _is_word_char(after):
            return True
        start = idx + 1


def _is_latin(text: str) -> bool:
    return all(ord(c) < 128 for c in text)


# --------------------------------------------------------------------------- #
# ASR fixes — common speech-recognition mishearings of trade words and
# place names (lower-case). Shared with the RAG query rewriter
# (``career_guidance.kaamvaani.rag.rewrite_query``): the extractor applies
# them before matching so a noisy transcript still yields its fields.
# --------------------------------------------------------------------------- #

ASR_FIXES = {
    "electrition": "electrician",
    "electrisian": "electrician",
    "electrican": "electrician",
    "weldering": "welding",
    "weldin": "welding",
    "tailer": "tailor",
    "tayloring": "tailoring",
    "plumer": "plumber",
    "pluming": "plumbing",
    "mechnic": "mechanic",
    "mechanick": "mechanic",
    "carpender": "carpenter",
    "masonary": "masonry",
    "farmingg": "farming",
    "madhurai": "madurai",
    "trichi": "trichy",
    "tiruchi": "trichy",
    "tuticorin": "thoothukudi",
    "banglore": "bengaluru",
    "bangalore": "bengaluru",
}


def fix_asr(text: str) -> tuple[str, list[str]]:
    """Replace whole-word ASR mishearings (case-insensitive). Returns
    (fixed text, list of ``wrong->right`` fixes applied). Non-replaced
    words keep their original case."""
    applied: list[str] = []
    parts = re.split(r"(\W+)", text)
    fixed = []
    for part in parts:
        lowered = part.lower()
        if lowered in ASR_FIXES and lowered != ASR_FIXES[lowered]:
            applied.append(f"{lowered}->{ASR_FIXES[lowered]}")
            fixed.append(ASR_FIXES[lowered])
        else:
            fixed.append(part)
    return "".join(fixed), applied


# --------------------------------------------------------------------------- #
# Education — English patterns mirror the frontend; Devanagari/Tamil forms
# are a Stage 2 extension (see module docstring). Native-script alternatives
# carry no trailing ``\\b``: a combining mark (e.g. the ी in 12वीं) is not
# a word character, so ``\\b`` after it can never match.
# --------------------------------------------------------------------------- #

EDUCATION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b12\s?th\b|\bclass\s*12\b|\bplus\s*two\b|\b\+2\b|\bhsc\b|\bxii\b"
        r"|12\s*(?:वीं|वी)|12\s*(?:ஆம்|ம்)\s*வகுப்பு|பன்னிரண்டாம்\s*வகுப்பு|बारहवीं",
        "12th pass",
    ),
    (
        r"\b10\s?th\b|\bclass\s*10\b|\bsslc\b|\bmetric\b"
        r"|10\s*(?:वीं|वी)|10\s*(?:ஆம்|ம்)\s*வகுப்பு|பத்தாம்\s*வகுப்பு|दसवीं",
        "10th pass",
    ),
    (
        r"\b8\s?th\b|\bclass\s*8\b"
        r"|8\s*(?:वीं|वी)|8\s*(?:ஆம்|ம்)\s*வகுப்பு|எட்டாம்\s*வகுப்பு|आठवीं",
        "8th pass",
    ),
    (r"\biti\b|आईटीआई|ஐடிஐ", "ITI"),
    (r"\bdiploma\b|डिप्लोमा|டிப்ளமோ", "Diploma"),
    (r"\bb\.?\s?tech\b|\bbtech\b|\bb\.?\s?e\b|\bengineering\b", "B.Tech"),
    (r"\bm\.?\s?tech\b|\bmtech\b", "M.Tech"),
    (r"\bb\.?\s?sc\b|\bbsc\b", "B.Sc"),
    (r"\bm\.?\s?sc\b|\bmsc\b", "M.Sc"),
    (r"\bb\.?\s?com\b|\bbcom\b", "B.Com"),
    (r"\bm\.?\s?com\b|\bmcom\b", "M.Com"),
    (r"\bmba\b", "MBA"),
    (r"\bb\.?\s?a\b|\bba\s+degree\b", "B.A."),
    (r"\bgraduate\b|\bgraduation\b|\bdegree\b", "Graduate"),
    (r"\bdropout\b|\bdropped\s+out\b|\bleft\s+school\b", "School (incomplete)"),
)

_EDUCATION_RES = [(re.compile(p, re.IGNORECASE), label) for p, label in EDUCATION_PATTERNS]


def extract_education(text: str) -> str:
    """First matching education label, or "" when nothing is recognised."""
    normalised = normalise_digits(text)
    for regex, label in _EDUCATION_RES:
        if regex.search(normalised):
            return label
    return ""


# --------------------------------------------------------------------------- #
# Income — ₹ / Rs / rupees / रुपये / ரூபாய் / "k" / thousand / हजार / ஆயிரம் /
# lakh / लाख / லட்சம், monthly. A bare number never matches (it is as likely
# a year or a phone fragment); a currency marker, a unit, or a monthly
# marker is required. Bounds ₹500–₹10,00,000/month (as the frontend).
# --------------------------------------------------------------------------- #

_CURRENCY = r"(?:₹|rs\.?|inr|rupees?|रुपये|रुपया|रू\.?|ரூபாய்|ரூ\.?)"
_UNIT = r"(k|thousand|हज़ार|हजार|ஆயிரம்|lakh|लाख|லட்சம்|l|lac)"
_MONTHLY = r"(?:per\s*month|monthly|a\s*month|/month|\bpm\b|महीना|मासिक|மாதம்|மாதாந்திர)"
_NUM = r"([\d,]*\d[\d,]*(?:\.\d+)?)"  # at least one digit: [\d,]+ also matches a bare ","
INCOME_RE = re.compile(
    rf"(?:{_CURRENCY}\s*{_NUM}\s*{_UNIT}?|{_NUM}\s*{_UNIT}\s*{_MONTHLY}?"
    rf"|{_NUM}\s*{_CURRENCY}\s*{_MONTHLY}?|{_NUM}\s*{_MONTHLY})",
    re.IGNORECASE,
)
_UNIT_MULTIPLIER = {
    "lakh": 100_000,
    "लाख": 100_000,
    "லட்சம்": 100_000,
    "l": 100_000,
    "lac": 100_000,
    "k": 1_000,
    "thousand": 1_000,
    "हज़ार": 1_000,
    "हजार": 1_000,
    "ஆயிரம்": 1_000,
}

MIN_INCOME_MONTHLY = 500
MAX_INCOME_MONTHLY = 1_000_000


def parse_income(text: str) -> tuple[int | None, str]:
    """(monthly amount in INR, display string) or (None, "") when absent."""
    match = INCOME_RE.search(normalise_digits(text))
    if not match:
        return None, ""
    groups = [g for g in match.groups() if g is not None]
    raw_num = groups[0].replace(",", "")
    unit = groups[1].lower() if len(groups) > 1 else ""
    try:
        num = float(raw_num)
    except ValueError:
        return None, ""
    if num <= 0:
        return None, ""
    amount = round(num * _UNIT_MULTIPLIER.get(unit, 1))
    if amount < MIN_INCOME_MONTHLY or amount > MAX_INCOME_MONTHLY:
        return None, ""
    return amount, f"₹{amount:,} / month"


# --------------------------------------------------------------------------- #
# City — English names need a preposition (as the frontend: from/in/near/at/
# around) or a Hindi/Tamil postposition after the city ("Chennai mein",
# "Madurai se", "Salem la"); native-script names match by substring
# because locatives are suffixes (மதுரையில் = "in Madurai"). First city in
# file order wins.
# --------------------------------------------------------------------------- #

_PREPOSITIONS = ("from", "in", "near", "at", "around", "mein", "me", "se")
_POSTPOSITIONS = ("mein", "me", "se", "la", "le")


def extract_city(text: str, vocab: Vocabulary | None = None) -> str:
    """Canonical English city name, or "" when none is recognised."""
    vocab = vocab or load_vocabulary()
    lowered = f" {normalise_digits(text).lower()} "
    pre = r"\b(?:" + "|".join(_PREPOSITIONS) + r")\s+"
    post = r"\s+(?:" + "|".join(_POSTPOSITIONS) + r")\b"
    for name, aliases in vocab.cities:
        for alias in aliases:
            if _is_latin(alias):
                escaped = re.escape(alias)
                if re.search(pre + escaped + r"\b", lowered) or re.search(
                    r"\b" + escaped + post, lowered
                ):
                    return name
            elif alias in lowered:
                return name
    return ""


# --------------------------------------------------------------------------- #
# Skills — longest-alias-first scan over the shared vocabulary.
# --------------------------------------------------------------------------- #


def extract_skills(text: str, vocab: Vocabulary | None = None) -> list[str]:
    """Canonical skill names found in ``text``, longest alias first."""
    vocab = vocab or load_vocabulary()
    lowered = f" {normalise_digits(text).lower()} "
    found: list[str] = []
    seen: set[str] = set()
    for alias, canonical in vocab.skill_aliases:
        if canonical in seen:
            continue
        if contains_phrase(lowered, alias):
            seen.add(canonical)
            found.append(canonical)
    return found


# --------------------------------------------------------------------------- #
# Goal type — Latin keywords use \b; native-script keywords match by
# substring (same combining-mark reason as the education patterns).
# --------------------------------------------------------------------------- #

_JOB_WORDS_LATIN = re.compile(
    r"\b(job|work|naukri|velai|kaam|earn|salary|employ|vazhkai|udyog|rozgar)\b",
    re.IGNORECASE,
)
_STUDY_WORDS_LATIN = re.compile(
    r"\b(study|college|degree|padhai|learn more|higher studies|university|padippu)\b",
    re.IGNORECASE,
)
_JOB_WORDS_NATIVE = ("வேலை", "சம்பளம்", "நௌகரி", "नौकरी", "काम", "रोजगार", "वेतन", "सैलरी")
_STUDY_WORDS_NATIVE = ("படிப்பு", "படிக்க", "கல்லூரி", "पढ़ाई", "पढ़ना", "कॉलेज", "यूनिवर्सिटी")


def extract_goal_type(text: str) -> str:
    """job_6_months / higher_studies / explore (job wins on a tie)."""
    if _JOB_WORDS_LATIN.search(text) or any(w in text for w in _JOB_WORDS_NATIVE):
        return "job_6_months"
    if _STUDY_WORDS_LATIN.search(text) or any(w in text for w in _STUDY_WORDS_NATIVE):
        return "higher_studies"
    return "explore"


# --------------------------------------------------------------------------- #
# Main extraction
# --------------------------------------------------------------------------- #


def extract_profile(text: str, vocab: Vocabulary | None = None) -> VoiceProfile:
    """Extract a structured profile from one transcript (or "" fields when
    the transcript says nothing the patterns recognise). ASR mishearings
    are fixed on the working copy before matching; ``raw_text`` keeps the
    original transcript."""
    vocab = vocab or load_vocabulary()
    trimmed = text.strip()
    if not trimmed:
        return VoiceProfile(raw_text="")

    fixed, _ = fix_asr(trimmed)
    skills = extract_skills(fixed, vocab)
    education = extract_education(fixed)
    city = extract_city(fixed, vocab)
    income_monthly, income_text = parse_income(fixed)

    # Interests: sentences that did not feed another field, so the user's
    # own words still reach the matcher instead of being thrown away.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", fixed) if s.strip()]
    kept = []
    for sentence in sentences:
        lower = sentence.lower()
        if education and any(regex.search(sentence) for regex, _ in _EDUCATION_RES):
            continue
        if city and city.lower() in lower:
            continue
        if income_monthly is not None and INCOME_RE.search(sentence):
            continue
        kept.append(sentence)
    interests = " ".join(kept)[:400]

    return VoiceProfile(
        skills=skills,
        interests=interests,
        education=education,
        city=city,
        income_text=income_text,
        income_monthly=income_monthly,
        goal_type=extract_goal_type(fixed),
        raw_text=trimmed,
    )
