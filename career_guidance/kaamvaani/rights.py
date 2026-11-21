"""Kaam-Vaani rights/scam assistant (Step 9.1).

A topic-restricted view of the Stage 2 RAG: the same
``answer_question`` (hybrid retrieval + refusal gates + Step 8.5
citation verifier), but retrieval is restricted to the rights
topics — rights, scam, wages, employment — so an occupation chunk
can never ground a rights answer, and a career question asked here
refuses instead of being answered from the wrong domain.

Escalation is the safety net, and it is the one place this module
speaks words the knowledge base never said — so it is tightly
bounded: the escalation block lists ONLY helpline numbers from
``data/kv_helplines.json``, every one of them verified against the
official source it cites. A number not in that file can never
reach a worker (pinned by test). Escalation appears when the
question shows scam intent (English keywords on the translated
query) or the top retrieved chunk is a scam chunk; a plain rights
answer carries no escalation — the grounded answer is the help.

Answers are verbatim English quotes even for Tamil/Hindi questions
(same as the main RAG path, L16); scam-intent detection is
English-keyword based, so a Tamil/Hindi scam question relies on
the retrieved chunk's topic for its escalation (L63).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from career_guidance.kaamvaani.rag import HybridRetriever, answer_question
from career_guidance.kaamvaani.text import tokenize
from career_guidance.kaamvaani.trace import Trace

logger = logging.getLogger("career_guidance.kaamvaani.rights")

# The rights domain: worker rights, scam protection, minimum wage,
# employment services. Occupation (974 chunks), skilling and courses
# are deliberately OUT — they belong to the career-matching flow,
# not to a rights answer (A62).
RIGHTS_TOPICS = ("rights", "scam", "wages", "employment")

HELPLINES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "kv_helplines.json"

_REQUIRED_HELPLINE_FIELDS = (
    "number",
    "name",
    "purpose",
    "source_url",
    "source_date",
    "for",
)

# Scam-intent signals, checked against the scored (translated) query
# and the raw query. Single words match whole tokens; phrases match
# substrings. English only (L63) — the glossary translation covers
# occupation/skill/trade terms, not scam vocabulary.
_SCAM_WORDS = frozenset(
    {
        "scam",
        "scams",
        "scammer",
        "scammers",
        "fraud",
        "frauds",
        "fraudster",
        "cheated",
        "cheating",
        "phishing",
        "blackmail",
        "impersonation",
        "fake",
        "duped",
        "swindled",
    }
)
_SCAM_PHRASES = (
    "asked for money",
    "asking for money",
    "upfront fee",
    "registration fee",
    "advance fee",
    "advance payment",
    "took my money",
    "stole my money",
    "stolen money",
    "money back",
    "fake job",
    "fake offer",
    "pay to apply",
    "pay before",
    "deposit before",
)

_cache: dict[str, list[dict]] = {}


def load_helplines(path: Path | None = None) -> list[dict]:
    """Verified helplines from ``data/kv_helplines.json`` (cached per
    path). Entries missing a required field are skipped with a
    warning, never served half-sourced. A missing or unreadable file
    returns [] — the assistant still answers grounded questions, it
    just cannot escalate with numbers it has not verified."""
    resolved = str((path or HELPLINES_PATH).resolve())
    if resolved in _cache:
        return _cache[resolved]
    entries: list[dict] = []
    try:
        with open(resolved, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("helplines file unreadable (%s): %s", resolved, exc)
        _cache[resolved] = entries
        return entries
    for entry in data.get("helplines", []):
        if not isinstance(entry, dict) or any(
            not entry.get(field) for field in _REQUIRED_HELPLINE_FIELDS
        ):
            logger.warning("skipping incomplete helpline entry: %r", entry)
            continue
        entries.append(entry)
    _cache[resolved] = entries
    return entries


def clear_helplines_cache() -> None:
    """Drop the load cache (tests only)."""
    _cache.clear()


def scam_intent(query: str) -> bool:
    """True when the question looks like a scam/fraud situation:
    a scam word among its tokens, or a scam phrase inside it."""
    lowered = query.lower()
    if set(tokenize(lowered)) & _SCAM_WORDS:
        return True
    return any(phrase in lowered for phrase in _SCAM_PHRASES)


def escalation_for(scam: bool, helplines: list[dict] | None = None) -> list[dict]:
    """The escalation block for a scam situation: the verified
    helplines tagged for scam/fraud, each with its number, name,
    purpose and source. No scam, no escalation — and the numbers
    come only from the loaded file, never from anywhere else."""
    if not scam:
        return []
    lines = load_helplines() if helplines is None else helplines
    return [
        {
            "number": entry["number"],
            "name": entry["name"],
            "purpose": entry["purpose"],
            "source_url": entry["source_url"],
            "portal": entry.get("portal", ""),
            "toll_free": bool(entry.get("toll_free")),
        }
        for entry in lines
        if "scam" in entry.get("for", []) or "fraud" in entry.get("for", [])
    ]


def answer_rights_question(
    query: str,
    retriever: HybridRetriever,
    top_k: int = 5,
    trace: Trace | None = None,
    helplines: list[dict] | None = None,
) -> dict:
    """A grounded rights/scam answer: the Stage 2 extractive answer
    restricted to the rights topics, plus an ``escalation`` block
    (verified helplines, possibly empty) and the ``topics`` covered.
    Refusals keep the standard refusal text; a refused scam question
    still carries its escalation — the worker needs the helpline
    most exactly when the base has no grounded answer for them."""
    result = answer_question(query, retriever, top_k=top_k, topics=RIGHTS_TOPICS, trace=trace)
    scored = result.get("translated_query") or query
    intent = scam_intent(scored) or scam_intent(query)
    retrieved = result.get("retrieved") or []
    top_topic = retrieved[0]["chunk"]["topic"] if retrieved else None
    show_escalation = intent or top_topic == "scam"
    result["escalation"] = escalation_for(show_escalation, helplines)
    result["topics"] = list(RIGHTS_TOPICS)
    result["scam_intent"] = intent
    return result
