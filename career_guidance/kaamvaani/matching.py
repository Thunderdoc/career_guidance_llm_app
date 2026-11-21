"""Kaam-Vaani matching (Stage 4): filters + scoring over MatcherV2.

Why this module exists: the Stage 3 demo showed the base matcher
failing Kaam-Vaani profiles — a farming/computer 12th-pass profile
from Madurai needing ₹15,000/month got teacher roles at 7–8% match
with "0 of 8 core skills". The base ranker (``matching2.MatcherV2``)
scores skills-only with a zone tiebreak, and a trade user's canonical
skills ("agricultural science", "attention to detail") have no
``DOMAIN_HINTS`` entries, so the tiny skills signal lets the zone
tiebreak crown unrelated zone-4 roles.

The Kaam-Vaani scorer re-ranks every occupation with five honest
signals (weights measured against five probe profiles — a farming /
computer demo, an electrician, a tailor, a bus driver, and a
high-income computer profile — see ``docs/KAAM_VAANI_PLAN.md`` Stage 4).
The weights and zone rules live in ``data/kv_ranker_weights.yaml``
and are combined + ordered by the separate :mod:`ranker` component
(Step 8.1: ``RankerConfig`` + ``MultiCriteriaRanker`` with an
injectable comparator) — this module keeps only the domain feature
computation. The refactor is score-identical: the pre-refactor top-5
for the five probe profiles is reproduced exactly (see
``tests/test_kv_step8_1.py``).

* **skill overlap (0.30)** — IDF-weighted overlap between the user's
  competencies (canonical skills mapped to O*NET competencies through
  ``KV_MAP``) and the occupation's core competencies (top 6 skills +
  top 4 knowledge). IDF stops generic competencies ("quality control
  analysis", "clerical") from crowning unrelated roles; a median
  floor stops short cores from winning on one generic hit.
* **title match (0.40)** — the strongest signal for trade users, who
  name the work they do. Phrases from the user's canonical skills,
  their YAML aliases (full-phrase AND semantics: "data entry" must
  match both words) and the transcript's content words, matched
  against the occupation title with the RAG title matcher (stemmed,
  compound-aware). Score = matched title words / title words for the
  best phrase. Single-word phrases come from canonical names and the
  transcript only — never from alias words, whose single words lie
  ("garment construction" is a fashion-design alias, not a
  construction trade).
* **base matcher (0.10)** — the MatcherV2 score, kept as a tiebreak
  signal; it is 0 for most Kaam-Vaani profiles (their terms have no
  DOMAIN_HINTS), which is fine — it only helps where it has signal.
* **zone fit (0.10)** — ``matching2.zone_fit`` against the target
  zone from the user's education. A hard filter excludes occupations
  more than one zone above the target (a 12th-pass user never sees
  zone-5 roles), and a zone-gap penalty (15% per zone above target,
  capped at 50%) demotes aspirational roles below fitting ones.
* **income fit (0.10)** — the user's monthly need annualised against
  the market seed's band for the occupation: 1.0 when the band's p50
  meets the need, 0.7 when only p75 does, 0.4 otherwise. The seed is
  curated estimates (labelled as such — see ``ASSUMPTIONS.md`` A9), so
  the fit is a coarse gate, never a wage promise.

Filters the spec names that have NO data to filter on (see
``LIMITATIONS.md``): **location radius** — no occupation carries a
location until Stage 5 employer listings exist, so the city is
recorded and shown but cannot filter; **shift/availability** — the
guided flow does not ask it and no occupation carries shift data;
**language** — no occupation carries a language requirement (the
session language drives the UI/TTS language instead). These are
documented, not faked.

Matches are suggestions, never job guarantees — the UI says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.rag import _title_term_matches, tokenize
from career_guidance.kaamvaani.ranker import (
    Comparator,
    MultiCriteriaRanker,
    RankerConfig,
    ScoredItem,
    load_ranker_config,
)
from career_guidance.learning import resources_for_gaps
from career_guidance.market_seed import MarketSeed, build_adapter
from career_guidance.matching2 import MatcherV2, education_zone, get_matcher_v2, zone_fit
from career_guidance.profile import CareerProfile
from career_guidance.skillgap import evaluate as evaluate_readiness
from career_guidance.synonyms import SkillNormalizer, load_normalizer
from career_guidance.taxonomy import Occupation, Taxonomy, load_taxonomy

# Scoring weights + zone rules live in data/kv_ranker_weights.yaml,
# loaded through ranker.RankerConfig (Step 8.1) — no hard-coded
# weights in this module. The measured values are unchanged from
# Stage 4 (skill 0.30, title 0.40, base 0.10, zone 0.10, income 0.10;
# zone filter slack 1.0; gap penalty 0.15/zone capped at 0.50).

# Canonical skill -> O*NET competencies it stands for. Tight on purpose:
# the full YAML ``expands`` list is too broad (it turned a farming /
# computer profile into Plumbers #1 — generic expansions match hundreds
# of occupations). A canonical with no entry falls back to its own name
# as a single competency term.
KV_MAP: dict[str, tuple[str, ...]] = {
    "agricultural science": ("food production", "biology"),
    "attention to detail": ("clerical", "quality control analysis"),
    "computer literacy": ("computers and electronics", "word processing software"),
    "electrical technician": (
        "repairing",
        "installation",
        "equipment maintenance",
        "operation monitoring",
    ),
    "welding": ("welding", "repairing", "equipment maintenance"),
    "plumbing": ("installation", "repairing", "building and construction"),
    "automotive": ("mechanical", "repairing", "troubleshooting"),
    "carpentry": ("building and construction", "repairing"),
    "masonry": ("building and construction", "operation and control"),
    "construction": ("building and construction",),
    "fashion design": ("production and processing", "design"),
    "hairdressing": ("customer and personal service",),
    "hospitality": ("customer and personal service", "food production"),
    "security services": ("public safety and security",),
    "teaching": ("education and training", "instructing"),
    "nursing": ("medicine and dentistry",),
    "sales": ("sales and marketing", "persuasion"),
    "customer service": ("customer and personal service",),
    "accounting": ("economics and accounting", "clerical"),
}

# Words that carry no title signal (generic query filler). Dropped from
# title phrases so "I need a job" does not match job titles.
TITLE_FILLER: frozenset[str] = frozenset(
    {
        "job",
        "need",
        "month",
        "pass",
        "rupee",
        "want",
        "earn",
        "live",
        "know",
        "like",
        "get",
        "work",
        "basic",
        "per",
        "good",
        "please",
        "help",
        "find",
        "near",
        "home",
        "money",
        "salary",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "have",
        "has",
        "had",
        "will",
        "would",
        "can",
        "could",
        "year",
        "day",
        "week",
        "hour",
        "time",
        "much",
        "many",
        "some",
        "very",
        "also",
        "just",
        "about",
        "into",
        "over",
        "after",
        "before",
    }
)


def expand_competencies(skills: list[str]) -> set[str]:
    """A user's canonical skills as O*NET competency names (lowercase).

    Mapped skills expand through :data:`KV_MAP`; an unmapped canonical
    falls back to its own name (which matches when an occupation lists
    that competency verbatim, e.g. "computer programming")."""
    expanded: set[str] = set()
    for skill in skills:
        key = skill.strip().lower()
        if not key:
            continue
        if key in KV_MAP:
            expanded.update(KV_MAP[key])
        else:
            expanded.add(key)
    return expanded


def core_competencies(occupation: Occupation) -> list[str]:
    """The occupation's core competencies in importance order: its top
    6 skills + top 4 knowledge areas (lowercase, de-duplicated)."""
    seen: dict[str, None] = {}
    for name in list(occupation.skills[:6]) + list(occupation.knowledge[:4]):
        seen.setdefault(name.lower(), None)
    return list(seen)


def word_variants(word: str) -> set[str]:
    """A word plus its -ing-stripped variants: "farming" also matches
    "farm" / "farme", so the user saying "farming" reaches Farmworkers."""
    out = {word}
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        out.add(base)
        if len(base) >= 3:
            out.add(base + "e")
    return out


def phrase_variant_sets(phrase: str) -> list[set[str]]:
    """One variant-set per content word of ``phrase``: a phrase matches
    a title only when EVERY word has a variant matching some title word
    (AND semantics — "data entry" needs both "data" and "entry")."""
    words = [
        w for w in tokenize(phrase) if w not in TITLE_FILLER and not any(c.isdigit() for c in w)
    ]
    return [word_variants(w) for w in words]


def title_purity(title: str, phrases: list[list[set[str]]]) -> float:
    """Best phrase's share of the title's words (0..1).

    Title words are stemmed through the shared ``tokenize`` (so
    "Electricians" matches "electrician"); matching reuses the RAG
    title matcher (compound-aware: "farmworker" matches "farm").
    Purity — not coverage — is the right shape for a bag-of-words
    query: it asks "how much of this job's name is about what the
    user said", without punishing the user for saying more words."""
    title_terms = tokenize(title)
    if not title_terms:
        return 0.0
    best = 0.0
    for phrase in phrases:
        if not phrase:
            continue
        matched_terms: set[str] = set()
        for variant_set in phrase:
            hits = {t for t in title_terms if any(_title_term_matches(t, q) for q in variant_set)}
            if not hits:
                break
            matched_terms |= hits
        else:
            best = max(best, len(matched_terms) / len(title_terms))
    return best


