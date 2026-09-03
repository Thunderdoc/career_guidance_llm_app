"""Shared domain models and exceptions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CareerSuggestion:
    """A single career path recommendation."""

    title: str
    rationale: str


class InvalidInputError(ValueError):
    """Raised when the user-provided input fails validation."""


class ProviderError(RuntimeError):
    """Raised when a suggestion provider fails to produce results."""
