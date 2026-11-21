#!/usr/bin/env python3
"""Generate ``frontend/lib/voice-vocabulary.ts`` from the skill synonyms.

The voice flow matches a spoken/typed transcript against the same skill
vocabulary the backend uses (``data/skill_synonyms.yaml``: 126 canonicals,
802 aliases, including Tamil/Hindi transliterations), plus a small curated
set of spoken-form aliases for trades and farm work that school-leavers
actually say ("farming", "tailoring", "mobile repair", ...). Every extra
alias maps to a canonical that exists in the YAML — the script fails
loudly if one does not, so the vocabulary can never invent a skill.

Run from the repo root after editing the YAML or the extra list:

    python scripts/gen_voice_vocab.py

The output is sorted longest-alias-first so multi-word phrases win over
their parts during matching ("data entry" before "data").
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "data" / "skill_synonyms.yaml"
VOICE_ALIASES_PATH = ROOT / "data" / "voice_aliases.yaml"
CITIES_PATH = ROOT / "data" / "kv_cities.yaml"
OUT_PATH = ROOT / "frontend" / "lib" / "voice-vocabulary.ts"


def load_extra_aliases() -> dict[str, str]:
    """Spoken-form aliases from ``data/voice_aliases.yaml`` — the single
    source of truth shared with the backend deterministic extractor
    (``career_guidance/kaamvaani/extract.py``), so both paths agree by
    construction (Stage 2)."""
    data = yaml.safe_load(VOICE_ALIASES_PATH.read_text(encoding="utf-8"))
    return {
        str(k).strip().lower(): str(v).strip().lower() for k, v in data["extra_aliases"].items()
    }


EXTRA_ALIASES: dict[str, str] = load_extra_aliases()


def main() -> int:
    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    skills = data["skills"]

    pairs: dict[str, str] = {}
    for canonical, entry in skills.items():
        canon = str(canonical).strip().lower()
        aliases = [canon, *[str(a).strip().lower() for a in entry.get("aliases", [])]]
        for alias in aliases:
            if len(alias) >= 2 and not alias.isdigit():
                pairs.setdefault(alias, canon)

    for alias, canon in EXTRA_ALIASES.items():
        if canon not in skills:
            msg = f"ERROR: extra alias {alias!r} maps to unknown canonical {canon!r}"
            print(msg, file=sys.stderr)
            return 1
        pairs.setdefault(alias, canon)

    ordered = sorted(pairs.items(), key=lambda kv: (-len(kv[0]), kv[0]))

    # Native-script city aliases (Stage 3 parity port): the same aliases
    # the backend extractor uses (data/kv_cities.yaml), so a Tamil/Hindi
    # transcript resolves to the canonical English city name offline too.
    # English city names stay in the hand-written CITIES list in
    # voice-profile.ts (pinned to the YAML by a test); only the
    # non-ASCII aliases are generated here.
    cities_data = yaml.safe_load(CITIES_PATH.read_text(encoding="utf-8"))
    city_pairs: dict[str, str] = {}
    for entry in cities_data["cities"]:
        for alias in entry.get("aliases", []):
            alias = str(alias).strip().lower()
            if any(ord(ch) > 127 for ch in alias):
                city_pairs.setdefault(alias, str(entry["name"]))
    city_ordered = sorted(city_pairs.items(), key=lambda kv: (-len(kv[0]), kv[0]))

    def ts_str(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [
        "/**",
        " * Skill vocabulary for the voice flow (/voice). GENERATED — do not edit",
        " * by hand. Regenerate with: python scripts/gen_voice_vocab.py",
        " *",
        " * Source: data/skill_synonyms.yaml (the same vocabulary the backend",
        " * matcher uses) plus a small curated set of spoken-form aliases for",
        " * trades and farm work (see the generator script). Pairs are sorted",
        " * longest-alias-first so multi-word phrases win during matching.",
        " * CITY_ALIASES below carries the native-script city aliases from",
        " * data/kv_cities.yaml (Stage 3 parity port).",
        " */",
        "",
        "export const SKILL_ALIASES: ReadonlyArray<"
        "readonly [alias: string, canonical: string]> = [",
    ]
    for alias, canon in ordered:
        lines.append(f"  [{ts_str(alias)}, {ts_str(canon)}],")
    lines.append("];")
    lines.append("")
    lines.append("/** Canonical skill names, for display and de-duplication. */")
    canonicals = sorted({canon for _, canon in ordered})
    lines.append("export const CANONICAL_SKILLS: ReadonlyArray<string> = [")
    for canon in canonicals:
        lines.append(f"  {ts_str(canon)},")
    lines.append("];")
    lines.append("")
    lines.append("/**")
    lines.append(" * Native-script (Tamil/Hindi) city aliases, longest first — the")
    lines.append(" * frontend mirror of the backend's kv_cities.yaml aliases.")
    lines.append(" * Matched by substring (Tamil locatives are suffixes, so word")
    lines.append(" * boundaries do not apply).")
    lines.append(" */")
    lines.append("export const CITY_ALIASES: ReadonlyArray<")
    lines.append("readonly [alias: string, canonical: string]> = [")
    for alias, canon in city_ordered:
        lines.append(f"  [{ts_str(alias)}, {ts_str(canon)}],")
    lines.append("];")
    lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"wrote {OUT_PATH} ({len(ordered)} aliases, {len(canonicals)} canonicals, "
        f"{len(city_ordered)} city aliases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