def income_fit(occupation: Occupation, need_monthly: int | None, seed: MarketSeed) -> float:
    """Can this occupation plausibly pay the user's monthly need?

    1.0 when the seed band's p50 meets the annualised need, 0.7 when
    only p75 does, 0.4 otherwise. 1.0 when no need is stated or the
    occupation has no band — no data must never punish a match. The
    seed is curated estimates, so this is a coarse gate, never a wage
    promise (see ASSUMPTIONS.md A9)."""
    if need_monthly is None:
        return 1.0
    snap = seed.snapshot(occupation, "in")
    need_annual = need_monthly * 12
    p50, p75 = snap.salary_p50, snap.salary_p75
    if p50 is None:
        return 1.0
    if p50 >= need_annual:
        return 1.0
    if p75 is not None and p75 >= need_annual:
        return 0.7
    return 0.4


@dataclass
class KVMatch:
    """One Kaam-Vaani match: the occupation, the score with its
    components (so the UI can say WHY it fits), and the skill gap
    (matched vs missing core competencies, importance order).
    ``components`` are the raw feature values (0..1);
    ``contributions`` are the ranker's per-feature contributions
    (weight x value, Step 8.1) — they sum to the pre-penalty score,
    so ``score == sum(contributions) x zone-penalty-factor``."""

    occupation: Occupation
    score: float
    components: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def match_percent(self) -> float:
        return round(self.score * 100, 1)

    def reasons(self) -> list[dict]:
        """Structured why-it-fits reasons for the frontend, which
        composes the sentence in the user's language (EN/HI/TA) from
        its i18n templates — the backend never writes prose in a
        language it cannot verify."""
        out: list[dict] = []
        if self.matched:
            out.append({"kind": "skill", "skills": self.matched})
        if self.components.get("title", 0.0) > 0:
            out.append({"kind": "title"})
        if self.components.get("income", 0.0) >= 1.0:
            out.append({"kind": "income"})
        if self.components.get("zone", 0.0) >= 0.9:
            out.append({"kind": "zone"})
        return out

    def to_dict(self) -> dict:
        return {
            "career_id": self.occupation.id,
            "title": self.occupation.title,
            "description": self.occupation.description,
            "job_zone": self.occupation.job_zone,
            "score": round(self.score, 4),
            "match_percent": self.match_percent,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "matched_skills": self.matched,
            "missing_skills": self.missing,
            "reasons": self.reasons(),
            "income_fit": self.components.get("income", 1.0),
            "zone_fit": self.components.get("zone", 1.0),
        }


