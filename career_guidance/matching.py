"""Semantic career matching against the bundled taxonomy.

Combines four explainable signals per occupation:

* **Competency overlap** — user skills (canonicalised, and expanded through
  ``DOMAIN_HINTS`` into O*NET skill/knowledge elements) intersected with the
  occupation's core skills & knowledge, weighted by importance rank and IDF.
* **Technology overlap** — concrete tools (Python, AutoCAD, Tally…) found in the
  occupation's technology list, IDF-weighted so ubiquitous tools count less.
* **Semantic similarity** — TF-IDF cosine between the whole profile text
  (skills, goals, interests, resume) and the occupation document.
* **Interest & experience fit** — optional RIASEC profile, plus a soft penalty
  when the occupation's job zone is far from the user's experience level.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from career_guidance.profile import EXPERIENCE_LEVELS, CareerProfile
from career_guidance.taxonomy import (
    DOMAIN_HINTS,
    Occupation,
    Taxonomy,
    extract_skills,
    load_taxonomy,
    normalize_skill,
)

_ZONE_FOR_LEVEL = {
    EXPERIENCE_LEVELS[0]: 2.5,
    EXPERIENCE_LEVELS[1]: 3.0,
    EXPERIENCE_LEVELS[2]: 3.5,
    EXPERIENCE_LEVELS[3]: 4.0,
}

_SUITABILITY_FOR_LEVEL = {
    EXPERIENCE_LEVELS[0]: "beginner",
    EXPERIENCE_LEVELS[1]: "beginner",
    EXPERIENCE_LEVELS[2]: "intermediate",
    EXPERIENCE_LEVELS[3]: "advanced",
}

# Technology names that appear across hundreds of occupations and therefore
# say nothing about fit.
_NOISY_TECH = re.compile(
    r"(software$|^microsoft (access|project|windows|visio|sharepoint|dynamics)|^data entry|"
    r"^word processing|^linkedin$|^facebook$|^sap$|^intuit quickbooks|^ibm notes|^oracle peoplesoft|"  # noqa: E501
    r"^adobe acrobat|^email|^web browser|^google )",
    re.I,
)

_TOOL_HINT_SKILLS = {
    "programming",
    "excel",
    "autodesk autocad",
    "adobe photoshop",
    "adobe illustrator",
}


@dataclass(frozen=True)
class Match:
    """A scored occupation match with explainable components."""

    occupation: Occupation
    score: float
    competency: float
    technology: float
    semantic: float
    interest: float
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)


class Matcher:
    """Ranks taxonomy occupations for a career profile."""

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy
        n = len(taxonomy.occupations)

        docs = [occ.document() for occ in taxonomy.occupations]
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, sublinear_tf=True, stop_words="english"
        )
        self._matrix = self._vectorizer.fit_transform(docs)

        # Per-occupation competency weights: rank-decayed importance.
        self._comp: list[dict[str, float]] = []
        comp_df: Counter[str] = Counter()
        for occ in taxonomy.occupations:
            weights: dict[str, float] = {}
            for rank, name in enumerate(occ.skills):
                weights[name.lower()] = max(weights.get(name.lower(), 0), 1.0 - 0.06 * rank)
            for rank, name in enumerate(occ.knowledge):
                weights[name.lower()] = max(weights.get(name.lower(), 0), 1.0 - 0.08 * rank)
            self._comp.append(weights)
            comp_df.update(weights)
        self._comp_idf = {k: math.log((n + 1) / (v + 1)) + 1 for k, v in comp_df.items()}
        totals = sorted(sum(w * self._comp_idf[c] for c, w in comp.items()) for comp in self._comp)
        self._comp_floor = totals[len(totals) // 2] if totals else 1.0  # median richness

        # Per-occupation technology sets (canonicalised, noise removed).
        self._tech: list[set[str]] = []
        tech_df: Counter[str] = Counter()
        for occ in taxonomy.occupations:
            terms = {normalize_skill(t) for t in occ.technology if not _NOISY_TECH.search(t)}
            terms.discard("")
            self._tech.append(terms)
            tech_df.update(terms)
        self._tech_idf = {k: math.log((n + 1) / (v + 1)) + 1 for k, v in tech_df.items()}
        self._tech_max_idf = max(self._tech_idf.values(), default=1.0)

    # ------------------------------------------------------------------ #

    def user_terms(self, profile: CareerProfile) -> set[str]:
        """Canonical user skills from the skills box and resume."""
        terms = set(extract_skills(profile.skills)) | set(extract_skills(profile.resume_text))
        terms.discard("")
        return terms

    def rank(
        self,
        profile: CareerProfile,
        top_k: int = 5,
        interests: dict[str, float] | None = None,
        exclude_ids: set[str] | None = None,
    ) -> list[Match]:
        """Return the best ``top_k`` matches for the profile."""
        user = self.user_terms(profile)
        # Expand user skills into implied O*NET competencies.
        implied: dict[str, str] = {}  # competency (lower) -> user skill that implies it
        # `sorted` matters: set iteration order depends on the process hash seed,
        # and the *first* skill claiming a hint wins. Without it the same profile
        # scored differently between runs (coverage moved by ~0.3 in the golden
        # set, which flipped one case in and out of the top 5).
        for skill in sorted(user):
            for hint in DOMAIN_HINTS.get(skill, ()):
                implied.setdefault(hint.lower(), skill)

        profile_text = profile.to_prompt_text().lower()
        sims = cosine_similarity(self._vectorizer.transform([profile_text]), self._matrix)[0]
        # Direct title intent: goals/interests naming a career or its alt titles.
        goal_text = f"{profile.goals} {profile.interests}".lower()
        goal_ids = self._title_intent(goal_text)
        # Weaker intent from the skills box itself ("Android", "welding", "plumbing").
        skill_ids = self._title_intent(profile.skills.lower(), stem=True)
        target_zone = _ZONE_FOR_LEVEL.get(profile.experience_level, 3.0)
        has_signal = bool(user) or bool(interests)

        results: list[Match] = []
        for idx, occ in enumerate(self.taxonomy.occupations):
            if exclude_ids and occ.id in exclude_ids:
                continue

            # Competency overlap
            comp = self._comp[idx]
            comp_hits = [c for c in comp if c in implied or c in user]
            comp_gain = sum(comp[c] * self._comp_idf[c] for c in comp_hits)
            # Normalise against a fixed "rich profile" so thin occupations
            # (1-2 competencies) can't reach 1.0 with a single hit.
            comp_total = max(sum(w * self._comp_idf[c] for c, w in comp.items()), self._comp_floor)
            competency = min(1.0, comp_gain / comp_total)

            # Technology overlap
            tech = self._tech[idx]
            tech_hits = sorted(t for t in user if t in tech or self._fuzzy_in(t, tech))
            tech_gain = sum(self._tech_idf.get(t, self._tech_max_idf) for t in tech_hits)
            technology = 1 - math.exp(-tech_gain / 6.0)  # saturating

            interest = _cosine(interests, occ.interests) if interests and occ.interests else 0.0
            semantic = float(sims[idx])

            matched_user = {implied[c] for c in comp_hits if c in implied} | set(tech_hits)
            matched_user |= {c for c in comp_hits if c in user}
            coverage = len(matched_user) / len(user) if user else 0.0

            zone_factor = max(0.65, 1.0 - 0.09 * abs(occ.job_zone - target_zone))
            if not comp_hits:
                technology *= 0.5  # tools without any core competency are weak evidence
            base = (
                0.40 * competency
                + 0.20 * technology
                + 0.25 * coverage
                + 0.15 * min(1.0, semantic * 4)
            )
            if occ.id in goal_ids:
                base += 0.20 * goal_ids[occ.id]
            elif occ.id in skill_ids:
                base += 0.10 * skill_ids[occ.id]
            if interests:
                base = 0.85 * base + 0.15 * interest
            score = base * zone_factor
            if has_signal and not comp_hits and not tech_hits and semantic < 0.03:
                continue

            results.append(
                Match(
                    occupation=occ,
                    score=score,
                    competency=competency,
                    technology=technology,
                    semantic=semantic,
                    interest=interest,
                    matching_skills=self._display_matches(matched_user, comp_hits, tech_hits, occ),
                    missing_skills=self._missing(comp_hits, tech_hits, user, occ),
                )
            )
        results.sort(key=lambda m: m.score, reverse=True)
        return _dedupe_family(results)[:top_k]

    # ------------------------------------------------------------------ #

    def _title_intent(self, text: str, stem: bool = False) -> dict[str, float]:
        """Occupations whose title / alt titles appear in the text.

        With ``stem=True`` the text is also matched on crude word stems so that
        "welding" / "plumbing" reach "Welders" / "Plumbers".
        """
        text = re.sub(r"[^a-z0-9 ]+", " ", text)
        text = " " + re.sub(r"\s+", " ", text).strip() + " "
        if len(text.strip()) < 4:
            return {}
        hits: dict[str, float] = {}
        for alias, ids in ROLE_ALIASES.items():
            if f" {alias} " in text or (stem and f" {alias}" in text):
                for oid in ids:
                    hits[oid] = 1.0
        stems = {_stem(w) for w in text.split() if len(w) >= 5} if stem else set()
        for occ in self.taxonomy.occupations:
            if stems:
                head = occ.title.lower().split(",")[0]
                title_stems = {_stem(w) for w in re.findall(r"[a-z]+", head) if len(w) >= 5}
                if title_stems and title_stems <= stems:
                    hits[occ.id] = 0.7
                    continue
            title = re.sub(r"[^a-z0-9 ]+", " ", occ.title.lower())
            title = re.sub(r"\s+", " ", title).strip()
            if title and f" {title} " in text:
                hits[occ.id] = 1.0
                continue
            for alt in occ.alt_titles:
                a = re.sub(r"[^a-z0-9 ]+", " ", alt.lower()).strip()
                if len(a) >= 6 and f" {a} " in text:
                    hits[occ.id] = max(hits.get(occ.id, 0.0), 0.8)
                    break
            else:
                # Singular / plural tolerant head-noun match ("analyst" in "data analysts")
                for a in [title, *[x.lower() for x in occ.alt_titles[:5]]]:
                    a = re.sub(r"[^a-z0-9 ]+", " ", a).strip().rstrip("s")
                    if len(a) >= 8 and " " in a and a in text:
                        hits[occ.id] = max(hits.get(occ.id, 0.0), 0.6)
                        break
        return hits

    @staticmethod
    def _fuzzy_in(term: str, terms: set[str]) -> bool:
        if len(term) < 5:
            return False
        return any(term in t for t in terms if len(t) >= 5)

    def _display_matches(
        self, matched_user: set[str], comp_hits: list[str], tech_hits: list[str], occ: Occupation
    ) -> list[str]:
        """User-facing 'you already have' list: the user's own skills, in taxonomy casing."""
        labels: dict[str, None] = {}
        for term in sorted(matched_user):
            labels.setdefault(self.taxonomy.display_term(term), None)
        # Also surface the core competencies they satisfy (max 3) for context.
        core = [c for c in occ.skills + occ.knowledge if c.lower() in comp_hits][:3]
        for c in core:
            labels.setdefault(c, None)
        return list(labels)[:8]

    def _missing(
        self,
        comp_hits: list[str],
        tech_hits: list[str],
        user: set[str],
        occ: Occupation,
        limit: int = 8,
    ) -> list[str]:
        out: list[str] = []
        hit_set = set(comp_hits)
        for name in occ.skills[:6] + occ.knowledge[:4]:
            if name.lower() not in hit_set and name not in out:
                out.append(name)
        tech_pool = occ.hot_technology + [t for t in occ.technology if t not in occ.hot_technology]
        for raw in tech_pool:
            if _NOISY_TECH.search(raw):
                continue
            n = normalize_skill(raw)
            if n in user or any(len(u) >= 5 and u in n for u in user):
                continue
            if raw not in out:
                out.append(raw)
            if len(out) >= limit + 4:
                break
        return out[:limit]


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    # `sorted` keeps the floating-point sum reproducible: iterating a set gives
    # a hash-seed dependent order, which changed the last bits of the score and
    # made ties break differently between runs.
    keys = sorted(set(a) | set(b))
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


