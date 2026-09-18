"""“I want to become X — do I qualify, and if not what do I do?”

This is the product's flagship question, answered honestly and with sources:

1. **Eligibility** — the target's job-zone requirement is compared with the
   zone implied by your education + experience; regulated professions are
   checked against a curated Indian admission gate (MBBS needs PCB + NEET, the
   Bar needs an LLB, and so on).
2. **Verdict** — ``eligible`` / ``reachable`` / ``blocked``, with the exact
   blockers and the strengths you already have. Nothing is softened: a B.Tech
   cannot become an MBBS, and the payload says so in one sentence.
3. **Bridges** — named Indian programmes you *can* enter from your current
   qualification (3-year LLB after any degree, CA Intermediate direct entry,
   MHA/MPH, patent agent, B.Ed …), each with duration, indicative fee,
   eligibility and entrance exam.
4. **Step plan** — a phased, week-by-week plan built from the same readiness
   maths as /plan, wired to the curated learning resources.
5. **Alternatives** — the closest careers you already cover, from the ladder.

Pure Python and deterministic: the same résumé and target always produce the
same plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.keywords import family_core_terms, target_terms
from career_guidance.ladder import build as build_ladder
from career_guidance.ladder import owned_terms, skill_set
from career_guidance.taxonomy import Occupation, Taxonomy, load_taxonomy, normalize_skill

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "bridge_paths.yaml"

#: Zone implied by each education level when experience is unknown.
EDUCATION_ZONES = {
    "10th pass": 1,
    "12th pass": 2,
    "ITI / diploma": 3,
    "Diploma": 3,
    "Bachelor's degree": 4,
    "Master's degree": 5,
    "Doctorate": 5,
    "Other": 3,
}

#: A gap worth this many hours of study (curated; shown to the user as a source).
HOURS_PER_GAP_SKILL = 14.0
WEEKS_PER_PHASE = 4


@dataclass(frozen=True)
class Profession:
    id: str
    label: str
    title_tokens: tuple[str, ...]
    code_prefixes: tuple[str, ...]
    requires: tuple[str, ...]
    cannot: str
    open_to_any_degree: bool
    bridges: tuple[dict, ...]

    def matches(self, occupation: Occupation) -> bool:
        title = occupation.title.lower()
        if any(token in title for token in self.title_tokens):
            return True
        return any(occupation.id.startswith(prefix) for prefix in self.code_prefixes)


@dataclass(frozen=True)
class BridgeBook:
    label: str
    updated: str
    professions: tuple[Profession, ...]
    open_doors: tuple[dict, ...]

    def for_occupation(self, occupation: Occupation) -> Profession | None:
        for profession in self.professions:
            if profession.matches(occupation):
                return profession
        return None


@lru_cache(maxsize=1)
def load_bridges(path: str | None = None) -> BridgeBook:
    data = yaml.safe_load(Path(path or DATA_PATH).read_text(encoding="utf-8")) or {}
    professions = tuple(
        Profession(
            id=str(item.get("id", "")),
            label=str(item.get("label", "")),
            title_tokens=tuple(str(t).lower() for t in item.get("title_tokens", [])),
            code_prefixes=tuple(str(c) for c in item.get("code_prefixes", [])),
            requires=tuple(str(r) for r in item.get("requires", [])),
            cannot=str(item.get("cannot", "")).strip(),
            open_to_any_degree=bool(item.get("open_to_any_degree", False)),
            bridges=tuple(item.get("bridges", [])),
        )
        for item in data.get("professions", [])
    )
    return BridgeBook(
        label=str(data.get("label", "Source: curated India pathways")),
        updated=str(data.get("updated", "")),
        professions=professions,
        open_doors=tuple(data.get("open_doors", [])),
    )


def clear_cache() -> bool:
    load_bridges.cache_clear()
    return True


def user_zone(education: str = "", years: float = 0.0) -> int:
    """Job zone the user's education + experience currently stands at."""
    base = EDUCATION_ZONES.get((education or "").strip(), 0)
    if not base:
        base = 3
    if years >= 6:
        return min(5, base + 1)
    if years >= 2 and base < 4:
        return base + 1
    return base


