"""Skill normaliser v2 — synonyms, Indian-English variants, ta/hi transliterations.

The taxonomy's ``SKILL_SYNONYMS`` map already covers the common abbreviations.
This module adds a **data-driven** layer on top:

* ``data/skill_synonyms.yaml`` (offline seed, admin-editable at runtime through
  the ``synonyms`` table — DB entries win);
* **expansions**: a canonical skill can also count as several taxonomy terms
  ("tally" → ``accounting software`` + ``bookkeeping software``), which is how
  a user's tool name reaches the occupation that lists a software family;
* **unmatched logging**: every term the user typed that we could not map is
  written to the ``unmatched_skills`` table so admins can close the loop with
  one click (admin console → Skills & synonyms → “Unmatched skills users typed”).

Everything here is pure Python (no web framework, no network) and unit-tested.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from career_guidance.migrations import migrate
from career_guidance.taxonomy import SKILL_SYNONYMS, extract_skills, normalize_skill

logger = logging.getLogger("career_guidance.synonyms")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "skill_synonyms.yaml"
MIN_TERM_LENGTH = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SynonymEntry:
    canonical: str
    aliases: tuple[str, ...] = ()
    expands: tuple[str, ...] = ()


@dataclass
class Resolution:
    """Result of normalising a free-text skill box or résumé."""

    matched: list[str] = field(default_factory=list)
    """Canonical skills we could map."""

    unmatched: list[str] = field(default_factory=list)
    """Terms the user typed that we could not map (logged for the admin)."""

    expansions: list[str] = field(default_factory=list)
    """Every taxonomy term the matched canonicals stand for (used by the matcher)."""

    @property
    def coverage(self) -> float:
        total = len(self.matched) + len(self.unmatched)
        return len(self.matched) / total if total else 0.0


class SkillNormalizer:
    """Alias → canonical skill mapping with expansion + unmatched tracking."""

    def __init__(self, path: str | Path | None = None, entries: list[SynonymEntry] | None = None):
        self.path = str(path or DEFAULT_PATH)
        self._entries: dict[str, SynonymEntry] = {}
        self._alias_index: dict[str, str] = {}
        self._canonical_index: dict[str, str] = {}
        self._alias_re = None
        self._load_file(Path(self.path))
        if entries:
            self.add_entries(entries)

    # ------------------------------------------------------------------ load
    def _load_file(self, path: Path) -> None:
        if not path.exists():
            logger.warning("skill synonym file %s missing — using taxonomy synonyms only", path)
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for canonical, body in (raw.get("skills") or {}).items():
            body = body or {}
            self.add_entry(
                SynonymEntry(
                    canonical=str(canonical).strip().lower(),
                    aliases=tuple(str(a).strip().lower() for a in body.get("aliases", [])),
                    expands=tuple(str(e).strip().lower() for e in body.get("expands", [])),
                )
            )

    def add_entry(self, entry: SynonymEntry) -> None:
        # The authored canonical key is authoritative — it must NOT go through
        # taxonomy.normalize_skill(), which would rewrite e.g. "data analysis"
        # to "pandas" and lose the richer expansion.
        canonical = entry.canonical.strip().lower()
        existing = self._entries.get(canonical)
        if existing:  # merge (DB overrides file entries)
            aliases = tuple(dict.fromkeys([*existing.aliases, *entry.aliases]))
            expands = tuple(dict.fromkeys([*existing.expands, *entry.expands]))
            entry = SynonymEntry(canonical, aliases, expands)
        self._entries[canonical] = entry
        self._canonical_index[canonical] = canonical
        self._alias_index[canonical] = canonical
        for alias in entry.aliases:
            key = alias.strip().lower()
            if key and len(key) >= MIN_TERM_LENGTH:
                self._alias_index[key] = canonical
        self._alias_re = None  # invalidate the compiled matcher
        for term in entry.expands:
            key = normalize_skill(term) or term
            if key:
                self._canonical_index[key] = canonical

    def add_entries(self, entries: list[SynonymEntry]) -> None:
        for entry in entries:
            self.add_entry(entry)

    # -------------------------------------------------------------- lookups
    def normalize(self, raw: str) -> str | None:
        """Canonical skill for a single typed term (None when unknown)."""
        text = (raw or "").strip().lower()
        if not text or len(text) < MIN_TERM_LENGTH:
            return None
        if text in self._alias_index:
            return self._alias_index[text]
        cleaned = normalize_skill(text)
        if cleaned in self._alias_index:
            return self._alias_index[cleaned]
        if cleaned in self._canonical_index:
            return self._canonical_index[cleaned]
        # Suffix/prefix tolerant: "excel skills" already handled by normalize_skill;
        # try removing a trailing tool word ("tally software").
        trimmed = re.sub(r"\b(software|tool|tools|suite|erp|app|application)\b", "", cleaned)
        trimmed = re.sub(r"\s+", " ", trimmed).strip()
        if trimmed and trimmed in self._alias_index:
            return self._alias_index[trimmed]
        return None

    def expansions_for(self, canonical: str) -> list[str]:
        entry = self._entries.get(canonical)
        terms = [canonical, *(entry.expands if entry else ())]
        out: dict[str, None] = {}
        for term in terms:
            for variant in (term, normalize_skill(term)):
                if variant:
                    out.setdefault(variant, None)
        return list(out)

    def known_aliases(self) -> list[str]:
        return sorted(self._alias_index)

    def canonical_skills(self) -> list[str]:
        return sorted(self._entries)

    # -------------------------------------------------------------- resolve
    def _alias_matcher(self):
        """One compiled regex over every alias (longest first), like taxonomy does."""
        if self._alias_re is None:
            keys = sorted(
                (k for k in self._alias_index if len(k) >= MIN_TERM_LENGTH),
                key=len,
                reverse=True,
            )
            if keys:
                pattern = "|".join(re.escape(k) for k in keys)
                self._alias_re = re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.I)
            else:  # pragma: no cover - empty dictionary edge case
                self._alias_re = re.compile(r"(?!x)x")
        return self._alias_re

    def scan(self, text: str) -> list[tuple[str, str]]:
        """(alias, canonical) pairs found verbatim in the text.

        Runs *in addition to* the taxonomy extractor so that aliases the taxonomy
        maps differently ("data analysis", Tamil/Hindi spellings) keep their
        richer canonical + expansions.
        """
        if not text:
            return []
        out: list[tuple[str, str]] = []
        for match in self._alias_matcher().finditer(text.lower()):
            alias = match.group(0).strip()
            canonical = self._alias_index.get(alias)
            if canonical:
                out.append((alias, canonical))
        return out

    def resolve(self, text: str, resume_text: str = "") -> Resolution:
        """Normalise a skills box / résumé into canonicals + unmatched terms."""
        result = Resolution()
        seen_matched: dict[str, None] = {}
        seen_unmatched: dict[str, None] = {}
        seen_expansions: dict[str, None] = {}

        merged_text = f"{text}\n{resume_text}"
        for term in extract_skills(text) + extract_skills(resume_text):
            canonical = self.normalize(term)
            if canonical:
                seen_matched.setdefault(canonical, None)
            else:
                seen_unmatched.setdefault(term, None)
        # Direct alias hits in the raw text (native script, Indian-English words).
        for _alias, canonical in self.scan(merged_text):
            seen_matched.setdefault(canonical, None)
            seen_unmatched.pop(_alias, None)

        # Drop a canonical that is a strict substring of another match, so a user
        # sees "accounting software" instead of both "accounting" and "accounting software".
        canonicals = sorted(seen_matched, key=len)
        kept: list[str] = []
        for candidate in canonicals:
            if any(candidate != other and candidate in other for other in canonicals):
                continue
            kept.append(candidate)

        for canonical in kept:
            for expansion in self.expansions_for(canonical):
                seen_expansions.setdefault(expansion, None)
        for canonical in kept:
            if canonical in SKILL_SYNONYMS:
                seen_expansions.setdefault(canonical, None)

        result.matched = kept
        result.unmatched = [t for t in seen_unmatched if len(t) >= MIN_TERM_LENGTH]
        result.expansions = list(seen_expansions)
        return result

    def known(self, term: str) -> bool:
        return self.normalize(term) is not None


@lru_cache(maxsize=1)
def load_normalizer(path: str | None = None) -> SkillNormalizer:
    """Cached normaliser built from the bundled YAML."""
    normalizer = SkillNormalizer(path)
    logger.info(
        "Skill normaliser ready (%d canonicals, %d aliases)",
        len(normalizer.canonical_skills()),
        len(normalizer.known_aliases()),
    )
    return normalizer


# ---------------------------------------------------------------------------- #
# Runtime store: admin synonyms + unmatched-skill log                          #
# ---------------------------------------------------------------------------- #


class SynonymStore:
    """Admin-editable synonyms and the “unmatched skills” quality loop."""

    def __init__(self, path: str | Path, normalizer: SkillNormalizer | None = None) -> None:
        self._path = str(path)
        self._normalizer = normalizer or load_normalizer()
        migrate(self._path)

    @property
    def normalizer(self):
        """The alias→canonical engine this store writes into."""
        return self._normalizer

    def resolve(self, text: str, resume_text: str = ""):
        """Delegate to the normaliser (keeps callers on one object)."""
        return self._normalizer.resolve(text, resume_text)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- synonyms --------------------------------------------------------
    def all(self, q: str = "") -> list[dict]:
        sql = "SELECT * FROM synonyms"
        params: tuple = ()
        if q:
            sql += " WHERE alias LIKE ? OR canonical LIKE ?"
            params = (f"%{q}%", f"%{q}%")
        sql += " ORDER BY updated_at DESC LIMIT 500"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    def upsert(self, alias: str, canonical: str, locale: str = "en", actor: str = "admin") -> None:
        alias = alias.strip().lower()
        canonical = canonical.strip().lower()
        if not alias or not canonical:
            raise ValueError("alias and canonical are required")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO synonyms (alias, canonical, locale, source, updated_at, updated_by) "
                "VALUES (?, ?, ?, 'admin', ?, ?) ON CONFLICT(alias) DO UPDATE SET "
                "canonical=excluded.canonical, locale=excluded.locale, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (alias, canonical, locale, _now(), actor),
            )
        self._normalizer.add_entry(SynonymEntry(canonical=canonical, aliases=(alias,)))

    def delete(self, alias: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM synonyms WHERE alias = ?", (alias.strip().lower(),))

    def as_entries(self) -> list[SynonymEntry]:
        grouped: dict[str, list[str]] = {}
        locales: dict[str, list[str]] = {}
        with self._connect() as conn:
            for row in conn.execute("SELECT alias, canonical, locale FROM synonyms"):
                grouped.setdefault(row["canonical"], []).append(row["alias"])
                if row["locale"] and row["locale"] != "en":
                    locales.setdefault(row["canonical"], []).append(row["locale"])
        return [
            SynonymEntry(canonical=c, aliases=tuple(a), expands=(c,)) for c, a in grouped.items()
        ]

    # ---- unmatched skills ------------------------------------------------
    def log_unmatched(self, terms: list[str]) -> None:
        """Increment counters for the terms we could not map."""
        clean = [t.strip().lower() for t in terms if t and t.strip()]
        if not clean:
            return
        now = _now()
        with self._connect() as conn:
            for term in dict.fromkeys(clean):
                conn.execute(
                    "INSERT INTO unmatched_skills (term, count, first_seen, last_seen) "
                    "VALUES (?, 1, ?, ?) ON CONFLICT(term) DO UPDATE SET "
                    "count = count + 1, last_seen = excluded.last_seen",
                    (term, now, now),
                )

    def unmatched(self, limit: int = 100, include_mapped: bool = False) -> list[dict]:
        sql = "SELECT * FROM unmatched_skills"
        if not include_mapped:
            sql += " WHERE mapped_to = ''"
        sql += " ORDER BY count DESC, last_seen DESC LIMIT ?"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (limit,))]

    def map_unmatched(self, term: str, canonical: str, actor: str = "admin") -> None:
        """One-click “map to …”: creates a synonym and marks the term handled."""
        term = term.strip().lower()
        canonical = canonical.strip().lower()
        self.upsert(term, canonical, actor=actor)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO unmatched_skills (term, count, first_seen, last_seen, mapped_to) "
                "VALUES (?, 0, ?, ?, ?) ON CONFLICT(term) DO UPDATE SET mapped_to = excluded.mapped_to",  # noqa: E501
                (term, _now(), _now(), canonical),
            )

    def dismiss_unmatched(self, term: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM unmatched_skills WHERE term = ?", (term.strip().lower(),))

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) n FROM unmatched_skills WHERE mapped_to = ''"
            ).fetchone()["n"]  # noqa: E501
            mapped = conn.execute(
                "SELECT COUNT(*) n FROM unmatched_skills WHERE mapped_to != ''"
            ).fetchone()["n"]  # noqa: E501
            synonyms = conn.execute("SELECT COUNT(*) n FROM synonyms").fetchone()["n"]
        return {"open": int(total), "mapped": int(mapped), "admin_synonyms": int(synonyms)}
