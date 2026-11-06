"""Scoped career chat (Phase 7) — grounded in ONE stored report, nothing else.

Contract and guardrails:

* Context is built ONLY from the caller's stored recommendation run
  (recommendations, the Reality Score recomputed deterministically for
  those same careers, and the run's linked 90-day plan when one exists)
  plus taxonomy entries for careers/skills the message itself names.
  No other user's data, no general knowledge, no invented figures.
* Scope is decided by a deterministic check (:func:`scope_check`) that
  needs no LLM: hard refusals for other-people/personal-data and
  coding-help/general-knowledge patterns; in-scope when the message
  carries a career-guidance intent word or names something in the
  report/retrieved context. Refusals carry the i18n key
  ``p7_chat_refusal`` so the UI localises them (EN/TA/HI).
* With an LLM configured (any factory provider), the model answers from
  the context text only and the answer must pass the shared faithfulness
  check (:func:`career_guidance.faithfulness.text_violations`); a
  violation or any provider failure falls back to the offline answerer.
* With NO LLM, a deterministic offline answerer extracts the relevant
  facts from the report (salary ladder, priority skills, gaps, plan…);
  when no specific intent matches it says so honestly:
  "AI chat is unavailable offline; here is what your report says: …".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from career_guidance.faithfulness import text_violations
from career_guidance.models import CareerRecommendation, ProviderError
from career_guidance.taxonomy import Taxonomy, extract_skills, load_taxonomy, normalize_skill

REFUSAL_KEY = "p7_chat_refusal"
REFUSAL_TEXT = (
    "I can only answer questions about this career report — your "
    "recommended careers, their skills, salaries, demand and your plan. "
    "Please ask about one of those."
)
OFFLINE_PREFIX = "AI chat is unavailable offline; here is what your report says: "

_CHAT_SYSTEM = (
    "You are a career counsellor answering questions about ONE stored "
    "career report. Answer ONLY from the REPORT CONTEXT provided. Do not "
    "use outside knowledge, do not invent salaries, skills or careers, "
    "and do not mention any other person. Keep the answer under 120 "
    "words and specific to the context."
)

# Requests that are never in scope for a report chat.
_HARD_PATTERNS = (
    "other user",
    "someone else",
    "another user",
    "another person",
    "password",
    "api key",
    "email address of",
    "phone number of",
    "write code",
    "write a program",
    "write a function",
    "debug this",
    "fix this code",
    "code for me",
    "solve this equation",
    "homework question",
    "capital of",
    "weather",
    "recipe for",
    "tell me a joke",
    "write a poem",
    "write a story",
    "cricket score",
    "stock price",
)

_INTENT_WORDS = (
    "career",
    "job",
    "salary",
    "pay",
    "earn",
    "learn",
    "skill",
    "course",
    "plan",
    "week",
    "roadmap",
    "why",
    "report",
    "match",
    "missing",
    "gap",
    "priority",
    "first",
    "demand",
    "market",
    "city",
    "cities",
    "sector",
    "interview",
    "resume",
    "alternative",
    "stepping",
    "compare",
    "better",
    "choose",
    "reality",
    "score",
    "prepare",
    "ready",
    "readiness",
    "transition",
    "switch",
    "fresher",
    "growth",
    "next step",
    "how long",
    "how much",
    "should i",
    "what should",
)


@dataclass
class CareerFact:
    """One recommendation flattened into chat-usable facts."""

    title: str
    career_id: str = ""
    match_percent: float = 0.0
    match_reason: str = ""
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    learning_path: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    salary_lines: list[str] = field(default_factory=list)
    reality_lines: list[str] = field(default_factory=list)


@dataclass
class ChatContext:
    """Everything the chat may draw on — and nothing else."""

    facts: list[CareerFact]
    priority_skills: list[str]
    plan_lines: list[str] = field(default_factory=list)
    retrieved: list[dict] = field(default_factory=list)
    allowed_terms: set[str] = field(default_factory=set)
    candidate_terms: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.facts:
            return "This report has no recommendations stored."
        top = self.facts[0]
        parts = [
            f"Top recommendation: {top.title} ({top.match_percent:.0f}% match).",
        ]
        if self.priority_skills:
            parts.append(f"Priority skills to learn first: {', '.join(self.priority_skills)}.")
        if top.next_steps:
            parts.append(f"First next step: {top.next_steps[0]}")
        return " ".join(parts)

    def prompt_text(self) -> str:
        lines = ["REPORT CONTEXT (the only facts you may use):", self.summary()]
        for fact in self.facts:
            lines.append(
                f"\n## {fact.title} — {fact.match_percent:.0f}% match\n"
                f"Why: {fact.match_reason}\n"
                f"Has: {', '.join(fact.matching_skills) or '—'}\n"
                f"Missing: {', '.join(fact.missing_skills) or '—'}\n"
                f"Learning path: {'; '.join(fact.learning_path[:4]) or '—'}\n"
                f"Next steps: {'; '.join(fact.next_steps[:3]) or '—'}"
            )
            lines += fact.salary_lines + fact.reality_lines
        if self.plan_lines:
            lines.append("\n90-day plan:\n" + "\n".join(self.plan_lines[:8]))
        for entry in self.retrieved:
            lines.append(
                f"\nTaxonomy entry — {entry['title']}: {entry['description'][:240]} "
                f"Core skills: {', '.join(entry['skills'][:8])}"
            )
        return "\n".join(lines)


def _inr_range(values) -> str | None:
    if not values or len(values) != 2:
        return None
    return f"₹{int(values[0]):,}–₹{int(values[1]):,} per year"


def _fact_for(rec: CareerRecommendation, taxonomy: Taxonomy) -> CareerFact:
    fact = CareerFact(
        title=rec.title,
        career_id=rec.career_id,
        match_percent=round(rec.match_score * 100, 1) if rec.match_score else 0.0,
        match_reason=rec.match_reason,
        matching_skills=list(rec.matching_skills),
        missing_skills=list(rec.missing_skills),
        learning_path=list(rec.learning_path),
        next_steps=list(rec.next_steps),
    )
    occ = taxonomy.get(rec.career_id) if rec.career_id else None
    if occ is not None:
        from career_guidance.reality import compute_reality

        reality = compute_reality(occ)
        if reality.get("score") is not None:
            fact.reality_lines.append(
                f"India Reality Score for {rec.title}: {reality['score']}/100 "
                f"(confidence {round(reality['confidence'] * 100)}%)."
            )
        market = (reality.get("india") or {}).get("market") or {}
        ladder = []
        for label, key in (
            ("Fresher", "fresher_salary_inr"),
            ("After ~3 years", "salary_3yr_inr"),
            ("After ~7 years", "salary_7yr_inr"),
        ):
            rendered = _inr_range(market.get(key))
            if rendered:
                ladder.append(f"{label}: {rendered}")
        if ladder:
            fact.salary_lines.append(
                f"India salary ladder for {rec.title} (estimates, not official): "
                + "; ".join(ladder)
                + "."
            )
        if market.get("top_cities"):
            fact.reality_lines.append(
                f"Top hiring cities for {rec.title}: {', '.join(market['top_cities'])}. "
                f"Sectors: {', '.join(market.get('top_sectors', []))}."
            )
    if rec.market and rec.market.salary_p50:
        fact.salary_lines.append(
            f"Typical (median) pay recorded for {rec.title}: "
            f"{rec.market.currency} {rec.market.salary_p50:,} "
            f"(source: {rec.market.source or 'market seed'})."
        )
    return fact


def retrieve_taxonomy(message: str, taxonomy: Taxonomy, limit: int = 3) -> list[dict]:
    """Taxonomy entries for careers/skills NAMED in the message."""
    low = f" {message.lower()} "
    extracted = set(extract_skills(message))
    scored: list[tuple[int, str, dict]] = []
    for occ in taxonomy.occupations:
        score = 0
        if occ.title.lower() in low or any(
            len(alt) >= 6 and alt.lower() in low for alt in occ.alt_titles
        ):
            score += 3
        overlap = extracted & {normalize_skill(t) for t in occ.all_skill_terms}
        score += len(overlap)
        if score >= 3:
            scored.append(
                (
                    score,
                    occ.title,
                    {
                        "title": occ.title,
                        "career_id": occ.id,
                        "description": occ.description,
                        "skills": list(occ.skills[:6]) + list(occ.knowledge[:2]),
                    },
                )
            )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


def build_context(
    profile: dict,
    recommendations: list[CareerRecommendation],
    taxonomy: Taxonomy | None = None,
    plan: dict | None = None,
    message: str = "",
) -> ChatContext:
    """Assemble the chat context from a stored run (+ its linked plan)."""
    from career_guidance.suggestions import _priority_skills

    taxonomy = taxonomy or load_taxonomy()
    facts = [_fact_for(rec, taxonomy) for rec in recommendations]
    retrieved = retrieve_taxonomy(message, taxonomy) if message else []
    rec_ids = {fact.career_id for fact in facts}
    retrieved = [entry for entry in retrieved if entry["career_id"] not in rec_ids]

    plan_lines: list[str] = []
    if plan:
        if plan.get("priority_skills"):
            plan_lines.append(f"Plan priority skills: {', '.join(plan['priority_skills'])}.")
        for week in (plan.get("weeks") or [])[:3]:
            tasks = "; ".join(task["title"] for task in week.get("tasks", [])[:2])
            plan_lines.append(f"Week {week.get('week')}: {week.get('theme', '')} — {tasks}")
    if not plan_lines and facts:
        top = facts[0]
        plan_lines = [f"Learning path for {top.title}: {'; '.join(top.learning_path[:4])}"]

    allowed: set[str] = set()
    for fact in facts:
        allowed.add(fact.title)
        allowed.update(fact.matching_skills)
        allowed.update(fact.missing_skills)
    priority = _priority_skills(recommendations)
    allowed.update(priority)
    for entry in retrieved:
        allowed.add(entry["title"])
        allowed.update(entry["skills"])
    from career_guidance.taxonomy import SKILL_SYNONYMS

    candidates = list(
        dict.fromkeys(
            [occ.title for occ in taxonomy.occupations]
            + taxonomy.canonical_terms()
            + list(SKILL_SYNONYMS)  # user-facing skills (welding, tally…) the
            # taxonomy term index does not carry as occupation terms
            + [fact.title for fact in facts]
        )
    )
    return ChatContext(
        facts=facts,
        priority_skills=priority,
        plan_lines=plan_lines,
        retrieved=retrieved,
        allowed_terms=allowed,
        candidate_terms=candidates,
    )


def _context_terms(context: ChatContext) -> set[str]:
    terms = {t.lower() for t in context.allowed_terms}
    for entry in context.retrieved:
        terms.add(entry["title"].lower())
    return terms


def scope_check(message: str, context: ChatContext) -> tuple[bool, str]:
    """Deterministic scope decision: (in_scope, reason). No LLM involved."""
    low = f" {re.sub(r'[^a-z0-9 ]+', ' ', message.lower())} "
    flat = low.strip()
    for pattern in _HARD_PATTERNS:
        if pattern in flat:
            return False, f"hard:{pattern}"
    terms = _context_terms(context)
    named = any(
        len(term) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low)
        for term in terms
    )
    extracted = set(extract_skills(message))
    if extracted & {normalize_skill(t) for t in terms}:
        named = True
    if named:
        return True, "context_overlap"
    if any(word in flat for word in _INTENT_WORDS):
        return True, "career_intent"
    return False, "no_overlap_or_intent"


def _named_fact(message: str, context: ChatContext) -> CareerFact | None:
    low = message.lower()
    for fact in context.facts:
        if fact.title.lower() in low:
            return fact
    return None


def _named_retrieved(message: str, context: ChatContext) -> dict | None:
    low = message.lower()
    for entry in context.retrieved:
        if entry["title"].lower() in low:
            return entry
    return None


def _has(low: str, *words: str) -> bool:
    """Word-boundary keyword check (so 'learn' never matches 'earn')."""
    return any(
        re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low) if " " not in w else w in low
        for w in words
    )


def offline_answer(message: str, context: ChatContext) -> str | None:
    """Deterministic fact extraction; None when no specific intent matches."""
    low = message.lower()
    fact = _named_fact(message, context) or (context.facts[0] if context.facts else None)
    if fact is None:
        return None
    if _has(low, "salary", "pay", "earn", "income"):
        if fact.salary_lines:
            return " ".join(fact.salary_lines)
        return f"Your report does not include salary data for {fact.title}."
    if _has(low, "demand", "hiring", "trend", "cities", "sector", "market"):
        if fact.reality_lines:
            return " ".join(fact.reality_lines)
        return f"Your report does not include demand or city data for {fact.title}."
    if "why not" in low or "not recommended" in low or "not in" in low:
        entry = _named_retrieved(message, context)
        if entry:
            return (
                f"{entry['title']} is not among this report's recommendations. "
                f"Its core skills in the taxonomy are: {', '.join(entry['skills'][:6])}. "
                f"Your report's top pick is {context.facts[0].title} "
                f"({context.facts[0].match_percent:.0f}% match)."
            )
        return (
            f"That career is not among this report's recommendations "
            f"({', '.join(f.title for f in context.facts)}), and the report "
            "stores no why-not analysis for it."
        )
    if _has(low, "compare", "versus", "better", " vs ") and len(context.facts) > 1:
        a, b = context.facts[0], context.facts[1]
        return (
            f"{a.title}: {a.match_percent:.0f}% match, "
            f"{len(a.matching_skills)} matching skills, {len(a.missing_skills)} gaps. "
            f"{b.title}: {b.match_percent:.0f}% match, "
            f"{len(b.matching_skills)} matching skills, {len(b.missing_skills)} gaps. "
            f"Learn first across both: {', '.join(context.priority_skills)}."
        )
    if _has(low, "missing", "gap", "lack", "don't have", "do not have"):
        return (
            f"For {fact.title}, the skills your report says are missing: "
            f"{', '.join(fact.missing_skills) or 'none — you cover the listed skills'}."
        )
    if _has(low, "learn first", "priority", "start with", "should i learn", "first"):
        if context.priority_skills:
            return (
                f"Learn these first, in your report's priority order: "
                f"{', '.join(context.priority_skills)}. They are the gaps shared "
                f"by your top recommendations."
            )
        return "Your report lists no priority skills."
    if _has(low, "plan", "week", "roadmap", "next step", "do now", "schedule"):
        if context.plan_lines:
            return " ".join(context.plan_lines)
        return "Your report has no plan stored."
    if _has(low, "why", "fit", "recommend"):
        return (
            f"{fact.title} ({fact.match_percent:.0f}% match): {fact.match_reason} "
            f"Skills you already have for it: {', '.join(fact.matching_skills) or '—'}."
        )
    entry = _named_retrieved(message, context)
    if entry:
        return (
            f"{entry['title']}: {entry['description'][:240]} "
            f"Core skills: {', '.join(entry['skills'][:6])}."
        )
    return None


@dataclass
class ChatReply:
    answer: str
    mode: str  # "llm" | "offline" | "refusal"
    refused: bool = False
    refusal_key: str | None = None
    violations: list[str] = field(default_factory=list)


def answer_chat(message: str, context: ChatContext, completer=None) -> ChatReply:
    """Answer one scoped question: refusal / LLM-grounded / offline."""
    message = (message or "").strip()
    in_scope, _reason = scope_check(message, context)
    if not in_scope:
        return ChatReply(REFUSAL_TEXT, "refusal", refused=True, refusal_key=REFUSAL_KEY)
    offline = offline_answer(message, context)
    if completer is None:
        if offline is not None:
            return ChatReply(offline, "offline")
        return ChatReply(OFFLINE_PREFIX + context.summary(), "offline")
    try:
        text = completer.complete(
            _CHAT_SYSTEM, f"{context.prompt_text()}\n\nQUESTION: {message}"
        ).strip()
    except ProviderError:
        text = ""
    if text:
        violations = text_violations(text, context.allowed_terms, context.candidate_terms)
        if not violations:
            return ChatReply(text, "llm")
        fallback = offline if offline is not None else OFFLINE_PREFIX + context.summary()
        return ChatReply(fallback, "offline", violations=violations)
    fallback = offline if offline is not None else OFFLINE_PREFIX + context.summary()
    return ChatReply(fallback, "offline")
