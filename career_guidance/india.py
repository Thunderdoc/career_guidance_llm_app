"""India data layer (Phase 2): O*NET->NCO-2015 crosswalk + India market estimates.

Honesty rules (docs/SOURCES.md, UPGRADE_PLAN C4):
* Crosswalk contains only defensible mappings; unknown occupations return None.
* Every market figure is kind="estimate", derived from data/market_seed.yaml,
  source-labelled as such, never presented as an official statistic.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.market_seed import load_seed
from career_guidance.taxonomy import Occupation

_ROOT = Path(__file__).resolve().parent.parent / "data"
CROSSWALK_PATH = _ROOT / "crosswalk_onet_nco.yaml"
INDIA_MARKET_PATH = _ROOT / "india_market.yaml"
ESTIMATE_SOURCE = "Derived from project market seed (curated estimates, not official statistics)"
AS_OF = "2026-11-06"


@lru_cache(maxsize=2)
def load_crosswalk(path: str | None = None) -> list[dict]:
    data = yaml.safe_load(Path(path or CROSSWALK_PATH).read_text(encoding="utf-8")) or {}
    return list(data.get("mappings", []))


@lru_cache(maxsize=2)
def _crosswalk_index(path: str | None = None) -> tuple[dict, dict]:
    by_code, by_title = {}, {}
    for m in load_crosswalk(path):
        if m.get("onet_code"):
            by_code[str(m["onet_code"])] = m
        if m.get("title"):
            by_title[str(m["title"]).lower()] = m
    return by_code, by_title


def lookup_crosswalk(
    occupation: Occupation | None = None, *, onet_code: str = "", title: str = ""
) -> dict | None:
    """Crosswalk entry for an occupation, or None honestly when unmapped."""
    by_code, by_title = _crosswalk_index()
    code = onet_code or (occupation.id if occupation else "")
    name = title or (occupation.title if occupation else "")
    if code and code in by_code:
        return dict(by_code[code])
    if name and name.lower() in by_title:
        return dict(by_title[name.lower()])
    return None


def crosswalk_payload(occupation: Occupation) -> dict:
    entry = lookup_crosswalk(occupation)
    if not entry:
        return {
            "mapped": False,
            "nco_code": None,
            "isco_code": None,
            "confidence": None,
            "method": "No defensible NCO-2015 mapping recorded for this occupation.",
            "source": "data/crosswalk_onet_nco.yaml",
            "as_of": AS_OF,
        }
    return {
        "mapped": True,
        "onet_code": entry.get("onet_code"),
        "nco_code": entry.get("nco_code"),
        "isco_code": entry.get("isco_code"),
        "confidence": entry.get("confidence"),
        "method": entry.get("method"),
        "source": "data/crosswalk_onet_nco.yaml",
        "as_of": AS_OF,
    }


@lru_cache(maxsize=2)
def load_india_market(path: str | None = None) -> list[dict]:
    data = yaml.safe_load(Path(path or INDIA_MARKET_PATH).read_text(encoding="utf-8")) or {}
    return list(data.get("entries", []))


def india_market_for(occupation: Occupation, overrides: dict | None = None) -> dict | None:
    """India market block for an occupation: admin override > occupation entry > family entry."""
    if overrides:
        for key in (occupation.id, occupation.title):
            if key in overrides and isinstance(overrides[key], dict):
                return _normalise({**overrides[key], "key": key, "admin_override": True})
    entries = load_india_market()
    for e in entries:
        ids = e.get("occupation_ids") or e.get("ids") or []
        if occupation.id in ids:
            return _normalise(e)
    seed = load_seed()
    family = seed.family_for(occupation)
    if family:
        for e in entries:
            if e.get("family") == family.id:
                # Prefer india_override band from market_seed when present.
                ov = seed.india_override(occupation)
                out = _normalise(e)
                if ov:
                    p = ov.inr
                    out["fresher_salary_inr"] = [round(p[0] * 0.6 / 1000) * 1000, p[0]]
                    out["salary_3yr_inr"] = [
                        round(p[1] * 0.8 / 1000) * 1000,
                        round(p[1] * 1.1 / 1000) * 1000,
                    ]
                    out["salary_7yr_inr"] = [
                        round(p[2] * 0.9 / 1000) * 1000,
                        round(p[2] * 1.3 / 1000) * 1000,
                    ]
                    if ov.trend:
                        out["entry_demand_trend"] = ov.trend
                    if ov.demand is not None:
                        out["demand"] = ov.demand
                return out
    return None


def _normalise(e: dict) -> dict:
    return {
        "family": e.get("family"),
        "key": e.get("key") or e.get("family"),
        "fresher_salary_inr": list(e.get("fresher_salary_inr") or []),
        "salary_3yr_inr": list(e.get("salary_3yr_inr") or []),
        "salary_7yr_inr": list(e.get("salary_7yr_inr") or []),
        "entry_demand_trend": e.get("entry_demand_trend") or e.get("trend") or "stable",
        "demand": e.get("demand"),
        "top_cities": list(e.get("top_cities") or []),
        "top_sectors": list(e.get("top_sectors") or []),
        "source": e.get("source") or ESTIMATE_SOURCE,
        "source_url": e.get("source_url") or "",
        "as_of": e.get("as_of") or AS_OF,
        "kind": e.get("kind") or "estimate",
        "derivation": e.get("derivation", ""),
        "admin_override": bool(e.get("admin_override")),
    }


def india_payload(occupation: Occupation, overrides: dict | None = None) -> dict:
    return {
        "crosswalk": crosswalk_payload(occupation),
        "market": india_market_for(occupation, overrides),
    }