class KVScorer:
    """The Kaam-Vaani scorer: IDF-weighted skill overlap + phrase title
    match + base matcher + zone + income, over the full taxonomy.

    Built once per router (taxonomy, matcher, seed and normalizer are
    cached singletons; the IDF table is computed at init). Feature
    combination and ordering delegate to the separate ranker
    (Step 8.1): ``config`` loads ``data/kv_ranker_weights.yaml`` by
    default, and ``comparator`` replaces the default order (score
    descending, title ascending) when a caller needs a different one.
    """

    def __init__(
        self,
        taxonomy: Taxonomy | None = None,
        matcher: MatcherV2 | None = None,
        seed: MarketSeed | None = None,
        normalizer: SkillNormalizer | None = None,
        config: RankerConfig | None = None,
        comparator: Comparator | None = None,
    ) -> None:
        self.taxonomy = taxonomy or load_taxonomy()
        self.matcher = matcher or get_matcher_v2()
        self.seed = seed or build_adapter().seed
        self.normalizer = normalizer or load_normalizer()
        self.config = config or load_ranker_config()
        self.ranker = MultiCriteriaRanker(self.config, comparator=comparator)
        occupations = self.taxonomy.occupations
        count = len(occupations)
        self._core = {o.id: core_competencies(o) for o in occupations}
        doc_freq: dict[str, int] = {}
        for core in self._core.values():
            for competency in set(core):
                doc_freq[competency] = doc_freq.get(competency, 0) + 1
        self._idf = {
            competency: math.log((count + 1) / (freq + 1)) + 1
            for competency, freq in doc_freq.items()
        }
        totals = sorted(sum(self._idf[c] for c in core) for core in self._core.values())
        # Median floor: a short core must not win on one generic hit.
        self._median_total = totals[len(totals) // 2] if totals else 1.0

    # ------------------------------------------------------------ phrases
    def phrases_for(self, profile: VoiceProfile) -> list[list[set[str]]]:
        """Title-match phrases for a profile: each canonical skill as a
        full phrase AND as single words, each alias as a full phrase
        only (alias single words lie — see module docstring), and each
        transcript content word alone (catches "farm" from "farming",
        "bus" from "I drive a bus")."""
        phrases: list[list[set[str]]] = []
        for skill in profile.skills:
            phrases.append(phrase_variant_sets(skill))
            for word in tokenize(skill):
                if word not in TITLE_FILLER and not any(c.isdigit() for c in word):
                    phrases.append([word_variants(word)])
            for alias in self.normalizer.aliases_for(skill):
                phrases.append(phrase_variant_sets(alias))
        for word in tokenize(f"{profile.interests} {profile.raw_text}"):
            if word not in TITLE_FILLER and not any(c.isdigit() for c in word):
                phrases.append([word_variants(word)])
        return [p for p in phrases if p]

    # ------------------------------------------------------------ scoring
    def _base_scores(self, profile: VoiceProfile) -> dict[str, float]:
        """MatcherV2 scores for the profile (0 when it has no signal —
        most Kaam-Vaani profiles)."""
        career_profile = CareerProfile(
            skills=", ".join(profile.skills) if profile.skills else profile.raw_text,
            interests=profile.interests,
            education=profile.education,
            experience_level="Student / No experience",
            # Goals only — the income is scored by the dedicated
            # income-fit component (need_monthly). Feeding the raw
            # income text here leaked ~1e-4 into base scores (L55,
            # fixed Step 8B).
            goals=profile.goal_type,
        )
        ranked = self.matcher.rank(career_profile, top_k=len(self.taxonomy.occupations))
        return {r.occupation.id: r.score for r in ranked}

    def _score_one(
        self,
        occupation: Occupation,
        *,
        expanded: set[str],
        phrases: list[list[set[str]]],
        base: float,
        target_zone: float,
        need_monthly: int | None,
    ) -> KVMatch:
        core = self._core[occupation.id]
        matched = [c for c in core if c in expanded]
        gain = sum(self._idf[c] for c in matched)
        total = max(sum(self._idf[c] for c in core), self._median_total)
        skill_overlap = gain / total if total else 0.0
        title = title_purity(occupation.title, phrases)
        zone = zone_fit(occupation.job_zone, target_zone)
        income = income_fit(occupation, need_monthly, self.seed)
        components = {
            "skill": skill_overlap,
            "title": title,
            "base": base,
            "zone": zone,
            "income": income,
        }
        # Combination delegates to the ranker (Step 8.1); the
        # components dict keeps the raw feature values (the API
        # contract — the frontend reads components["title"] etc.)
        # and the contributions dict carries the per-feature
        # weight x value (so the UI can say HOW MUCH each signal
        # counted, not just that it was present).
        score, contributions = self.ranker.combine(components)
        # Zone-gap penalty: roles needing more preparation than the user
        # has lose 15% per zone of gap (capped at 50%) — they still
        # appear when their skill/title fit is strong, but fitting roles
        # win ties. The penalty stays in the scorer: it is a domain
        # rule about preparation gaps, not a ranking primitive.
        gap = max(0.0, occupation.job_zone - target_zone)
        score *= max(
            1.0 - self.config.zone_gap_penalty_cap,
            1.0 - self.config.zone_gap_penalty * gap,
        )
        return KVMatch(
            occupation=occupation,
            score=score,
            components=components,
            contributions=contributions,
            matched=matched,
            missing=[c for c in core if c not in expanded],
        )

    def rank(self, profile: VoiceProfile, top_k: int = 5) -> tuple[list[KVMatch], dict]:
        """Top-``top_k`` matches for a confirmed profile, plus ranking
        metadata (target zone, how many occupations the zone filter
        excluded). The zone filter drops occupations more than one zone
        above the target before ranking."""
        expanded = expand_competencies(profile.skills)
        phrases = self.phrases_for(profile)
        base_by_id = self._base_scores(profile)
        target_zone = education_zone(profile.education, "Student / No experience")
        scored: list[ScoredItem] = []
        excluded = 0
        for occupation in self.taxonomy.occupations:
            if occupation.job_zone > target_zone + self.config.zone_filter_slack:
                excluded += 1
                continue
            match = self._score_one(
                occupation,
                expanded=expanded,
                phrases=phrases,
                base=base_by_id.get(occupation.id, 0.0),
                target_zone=target_zone,
                need_monthly=profile.income_monthly,
            )
            scored.append(ScoredItem(item=match, score=match.score, tiebreak=occupation.title))
        # Ordering delegates to the ranker (Step 8.1) — the default
        # comparator reproduces the Stage 4 order (score desc, title
        # asc); an injected comparator replaces it.
        ranked = [entry.item for entry in self.ranker.rank(scored)]
        meta = {"target_zone": round(target_zone, 2), "excluded_zone": excluded}
        return ranked[:top_k], meta

    def match_for(self, profile: VoiceProfile, occupation_id: str) -> KVMatch | None:
        """Score ONE occupation for a profile (the gap-learning step) —
        the same scoring as :meth:`rank`, without the zone filter (the
        user already chose this occupation; the score still carries the
        zone-gap penalty, so the gap view stays honest)."""
        occupation = self.taxonomy.get(occupation_id)
        if occupation is None:
            return None
        expanded = expand_competencies(profile.skills)
        phrases = self.phrases_for(profile)
        base_by_id = self._base_scores(profile)
        target_zone = education_zone(profile.education, "Student / No experience")
        return self._score_one(
            occupation,
            expanded=expanded,
            phrases=phrases,
            base=base_by_id.get(occupation.id, 0.0),
            target_zone=target_zone,
            need_monthly=profile.income_monthly,
        )


# --------------------------------------------------------------------------- #
# Gap + learning path (Stage 4, step 2)
# --------------------------------------------------------------------------- #


def gap_for_match(match: KVMatch, taxonomy: Taxonomy | None = None) -> dict:
    """The skill gap for one match, through the shared skill-gap engine
    (``skillgap.evaluate``): matched core competencies rate 5 (strong),
    the rest rate 0 (missing) — no invented self-ratings, the gap is
    exactly what the match says the user has and has not. Returns the
    engine's ``Readiness.to_dict`` (readiness %, counts, radar)."""
    ratings = {name.lower(): 5 for name in match.matched}
    readiness = evaluate_readiness(match.occupation.id, ratings, taxonomy)
    return readiness.to_dict()


def learning_path_for(
    missing: list[str],
    per_skill: int = 1,
    limit: int = 5,
) -> list[dict]:
    """Free learning resources for a gap list, from the curated
    catalogue (``learning.resources_for_gaps`` — O*NET competency
    aliases + DOMAIN_HINTS fallbacks, de-duplicated by URL). Every item
    carries its source, provider and free flag; an empty gap list
    returns an empty path (never invented courses)."""
    items: list[dict] = []
    for resource in resources_for_gaps(missing, per_skill=per_skill, limit=limit):
        items.append(
            {
                "skill": resource.skill,
                "title": resource.title,
                "url": resource.url,
                "provider": resource.provider,
                "free": resource.free,
                "source": "curated catalogue",
            }
        )
    return items


def course_citations_for(
    retriever, occupation_title: str, missing: list[str], top_k: int = 3
) -> list[dict]:
    """RAG citations for learning: courses + skilling chunks matching
    the occupation and its top gaps (Stage 2 knowledge base — SWAYAM /
    NPTEL / NSDC / PMKVY sources). Each citation carries title, URL,
    source date and a short verbatim snippet. Empty when the store has
    no course/skilling chunk for the query — never invented."""
    query = f"{occupation_title} {' '.join(missing[:3])} free course training".strip()
    seen: set[str] = set()
    citations: list[dict] = []
    for topic in ("courses", "skilling"):
        for hit in retriever.search(query, top_k=2, topic=topic):
            url = hit.chunk.source_url
            if url and url in seen:
                continue
            if url:
                seen.add(url)
            text = " ".join(hit.chunk.text.split())
            citations.append(
                {
                    **hit.chunk.citation(),
                    "snippet": text[:240] + ("…" if len(text) > 240 else ""),
                }
            )
            if len(citations) >= top_k:
                return citations
    return citations
