"""Build the occupation catalog from O*NET text files.

Usage:
    python scripts/build_catalog.py --source /path/to/onet_txt --out data/catalog/occupations.json

The O*NET database is licensed under CC BY 4.0 by the U.S. Department of
Labor / Employment and Training Administration. See data/catalog/NOTICE.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

SKILL_IMPORTANCE_MIN = 2.5  # O*NET importance scale 1..5
KNOWLEDGE_IMPORTANCE_MIN = 3.5
MAX_SKILLS = 12
MAX_KNOWLEDGE = 6
MAX_TECH = 60
MAX_ALT_TITLES = 10
MAX_RELATED = 6

_GENERIC_SKILLS = {
    "Active Listening",
    "Speaking",
    "Reading Comprehension",
    "Monitoring",
    "Social Perceptiveness",
    "Coordination",
    "Time Management",
    "Judgment and Decision Making",
    "Critical Thinking",
    "Writing",
    "Active Learning",
    "Learning Strategies",
}

_TECH_NOISE = re.compile(
    r"^(microsoft (word|excel|outlook|powerpoint|office)|web browser software|"
    r"email software|google (docs|sheets|gmail)|adobe systems adobe acrobat)$",
    re.I,
)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


_ABBREV = re.compile(r"^(.*?\S)\s+([A-Z][A-Za-z0-9+#.]{1,9})$")


def _clean_tech(example: str) -> str:
    """Normalise O*NET technology examples into recognisable names.

    'Oracle Java' -> 'Java'; 'Adobe Systems Adobe Photoshop' -> 'Adobe Photoshop';
    'Structured query language SQL' -> 'SQL'; 'Cascading Style Sheets CSS' -> 'CSS'.
    """
    example = example.strip()
    for prefix in ("Oracle ", "The MathWorks ", "Adobe Systems "):
        if example.startswith(prefix) and len(example) > len(prefix) + 2:
            example = example[len(prefix) :]
    match = _ABBREV.match(example)
    if match:
        long, short = match.groups()
        words = [w for w in re.split(r"[\s-]+", long) if w]
        initials = "".join(w[0].upper() for w in words)
        if len(words) >= 2 and initials.replace("-", "") in short.upper():
            return short
    return example


def build(source: Path) -> list[dict]:
    occupations = {
        row["O*NET-SOC Code"]: {
            "id": row["O*NET-SOC Code"],
            "title": row["Title"],
            "description": row["Description"],
        }
        for row in _read(source / "Occupation Data.txt")
    }

    skills: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for row in _read(source / "Skills.txt"):
        if row["Scale ID"] != "IM" or row.get("Recommend Suppress") == "Y":
            continue
        name = row["Element Name"]
        value = float(row["Data Value"])
        if name in _GENERIC_SKILLS:
            value -= 1.0  # keep, but rank generic skills lower
        if value >= SKILL_IMPORTANCE_MIN:
            skills[row["O*NET-SOC Code"]].append((value, name))

    knowledge: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for row in _read(source / "Knowledge.txt"):
        if row["Scale ID"] != "IM" or row.get("Recommend Suppress") == "Y":
            continue
        value = float(row["Data Value"])
        if value >= KNOWLEDGE_IMPORTANCE_MIN:
            knowledge[row["O*NET-SOC Code"]].append((value, row["Element Name"]))

    tech: dict[str, list[tuple[int, str]]] = defaultdict(list)
    seen_tech: dict[str, set[str]] = defaultdict(set)
    for row in _read(source / "Technology Skills.txt"):
        example = _clean_tech(row["Example"])
        if _TECH_NOISE.match(example):
            continue
        code = row["O*NET-SOC Code"]
        key = example.lower()
        if key in seen_tech[code]:
            continue
        seen_tech[code].add(key)
        hot = 1 if row.get("Hot Technology") == "Y" else 0
        tech[code].append((hot, len(tech[code]), example))

    zones: dict[str, int] = {}
    for row in _read(source / "Job Zones.txt"):
        zones[row["O*NET-SOC Code"]] = int(row["Job Zone"])

    alt: dict[str, list[str]] = defaultdict(list)
    for row in _read(source / "Alternate Titles.txt"):
        code = row["O*NET-SOC Code"]
        if len(alt[code]) < MAX_ALT_TITLES:
            alt[code].append(row["Alternate Title"])

    interests: dict[str, dict[str, float]] = defaultdict(dict)
    for row in _read(source / "Interests.txt"):
        if row["Scale ID"] == "OI":
            interests[row["O*NET-SOC Code"]][row["Element Name"][0]] = float(row["Data Value"])

    related: dict[str, list[str]] = defaultdict(list)
    matrix = source / "Career Changers Matrix.txt"
    if matrix.exists():
        for row in _read(matrix):
            code = row["O*NET-SOC Code"]
            if len(related[code]) < MAX_RELATED:
                related[code].append(row["Related O*NET-SOC Code"])

    catalog = []
    for code, occ in occupations.items():
        if code not in skills and code not in tech:
            continue  # no measurable profile (e.g. "All Other" aggregates)
        top_skills = [n for _, n in sorted(skills[code], reverse=True)[:MAX_SKILLS]]
        top_knowledge = [n for _, n in sorted(knowledge[code], reverse=True)[:MAX_KNOWLEDGE]]
        # Hot technologies first, then file order. Keep a generous list for
        # matching; the UI shows only the top few.
        ranked = sorted(tech[code], key=lambda t: (-t[0], t[1]))
        top_tech = [n for _, _, n in ranked[:MAX_TECH]]
        hot_tech = [n for hot, _, n in ranked if hot][:10]
        riasec = interests.get(code, {})
        holland = "".join(k for k, _ in sorted(riasec.items(), key=lambda kv: -kv[1])[:3])
        catalog.append(
            {
                **occ,
                "job_zone": zones.get(code, 3),
                "skills": top_skills,
                "knowledge": top_knowledge,
                "technology": top_tech,
                "hot_technology": hot_tech,
                "alt_titles": alt.get(code, []),
                "holland_code": holland,
                "interests": riasec,
                "related": [r for r in related.get(code, []) if r in occupations],
            }
        )
    catalog.sort(key=lambda o: o["id"])
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", default=Path("data/catalog/occupations.json"), type=Path)
    args = parser.parse_args()
    catalog = build(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
    print(f"Wrote {len(catalog)} occupations to {args.out}")


if __name__ == "__main__":
    main()