_FAMILY_RE = re.compile(r"^(\d{2}-\d{4})")


# Modern role names that O*NET 24 alt-titles do not cover well -> O*NET ids.
_SW_APPS, _SW_SYS, _PROG, _WEB = "15-1132.00", "15-1133.00", "15-1131.00", "15-1134.00"
_NETADMIN, _SYSENG, _INFOSEC = "15-1142.00", "15-1199.02", "15-1122.00"
ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "software engineer": (_SW_APPS, _SW_SYS, _PROG),
    "software developer": (_SW_APPS, _SW_SYS),
    "backend": (_SW_APPS, _PROG),
    "back end": (_SW_APPS, _PROG),
    "full stack": (_WEB, _SW_APPS),
    "fullstack": (_WEB, _SW_APPS),
    "frontend": (_WEB,),
    "front end": (_WEB,),
    "android": (_SW_APPS,),
    "kotlin": (_SW_APPS,),
    "flutter": (_SW_APPS,),
    "react native": (_SW_APPS,),
    "swift": (_SW_APPS,),
    "mobile app": (_SW_APPS,),
    "mobile developer": (_SW_APPS,),
    "spring boot": (_SW_APPS,),
    "django": (_WEB, _SW_APPS),
    "node": (_WEB, _SW_APPS),
    "devops": (_NETADMIN, _SYSENG, _SW_SYS),
    "site reliability": (_NETADMIN, _SYSENG),
    "kubernetes": (_NETADMIN, _SYSENG),
    "docker": (_SYSENG, _SW_SYS),
    "ci cd": (_SYSENG, _SW_SYS),
    "cloud engineer": (_SYSENG, "15-1143.00"),
    "aws": (_SYSENG, "15-1143.00"),
    "azure": (_SYSENG, "15-1143.00"),
    "cyber security": (_INFOSEC,),
    "cybersecurity": (_INFOSEC,),
    "penetration": (_INFOSEC,),
    "ethical hacking": (_INFOSEC,),
    "game develop": ("15-1199.11", _SW_APPS),
    "unity": ("15-1199.11", _SW_APPS),
    "unreal": ("15-1199.11", _SW_APPS),
    "data scientist": ("15-1111.00", "15-2041.00"),
    "machine learning": ("15-1111.00", "15-2041.00"),
    "data analyst": ("15-2041.00", "15-1199.08"),
    "data engineer": ("15-1199.07", "15-1141.00"),
    "product manager": ("11-2021.00", "15-1121.00"),
    "ui ux": ("27-1024.00", _WEB),
    "ux": ("27-1024.00", _WEB),
    "cabin crew": ("53-2031.00",),
    "air hostess": ("53-2031.00",),
    "event planning": ("13-1121.00",),
    "event manager": ("13-1121.00",),
    "sustainability": ("19-2041.00", "13-1199.05"),
    "gis": ("15-1199.05", "19-2041.00"),
}


