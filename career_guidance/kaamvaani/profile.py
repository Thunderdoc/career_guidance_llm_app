"""LLM profile extraction + voice conversation state machine (Kaam-Vaani Stage 3).

Two halves, one module:

1. **Extraction.** :func:`extract_profile_smart` is the entry point the
   voice router calls. When an LLM is configured (the existing
   ``career_guidance.providers.ProviderFactory`` — OpenAI / Gemini /
   Ollama, selected by ``LLM_PROVIDER`` or key presence), the transcript
   goes through structured-output extraction first: the versioned
   system prompt in ``prompts/profile-extractor.md``, JSON parsed and
   validated against the :class:`VoiceProfile` schema, ONE repair
   attempt on invalid output (master prompt §5.3), then the
   deterministic extractor as the fallback. With no LLM configured the
   deterministic path runs directly — identical output to Stage 2, so
   the golden eval numbers do not move. LLM-extracted skills are
   normalised through the shared vocabulary (``data/skill_synonyms.yaml``
   + ``data/voice_aliases.yaml``) so both paths emit the same canonical
   skill names; a skill the vocabulary does not know is kept in the
   free-text ``interests`` field instead of being dropped or invented
   into a canonical.

   Model routing (§5.5b): extraction deliberately uses the single
   configured completer, which is already the cheap/fast tier in this
   app (``gpt-4o-mini`` / ``gemini-2.0-flash`` / local Ollama). There
   is no second, larger model configured anywhere in the app, so a
   two-model router would be fake — see ``ASSUMPTIONS.md``.

2. **Conversation state machine** (master prompt §5.4): greet →
   language → questions → confirm → matches → gap/learning → consent
   → next steps. :class:`VoiceSession` is the (serialisable) session
   state; :func:`transition` is a pure function over it, so the
   frontend can hold the state in ``sessionStorage`` and the server
   validates every transition on round-trip — no server-side session
   store, no transcript stored anywhere, and "resume if interrupted"
   works across a page reload within the tab session. Multi-turn
   memory is limited to the current session unless the user opts in
   (``remember=True`` — the opt-in storage for that is a later stage;
   the flag is recorded, not acted on, in Stage 3).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from career_guidance.config import Settings
from career_guidance.kaamvaani.cache import cached_completer
from career_guidance.kaamvaani.extract import (
    MAX_INCOME_MONTHLY,
    MIN_INCOME_MONTHLY,
    Vocabulary,
    VoiceProfile,
    contains_phrase,
    extract_education,
    extract_goal_type,
    extract_profile,
    extract_skills,
    load_vocabulary,
    normalise_digits,
    parse_income,
)
from career_guidance.models import ProviderError
from career_guidance.providers import ChatCompleter

logger = logging.getLogger("career_guidance.kaamvaani.profile")

ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = ROOT / "prompts"

# The guided-flow questions, in order (Stage 3 frontend asks these five;
# the state machine tracks answers by id). The question TEXT lives in the
# frontend i18n dicts — the backend only needs the stable ids.
QUESTION_IDS: tuple[str, ...] = ("skills", "education", "city", "income", "goal")

VOICE_STATES: tuple[str, ...] = (
    "greet",
    "language",
    "questions",
    "confirm",
    "matches",
    "gap_learning",
    "consent",
    "next_steps",
    "done",
)

VoiceState = Literal[
    "greet",
    "language",
    "questions",
    "confirm",
    "matches",
    "gap_learning",
    "consent",
    "next_steps",
    "done",
]

GOAL_TYPES = ("job_6_months", "higher_studies", "explore")

# Extraction methods reported to the frontend (and the status endpoint):
# which path produced the profile. Honest by construction — the caller
# cannot claim "llm" when the deterministic fallback ran.
EXTRACTION_METHODS = ("llm", "llm-repaired", "deterministic", "deterministic-fallback")


class ExtractionError(Exception):
    """LLM extraction failed (invalid output even after the repair
    attempt). Callers fall back to the deterministic extractor."""


# --------------------------------------------------------------------------- #
# Prompt library
# --------------------------------------------------------------------------- #


class PromptTemplate(BaseModel):
    """One versioned system prompt from ``/prompts``."""

    name: str
    version: str
    system_prompt: str


_VERSION_RE = re.compile(r"<!--\s*prompt:\s*([\w-]+)\s*\|\s*version:\s*([\d.]+)")


@lru_cache(maxsize=16)
def load_prompt(name: str) -> PromptTemplate:
    """Load ``prompts/<name>.md``: the version from its header comment,
    the system prompt from the rest of the file. Raises FileNotFoundError
    for an unknown prompt and ValueError when the version header is
    missing (an unversioned prompt must never ship silently)."""
    path = PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match or match.group(1) != name:
        raise ValueError(f"prompts/{name}.md has no valid version header")
    # The system prompt is everything after the header comment line.
    body = text.split("-->", 1)[1].strip()
    if not body:
        raise ValueError(f"prompts/{name}.md has an empty system prompt")
    return PromptTemplate(name=name, version=match.group(2), system_prompt=body)


# --------------------------------------------------------------------------- #
# LLM structured-output extraction
# --------------------------------------------------------------------------- #


def _strip_object_fence(payload: str) -> str:
    """Extract the JSON object from a model reply: strip ``` fences and
    take the substring from the first ``{`` to the last ``}``."""
    cleaned = payload.strip()
    if cleaned.startswith("```"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        cleaned = cleaned[start : end + 1] if start != -1 and end != -1 else cleaned
    return cleaned