def _experience_years(experience_level: str) -> float:
    text = (experience_level or "").lower()
    if "senior" in text or "5+" in text:
        return 7.0
    if "mid" in text or "2-5" in text or "2–5" in text:
        return 3.5
    if "junior" in text or "0-2" in text or "0–2" in text:
        return 1.5
    return 0.0


def _check(requirement: str, status: str, detail: str, source: str) -> dict:
    return {"requirement": requirement, "status": status, "detail": detail, "source": source}


def evaluate(
    career: Occupation,
    *,
    taxonomy: Taxonomy | None = None,
    ratings: dict[str, int] | None = None,
    resume_text: str = "",
    education: str = "",
    experience_level: str = "",
    current_role: str = "",
    extra_skills: list[str] | tuple[str, ...] = (),
) -> dict:
    """Honest eligibility verdict for one target career."""
    taxonomy = taxonomy or load_taxonomy()
    book = load_bridges()
    years = _experience_years(experience_level)
    zone = user_zone(education, years)
    owned = owned_terms(ratings, resume_text, extra_skills)
    if current_role:
        occ = taxonomy.get(current_role)
        if occ:
            for skill in skill_set(occ, limit_tools=6):
                owned.update(owned_terms(extra_skills=[skill]))

    wanted = skill_set(career)
    shared = [s for s in wanted if (normalize_skill(s) or s.lower()) in owned]
    missing = [s for s in wanted if s not in shared]
    coverage = len(shared) / len(wanted) if wanted else 0.0

    requirements: list[dict] = []
    blockers: list[dict] = []
    strengths: list[str] = []

    def block(kind: str, severity: str, text: str) -> None:
        blockers.append({"kind": kind, "severity": severity, "text": text})

    # 1. job zone ------------------------------------------------------------
    zone_gap = career.job_zone - zone
    if zone_gap <= 0:
        requirements.append(
            _check(
                f"Job-zone {career.job_zone} preparation",
                "met",
                f"Your education and experience sit at zone {zone}, which meets this role.",
                "Source: O*NET job-zone definitions",
            )
        )
        strengths.append(f"Education level already meets zone {career.job_zone}.")
    elif zone_gap == 1:
        requirements.append(
            _check(
                f"Job-zone {career.job_zone} preparation",
                "partial",
                f"You are at zone {zone}; this role is one level higher — usually a "
                "specialisation, certification or promotion away.",
                "Source: O*NET job-zone definitions",
            )
        )
    else:
        requirements.append(
            _check(
                f"Job-zone {career.job_zone} preparation",
                "missing",
                f"You are at zone {zone}; this role is {zone_gap} levels above the "
                "preparation your degree implies.",
                "Source: O*NET job-zone definitions",
            )
        )
        block(
            "preparation",
            "hard",
            f"Preparation gap: this role expects job zone {career.job_zone}, your "
            f"education/experience is at zone {zone}.",
        )

    # 2. regulated profession ------------------------------------------------
    profession = book.for_occupation(career)
    if profession and not profession.open_to_any_degree:
        requirements.append(
            _check(
                f"Non-negotiable admission gate: {profession.label}",
                "missing",
                " ".join(profession.requires),
                book.label,
            )
        )
        block("gate", "hard", profession.cannot)
    elif profession:
        requirements.append(
            _check(
                f"{profession.label} entrance exam",
                "partial",
                "Any degree is accepted; the entry gate is: " + "; ".join(profession.requires),
                book.label,
            )
        )

    # 3. skills --------------------------------------------------------------
    if coverage >= 0.7:
        requirements.append(
            _check(
                "Role skill set",
                "met",
                f"You already cover {round(coverage * 100)}% of the role's core skills.",
                "Source: readiness maths over the bundled skill sets",
            )
        )
        strengths.append(f"{round(coverage * 100)}% of the core skills are already in place.")
    elif coverage >= 0.35:
        requirements.append(
            _check(
                "Role skill set",
                "partial",
                f"You cover {round(coverage * 100)}% — {len(missing)} skills to close.",
                "Source: readiness maths over the bundled skill sets",
            )
        )
    else:
        requirements.append(
            _check(
                "Role skill set",
                "missing",
                f"You cover {round(coverage * 100)}% of the role's core skills.",
                "Source: readiness maths over the bundled skill sets",
            )
        )
        block(
            "skills",
            "soft",
            f"Skill gap: {len(missing)} of {len(wanted)} core skills are not evidenced yet "
            f"— close them with the step plan below.",
        )

    # 4. experience ----------------------------------------------------------
    requirements.append(
        _check(
            "Relevant experience",
            "met" if years >= 2 else "partial",
            (
                f"About {years:g} year(s) of experience read from your profile."
                if years
                else "No experience recorded yet — internships and portfolio projects count."
            ),
            "Source: your profile + O*NET job-zone experience bands",
        )
    )

    hard = [b for b in blockers if b["severity"] == "hard"]
    if hard:
        verdict = "blocked"
        headline = (
            f"Not directly reachable yet: {len(hard)} hard blocker(s) on the way to "
            f"{career.title} — the bridges below are the realistic routes."
        )
    elif coverage >= 0.7 and zone_gap <= 0:
        verdict = "eligible"
        headline = f"You are already a credible candidate for {career.title}."
    else:
        verdict = "reachable"
        headline = (
            f"{career.title} is reachable from where you are — "
            f"{len(missing)} skills and {max(0, zone_gap)} preparation level(s) to close."
        )

    return {
        "target": {"id": career.id, "title": career.title, "job_zone": career.job_zone},
        "verdict": verdict,
        "headline": headline,
        "eligible_now": verdict == "eligible",
        "coverage": round(coverage * 100, 1),
        "user_zone": zone,
        "requirements": requirements,
        "blockers": blockers,
        "hard_blockers": [b["text"] for b in hard],
        "strengths": strengths,
        "shared_skills": shared[:12],
        "gap_skills": missing[:12],
        "gap_count": len(missing),
        "profession": (
            {
                "id": profession.id,
                "label": profession.label,
                "requires": list(profession.requires),
                "cannot": profession.cannot,
                "open_to_any_degree": profession.open_to_any_degree,
            }
            if profession
            else None
        ),
        "source": "Source: job-zone maths + curated India admission gates",
    }


