"""Labour-market signals: salary and demand per occupation.

Adapters:

* ``AdzunaAdapter`` — live data when ``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY`` are
  configured (free tier). Cached in-process for 24 h.
* ``StaticMarketAdapter`` — offline fallback derived from O*NET job zones and
  a small India salary band table, so every card can still show a range.

All adapters return ``MarketSnapshot``; missing fields stay ``None``.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

import httpx

from career_guidance.models import MarketSnapshot
from career_guidance.taxonomy import Occupation

logger = logging.getLogger("career_guidance.market")

# Approximate annual INR bands by O*NET job zone (entry -> experienced). These
# are conservative national medians for India used only when live data is
# unavailable, and are labelled as estimates in the UI.
_INDIA_BANDS = {
    1: (180_000, 240_000, 330_000),
    2: (220_000, 320_000, 480_000),
    3: (300_000, 480_000, 780_000),
    4: (420_000, 750_000, 1_400_000),
    5: (600_000, 1_100_000, 2_200_000),
}

# Occupation-family multipliers reflecting Indian market demand (SOC major group).
_FAMILY_FACTOR = {
    "15": 1.35,  # computer & mathematical
    "17": 1.10,  # engineering
    "13": 1.10,  # business & financial
    "11": 1.25,  # management
    "29": 1.05,  # healthcare practitioners
    "25": 0.85,  # education
    "27": 0.95,  # arts, design, media
    "41": 0.90,  # sales
    "43": 0.80,  # office & admin
    "35": 0.70,  # food service
    "37": 0.65,  # cleaning & maintenance
    "47": 0.75,  # construction
    "49": 0.85,  # installation & repair
    "51": 0.80,  # production
    "53": 0.80,  # transportation
}

# Broad demand trend by family for India (public labour-market commentary).
_FAMILY_TREND = {
    "15": "up",
    "29": "up",
    "13": "up",
    "17": "flat",
    "11": "up",
    "25": "flat",
    "27": "flat",
    "41": "flat",
    "43": "down",
    "35": "flat",
    "51": "flat",
    "49": "flat",
}


class MarketAdapter(Protocol):
    def snapshot(self, occupation: Occupation, country: str = "in") -> MarketSnapshot: ...


class StaticMarketAdapter:
    """Offline estimate from job zone + occupation family."""

    def snapshot(self, occupation: Occupation, country: str = "in") -> MarketSnapshot:
        zone = min(max(occupation.job_zone, 1), 5)
        p25, p50, p75 = _INDIA_BANDS[zone]
        family = occupation.id[:2]
        factor = _FAMILY_FACTOR.get(family, 1.0)
        return MarketSnapshot(
            currency="INR",
            salary_p25=int(p25 * factor),
            salary_p50=int(p50 * factor),
            salary_p75=int(p75 * factor),
            postings_30d=None,
            trend=_FAMILY_TREND.get(family, "unknown"),
            source="Estimate (O*NET job zone × India band)",
        )


class AdzunaAdapter:
    """Live salary histogram + posting counts from Adzuna."""

    def __init__(self, app_id: str, app_key: str, ttl_seconds: int = 86_400) -> None:
        self._id, self._key, self._ttl = app_id, app_key, ttl_seconds
        self._cache: dict[str, tuple[float, MarketSnapshot]] = {}
        self._fallback = StaticMarketAdapter()

    def snapshot(self, occupation: Occupation, country: str = "in") -> MarketSnapshot:
        key = f"{country}:{occupation.id}"
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self._ttl:
            return hit[1]
        try:
            snap = self._fetch(occupation, country)
        except Exception as error:  # noqa: BLE001 - never break the product on market data
            logger.warning("Adzuna lookup failed for %s: %s", occupation.title, error)
            snap = self._fallback.snapshot(occupation, country)
        self._cache[key] = (time.time(), snap)
        return snap

    def _fetch(self, occupation: Occupation, country: str) -> MarketSnapshot:
        title = occupation.alt_titles[0] if occupation.alt_titles else occupation.title
        title = title.split(",")[0]
        params = {
            "app_id": self._id,
            "app_key": self._key,
            "what": title,
            "results_per_page": 1,
            "content-type": "application/json",
        }
        base = f"https://api.adzuna.com/v1/api/jobs/{country}"
        with httpx.Client(timeout=8.0) as client:
            search = client.get(f"{base}/search/1", params=params).json()
            hist = client.get(f"{base}/histogram", params=params).json()
        count = int(search.get("count", 0))
        histogram = {int(k): int(v) for k, v in (hist.get("histogram") or {}).items()}
        p25 = p50 = p75 = None
        if histogram:
            total = sum(histogram.values())
            running = 0
            for salary in sorted(histogram):
                running += histogram[salary]
                if p25 is None and running >= total * 0.25:
                    p25 = salary
                if p50 is None and running >= total * 0.5:
                    p50 = salary
                if p75 is None and running >= total * 0.75:
                    p75 = salary
        currency = {"in": "INR", "gb": "GBP", "us": "USD"}.get(country, "USD")
        return MarketSnapshot(
            currency=currency,
            salary_p25=p25,
            salary_p50=p50,
            salary_p75=p75,
            postings_30d=count,
            trend="unknown",
            source="Adzuna",
        )


_adapter: MarketAdapter | None = None


def get_market_adapter() -> MarketAdapter:
    """Return the configured adapter (Adzuna if keys present, else static)."""
    global _adapter
    if _adapter is None:
        app_id, app_key = os.getenv("ADZUNA_APP_ID", ""), os.getenv("ADZUNA_APP_KEY", "")
        _adapter = AdzunaAdapter(app_id, app_key) if app_id and app_key else StaticMarketAdapter()
    return _adapter
