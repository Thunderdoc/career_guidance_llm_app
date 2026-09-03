"""Shared domain models and exceptions."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CareerSuggestion:
    """A single career path recommendation (simple form)."""

    title: str
    rationale: str


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


class InvalidInputError(ValueError):
    """Raised when the user-provided input fails validation."""


class ProviderError(RuntimeError):
    """Raised when a suggestion provider fails to produce results."""
