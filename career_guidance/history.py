"""Session-scoped guidance history with export helpers."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from career_guidance.models import CareerSuggestion
from career_guidance.suggestions import GuidanceResult, format_suggestions_markdown

_EXCERPT_LENGTH = 120


@dataclass(frozen=True)
class HistoryEntry:
    """A single guidance run recorded in the session history."""

    timestamp: str
    input_excerpt: str
    provider_name: str
    suggestions: list[CareerSuggestion]


class GuidanceHistory:
    """In-memory history of guidance runs for the current session."""

    def __init__(self) -> None:
        self._entries: list[HistoryEntry] = []

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> list[HistoryEntry]:
        """Return a copy of the recorded entries."""
        return list(self._entries)

    def add(self, raw_input: str, result: GuidanceResult) -> HistoryEntry:
        """Record a guidance run and return the created entry."""
        excerpt = " ".join((raw_input or "").split())
        if len(excerpt) > _EXCERPT_LENGTH:
            excerpt = excerpt[: _EXCERPT_LENGTH - 3] + "..."
        entry = HistoryEntry(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            input_excerpt=excerpt,
            provider_name=result.provider_name,
            suggestions=list(result.suggestions),
        )
        self._entries.append(entry)
        return entry

    def clear(self) -> None:
        """Remove all recorded entries."""
        self._entries.clear()

    def to_json(self) -> str:
        """Export the history as pretty-printed JSON."""
        return json.dumps(
            [
                {
                    "timestamp": entry.timestamp,
                    "input": entry.input_excerpt,
                    "provider": entry.provider_name,
                    "suggestions": [
                        {"title": item.title, "rationale": item.rationale}
                        for item in entry.suggestions
                    ],
                }
                for entry in self._entries
            ],
            indent=2,
        )

    def to_markdown(self) -> str:
        """Export the history as a Markdown document."""
        if not self._entries:
            return "No history yet."
        blocks = [
            f"## {entry.timestamp} · {entry.provider_name}\n\n"
            f"> {entry.input_excerpt}\n\n"
            f"{format_suggestions_markdown(entry.suggestions)}"
            for entry in self._entries
        ]
        return "\n\n".join(blocks)
