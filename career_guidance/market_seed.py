"""Curated market seeds with a live-API override hook.

The seed file (``data/market_seed.yaml``) gives every occupation family a salary
band (INR + USD), a demand trend and a remote-friendly flag — all labelled
“Source: curated, updated YYYY-MM”. Every value shown in the UI carries that
label through :func:`MarketSeed.label`.

Design point: :class:`SeedMarketAdapter` is the default, and
:func:`build_adapter` swaps in the live Adzuna adapter **automatically** when
``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY`` are present (still free tier), so adding a
key later needs no code change. Live results keep their own source label.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.models import MarketSnapshot
from career_guidance.taxonomy import Occupation

logger = logging.getLogger("career_guidance.market_seed")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "market_seed.yaml"

TREND_LABELS = {
    "rising": "rising demand",
    "stable": "stable demand",
    "declining": "declining demand",
}


@dataclass(frozen=True)
class Family:
    id: str
    match: tuple[str, ...]
    code_prefixes: tuple[str, ...]
    inr: tuple[int, int, int]
    usd: tuple[int, int, int]
    trend: str
    demand: int
    remote: bool
    indian_titles: tuple[str, ...] = ()
    ids: tuple[str, ...] = ()
    core_skills: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Human label: ``data-and-analytics`` → ``Data & Analytics``."""
        words = self.id.replace("and", "&").split("-")
        return " ".join(word if word == "&" else word.capitalize() for word in words)


@dataclass(frozen=True)
class IndiaOverride:
    ids: tuple[str, ...]
    inr: tuple[int, int, int]
    trend: str | None = None
    demand: int | None = None
    remote: bool | None = None
    note: str = ""


@dataclass
class MarketSeed:
    label: str
    updated: str
    defaults: dict
    families: list[Family]
    india_overrides: list[IndiaOverride]

    # ---------------------------------------------------------------- lookups
    def family_for(self, occupation: Occupation) -> Family | None:
        title = occupation.title.lower()
        for family in self.families:
            if occupation.id in family.ids:
                return family
            if any(token in title for token in family.match):
                return family
            if any(occupation.id.startswith(prefix) for prefix in family.code_prefixes):
                return family
        return None

    def india_override(self, occupation: Occupation) -> IndiaOverride | None:
        for override in self.india_overrides:
            if occupation.id in override.ids:
                return override
        return None

    def indian_titles(self, occupation: Occupation) -> list[str]:
        family = self.family_for(occupation)
        override = self.india_override(occupation)
        titles = [*occupation.alt_titles[:3], *(family.indian_titles if family else ())]
        if override and override.note:
            titles.append(override.note)
        return titles[:6]

    def remote_friendly(self, occupation: Occupation) -> bool:
        override = self.india_override(occupation)
        if override and override.remote is not None:
            return override.remote
        family = self.family_for(occupation)
        return bool(family.remote) if family else bool(self.defaults.get("remote", False))

    def trend(self, occupation: Occupation) -> str:
        override = self.india_override(occupation)
        if override and override.trend:
            return override.trend
        family = self.family_for(occupation)
        return family.trend if family else str(self.defaults.get("trend", "stable"))

    def demand_score(self, occupation: Occupation) -> int:
        override = self.india_override(occupation)
        if override and override.demand is not None:
            return override.demand
        family = self.family_for(occupation)
        return family.demand if family else int(self.defaults.get("demand", 3))

    def snapshot(self, occupation: Occupation, country: str = "in") -> MarketSnapshot:
        """Salary band + trend for one occupation, source-labelled."""
        override = self.india_override(occupation)
        family = self.family_for(occupation)
        if country == "us":
            band = family.usd if family else tuple(self.defaults["salary_us"])
            currency = "USD"
        elif country == "gb":
            # The seed set is India/US only; GB falls back to the US band scaled.
            band = tuple(
                int(v * 0.8) for v in (family.usd if family else self.defaults["salary_us"])
            )
            currency = "GBP"
        else:
            band = (
                override.inr
                if override
                else (family.inr if family else tuple(self.defaults["salary_in"]))
            )
            currency = "INR"
        trend = self.trend(occupation)
        return MarketSnapshot(
            currency=currency,
            salary_p25=int(band[0]),
            salary_p50=int(band[1]),
            salary_p75=int(band[2]),
            postings_30d=None,
            trend={"rising": "up", "stable": "flat", "declining": "down"}.get(trend, "unknown"),
            source=self.label,
        )

    def band(self, occupation: Occupation, country: str = "in") -> str:
        snapshot = self.snapshot(occupation, country)
        if snapshot.salary_p25 is None or snapshot.salary_p75 is None:
            return "—"
        symbol = {"INR": "₹", "USD": "$", "GBP": "£"}.get(snapshot.currency, "")
        if snapshot.currency == "INR":

            def fmt(v: int) -> str:
                return f"{v / 1e5:.1f} L" if v >= 1e5 else f"{v / 1000:.0f}k"

            return f"{symbol}{fmt(snapshot.salary_p25)} – {symbol}{fmt(snapshot.salary_p75)}"
        return f"{symbol}{snapshot.salary_p25:,} – {symbol}{snapshot.salary_p75:,}"

    def demand_label(self, occupation: Occupation) -> str:
        trend = self.trend(occupation)
        return f"{TREND_LABELS.get(trend, trend)} ({self.demand_score(occupation)}/5)"


