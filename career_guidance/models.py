"""Shared domain models and exceptions."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CareerSuggestion:
    """A single career path recommendation (simple form)."""

    title: str
    rationale: str


@dataclass(frozen=True)
class MarketSnapshot:
    """Labour-market signal for an occupation (may be partially populated)."""

    currency: str = "INR"
    salary_p25: int | None = None
    salary_p50: int | None = None
    salary_p75: int | None = None
    postings_30d: int | None = None
    trend: str = "unknown"  # up | flat | down | unknown
    source: str = ""


@dataclass(frozen=True)
class LearningResource:
    """A curated learning link for a skill."""

    skill: str
    title: str
    url: str
    provider: str = ""
    free: bool = True


@dataclass(frozen=True)
class CareerRecommendation:
    """A structured career recommendation with skill-gap analysis."""

    title: str
    match_reason: str
    suitability: str  # beginner | intermediate | advanced
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    learning_path: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    # v2 fields (all optional so stored v1 rows still deserialise)
    career_id: str = ""
    match_score: float = 0.0
    description: str = ""
    job_zone: int = 0
    transition_path: list[str] = field(default_factory=list)
    market: MarketSnapshot | None = None
    resources: list[LearningResource] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "CareerRecommendation":
        """Build from a stored/JSON dict, tolerating missing v2 fields."""
        data = dict(data)
        market = data.get("market")
        if isinstance(market, dict):
            data["market"] = MarketSnapshot(**market)
        resources = data.get("resources") or []
        data["resources"] = [LearningResource(**r) if isinstance(r, dict) else r for r in resources]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class InvalidInputError(ValueError):
    """Raised when the user-provided input fails validation."""


class ProviderError(RuntimeError):
    """Raised when a suggestion provider fails to produce results."""