def _phases(
    career: Occupation,
    gaps: list[str],
    *,
    hours_per_week: int,
    resource_lookup=None,
    start: date | None = None,
) -> dict:
    """Turn the gap list into phases of ~4 weeks, most important first."""
    start = start or date.today()
    weights = target_terms(career, max_terms=24)
    ordered = sorted(
        gaps,
        key=lambda skill: (-weights.get(skill, 4.0), skill),
    )
    per_phase = max(1, int(WEEKS_PER_PHASE * hours_per_week / HOURS_PER_GAP_SKILL))
    phases: list[dict] = []
    week_cursor = 1
    for index in range(0, len(ordered), per_phase):
        chunk = ordered[index : index + per_phase]
        if not chunk:
            continue
        hours = HOURS_PER_GAP_SKILL * len(chunk)
        weeks = max(1, int(round(hours / max(1, hours_per_week))))
        resources: list[dict] = []
        for skill in chunk[:3]:
            if resource_lookup is None:
                continue
            for item in resource_lookup(skill) or []:
                if isinstance(item, dict):
                    entry = dict(item)
                else:  # dataclass (LearningResource) — keep the fields the UI shows
                    entry = {
                        key: getattr(item, key)
                        for key in ("title", "url", "provider", "free")
                        if hasattr(item, key)
                    }
                resources.append({"skill": skill, **entry})
        phases.append(
            {
                "phase": len(phases) + 1,
                "label": f"Weeks {week_cursor}–{week_cursor + weeks - 1}",
                "start_week": week_cursor,
                "weeks": weeks,
                "focus_skills": chunk,
                "hours": int(round(hours)),
                "action": (
                    f"Close {', '.join(chunk[:3])}"
                    + (" and similar gaps" if len(chunk) > 3 else "")
                    + f" — {int(HOURS_PER_GAP_SKILL)} h per skill, then re-rate yourself."
                ),
                "checkpoint": (
                    "Add every closed skill to the résumé with the number it moved "
                    "(%, ₹, hours saved) and re-run the résumé score."
                ),
                "resources": resources[:4],
            }
        )
        week_cursor += weeks
    total_hours = int(round(HOURS_PER_GAP_SKILL * len(ordered)))
    # Weeks come from the phase schedule itself so the header and the phase list
    # can never disagree.
    weeks = max(1, week_cursor - 1) if ordered else 0
    return {
        "phases": phases,
        "total_hours": total_hours,
        "weeks": weeks,
        "eta": (start + timedelta(weeks=weeks)).isoformat() if ordered else start.isoformat(),
        "hours_per_week": hours_per_week,
        "source": (
            "Source: curated study estimate "
            f"({int(HOURS_PER_GAP_SKILL)} h per missing skill) at {hours_per_week} h/week"
        ),
    }


