"""RIASEC (Holland) interest inventory — 36 items, 6 per type.

Pure, offline, data-driven: items live in ``data/assessment_items.yaml`` (admins
can edit, deactivate or add items at runtime), scoring maps the 1–5 Likert
answers onto O*NET's 1–7 interest scale, and the resulting Holland code feeds the
matcher's interest term.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.migrations import migrate

ITEMS_PATH = Path(__file__).resolve().parent.parent / "data" / "assessment_items.yaml"
LOCALES = ("en", "ta", "hi")

DIMENSION_NAMES = {
    "R": "Realistic",
    "I": "Investigative",
    "A": "Artistic",
    "S": "Social",
    "E": "Enterprising",
    "C": "Conventional",
}

DIMENSION_BLURBS = {
    "R": "Doers — practical, hands-on, mechanical or outdoor work.",
    "I": "Thinkers — analysing, researching, understanding how things work.",
    "A": "Creators — design, writing, media and self-expression.",
    "S": "Helpers — teaching, care, counselling and service.",
    "E": "Persuaders — leading, selling, launching and negotiating.",
    "C": "Organisers — data, procedures, finance and accuracy.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Item:
    id: str
    dim: str
    text: str
    weight: float = 1.0
    locale: str = "en"
    active: bool = True

    def as_question(self) -> dict:
        return {"id": self.id, "dim": self.dim, "text": self.text}


@lru_cache(maxsize=4)
def load_items(locale: str = "en") -> tuple[Item, ...]:
    """All active items for a locale (English used when a translation is absent)."""
    raw = yaml.safe_load(ITEMS_PATH.read_text(encoding="utf-8")) or {}
    key = locale if locale in LOCALES else "en"
    items: list[Item] = []
    for entry in raw.get("items", []):
        text = entry.get(key) or entry.get("en") or ""
        if not text:
            continue
        items.append(
            Item(
                id=str(entry["id"]),
                dim=str(entry["dim"]).upper(),
                text=str(text),
                weight=float(entry.get("weight", 1.0)),
                locale=key,
            )
        )
    return tuple(items)


def questions(locale: str = "en", items: list[Item] | None = None) -> list[dict]:
    """The 36 statements the user rates."""
    pool = items if items is not None else list(load_items(locale))
    return [i.as_question() for i in pool if i.active]


def score(
    answers: dict[str, int],
    items: list[Item] | None = None,
    locale: str = "en",
    profiles: dict[str, float] | None = None,
) -> dict:
    """Score Likert answers (1–5) into per-dimension 1–7 scores + Holland code.

    ``profiles`` is an optional ``{item_id: {dim: weight}}`` table for weighted
    items (used when an admin gives an item more weight).
    """
    pool = items if items is not None else list(load_items(locale))
    totals: dict[str, list[float]] = {d: [] for d in DIMENSION_NAMES}
    for item in pool:
        value = answers.get(item.id)
        if not isinstance(value, (int, float)) or not 1 <= value <= 5:
            continue
        totals[item.dim].append(float(value) * item.weight)

    scored: dict[str, float] = {}
    for dim, values in totals.items():
        mean = sum(values) / len(values) if values else 3.0
        scored[dim] = round(1 + (mean - 1) * 1.5, 2)  # 1..5 → 1..7

    ordered = sorted(scored, key=lambda d: (-scored[d], d))
    code = "".join(ordered[:3])
    return {
        "scores": scored,
        "holland_code": code,
        "profile": [
            {
                "dim": dim,
                "name": DIMENSION_NAMES[dim],
                "score": scored[dim],
                "blurb": DIMENSION_BLURBS[dim],
            }
            for dim in ordered
        ],
        "answered": sum(len(v) for v in totals.values()),
        "total": len(pool),
    }


def top_careers(scores: dict[str, float], limit: int = 15, taxonomy=None) -> list[dict]:
    """Careers whose O*NET interest profile best matches the user's scores."""
    from career_guidance.matching2 import _cosine_positive
    from career_guidance.taxonomy import load_taxonomy

    taxonomy = taxonomy or load_taxonomy()
    user = {k.upper(): float(v) for k, v in scores.items()}
    if not user:
        return []
    ranked: list[tuple[float, object]] = []
    for occupation in taxonomy.occupations:
        if not occupation.interests:
            continue
        fit = _cosine_positive(user, occupation.interests)
        ranked.append((fit, occupation))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].title))
    return [
        {
            "id": occ.id,
            "title": occ.title,
            "fit": round(fit * 100, 1),
            "holland_code": occ.holland_code,
            "top_interests": sorted((k for k in occ.interests), key=lambda k: -occ.interests[k])[
                :3
            ],
        }
        for fit, occ in ranked[:limit]
    ]


class AssessmentStore:
    """Persist assessment runs so users can retake the test and compare history."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, user_id: str | None, answers: dict[str, int], result: dict) -> int:
        import json

        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO assessment_runs (user_id, created_at, answers_json, scores_json, "
                "holland_code) VALUES (?, ?, ?, ?, ?)",
                (
                    user_id,
                    _now(),
                    json.dumps(answers),
                    json.dumps(result["scores"]),
                    result["holland_code"],
                ),
            )
            return int(cur.lastrowid or 0)

    def history(self, user_id: str | None, limit: int = 20) -> list[dict]:
        import json

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assessment_runs WHERE user_id IS ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "holland_code": row["holland_code"],
                "scores": json.loads(row["scores_json"]),
            }
            for row in rows
        ]

    def latest(self, user_id: str | None) -> dict | None:
        runs = self.history(user_id, limit=1)
        return runs[0] if runs else None

    # ---- admin: editable items -------------------------------------------
    def item_overrides(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM assessment_items ORDER BY id")]

    def upsert_item(
        self, item_id: str, dim: str, text: str, weight: float = 1.0, active: bool = True
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO assessment_items (id, dim, text, locale, weight, active) "
                "VALUES (?, ?, ?, 'en', ?, ?) ON CONFLICT(id) DO UPDATE SET dim=excluded.dim, "
                "text=excluded.text, weight=excluded.weight, active=excluded.active",
                (item_id, dim.upper(), text, float(weight), int(active)),
            )

    def delete_item(self, item_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM assessment_items WHERE id = ?", (item_id,))

    def merged_items(self, locale: str = "en") -> list[Item]:
        """File items with admin overrides applied (text/weight/active)."""
        overrides = {row["id"]: row for row in self.item_overrides()}
        out: list[Item] = []
        for item in load_items(locale):
            row = overrides.pop(item.id, None)
            if row:
                out.append(
                    Item(
                        id=item.id,
                        dim=row["dim"],
                        text=row["text"] or item.text,
                        weight=float(row["weight"]),
                        locale=locale,
                        active=bool(row["active"]),
                    )
                )
            else:
                out.append(item)
        for row in overrides.values():  # admin-added items
            out.append(
                Item(
                    id=row["id"],
                    dim=row["dim"],
                    text=row["text"],
                    weight=float(row["weight"]),
                    locale=locale,
                    active=bool(row["active"]),
                )
            )
        return out
