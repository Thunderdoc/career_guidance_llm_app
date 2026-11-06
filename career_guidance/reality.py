"""India Reality Score (Phase 2) — deterministic, transparent, 0-100.

Components (each 0-100; higher = more favourable reality for an entrant):
  entry_demand      w=0.30  from market-seed demand (1-5) + trend
  ai_exposure       w=0.20  INVERSE of a documented keyword heuristic (see below)
  salary_ladder     w=0.20  7-year vs fresher salary growth (india_market estimate)
  barrier_to_entry  w=0.15  INVERSE of O*NET job zone (preparation required)
  time_to_first_job w=0.15  INVERSE of an estimate from demand + barrier

Weighted average over AVAILABLE components only. A component with no data is
excluded, listed in ``missing_components``, status="insufficient_data", and
overall confidence = sum of available weights (so it drops below 1.0).

AI-exposure heuristic (kind="heuristic_estimate", NOT a measurement): routine,
rule-based, screen-based task keywords (data entry, transcription, telemarketing,
cashier, bookkeeping, routine reporting...) raise exposure; hands-on physical,
in-person care, licensed-judgement and creative keywords lower it. Base 50,
each high keyword +9, each low keyword -9, clamped 5..95.
"""

from __future__ import annotations

from career_guidance.india import india_payload
from career_guidance.taxonomy import Occupation

WEIGHTS = {
    "entry_demand": 0.30,
    "ai_exposure": 0.20,
    "salary_ladder": 0.20,
    "barrier_to_entry": 0.15,
    "time_to_first_job": 0.15,
}
HIGH_EXPOSURE = (
    "data entry",
    "transcription",
    "telemarket",
    "cashier",
    "bookkeeping",
    "clerical",
    "billing",
    "typing",
    "filing",
    "scheduling",
    "payroll",
    "reception",
    "call center",
    "contact centre",
    "proofread",
)
LOW_EXPOSURE = (
    "patient care",
    "repair",
    "install",
    "weld",
    "plumb",
    "counsel",
    "surgery",
    "diagnos",
    "design",
    "teach",
    "instruct",
    "negotiat",
    "leadership",
    "creative",
    "field",
    "emergency",
    "therapy",
)
_ZONE_BARRIER = {1: 10.0, 2: 30.0, 3: 55.0, 4: 75.0, 5: 95.0}


def _clamp(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 1)


def ai_exposure_score(occupation: Occupation) -> tuple[float, str]:
    text = " ".join(
        [
            occupation.title,
            *occupation.skills,
            *occupation.knowledge,
            *occupation.technology,
            occupation.description,
        ]
    ).lower()
    high = [k for k in HIGH_EXPOSURE if k in text]
    low = [k for k in LOW_EXPOSURE if k in text]
    exposure = max(5.0, min(95.0, 50 + 9 * len(set(high)) - 9 * len(set(low))))
    return (
        exposure,
        f"Heuristic estimate: {len(set(high))} routine-task signals, "
        f"{len(set(low))} hands-on/judgement signals in O*NET text.",
    )