def build_pathway(
    career: Occupation,
    *,
    taxonomy: Taxonomy | None = None,
    ratings: dict[str, int] | None = None,
    resume_text: str = "",
    education: str = "",
    experience_level: str = "",
    current_role: str = "",
    hours_per_week: int = 6,
    market=None,
    resource_lookup=None,
) -> dict:
    """Full “how do I actually become X?” report for one target career."""
    taxonomy = taxonomy or load_taxonomy()
    book = load_bridges()
    verdict = evaluate(
        career,
        taxonomy=taxonomy,
        ratings=ratings,
        resume_text=resume_text,
        education=education,
        experience_level=experience_level,
        current_role=current_role,
    )
    gaps = list(verdict["gap_skills"])
    plan = _phases(
        career,
        gaps,
        hours_per_week=max(1, int(hours_per_week)),
        resource_lookup=resource_lookup,
    )

    # Closest careers you already cover — the realistic alternatives.
    origin = taxonomy.get(current_role) or career
    ladder = build_ladder(
        origin,
        taxonomy,
        ratings=ratings,
        resume_text=resume_text,
        hours_per_week=max(1, int(hours_per_week)),
        market=market,
        limit=4,
    )
    alternatives = [
        rung
        for bucket in ("step_across", "step_up", "entry_points")
        for rung in ladder[bucket]
        if rung["id"] != career.id and rung["job_zone"] >= career.job_zone - 1
    ][:4]

    matched = book.for_occupation(career)
    verdict_profession = verdict.get("profession")
    bridges: list[dict] = []
    if matched is not None:
        bridges = [dict(bridge, source=book.label) for bridge in matched.bridges]
    elif verdict_profession is None and verdict["verdict"] != "eligible":
        # Not a curated profession: bridge means “adjacent role you can enter now”.
        bridges = [
            {
                "title": rung["title"],
                "duration": f"{rung['weeks_at_your_pace']} weeks at {hours_per_week} h/week",
                "cost_inr": "Free–₹50,000 with the linked courses",
                "eligibility": f"You already cover {rung['coverage']}% of this role's skills",
                "entrance": "Direct hiring after the skill plan",
                "why": "Adjacent role that shortens the distance to your target.",
                "career_id": rung["id"],
                "source": ladder["source"],
            }
            for rung in ladder["step_across"][:3]
        ]

    market_payload = None
    if market is not None:
        snapshot = market.snapshot(career, "in")
        market_payload = {
            "salary_p25": snapshot.salary_p25,
            "salary_p50": snapshot.salary_p50,
            "salary_p75": snapshot.salary_p75,
            "currency": snapshot.currency,
            "symbol": "₹" if snapshot.currency == "INR" else "$",
            "demand_label": market.seed.demand_label(career),
            "trend": market.seed.trend(career),
            "remote": market.seed.remote_friendly(career),
            "band": market.seed.band(career, "in"),
            "source": snapshot.source,
        }

    return {
        "verdict": verdict,
        "target": {
            **verdict["target"],
            "family": (
                market.seed.family_for(career).id
                if market and market.seed.family_for(career)
                else "other"
            ),
            "core_skills": family_core_terms(career)[:10],
            "education_path": [
                {"level": f"Job zone {career.job_zone}", "typical": "See the ladder below"}
            ],
        },
        "market": market_payload,
        "plan": plan,
        "bridges": bridges,
        "alternatives": alternatives,
        "open_doors": list(book.open_doors) if verdict["verdict"] == "blocked" else [],
        "ladder": {
            "entry_points": ladder["entry_points"],
            "step_across": ladder["step_across"],
            "step_up": ladder["step_up"],
        },
        "next_step": (
            f"Step 1: {plan['phases'][0]['action']}"
            if plan["phases"]
            else "You already cover the role's core skills — apply and interview."
        ),
        "sources": {
            "pathways": book.label,
            "skills": ladder["source"],
            "plan": plan["source"],
            "market": market_payload["source"] if market_payload else "",
        },
    }