def _stem(word: str) -> str:
    """Very small suffix stripper good enough for occupation head nouns."""
    for suf in ("ings", "ing", "ers", "ists", "ist", "ers", "er", "es", "s"):
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word


def _dedupe_family(matches: list[Match]) -> list[Match]:
    """Keep at most two occupations per 6-digit SOC family for variety."""
    seen: Counter[str] = Counter()
    out = []
    for m in matches:
        fam = _FAMILY_RE.match(m.occupation.id)
        key = fam.group(1) if fam else m.occupation.id
        if seen[key] >= 2:
            continue
        seen[key] += 1
        out.append(m)
    return out


def suitability_for(level: str) -> str:
    return _SUITABILITY_FOR_LEVEL.get(level, "beginner")


def prioritise_gaps(matches: list[Match], limit: int = 3) -> list[str]:
    """Rank missing skills by how many top matches need them, weighted by rank."""
    scores: Counter[str] = Counter()
    for rank, m in enumerate(matches):
        weight = 1.0 / (rank + 1)
        for pos, skill in enumerate(m.missing_skills[:6]):
            scores[skill] += weight * (1.0 - 0.1 * pos)
    return [s for s, _ in scores.most_common(limit)]


def transition_path(target: Occupation, taxonomy: Taxonomy, user_terms: set[str]) -> list[str]:
    """Suggest up to two stepping-stone occupations toward the target."""
    implied = {h.lower() for u in user_terms for h in DOMAIN_HINTS.get(u, ())}

    def overlap(occ: Occupation) -> int:
        comp = {c.lower() for c in occ.skills + occ.knowledge}
        return len(comp & implied)

    target_overlap = overlap(target)
    candidates = []
    for rid in target.related:
        occ = taxonomy.get(rid)
        if not occ or occ.job_zone >= target.job_zone:
            continue
        ov = overlap(occ)
        if ov >= max(1, target_overlap - 1):
            candidates.append((ov, occ.title))
    candidates.sort(reverse=True)
    return [title for _, title in candidates[:2]]


@lru_cache(maxsize=1)
def get_matcher() -> Matcher:
    """Shared matcher over the bundled taxonomy."""
    return Matcher(load_taxonomy())
