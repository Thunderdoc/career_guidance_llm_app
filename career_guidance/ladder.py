"""Career ladder: what you can move *into*, *across* and *up* from a role.

The engine answers the question the product exists for — “I am here, what can I
realistically become next?” — with maths instead of opinion:

* every candidate is scored by how much of its **target skill set** you already
  hold (coverage) and how far its job zone is from yours,
* the skill sets come from the same sources the matcher uses (family core kit +
  O*NET skills + ranked tools), so the number you see is the number the
  readiness screen shows,
* each rung carries a curated study-effort estimate and a source label.

Pure Python, no API keys, deterministic: the same inputs always give the same
ladder.
"""

from __future__ import annotations

from dataclasses import dataclass

from career_guidance.keywords import GENERIC_NOISE, family_core_terms, ranked_technology
from career_guidance.taxonomy import Occupation, Taxonomy, normalize_skill

#: Curated study effort per missing skill, used for the “≈n weeks” badge.
HOURS_PER_SKILL = 14.0
#: Coverage below this is noise: you would be starting from scratch.
MIN_COVERAGE = 0.18


def skill_set(occupation: Occupation, limit_tools: int = 10) -> list[str]:
    """Everything a role asks for, deduped: curated kit + O*NET + tools."""
    seen: dict[str, str] = {}
    values = [
        *family_core_terms(occupation),
        *occupation.skills,
        *occupation.knowledge,
        *ranked_technology(occupation, limit=limit_tools),
    ]
    for value in values:
        cleaned = (value or "").strip()
        if not cleaned or cleaned.lower() in GENERIC_NOISE or len(cleaned) < 3:
            continue
        key = normalize_skill(cleaned) or cleaned.lower()
        seen.setdefault(key, cleaned)
    return list(seen.values())


def _covers(owned: set[str], wanted: list[str]) -> tuple[list[str], list[str]]:
    shared, missing = [], []
    for item in wanted:
        key = normalize_skill(item) or item.lower()
        (shared if key in owned else missing).append(item)
    return shared, missing


@dataclass
class Rung:
    """One reachable role, with the maths that put it there."""

    occupation: Occupation
    direction: str  # entry | across | up
    coverage: float  # share of the *destination's* skills you already hold
    shared: list[str]
    missing: list[str]
    hours: float

    def to_dict(self, market=None, hours_per_week: int = 6) -> dict:
        weeks = max(1, int(round(self.hours / max(1, hours_per_week))))
        payload = {
            "id": self.occupation.id,
            "title": self.occupation.title,
            "direction": self.direction,
            "job_zone": self.occupation.job_zone,
            "coverage": round(self.coverage * 100, 1),
            "shared_skills": self.shared[:8],
            "gap_skills": self.missing[:8],
            "gap_count": len(self.missing),
            "study_hours": int(round(self.hours)),
            "weeks_at_your_pace": weeks,
            "holland_code": self.occupation.holland_code,
            "source": (
                "Source: shared skills × curated study estimate "
                f"({int(HOURS_PER_SKILL)} h per missing skill)"
            ),
        }
        if market is not None:
            snapshot = market.snapshot(self.occupation, "in")
            payload.update(
                {
                    "salary_p50": snapshot.salary_p50,
                    "currency": snapshot.currency,
                    "market_source": snapshot.source,
                    "demand_label": market.seed.demand_label(self.occupation),
                    "remote": market.seed.remote_friendly(self.occupation),
                    "family": (
                        market.seed.family_for(self.occupation).id
                        if market.seed.family_for(self.occupation)
                        else "other"
                    ),
                }
            )
        return payload


def owned_terms(
    ratings: dict[str, int] | None = None,
    resume_text: str = "",
    extra_skills: list[str] | tuple[str, ...] = (),
) -> set[str]:
    """Skill keys the user is considered to have.

    Self-ratings of 3+ (the app's “competent” bar), every skill extracted from
    the résumé, plus anything passed explicitly.  Everything is normalised
    through the synonym table so “excel” and “spreadsheet software” agree.
    """
    from career_guidance.taxonomy import extract_skills

    owned: set[str] = set()
    for raw in extra_skills or ():
        for key in _keys(raw):
            owned.add(key)
    for name, value in (ratings or {}).items():
        try:
            score = int(value)
        except (TypeError, ValueError):
            continue
        if score >= 3:
            for key in _keys(name):
                owned.add(key)
    for name in extract_skills(resume_text or ""):
        for key in _keys(name):
            owned.add(key)
    return owned