def profession_export(profession: Profession) -> list[dict]:
    """Bridges of a curated profession, ready for JSON."""
    return [dict(bridge) for bridge in profession.bridges]


# --------------------------------------------------------------------------- #
# Résumé signals: let the user paste a CV instead of filling a form
# --------------------------------------------------------------------------- #
_DEGREES: tuple[tuple[str, str], ...] = (
    ("phd", "Doctorate"),
    ("doctorate", "Doctorate"),
    ("m.tech", "Master's degree"),
    ("mtech", "Master's degree"),
    ("m.sc", "Master's degree"),
    ("msc", "Master's degree"),
    ("mba", "Master's degree"),
    ("m.com", "Master's degree"),
    ("mca", "Master's degree"),
    ("m.a", "Master's degree"),
    ("master", "Master's degree"),
    ("b.tech", "Bachelor's degree"),
    ("btech", "Bachelor's degree"),
    ("b.e", "Bachelor's degree"),
    ("b.sc", "Bachelor's degree"),
    ("bsc", "Bachelor's degree"),
    ("b.com", "Bachelor's degree"),
    ("bca", "Bachelor's degree"),
    ("b.a", "Bachelor's degree"),
    ("bachelor", "Bachelor's degree"),
    ("llb", "Bachelor's degree"),
    ("diploma", "Diploma"),
    ("iti", "ITI / diploma"),
    ("12th", "12th pass"),
    ("hsc", "12th pass"),
    ("10th", "10th pass"),
    ("sslc", "10th pass"),
)

_EXPERIENCE_RE = None


def read_resume_signals(text: str) -> dict:
    """Best-effort education / experience / skills from a résumé's text.

    Deliberately simple and explainable: substring matches for Indian degree
    names and a handful of experience patterns, then the same synonym-backed
    skill extractor the matcher uses. Everything it returns is shown back to
    the user for confirmation, never trusted silently.
    """
    import re

    from career_guidance.taxonomy import extract_skills

    global _EXPERIENCE_RE
    if _EXPERIENCE_RE is None:
        _EXPERIENCE_RE = re.compile(
            r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b[^.\n]{0,40}?(experience|worked)",
            re.IGNORECASE,
        )
    lowered = (text or "").lower()
    degrees = [label for token, label in _DEGREES if token in lowered]
    education = ""
    for level in (
        "Doctorate",
        "Master's degree",
        "Bachelor's degree",
        "Diploma",
        "ITI / diploma",
        "12th pass",
        "10th pass",
    ):
        if level in degrees:
            education = level
            break

    years = 0.0
    for match in _EXPERIENCE_RE.finditer(text or ""):
        years = max(years, float(match.group(1)))
    if not years:
        match = re.search(r"(\d{1,2})\+?\s*(?:years?|yrs?)", lowered)
        if match:
            years = float(match.group(1))

    skills = extract_skills(text or "")
    return {
        "education": education,
        "education_candidates": degrees[:4],
        "experience_years": years,
        "experience_level": (
            "Senior (5+ years)"
            if years >= 5
            else "Mid-level (2-5 years)"
            if years >= 2
            else "Junior (0-2 years)"
        ),
        "skills": skills[:20],
        "skill_count": len(skills),
        "source": "Source: rule-based résumé parser (degrees, experience years, skill synonyms)",
    }
