"""Translation coverage report (English / Tamil / Hindi).

The UI strings live in ``frontend/lib/i18n.tsx`` as three flat objects; template
sentences live in ``data/templates/explanations.{en,ta,hi}.yaml``; the RIASEC
inventory ships English, Tamil and Hindi statements in
``data/assessment_items.yaml``. This module measures all three so the admin
console (and ``docs/TEST_REPORT.md``) can show a real number instead of a claim.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
I18N_FILE = ROOT / "frontend" / "lib" / "i18n.tsx"
TEMPLATES_DIR = ROOT / "data" / "templates"
ITEMS_FILE = ROOT / "data" / "assessment_items.yaml"
LOCALES = ("en", "ta", "hi")

_BLOCK = re.compile(r"(?:^|\n)const (en|ta|hi)[^=]*=\s*\{(.*?)\n\};", re.S)
_KEY = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", re.M)


def ui_keys() -> dict[str, set[str]]:
    """Locale → set of translation keys found in the TypeScript message table."""
    if not I18N_FILE.exists():
        return {locale: set() for locale in LOCALES}
    text = I18N_FILE.read_text(encoding="utf-8")
    found: dict[str, set[str]] = {}
    for locale, block in _BLOCK.findall(text):
        found.setdefault(locale, set()).update(_KEY.findall(block))
    return {locale: found.get(locale, set()) for locale in LOCALES}


def template_keys() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for locale in LOCALES:
        path = TEMPLATES_DIR / f"explanations.{locale}.yaml"
        if not path.exists():
            out[locale] = set()
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[locale] = {str(k) for k in (raw.get("templates") or {})}
    return out


def assessment_coverage() -> dict[str, int]:
    raw = yaml.safe_load(ITEMS_FILE.read_text(encoding="utf-8")) or {}
    counts = {locale: 0 for locale in LOCALES}
    for item in raw.get("items", []):
        for locale in LOCALES:
            if item.get(locale):
                counts[locale] += 1
    counts["total_items"] = len(raw.get("items", []))
    return counts


def locale_catalog() -> dict:
    """Everything the admin “System → translations” panel shows."""
    ui = ui_keys()
    templates = template_keys()
    english_ui = len(ui["en"]) or 1
    english_templates = len(templates["en"]) or 1
    items = assessment_coverage()
    total_items = items["total_items"] or 1
    report = {}
    for locale in LOCALES:
        report[locale] = {
            "ui_keys": len(ui[locale]),
            "ui_coverage_percent": round(100 * len(ui[locale]) / english_ui, 1),
            "template_keys": len(templates[locale]),
            "template_coverage_percent": round(100 * len(templates[locale]) / english_templates, 1),
            "assessment_items": items[locale],
            "assessment_coverage_percent": round(100 * items[locale] / total_items, 1),
            "missing_ui_keys": sorted(ui["en"] - ui[locale])[:20],
            "missing_template_keys": sorted(templates["en"] - templates[locale])[:20],
        }
    overall = min(report[locale]["ui_coverage_percent"] for locale in ("ta", "hi"))
    return {
        "locales": report,
        "english_ui_keys": len(ui["en"]),
        "english_template_keys": len(templates["en"]),
        "worst_locale_coverage_percent": overall,
        "source": "Source: parsed from frontend/lib/i18n.tsx and data/templates/*.yaml at runtime",
    }


if __name__ == "__main__":  # pragma: no cover - convenience CLI
    import json

    print(json.dumps(locale_catalog(), indent=2))
