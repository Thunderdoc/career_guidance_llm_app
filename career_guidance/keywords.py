"""Keyword ranking for one occupation — shared by résumé scoring and the API.

The bundled O*NET catalog stores each occupation's technology list in
alphabetical order, so the naive ``technology[:15]`` slice shows ABAP/AJAX/
Adobe Acrobat for almost every IT role. :func:`ranked_technology` instead:

1. keeps terms we can explain (present in ``data/skill_synonyms.yaml``),
2. sorts by how many occupations use a term (most widely used first),
3. drops long vendor product strings and one-letter noise,
4. falls back to the full list when nothing is curated.
"""

from __future__ import annotations

from functools import lru_cache

from career_guidance.taxonomy import Occupation


@lru_cache(maxsize=1)
def document_frequency() -> dict[str, int]:
    """How many occupations list each technology term (cached)."""
    from career_guidance.taxonomy import load_taxonomy

    counts: dict[str, int] = {}
    for occupation in load_taxonomy().occupations:
        for term in set(occupation.technology) | set(occupation.hot_technology):
            counts[term] = counts.get(term, 0) + 1
    return counts


@lru_cache(maxsize=1)
def _curated_terms() -> frozenset[str]:
    """Canonicals + aliases from the synonym catalogue (mainstream, explainable)."""
    try:
        from career_guidance.synonyms import load_normalizer

        normalizer = load_normalizer()
    except Exception:  # noqa: BLE001 - keyword ranking must work without the YAML
        return frozenset()
    terms = {alias.lower() for alias in normalizer.known_aliases()}
    terms |= {canonical.lower() for canonical in normalizer.canonical_skills()}
    return frozenset(terms)


def _looks_usable(term: str) -> bool:
    cleaned = term.strip()
    if len(cleaned) < 3 or len(cleaned) > 38:
        return False
    if cleaned.lower().endswith(("software", "system", "systems")) and len(cleaned) > 30:
        return False
    return True


def ranked_technology(occupation: Occupation, limit: int = 12) -> list[str]:
    """Most useful tools for an occupation, best first."""
    candidates = [
        t.strip() for t in dict.fromkeys([*occupation.hot_technology, *occupation.technology])
    ]
    usable = [t for t in candidates if _looks_usable(t)]
    if not usable:
        return candidates[:limit]
    curated = _curated_terms()
    frequency = document_frequency()

    def key(term: str) -> tuple[int, int, str]:
        lowered = term.lower()
        is_curated = 0 if lowered in curated else 1
        return (is_curated, -frequency.get(term, 0), lowered)

    ranked = sorted(usable, key=key)
    curated_first = [t for t in ranked if t.lower() in curated][:limit]
    if len(curated_first) >= limit:
        return curated_first
    rest = [t for t in ranked if t.lower() not in curated and t not in curated_first]
    return (curated_first + rest)[:limit]


#: O*NET "basic/soft" skills that are real job requirements but useless as
#: résumé keywords — a candidate is never hired for listing "Persuasion".
SOFT_SKILLS = frozenset(
    {
        "active learning",
        "active listening",
        "complex problem solving",
        "coordination",
        "critical thinking",
        "equipment maintenance",
        "equipment selection",
        "instructing",
        "judgment and decision making",
        "learning strategies",
        "management of financial resources",
        "management of material resources",
        "management of personnel resources",
        "mathematics",
        "monitoring",
        "negotiation",
        "operations analysis",
        "operations monitoring",
        "persuasion",
        "quality control analysis",
        "reading comprehension",
        "repairing",
        "service orientation",
        "social perceptiveness",
        "speaking",
        "systems analysis",
        "systems evaluation",
        "time management",
        "troubleshooting",
        "writing",
    }
)


@lru_cache(maxsize=1)
def _seed():
    try:
        from career_guidance.market_seed import load_seed

        return load_seed()
    except Exception:  # noqa: BLE001 - keyword ranking works without the seed file
        return None


#: Catalog technology rows that sound like tools but say nothing to a recruiter.
GENERIC_NOISE = frozenset({"data entry software", "word processing software"})


def family_core_terms(occupation: Occupation) -> list[str]:
    """Curated core toolkit for the occupation's market family.

    The bundled O*NET catalog predates today's tools (its "technology" list for
    Business Intelligence Analysts has no SQL or Tableau), so the family
    overlay in ``data/market_seed.yaml`` supplies the mainstream kit.  Source:
    curated, updated 2026-09.
    """
    seed = _seed()
    if seed is None:
        return []
    family = seed.family_for(occupation)
    return list(family.core_skills) if family else []


def target_terms(occupation: Occupation, max_terms: int = 18) -> dict[str, float]:
    """Weighted keyword list: family toolkit, hard role skills, then tools."""
    from career_guidance.skillgap import catalog_importance

    terms: dict[str, float] = {}
    for rank, skill in enumerate(family_core_terms(occupation)):
        terms[skill] = round(max(6.0, 10.0 - rank * 0.35), 1)
    for name, importance in list(catalog_importance(occupation).items())[:10]:
        if name.strip().lower() in SOFT_SKILLS:
            continue
        terms.setdefault(name, round(importance * 0.75, 1))
    for rank, tool in enumerate(ranked_technology(occupation, limit=8)):
        if tool.strip().lower() in GENERIC_NOISE:
            continue
        terms.setdefault(tool, round(max(4.0, 9.0 - rank * 0.6), 1))
    ordered = sorted(terms.items(), key=lambda kv: -kv[1])[:max_terms]
    return dict(ordered)


def clear_cache() -> bool:
    document_frequency.cache_clear()
    _curated_terms.cache_clear()
    _seed.cache_clear()
    return True
