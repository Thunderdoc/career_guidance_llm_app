"""Template explanation engine (no LLM).

Every sentence the product shows about a match, a gap, a roadmap or a résumé is
assembled from these templates plus **real data**, so each claim is traceable to
its source::

    >>> ex = Explanations()
    >>> ex.render("match.headline", matched_count=7, total_skills=11, title="Data Analyst")
    'You match 7 of 11 core skills for Data Analyst.'

Templates live in ``data/templates/explanations.{en,ta,hi}.yaml`` and can be
overridden at runtime by admins (``template_overrides`` table) without a deploy.
Missing keys or locales fall back to English, then to the key itself, so the UI
never breaks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger("career_guidance.explanations")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "data" / "templates"
LOCALES = ("en", "ta", "hi")
SOURCE_LABEL = "Source: template engine (curated templates, updated {updated})"


@dataclass
class Explanations:
    """Locale-aware template renderer."""

    templates: dict[str, dict[str, str]] = field(default_factory=dict)
    overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    updated: str = "2026-09"

    @property
    def locales(self) -> tuple[str, ...]:
        """Locales with a loaded template file, English first."""
        return tuple(sorted(self.templates, key=lambda loc: (loc != "en", loc)))

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, directory: str | Path | None = None) -> Explanations:
        directory = Path(directory or TEMPLATES_DIR)
        templates: dict[str, dict[str, str]] = {}
        updated = "2026-09"
        for locale in LOCALES:
            path = directory / f"explanations.{locale}.yaml"
            if not path.exists():
                logger.warning("explanation templates missing for %s (%s)", locale, path)
                continue
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            templates[locale] = {str(k): str(v) for k, v in (raw.get("templates") or {}).items()}
            updated = str(raw.get("updated") or updated)
        return cls(templates=templates, updated=updated)

    def set_overrides(self, overrides: dict[str, dict[str, str]]) -> None:
        """Admin edits: ``{locale: {key: template}}``."""
        self.overrides = {
            str(loc): {str(k): str(v) for k, v in (values or {}).items()}
            for loc, values in (overrides or {}).items()
        }

    def locale_templates(self, locale: str) -> dict[str, str]:
        return {
            **self.templates.get("en", {}),
            **self.templates.get(locale, {}),
            **self.overrides.get("en", {}),
            **self.overrides.get(locale, {}),
        }  # noqa: E501

    def keys(self, locale: str = "en") -> list[str]:
        return sorted(self.templates.get(locale, self.templates.get("en", {})))

    # ------------------------------------------------------------------ #
    def render(self, key: str, locale: str = "en", **values: object) -> str:
        """Fill ``key`` with ``values``; unknown placeholders are left visible."""
        table = self.locale_templates(locale if locale in LOCALES else "en")
        template = table.get(key) or self.templates.get("en", {}).get(key) or key
        out = template
        for name, value in values.items():
            out = out.replace("{" + name + "}", _format_value(value))
        return out

    def source(self) -> str:
        return SOURCE_LABEL.format(updated=self.updated)

    def preview(self, locale: str = "en", sample: dict | None = None) -> dict[str, str]:
        """Render every template with the sample values (admin live preview)."""
        values = sample or SAMPLE_VALUES
        return {key: self.render(key, locale, **values) for key in self.keys(locale)}


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return ", ".join(str(v) for v in items[:4]) + ("…" if len(items) > 4 else "")
    return str(value)


#: Values used for the admin template preview and for tests.
SAMPLE_VALUES: dict[str, object] = {
    "title": "Data Analyst",
    "matched_count": 7,
    "total_skills": 11,
    "missing_count": 4,
    "strongest": "SQL, Statistics",
    "gap": "Tableau",
    "interest_top": "Investigative",
    "interest_pct": 82,
    "skills_score": 71,
    "interest_score": 82,
    "zone_score": 93,
    "job_zone": 4,
    "job_zone_label": "needs a Bachelor's degree",
    "target_zone": 3,
    "zone_distance": 1,
    "direction": "above",
    "demand": "rising",
    "salary_band": "₹6.5 L – ₹14.0 L",
    "currency": "INR",
    "source": "Source: curated, updated 2026-09",
    "resource_count": 3,
    "readiness": 62,
    "readiness_before": 62,
    "readiness_after": 84,
    "strong": 5,
    "weak": 3,
    "missing": 4,
    "importance": 9,
    "rating": 2,
    "weeks": 8,
    "week": 3,
    "hours": 6,
    "skill": "Tableau",
    "eta": "14 Nov 2026",
    "delta_count": 2,
    "delta": "SQL, Tableau",
    "hops": 2,
    "from_title": "Marketing Executive",
    "to_title": "Data Analyst",
    "task": "build a monthly sales dashboard",
    "score": 74,
    "grade": "Good",
    "percent": 68,
    "quantified": 6,
    "bullets": 12,
    "verb_count": 9,
    "sections": "Education, Experience, Skills",
    "suggestion": "Add a number to the first bullet.",
    "shared": "SQL, Excel, communication",
    "level": "Beginner",
    "provider": "NPTEL",
    "updated": "2026-09",
}


@lru_cache(maxsize=1)
def get_explanations() -> Explanations:
    """Process-wide template engine (cached)."""
    return Explanations.load()
