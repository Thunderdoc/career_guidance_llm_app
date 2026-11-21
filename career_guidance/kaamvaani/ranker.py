"""Kaam-Vaani ranker (Step 8.1): a separate, configurable ranking
component with an injectable comparator.

Why this module exists: the Stage 4 scorer (``matching.KVScorer``)
hard-coded its five feature weights and its sort order inside the
scorer. The execution prompt (§8.1) asks for the ranker as a separate
class with an injected comparator, tuned on the gold set with no
hardcoding — so the weights now live in
``data/kv_ranker_weights.yaml`` and the ordering is a comparator the
caller can replace.

Design:

* :class:`RankerConfig` — weights + zone parameters, loaded from YAML
  and validated (weights sum to 1.0, all >= 0, no unknown features).
  :meth:`RankerConfig.default` returns the measured Stage 4 values so
  tests and embedders never need the file.
* :class:`MultiCriteriaRanker` — pure weighted combination
  (:meth:`combine`) plus ordering (:meth:`rank`) over
  :class:`ScoredItem`. The comparator is a ``Callable[[ScoredItem,
  ScoredItem], int]`` injected at construction; the default reproduces
  the Stage 4 order (score descending, tiebreak ascending). The
  comparator is a total order: two items equal on score AND tiebreak
  compare 0 (distinct occupations always differ on title, so ties in
  practice never reach it — verified by the order-independence test).
* ``KVScorer`` keeps the domain feature computation (skill overlap,
  title purity, zone fit, income fit) and delegates combination and
  ordering here. The zone-gap penalty stays in the scorer: it is a
  domain rule about preparation gaps, not a ranking primitive.

Complexity: ``combine`` is O(F) in the number of features;
``rank`` is O(n log n) comparisons, each O(1). The ranker adds no
asymptotic cost over the old inline sort.

Fairness: the ranker sees only the feature dict it is handed. The
five live features are skill, title, base, zone and income — all of
them capability or fit signals, none of them a protected attribute.
The feature set is fixed by the config's known-feature list, and the
tests assert both the key set and that no protected-attribute name
appears in this module or ``matching.py`` (the names are deliberately
not listed here, so the source grep stays meaningful).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "kv_ranker_weights.yaml"

#: Features the ranker knows. The first five carry weight; the last
#: three are aspirational (weight 0 — no per-occupation data, see
#: LIMITATIONS.md L30) and listed so the gap is visible, not hidden.
KNOWN_FEATURES: tuple[str, ...] = (
    "skill",
    "title",
    "base",
    "zone",
    "income",
    "distance",
    "availability",
    "language",
)

#: Features that actually score (weight > 0 in the default config).
LIVE_FEATURES: tuple[str, ...] = ("skill", "title", "base", "zone", "income")


@dataclass(frozen=True)
class RankerConfig:
    """Validated ranker configuration: feature weights + zone rules."""

    weights: dict[str, float] = field(default_factory=dict)
    zone_filter_slack: float = 1.0
    zone_gap_penalty: float = 0.15
    zone_gap_penalty_cap: float = 0.5

    @classmethod
    def default(cls) -> RankerConfig:
        """The measured Stage 4 values (matching.py, pre-refactor)."""
        return cls(
            weights={
                "skill": 0.30,
                "title": 0.40,
                "base": 0.10,
                "zone": 0.10,
                "income": 0.10,
                "distance": 0.0,
                "availability": 0.0,
                "language": 0.0,
            },
            zone_filter_slack=1.0,
            zone_gap_penalty=0.15,
            zone_gap_penalty_cap=0.5,
        )

    def validate(self) -> None:
        """Reject a config that cannot rank honestly."""
        unknown = sorted(set(self.weights) - set(KNOWN_FEATURES))
        if unknown:
            raise ValueError(f"unknown ranker features: {unknown}")
        missing = sorted(set(LIVE_FEATURES) - set(self.weights))
        if missing:
            raise ValueError(f"ranker config missing live features: {missing}")
        for name, weight in self.weights.items():
            if weight < 0:
                raise ValueError(f"ranker weight for {name!r} is negative: {weight}")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ranker weights sum to {total}, not 1.0")
        if self.zone_filter_slack < 0:
            raise ValueError("zone_filter_slack must be >= 0")
        if not 0 <= self.zone_gap_penalty <= 1:
            raise ValueError("zone_gap_penalty must be in [0, 1]")
        if not 0 <= self.zone_gap_penalty_cap <= 1:
            raise ValueError("zone_gap_penalty_cap must be in [0, 1]")

    def weight(self, feature: str) -> float:
        """The weight for one feature (0.0 when the config omits it)."""
        return self.weights.get(feature, 0.0)


def load_ranker_config(path: Path | str | None = None) -> RankerConfig:
    """Load + validate the ranker config from YAML (default:
    ``data/kv_ranker_weights.yaml``). Raises on a missing file or an
    invalid config — a ranker must never silently rank on wrong
    weights."""
    config_path = Path(path) if path is not None else CONFIG_PATH
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = RankerConfig(
        weights={str(k): float(v) for k, v in (data.get("weights") or {}).items()},
        zone_filter_slack=float(data.get("zone_filter_slack", 1.0)),
        zone_gap_penalty=float(data.get("zone_gap_penalty", 0.15)),
        zone_gap_penalty_cap=float(data.get("zone_gap_penalty_cap", 0.5)),
    )
    config.validate()
    return config


@dataclass
class ScoredItem:
    """One ranked item: the payload, its combined score, the
    per-feature contributions (weight x value, so the caller can say
    WHY it ranked where it did), and a tiebreak key (the occupation
    title for matches — ascending, so ties break alphabetically)."""

    item: Any
    score: float
    components: dict[str, float] = field(default_factory=dict)
    tiebreak: str = ""


#: A comparator over scored items: negative when ``a`` ranks before
#: ``b``, positive when after, 0 when equivalent.
Comparator = Callable[[ScoredItem, ScoredItem], int]


def default_comparator(a: ScoredItem, b: ScoredItem) -> int:
    """The Stage 4 order: higher score first; ties by tiebreak key
    ascending. A total order over distinct items."""
    if a.score != b.score:
        return -1 if a.score > b.score else 1
    if a.tiebreak != b.tiebreak:
        return -1 if a.tiebreak < b.tiebreak else 1
    return 0


class MultiCriteriaRanker:
    """Weighted multi-criteria combination + ordering with an
    injectable comparator."""

    def __init__(
        self,
        config: RankerConfig | None = None,
        comparator: Comparator | None = None,
    ) -> None:
        self.config = config or RankerConfig.default()
        self.config.validate()
        self.comparator: Comparator = comparator or default_comparator

    def combine(self, features: dict[str, float]) -> tuple[float, dict[str, float]]:
        """Weighted sum of the features + per-feature contributions.

        Features absent from the config score 0 (a zero-weight or
        unknown feature never contributes); features in the config but
        absent from the input score 0. Returns ``(score,
        contributions)`` where contributions maps each live feature to
        weight x value.
        """
        contributions: dict[str, float] = {}
        score = 0.0
        for name, weight in self.config.weights.items():
            if weight == 0:
                continue
            contribution = weight * features.get(name, 0.0)
            contributions[name] = contribution
            score += contribution
        return score, contributions

    def score_item(self, item: Any, features: dict[str, float], tiebreak: str = "") -> ScoredItem:
        """Combine ``features`` for ``item`` into a scored item."""
        score, contributions = self.combine(features)
        return ScoredItem(item=item, score=score, components=contributions, tiebreak=tiebreak)

    def rank(self, scored: list[ScoredItem]) -> list[ScoredItem]:
        """A new list ordered by the injected comparator (input
        untouched; Python's sort is stable, so equivalent items keep
        their input order)."""
        return sorted(scored, key=functools.cmp_to_key(self.comparator))
