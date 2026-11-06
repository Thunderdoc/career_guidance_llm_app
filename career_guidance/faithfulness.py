"""Faithfulness checks (Phase 7) — one implementation, reused everywhere.

A *faithfulness* failure is output that names skills/careers the grounding
context never supplied. Two shapes are checked:

* **Structured recommendations** — an LLM item's ``matching_skills`` /
  ``missing_skills`` must be subsets of the lists the taxonomy retrieval
  provided for that career. :func:`skill_violations` reports the planted
  skills; :func:`filter_grounded_skills` returns the cleaned lists (the
  grounded engine's merge uses it — extracted here in Phase 7 so the eval
  and the chat path run the *same* code, not a copy).
* **Free text (chat)** — :func:`text_violations` finds candidate terms
  (taxonomy skills / occupation titles supplied by the caller) that appear
  in a text but are not in the allowed set for that conversation.
"""

from __future__ import annotations

import re


def skill_violations(
    reported_have: list[str],
    reported_gap: list[str],
    allowed_have: set[str],
    allowed_gap: set[str],
) -> dict[str, list[str]]:
    """Ungrounded skills in one structured item, by field (empty = faithful)."""
    return {
        "matching_skills": [s for s in reported_have if s not in allowed_have],
        "missing_skills": [s for s in reported_gap if s not in allowed_gap],
    }


def filter_grounded_skills(
    reported_have: list[str],
    reported_gap: list[str],
    allowed_have: set[str],
    allowed_gap: set[str],
    fallback_have: list[str],
    fallback_gap: list[str],
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Clean an item's skill lists against the grounding context.

    Returns ``(have, gap, violations)``. A field whose reported list is
    entirely ungrounded (or empty) falls back to the retrieved list —
    the exact behaviour the grounded merge has always had.
    """
    violations = skill_violations(reported_have, reported_gap, allowed_have, allowed_gap)
    have = [s for s in reported_have if s in allowed_have] or list(fallback_have)
    gap = [s for s in reported_gap if s in allowed_gap] or list(fallback_gap)
    return have, gap, violations


def _norm(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


def text_violations(text: str, allowed_terms: set[str], candidate_terms) -> list[str]:
    """Candidate terms present in ``text`` but absent from ``allowed_terms``.

    ``candidate_terms`` is the universe to police (e.g. every taxonomy
    skill + occupation title); terms shorter than 4 chars are ignored to
    avoid noise from abbreviations. Matching is word-boundary aware for
    single words and substring for phrases/titles.
    """
    lowered = f" {_norm(text)} "
    allowed = {_norm(t) for t in allowed_terms}
    found: list[str] = []
    for term in candidate_terms:
        norm = _norm(str(term))
        if len(norm) < 4 or norm in allowed:
            continue
        if " " in norm or "-" in norm or "/" in norm:
            hit = norm in lowered
        else:
            hit = re.search(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", lowered) is not None
        if hit:
            found.append(str(term))
    return sorted(set(found))