def compute_reality(occupation: Occupation, india: dict | None = None) -> dict:
    india = india if india is not None else india_payload(occupation)
    market = india.get("market") if india else None
    components: list[dict] = []
    missing: list[str] = []

    def add(key, label, value, status, explanation, kind, source):
        components.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "weight": WEIGHTS[key],
                "status": status,
                "explanation": explanation,
                "kind": kind,
                "source": source,
            }
        )

    # entry demand
    if market and market.get("demand") is not None:
        demand = int(market["demand"])
        trend = market.get("entry_demand_trend", "stable")
        v = (demand - 1) / 4 * 100 + {"rising": 10, "declining": -15}.get(trend, 0)
        add(
            "entry_demand",
            "Entry demand",
            _clamp(v),
            "ok",
            f"Demand {demand}/5 with {trend} trend in the India market seed.",
            market.get("kind", "estimate"),
            market.get("source", ""),
        )
    else:
        missing.append("entry_demand")
        add(
            "entry_demand",
            "Entry demand",
            None,
            "insufficient_data",
            "No India demand data for this career.",
            "estimate",
            "",
        )

    # AI exposure (always derivable from occupation text)
    exposure, why = ai_exposure_score(occupation)
    add(
        "ai_exposure",
        "AI exposure (lower is safer)",
        _clamp(100 - exposure),
        "ok",
        why,
        "heuristic_estimate",
        "Heuristic over O*NET occupation text — see docs/SOURCES.md",
    )

    # salary ladder
    if market and market.get("fresher_salary_inr") and market.get("salary_7yr_inr"):
        f = sum(market["fresher_salary_inr"]) / 2
        s = sum(market["salary_7yr_inr"]) / 2
        ratio = (s / f) if f else 0.0
        v = _clamp((ratio - 1) / 2.5 * 100)  # ratio 1 -> 0, 3.5+ -> 100
        add(
            "salary_ladder",
            "Salary ladder",
            v,
            "ok",
            f"Estimated pay grows ~{ratio:.1f}x from fresher to ~7 years "
            "(estimates, not official).",
            market.get("kind", "estimate"),
            market.get("source", ""),
        )
    else:
        missing.append("salary_ladder")
        add(
            "salary_ladder",
            "Salary ladder",
            None,
            "insufficient_data",
            "No India salary ladder data for this career.",
            "estimate",
            "",
        )

    # barrier
    if occupation.job_zone:
        barrier = _ZONE_BARRIER.get(int(occupation.job_zone), 55.0)
        add(
            "barrier_to_entry",
            "Barrier to entry (lower barrier scores higher)",
            _clamp(100 - barrier),
            "ok",
            f"O*NET job zone {occupation.job_zone} (preparation level).",
            "catalogue",
            "O*NET job zone",
        )
    else:
        barrier = None
        missing.append("barrier_to_entry")
        add(
            "barrier_to_entry",
            "Barrier to entry",
            None,
            "insufficient_data",
            "No job-zone data.",
            "catalogue",
            "",
        )

    # time to first job
    if market and market.get("demand") is not None and occupation.job_zone:
        months = max(1.0, min(12.0, 2 + occupation.job_zone * 1.5 - int(market["demand"]) * 0.8))
        add(
            "time_to_first_job",
            "Time to first job (estimate)",
            _clamp(100 - (months - 1) / 11 * 100),
            "ok",
            f"Estimated ~{months:.0f} months to a first job, from demand + "
            "preparation level. Labelled estimate.",
            "estimate",
            market.get("source", ""),
        )
    else:
        missing.append("time_to_first_job")
        add(
            "time_to_first_job",
            "Time to first job",
            None,
            "insufficient_data",
            "Needs both demand and job-zone data.",
            "estimate",
            "",
        )

    available = [c for c in components if c["value"] is not None]
    total_w = sum(c["weight"] for c in available)
    score = (
        round(sum(c["value"] * c["weight"] for c in available) / total_w, 1) if total_w else None
    )
    return {
        "score": score,
        "confidence": round(total_w, 2) if total_w else 0.0,
        "components": components,
        "missing_components": missing,
        "weights": WEIGHTS,
        "india": india,
        "method": (
            "Weighted average over available components only; missing "
            "components are excluded and lower confidence."
        ),
    }


def enrich_result(
    result: dict, taxonomy, profile=None, india_overrides: dict | None = None
) -> dict:
    """Add reality/why_not/alternatives to a recommend payload (additive).

    why_not candidates must already be scored: result['_scored_extra'] may
    carry extra ranked dicts (career_id, title, match_percent/match_score,
    missing_skills) produced by the same matcher run in suggestions2.
    """
    from career_guidance.transitions import delta_skills

    recs = result.get("recommendations", [])
    for rec in recs:
        occ = taxonomy.get(rec.get("career_id", ""))
        if occ is None:
            rec.setdefault("reality", None)
            continue
        india = india_payload(occ, india_overrides)
        rec["reality"] = compute_reality(occ, india)
    # alternatives for top pick: related occupations = stepping stones
    alternatives = []
    if recs:
        top = taxonomy.get(recs[0].get("career_id", ""))
        if top is not None:
            for rel_id in (top.related or [])[:4]:
                rel = taxonomy.get(rel_id)
                if rel is None:
                    continue
                delta, shared = delta_skills(top, rel)
                alternatives.append(
                    {
                        "career_id": rel.id,
                        "title": rel.title,
                        "job_zone": rel.job_zone,
                        "shared_skills": shared,
                        "delta_skills": delta,
                        "source": "O*NET related-occupations matrix (transitions data)",
                    }
                )
    result["alternatives"] = alternatives
    # why_not from actually-scored extras
    why_not = []
    top_score = recs[0].get("match_percent") if recs else None
    top_missing = len(recs[0].get("missing_skills", [])) if recs else 0
    for extra in result.pop("_scored_extra", [])[:2]:
        pct = extra.get("match_percent")
        if pct is None and extra.get("match_score") is not None:
            pct = round(extra["match_score"] * 100, 1)
        miss = len(extra.get("missing_skills", []))
        why_not.append(
            {
                "career_id": extra.get("career_id"),
                "title": extra.get("title"),
                "match_percent": pct,
                "missing_skills_count": miss,
                "missing_skills": extra.get("missing_skills", [])[:6],
                "explanation": (
                    f"Scored {pct}% vs {top_score}% for your top pick, with {miss} missing skills "
                    f"vs {top_missing} for the top pick — a weaker fit for the skills "
                    f"you gave, not a bad career."
                ),
                "source": "Same matcher run that produced your top 5 (matcher-v2 scores)",
            }
        )
    result["why_not"] = why_not
    prov = list(result.get("provenance_sources", []))
    prov += [
        "data/crosswalk_onet_nco.yaml (NCO-2015/ISCO-08, manual, confidence-labelled)",
        "data/india_market.yaml — Derived from project market seed "
        "(curated estimates, not official statistics)",
    ]
    result["provenance_sources"] = prov
    if result.get("source"):
        result["source"] = (
            result["source"]
            + " | India layer: estimates derived from project market seed (not official statistics)"
        )
    return result