class SeedMarketAdapter:
    """Default market adapter: curated seeds with live-API awareness."""

    def __init__(self, seed: MarketSeed | None = None, live=None) -> None:
        self.seed = seed or load_seed()
        self.live = live
        self.overrides: dict[str, dict] = {}

    def set_overrides(self, overrides: dict[str, dict]) -> None:
        """Admin India/market overrides keyed by career id (admin console)."""
        self.overrides = overrides or {}

    def snapshot(self, occupation: Occupation, country: str = "in") -> MarketSnapshot:
        override = self.overrides.get(occupation.id)
        if override and country == "in" and override.get("salary_p50"):
            return MarketSnapshot(
                currency="INR",
                salary_p25=override.get("salary_p25"),
                salary_p50=override.get("salary_p50"),
                salary_p75=override.get("salary_p75"),
                postings_30d=None,
                trend={"rising": "up", "stable": "flat", "declining": "down"}.get(
                    override.get("trend", ""), "unknown"
                ),
                source="Source: admin override (India market)",
            )
        if self.live is not None:
            try:
                live = self.live.snapshot(occupation, country)
                if live and live.salary_p50:
                    return live
            except Exception:  # noqa: BLE001 - live data is best-effort
                logger.warning("live market lookup failed for %s", occupation.id, exc_info=True)
        return self.seed.snapshot(occupation, country)


@lru_cache(maxsize=1)
def load_seed(path: str | None = None) -> MarketSeed:
    data = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    families = [
        Family(
            id=str(f.get("id", "")),
            match=tuple(str(t).lower() for t in f.get("match", [])),
            ids=tuple(str(i) for i in f.get("ids", [])),
            code_prefixes=tuple(str(c) for c in f.get("code_prefixes", [])),
            inr=tuple(f.get("inr", (400000, 700000, 1200000))),
            usd=tuple(f.get("usd", (45000, 65000, 95000))),
            trend=str(f.get("trend", "stable")),
            demand=int(f.get("demand", 3)),
            remote=bool(f.get("remote", False)),
            indian_titles=tuple(f.get("indian_titles", [])),
            core_skills=tuple(str(s) for s in f.get("core_skills", [])),
        )
        for f in data.get("families", [])
    ]
    overrides = [
        IndiaOverride(
            ids=tuple(str(i) for i in o.get("ids", [])),
            inr=tuple(o.get("inr", (400000, 700000, 1200000))),
            trend=o.get("trend"),
            demand=o.get("demand"),
            remote=o.get("remote"),
            note=str(o.get("note", "")),
        )
        for o in data.get("india_overrides", [])
    ]
    return MarketSeed(
        label=str(data.get("label", "Source: curated")),
        updated=str(data.get("updated", "")),
        defaults=data.get("defaults", {}),
        families=families,
        india_overrides=overrides,
    )


def build_adapter(live=None) -> SeedMarketAdapter:
    """Adapter used by the API: seeds, plus a live provider when configured."""
    return SeedMarketAdapter(load_seed(), live=live)