def _parse_profile(payload: str) -> VoiceProfile:
    """Parse + Pydantic-validate one model reply as a VoiceProfile."""
    try:
        data = json.loads(_strip_object_fence(payload))
    except json.JSONDecodeError as error:
        raise ExtractionError(f"not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ExtractionError("expected a JSON object, got a JSON array or scalar")
    try:
        return VoiceProfile.model_validate(data)
    except ValidationError as error:
        raise ExtractionError(f"schema validation failed: {error}") from error


_REPAIR_TEMPLATE = (
    "Your previous reply was not valid output for the profile schema.\n"
    "Error: {error}\n"
    "Previous reply:\n{previous}\n\n"
    "Reply again with ONLY a corrected JSON object matching the schema — "
    "same transcript, same rules, no explanation."
)


def extract_profile_llm(
    text: str,
    completer: ChatCompleter,
    *,
    language: str = "en",
    vocab: Vocabulary | None = None,
) -> tuple[VoiceProfile, bool]:
    """Extract a profile with the LLM: structured output, Pydantic
    validation, ONE repair attempt on invalid output (§5.3). Returns
    ``(profile, repaired)`` — ``repaired`` is True when the repair
    attempt produced the profile. Raises :class:`ExtractionError` when
    both attempts fail, :class:`ProviderError` when the completer
    itself fails. The caller falls back to the deterministic extractor
    on either."""
    prompt = load_prompt("profile-extractor")
    user_content = f"Language: {language}.\nTranscript: {text.strip()}"
    try:
        first_reply = completer.complete(prompt.system_prompt, user_content)
        profile = _parse_profile(first_reply)
        repaired = False
    except ExtractionError as first_error:
        logger.warning("LLM extraction invalid output; retrying with repair prompt")
        repair = _REPAIR_TEMPLATE.format(error=first_error, previous=first_reply)
        profile = _parse_profile(completer.complete(prompt.system_prompt, repair))
        repaired = True
    return normalise_llm_profile(profile, text, vocab), repaired


def normalise_llm_profile(
    profile: VoiceProfile, raw_text: str, vocab: Vocabulary | None = None
) -> VoiceProfile:
    """Bring an LLM-extracted profile into line with the deterministic
    path's contract: skills through the shared vocabulary (unknown ones
    kept in ``interests`` so the words still reach the matcher), income
    clamped to the same bounds, goal type validated, raw transcript kept."""
    vocab = vocab or load_vocabulary()
    alias_map = dict(vocab.skill_aliases)  # alias (lower) -> canonical
    canonicals = vocab.canonical_skills

    kept: list[str] = []
    unmatched: list[str] = []
    for skill in profile.skills:
        lowered = str(skill).strip().lower()
        if not lowered:
            continue
        if lowered in canonicals:
            canonical = lowered
        elif lowered in alias_map:
            canonical = alias_map[lowered]
        else:
            unmatched.append(str(skill).strip())
            continue
        if canonical not in kept:
            kept.append(canonical)

    interests = profile.interests.strip()
    if unmatched:
        extra = "Also mentioned: " + ", ".join(unmatched)
        interests = f"{interests} {extra}".strip() if interests else extra
    interests = interests[:400]

    income_monthly = profile.income_monthly
    income_text = profile.income_text.strip()
    if income_monthly is not None and not (
        MIN_INCOME_MONTHLY <= income_monthly <= MAX_INCOME_MONTHLY
    ):
        income_monthly, income_text = None, ""
    elif income_monthly is None and income_text:
        income_monthly, income_text = parse_income(income_text)
    elif income_monthly is not None:
        income_text = f"₹{income_monthly:,} / month"

    goal_type = profile.goal_type if profile.goal_type in GOAL_TYPES else "explore"

    return VoiceProfile(
        skills=kept,
        interests=interests,
        education=profile.education.strip()[:60],
        city=profile.city.strip()[:80],
        income_text=income_text,
        income_monthly=income_monthly,
        goal_type=goal_type,
        raw_text=raw_text.strip(),
    )


def extract_profile_smart(
    text: str,
    settings: Settings | None = None,
    *,
    completer: ChatCompleter | None = None,
    vocab: Vocabulary | None = None,
) -> tuple[VoiceProfile, str]:
    """The extraction entry point: LLM first when a completer is
    configured (or passed in), deterministic fallback otherwise and on
    any LLM failure. Returns ``(profile, method)`` where ``method`` is
    one of ``EXTRACTION_METHODS``. With no completer the result is
    byte-identical to :func:`extract_profile` — the Stage 2 eval
    measures exactly this path.

    A completer created here from ``settings`` is wrapped in the
    shared LLM cache (``cached_completer``); a completer passed in by
    the caller is used as-is (the caller's choice — the voice router
    passes an already-cached one). The (profile, method) RESULT is
    cached one level up, in the voice router (``backend/kv_voice.py``),
    not here: this function takes an explicit completer and vocab, so
    (text, prompt version) alone does not determine its result, while
    the router owns one fixed completer and the process vocabulary,
    where the key is complete (Step 8.6, ``cache.profile_cache``).
    """
    if completer is None and settings is not None:
        completer = cached_completer(settings)
    if completer is None:
        return extract_profile(text, vocab), "deterministic"
    try:
        profile, repaired = extract_profile_llm(text, completer, vocab=vocab)
        return profile, "llm-repaired" if repaired else "llm"
    except (ProviderError, ExtractionError) as error:
        logger.warning(
            "LLM extraction failed (%s); using deterministic fallback", type(error).__name__
        )
        return extract_profile(text, vocab), "deterministic-fallback"


def match_city_bare(answer: str, vocab: Vocabulary | None = None) -> str:
    """Match a city name in a guided-flow answer WITHOUT requiring a
    preposition: the answer to "where do you live?" is a location by
    construction, so a bare "Madurai" counts. Still requires a real
    city from the shared list — anything else returns "" (never an
    invented city). Latin aliases need a word boundary (so "salem"
    does not match inside another word); native-script names match by
    substring, as in :func:`extract_city`."""
    vocab = vocab or load_vocabulary()
    lowered = f" {normalise_digits(answer).lower()} "
    for name, aliases in vocab.cities:
        for alias in aliases:
            if all(ord(c) < 128 for c in alias):
                if contains_phrase(lowered, alias):
                    return name
            elif alias in lowered:
                return name
    return ""


def extract_profile_guided(
    answers: dict[str, str],
    settings: Settings | None = None,
    *,
    completer: ChatCompleter | None = None,
    vocab: Vocabulary | None = None,
) -> tuple[VoiceProfile, str]:
    """Extract a profile from the guided flow's per-question answers.

    The base extraction runs over the combined transcript (LLM first
    when configured, deterministic otherwise — the same path as
    :func:`extract_profile_smart`), then the question context sharpens
    it: the city answer is matched bare (a bare "Madurai" counts), the
    education/income answers are parsed on their own, the skills
    answer's skills are unioned in, and the goal answer's goal wins
    when it names one. Per-question results only ever ADD precision —
    a field the question context cannot resolve keeps the base value,
    and nothing is invented for an unanswered question."""
    vocab = vocab or load_vocabulary()
    ordered = [answers.get(q, "").strip() for q in QUESTION_IDS]
    combined = ". ".join(part for part in ordered if part)
    profile, method = extract_profile_smart(combined, settings, completer=completer, vocab=vocab)

    by_question = dict(zip(QUESTION_IDS, ordered, strict=True))
    city = match_city_bare(by_question["city"], vocab)
    education = extract_education(by_question["education"])
    income_monthly, income_text = parse_income(by_question["income"])
    skills = extract_skills(by_question["skills"], vocab)
    goal = extract_goal_type(by_question["goal"])

    merged_skills = list(profile.skills)
    for skill in skills:
        if skill not in merged_skills:
            merged_skills.append(skill)
    return (
        profile.model_copy(
            update={
                "skills": merged_skills,
                "education": education or profile.education,
                "city": city or profile.city,
                "income_monthly": income_monthly
                if income_monthly is not None
                else profile.income_monthly,
                "income_text": income_text or profile.income_text,
                "goal_type": goal if goal != "explore" else profile.goal_type,
            }
        ),
        method,
    )


# --------------------------------------------------------------------------- #
# Conversation state machine (§5.4)
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VoiceSession(BaseModel):
    """One voice-onboarding session. Held by the client (sessionStorage)
    and round-tripped through the server, which validates every
    transition — the server stores no session and no transcript."""

    state: VoiceState = "greet"
    language: str = "en"
    question_index: int = 0
    answers: dict[str, str] = {}
    answer_source: dict[str, str] = {}
    profile: VoiceProfile | None = None
    confirmed: bool = False
    # Opt-in only: multi-turn memory beyond the current session. Stage 3
    # records the flag; the storage it would enable is a later stage.
    remember: bool = False
    created_at: datetime = _now()
    updated_at: datetime = _now()


def new_session(language: str = "en") -> VoiceSession:
    """A fresh session at the greet state."""
    if language not in ("en", "hi", "ta"):
        raise ValueError(f"unsupported language: {language!r}")
    return VoiceSession(language=language)


def combined_transcript(session: VoiceSession) -> str:
    """The session's non-empty answers joined in question order — the
    single transcript the extractor runs over."""
    parts = [session.answers[q].strip() for q in QUESTION_IDS if session.answers.get(q, "").strip()]
    return ". ".join(parts)


def _touch(session: VoiceSession, **changes) -> VoiceSession:
    """A copy of ``session`` with ``changes`` applied and ``updated_at``
    refreshed (the machine is pure — transitions never mutate)."""
    return session.model_copy(update={"updated_at": _now(), **changes})


def transition(session: VoiceSession, event: str, **data) -> VoiceSession:
    """Apply one event to ``session`` and return the new session.
    Raises ValueError on an illegal transition (wrong state, missing
    data, or a guard that fails) — the router turns that into a 400,
    so a client can never jump the flow (e.g. confirm without a
    profile, or reach matches without confirming)."""
    state = session.state

    if event == "restart":
        return new_session(session.language)

    if event == "start":
        if state != "greet":
            raise ValueError(f"start is only legal from greet, not {state}")
        return _touch(session, state="language")

    if event == "set_language":
        if state != "language":
            raise ValueError(f"set_language is only legal from language, not {state}")
        language = str(data.get("language", "")).strip().lower()
        if language not in ("en", "hi", "ta"):
            raise ValueError(f"unsupported language: {language!r}")
        return _touch(session, state="questions", language=language, question_index=0)

    if event == "answer":
        if state != "questions":
            raise ValueError(f"answer is only legal from questions, not {state}")
        question_id = str(data.get("question_id", ""))
        if question_id not in QUESTION_IDS:
            raise ValueError(f"unknown question: {question_id!r}")
        source = str(data.get("source", "typed"))
        if source not in ("voice", "typed", "skipped"):
            raise ValueError(f"unknown answer source: {source!r}")
        transcript = "" if source == "skipped" else str(data.get("transcript", "")).strip()
        answers = dict(session.answers)
        answers[question_id] = transcript
        sources = dict(session.answer_source)
        sources[question_id] = source
        # Advance to the next unanswered question (or past the end).
        remaining = [q for q in QUESTION_IDS if q not in answers]
        next_index = QUESTION_IDS.index(remaining[0]) if remaining else len(QUESTION_IDS)
        return _touch(session, answers=answers, answer_source=sources, question_index=next_index)

    if event == "extracted":
        if state != "questions":
            raise ValueError(f"extracted is only legal from questions, not {state}")
        missing = [q for q in QUESTION_IDS if q not in session.answers]
        if missing:
            raise ValueError(f"cannot extract with unanswered questions: {missing}")
        profile = data.get("profile")
        if not isinstance(profile, VoiceProfile):
            raise ValueError("extracted requires a VoiceProfile")
        return _touch(session, state="confirm", profile=profile)

    if event == "confirm":
        if state != "confirm":
            raise ValueError(f"confirm is only legal from confirm, not {state}")
        if session.profile is None:
            raise ValueError("cannot confirm without a profile")
        if data.get("confirmed") is not True:
            raise ValueError("confirm requires confirmed=true")
        return _touch(session, state="matches", confirmed=True)

    if event == "decline":
        if state != "confirm":
            raise ValueError(f"decline is only legal from confirm, not {state}")
        return _touch(session, state="questions", confirmed=False)

    if event == "edit_answer":
        if state != "confirm":
            raise ValueError(f"edit_answer is only legal from confirm, not {state}")
        question_id = str(data.get("question_id", ""))
        if question_id not in QUESTION_IDS:
            raise ValueError(f"unknown question: {question_id!r}")
        return _touch(session, state="questions", question_index=QUESTION_IDS.index(question_id))

    # Later stages plug in here (Stages 4/6 define the events that drive
    # them); the machine already knows the order, so a client cannot
    # skip ahead to consent before matches exist.
    if event == "to_gap_learning":
        if state != "matches":
            raise ValueError(f"to_gap_learning is only legal from matches, not {state}")
        return _touch(session, state="gap_learning")
    if event == "to_consent":
        if state != "gap_learning":
            raise ValueError(f"to_consent is only legal from gap_learning, not {state}")
        return _touch(session, state="consent")
    if event == "to_next_steps":
        if state != "consent":
            raise ValueError(f"to_next_steps is only legal from consent, not {state}")
        return _touch(session, state="next_steps")
    if event == "finish":
        if state != "next_steps":
            raise ValueError(f"finish is only legal from next_steps, not {state}")
        return _touch(session, state="done")

    raise ValueError(f"unknown event: {event!r}")