def _keys(term: str) -> list[str]:
    """Normalised keys for a term plus its canonical/alias expansions."""
    raw = (term or "").strip().lower()
    keys = [raw]
    canonical = normalize_skill(term) or raw
    keys.append(canonical)
    try:
        from career_guidance.synonyms import load_normalizer

        normalizer = load_normalizer()
        mapped = normalizer.normalize(term)
        if mapped:
            keys.append(mapped.lower())
            keys.extend(alias.lower() for alias in normalizer.expansions_for(mapped))
    except Exception:  # noqa: BLE001 - the ladder works without the synonym file
        pass
    return [k for k in dict.fromkeys(keys) if k]


def build(
    origin: Occupation,
    taxonomy: Taxonomy,
    *,
    ratings: dict[str, int] | None = None,
    resume_text: str = "",
    extra_skills: list[str] | tuple[str, ...] = (),
    hours_per_week: int = 6,
    market=None,
    limit: int = 6,
    exclude_ids: set[str] | None = None,
) -> dict:
    """The ladder for ``origin``: entry points, lateral moves, steps up."""
    owned = owned_terms(ratings, resume_text, extra_skills)
    # What the origin role itself expects counts as held experience.
    for skill in skill_set(origin, limit_tools=6):
        owned.update(_keys(skill))
    owned = {key for key in owned if key}

    excluded = set(exclude_ids or ()) | {origin.id}
    origin_family = None
    if market is not None:
        family = market.seed.family_for(origin)
        origin_family = family.id if family else None

    buckets: dict[str, list[Rung]] = {"entry": [], "across": [], "up": []}
    for occupation in taxonomy.occupations:
        if occupation.id in excluded:
            continue
        wanted = skill_set(occupation)
        if len(wanted) < 4:
            continue
        shared, missing = _covers(owned, wanted)
        coverage = len(shared) / len(wanted)
        if coverage < MIN_COVERAGE:
            continue
        zone_delta = occupation.job_zone - origin.job_zone
        if zone_delta < -1 or zone_delta > 2:
            # A zone-4 analyst dropping to a zone-1 counter job is not a rung;
            # neither is jumping three preparation levels in one move.
            continue
        direction = "up" if zone_delta > 0 else ("entry" if zone_delta < 0 else "across")
        if direction == "entry":
            # Stepping *down* only reads as advice inside the same market
            # family — otherwise O*NET's generic competency lists hand back
            # unrelated junior jobs.
            family = market.seed.family_for(occupation) if market is not None else None
            same_family = (
                origin_family is not None and family is not None and family.id == origin_family
            )
            if origin_family is not None and not same_family:
                continue
            if origin_family is None and coverage < 0.5:
                continue
        rung = Rung(
            occupation=occupation,
            direction=direction,
            coverage=coverage,
            shared=shared,
            missing=missing,
            hours=HOURS_PER_SKILL * len(missing),
        )
        buckets[direction].append(rung)

    def rank(rungs: list[Rung], *, prefer_family: bool = False) -> list[Rung]:
        def key(rung: Rung) -> tuple:
            fam = None
            if market is not None:
                family = market.seed.family_for(rung.occupation)
                fam = family.id if family else None
            same = 0 if (prefer_family and fam and fam == origin_family) else 1
            return (same, -rung.coverage, rung.occupation.title)

        return sorted(rungs, key=key)

    def payload(rungs: list[Rung], name: str) -> list[dict]:
        return [r.to_dict(market=market, hours_per_week=hours_per_week) for r in rungs[:limit]]

    entry = payload(rank(buckets["entry"]), "entry")
    across = payload(rank(buckets["across"], prefer_family=True), "across")
    up = payload(rank(buckets["up"], prefer_family=True), "up")
    skills = skill_set(origin)
    return {
        "current": {
            "id": origin.id,
            "title": origin.title,
            "job_zone": origin.job_zone,
            "family": origin_family or "other",
            "skills_considered": shared_count(owned, skills),
            "skill_count": len(skills),
        },
        "entry_points": entry,
        "step_across": across,
        "step_up": up,
        "owned_skills": sorted(
            {skill for skill in skills if (normalize_skill(skill) or skill.lower()) in owned}
        )[:20],
        "hours_per_week": hours_per_week,
        "source": (
            "Source: ladder maths over the bundled 974-career catalogue "
            "(skill overlap × job zone) + curated study estimates"
        ),
    }


def shared_count(owned: set[str], wanted: list[str]) -> int:
    shared, _ = _covers(owned, wanted)
    return len(shared)
