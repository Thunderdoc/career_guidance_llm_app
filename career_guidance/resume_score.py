"""Résumé scorer v2 — rule-based, explainable, no LLM.

Six signals, each with its own weight (total 100):

======================  ======  ================================================
signal                  weight  how it is measured
======================  ======  ================================================
keyword coverage          40    canonical skills from the text vs the target
                                 occupation's core skills (IDF-weighted)
action verbs              15    presence of strong verbs (built/led/designed…)
quantified impact         15    share of bullet points containing a number or %
sections                   10    education / experience / skills / projects blocks
experience vs job zone     10    detected years of experience vs the O*NET zone
length & readability       10    bullets, words per bullet, no wall of text
======================  ======  ================================================

The result lists the **missing keywords**, suggests **bullet rewrites** from
templates and reports the detected sections — all with a source label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from career_guidance.taxonomy import Occupation, extract_skills, load_taxonomy, normalize_skill

SOURCE = "Source: rule-based résumé analysis (keywords from the O*NET catalog)"

WEIGHTS = {
    "keywords": 40,
    "verbs": 15,
    "impact": 15,
    "sections": 10,
    "experience": 10,
    "readability": 10,
}

ACTION_VERBS = {
    "achieved",
    "analysed",
    "analyzed",
    "automated",
    "built",
    "coached",
    "collaborated",
    "completed",
    "conducted",
    "configured",
    "created",
    "delivered",
    "deployed",
    "designed",
    "developed",
    "diagnosed",
    "documented",
    "drove",
    "engineered",
    "established",
    "expanded",
    "implemented",
    "improved",
    "increased",
    "initiated",
    "installed",
    "introduced",
    "launched",
    "led",
    "managed",
    "measured",
    "migrated",
    "mentored",
    "modelled",
    "modeled",
    "negotiated",
    "optimised",
    "optimized",
    "organised",
    "organized",
    "planned",
    "prepared",
    "presented",
    "produced",
    "published",
    "reduced",
    "resolved",
    "reviewed",
    "scaled",
    "simplified",
    "streamlined",
    "supervised",
    "supported",
    "trained",
    "validated",
    "wrote",
}

WEAK_PHRASES = {
    "responsible for": "Replace “responsible for” with the verb you actually did (managed, built, reviewed).",  # noqa: E501
    "worked on": "Say what you delivered, not what you “worked on” (e.g. “built the weekly dashboard”).",  # noqa: E501
    "helped with": "Name your own contribution (e.g. “automated the report, saving 6 hours/week”).",
    "duties included": "Lead with outcomes, not duties.",
    "team player": "Show teamwork with an example instead of the phrase.",
}

SECTION_PATTERNS = {
    "Contact": r"(?i)\b([\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{8,})\b",
    "Summary": r"(?im)^\s*(summary|objective|profile|about me)\b",
    "Experience": r"(?im)^\s*(experience|work experience|employment|professional experience)\b",
    "Education": r"(?im)^\s*(education|qualification|academics|academic background)\b",
    "Skills": r"(?im)^\s*(skills|technical skills|core competencies|technologies)\b",
    "Projects": r"(?im)^\s*(projects|portfolio)\b",
    "Certifications": r"(?im)^\s*(certifications?|courses?|training)\b",
}

_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I)
_DATE_RANGE = re.compile(
    r"\b(19|20)\d{2}\s*[-–—to]+\s*((19|20)\d{2}|present|current|till date)\b", re.I
)
_BULLET = re.compile(r"^[\s]*[-•*·▪‣–]\s+", re.M)
_NUMBERISH = re.compile(
    r"(\d+[\d,.]*\s*(%|percent|k\b|lakh|lpa|cr\b|million|hours?|days?|users?|clients?|customers?|projects?|people|students?|₹|\$)?)",
    re.I,
)  # noqa: E501


@dataclass
class Section:
    name: str
    found: bool


@dataclass
class Rewrite:
    original: str
    suggestion: str
    reason: str

    def to_dict(self) -> dict:
        return {"original": self.original, "suggestion": self.suggestion, "reason": self.reason}


@dataclass
class ResumeScore:
    score: float = 0.0
    grade: str = "Needs work"
    target: Occupation | None = None
    parts: dict[str, float] = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    coverage: float = 0.0
    verbs: list[str] = field(default_factory=list)
    bullets: int = 0
    quantified: int = 0
    quantified_examples: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    detected_years: float = 0.0
    job_zone_fit: float = 0.0
    rewrites: list[Rewrite] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "target_career": (
                {"id": self.target.id, "title": self.target.title} if self.target else None
            ),
            "score_parts": {k: round(v, 1) for k, v in self.parts.items()},
            "keyword_coverage": {
                "matched": self.matched,
                "missing": self.missing,
                "percent": round(self.coverage, 1),
            },
            "action_verbs": {
                "found": self.verbs,
                "percent": round(self.parts.get("verbs", 0) / WEIGHTS["verbs"] * 100, 1),
            },  # noqa: E501
            "quantified_impact": {
                "bullets": self.bullets,
                "quantified": self.quantified,
                "percent": round(self.quantified / self.bullets * 100, 1) if self.bullets else 0.0,
                "examples": self.quantified_examples,
            },
            "sections": [{"name": s.name, "found": s.found} for s in self.sections],
            "detected_years": self.detected_years,
            "job_zone_fit": round(self.job_zone_fit, 1),
            "missing_keywords": self.missing[:15],
            "rewrites": [r.to_dict() for r in self.rewrites],
            "source": SOURCE,
        }


def grade_for(score: float) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 55:
        return "Fair"
    return "Needs work"


def detect_sections(text: str) -> list[Section]:
    return [
        Section(name=name, found=bool(re.search(pattern, text)))
        for name, pattern in SECTION_PATTERNS.items()
    ]  # noqa: E501


def detect_years(text: str) -> float:
    """Years of experience: explicit “5 years” wins, else date ranges are summed."""
    explicit = [float(m.group(1)) for m in _YEARS.finditer(text)]
    if explicit:
        return max(explicit)
    spans = []
    for match in _DATE_RANGE.finditer(text):
        start = int(match.group(0)[:4])
        end_raw = match.group(2).lower()
        end = 2026 if end_raw in {"present", "current", "till date"} else int(end_raw)
        if 1980 <= start <= end <= 2035:
            spans.append(end - start)
    return float(min(sum(spans), 40)) if spans else 0.0


def bullet_lines(text: str) -> list[str]:
    bullets = [line.strip() for line in _BULLET.findall(text)] if False else []
    for line in text.splitlines():
        if _BULLET.match(line):
            bullets.append(_BULLET.sub("", line).strip())
    if bullets:
        return bullets
    # No bullet characters: treat long sentences as bullets.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]
    return sentences


def _zone_target(years: float) -> float:
    if years >= 8:
        return 4.8
    if years >= 5:
        return 4.2
    if years >= 2:
        return 3.6
    if years >= 1:
        return 3.0
    return 2.5


def score(
    resume_text: str,
    career_id: str | None = None,
    extra_skills: str = "",
    taxonomy=None,
) -> ResumeScore:
    """Score ``resume_text`` (optionally against a target occupation)."""
    taxonomy = taxonomy or load_taxonomy()
    target = taxonomy.get(career_id) if career_id else None
    text = resume_text or ""
    lowered = text.lower()

    detected = {s for s in extract_skills(text) if s}
    if extra_skills:
        detected |= set(extract_skills(extra_skills))
    # Synonym expansion: "excel" also counts as "spreadsheet software", "tally" as
    # "accounting software", Tamil/Hindi spellings as their English canonical.
    detected_expanded = _expand_skills(detected)

    result = ResumeScore(target=target)

    # --- 1. keyword coverage -------------------------------------------------
    if target is not None:
        wanted = target_terms(target)
        detected_norm = {normalize_skill(term) or term for term in detected} | detected_expanded
        matched = [name for name in wanted if _term_present(name, lowered, detected_norm)]
        missing = [name for name in wanted if name not in matched]
        total_weight = sum(wanted.values()) or 1.0
        coverage = sum(wanted[name] for name in matched) / total_weight
        result.matched, result.missing, result.coverage = matched, missing, coverage * 100
        result.parts["keywords"] = coverage * WEIGHTS["keywords"]
    else:
        result.coverage, result.parts["keywords"] = 0.0, WEIGHTS["keywords"] * 0.6

    # --- 2. action verbs -----------------------------------------------------
    words = set(re.findall(r"[a-z]+", lowered))
    verbs = sorted(words & ACTION_VERBS)
    result.verbs = verbs
    result.parts["verbs"] = min(1.0, len(verbs) / 8) * WEIGHTS["verbs"]

    # --- 3. quantified impact ------------------------------------------------
    bullets = bullet_lines(text)
    result.bullets = len(bullets)
    quantified = [b for b in bullets if _NUMBERISH.search(b)]
    result.quantified = len(quantified)
    result.quantified_examples = quantified[:3]
    share = len(quantified) / len(bullets) if bullets else 0.0
    result.parts["impact"] = min(1.0, share / 0.4) * WEIGHTS["impact"]

    # --- 4. sections ---------------------------------------------------------
    result.sections = detect_sections(text)
    found = sum(1 for s in result.sections if s.found)
    result.parts["sections"] = min(1.0, found / 5) * WEIGHTS["sections"]

    # --- 5. experience vs job zone ------------------------------------------
    years = detect_years(text)
    result.detected_years = years
    if target is not None:
        gap = abs(_zone_target(years) - target.job_zone)
        result.job_zone_fit = max(0.0, 100 - gap * 25)
        result.parts["experience"] = max(0.0, 1 - gap / 4) * WEIGHTS["experience"]
    else:
        result.job_zone_fit = 50.0
        result.parts["experience"] = WEIGHTS["experience"] * 0.5

    # --- 6. readability ------------------------------------------------------
    word_count = len(re.findall(r"[A-Za-z]+", text))
    avg_bullet = (word_count / len(bullets)) if bullets else float(word_count)
    ideal = 12 <= avg_bullet <= 30
    result.parts["readability"] = WEIGHTS["readability"] * (
        1.0 if ideal else 0.6 if bullets else 0.3
    )

    result.score = sum(result.parts.values())
    result.grade = grade_for(result.score)
    result.rewrites = suggest_rewrites(text, bullets, result.missing)
    return result


def target_terms(occupation: Occupation, max_terms: int = 18) -> dict[str, float]:
    """Weighted keyword list for a target occupation.

    Delegates to :mod:`career_guidance.keywords`, which ranks the catalog's
    alphabetically-stored tool lists into “curated, widely used, explainable”
    tools instead of ABAP/AJAX/Acrobat noise.
    """
    from career_guidance.keywords import target_terms as _ranked

    return _ranked(occupation, max_terms)


def _expand_skills(detected: set[str]) -> set[str]:
    """Expand detected skills with their canonical name and known aliases.

    ``excel`` → ``spreadsheet software`` → ``microsoft excel`` … so a résumé
    written with a local tool name satisfies the target occupation's keyword
    list, and vice-versa.  Never raises: unknown terms are returned as-is.
    """
    if not detected:
        return set()
    try:
        from career_guidance.synonyms import load_normalizer
    except Exception:  # pragma: no cover - defensive
        return set()
    try:
        normalizer = load_normalizer()
    except Exception:  # pragma: no cover - defensive
        return set()
    out: set[str] = set()
    for raw in detected:
        if not raw:
            continue
        canonical = normalizer.normalize(raw)
        if not canonical:
            continue
        out.add(canonical.lower())
        try:
            out.update(a.lower() for a in normalizer.expansions_for(canonical) if a)
        except Exception:  # pragma: no cover - defensive
            continue
    return out


def _term_present(term: str, lowered_text: str, detected_norm: set[str]) -> bool:
    """True when a target keyword appears in the résumé (canonical or verbatim)."""
    normalized = (normalize_skill(term) or term.lower()).strip()
    if normalized and normalized in detected_norm:
        return True
    if term.lower() in lowered_text:
        return True
    if len(normalized) >= 4 and normalized in lowered_text:
        return True
    # Fuzzy / synonym: "excel" satisfies "spreadsheet software", "sql server"
    # satisfies "sql", "data analysis" satisfies "analyzing data".
    return any(len(d) >= 4 and (d in normalized or normalized in d) for d in detected_norm if d)


def suggest_rewrites(
    text: str, bullets: list[str], missing: list[str], limit: int = 4
) -> list[Rewrite]:
    """Template-based bullet suggestions (weak phrasing, missing numbers, gaps)."""
    out: list[Rewrite] = []
    lowered = text.lower()
    for phrase, reason in WEAK_PHRASES.items():
        if phrase in lowered:
            out.append(Rewrite(original=phrase, suggestion=_stronger(phrase), reason=reason))
        if len(out) >= limit:
            return out
    for bullet in bullets:
        if not _NUMBERISH.search(bullet):
            out.append(
                Rewrite(
                    original=bullet[:140],
                    suggestion=_add_number(bullet),
                    reason="Add a measurable result (%, ₹, hours saved, users) so the impact is checkable.",  # noqa: E501
                )
            )
        if len(out) >= limit:
            return out
    if missing:
        out.append(
            Rewrite(
                original="(skills section)",
                suggestion=f"Add a line for {', '.join(missing[:3])} if you have used them.",
                reason="These are the target occupation's core skills and they never appear in your résumé.",  # noqa: E501
            )
        )
    return out[:limit]


def _stronger(phrase: str) -> str:
    mapping = {
        "responsible for": "Owned …",
        "worked on": "Delivered …",
        "helped with": "Built / ran …",
        "duties included": "Led …",
        "team player": "Collaborated with … to … (add the outcome)",
    }
    return mapping.get(phrase, phrase.title())


def _add_number(bullet: str) -> str:
    clean = bullet.strip().rstrip(".")
    return f"{clean} — cutting turnaround time by 30% (replace with your real number)."
