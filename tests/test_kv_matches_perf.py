"""Performance pins for the /matches optimisation (22 Nov 2026).

The optimisation precomputes per-occupation data at scorer init (title
match index, IDF core totals, income bands), caches base-matcher scores
per profile signature, and precomputes the title-intent strings in the
base matcher. Every change is score-identical BY CONSTRUCTION — but
construction is not proof (L55 taught this codebase that scores are
sensitive to tiny leaks), so this file pins the behaviour:

* title-purity equivalence: the indexed core returns the same value as
  a reference implementation of the original per-term loop, for every
  occupation in the taxonomy x a battery of phrase lists.
* income-band / core-total equivalence: the precomputed tables hold
  exactly the values the per-request code computed.
* base-cache correctness: repeat profiles hit the cache, different
  profiles miss, and a cached dict is the dict the matcher computes.
* full-rank identity: the top-5 for the five probe profiles matches
  the scores measured on the ORIGINAL code (before the optimisation)
  exactly — order, scores, components, contributions, matched and
  missing lists. The expected values are embedded as literals below
  (rounded to 4 decimals, as the API returns them); they were captured
  from the pre-optimisation code on 22 Nov 2026 and must never be
  regenerated from the new code.
"""

import pytest

from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.matching import (
    KVScorer,
    _income_fit_from_band,
    _title_purity_indexed,
    income_fit,
    title_match_keys,
    title_purity,
)
from career_guidance.kaamvaani.rag import _title_term_matches, tokenize


def _reference_title_purity(title: str, phrases: list[list[set[str]]]) -> float:
    """The ORIGINAL title_purity loop, verbatim logic: per-term
    matching through _title_term_matches. The indexed core must agree
    with this on every input."""
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


def _profile(**overrides):
    base = {
        "skills": ["attention to detail", "computer literacy", "agricultural science"],
        "interests": "farming and basic computer work, and I can type. Madurai. I need a job",
        "education": "12th pass",
        "city": "Madurai",
        "income_text": "₹15,000 / month",
        "income_monthly": 15000,
        "goal_type": "job_6_months",
        "raw_text": "farming and basic computer work, and I can type. 12th pass. Madurai. "
        "15000 rupees a month. I need a job",
    }
    base.update(overrides)
    return VoiceProfile(**base)


PROFILES = {
    "demo": _profile(),
    "electrician": _profile(
        skills=["electrical technician"],
        interests="I am an electrician, house wiring and fan repair",
        education="ITI",
        city="Salem",
        income_monthly=20000,
        income_text="₹20,000 / month",
        raw_text="I am an electrician, house wiring and fan repair. ITI. Salem. "
        "20000 rupees a month. I need a job",
    ),
    "tailor": _profile(
        skills=["fashion design"],
        interests="tailoring and stitching clothes",
        education="10th pass",
        city="Tiruppur",
        income_monthly=12000,
        income_text="₹12,000 / month",
        raw_text="tailoring and stitching clothes. 10th pass. Tiruppur. "
        "12000 rupees a month. I need a job",
    ),
    "high_income": _profile(income_monthly=60000, income_text="₹60,000 / month"),
    "empty": _profile(
        skills=[],
        interests="",
        education="12th pass",
        income_monthly=None,
        income_text="",
        raw_text="",
    ),
}

# Top-5 expected values per probe profile, captured from the ORIGINAL
# (pre-optimisation) code on 22 Nov 2026. Scores, components and
# contributions rounded to 4 decimals, as the API returns them. These
# literals are the score-identity pin: if the optimisation changes a
# score by even a rounding margin, this test fails.
EXPECTED_TOP5 = {
    "demo": [
        {
            "career_id": "43-9021.00",
            "title": "Data Entry Keyers",
            "score": 0.5088,
            "components": {
                "skill": 0.1714,
                "title": 0.6667,
                "base": 0.0,
                "zone": 0.9073,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0514,
                "title": 0.2667,
                "base": 0.0,
                "zone": 0.0907,
                "income": 0.1,
            },
            "matched": ["clerical"],
            "missing": [
                "complex problem solving",
                "service orientation",
                "reading comprehension",
                "management of personnel resources",
                "instructing",
                "english language",
                "customer and personal service",
                "law and government",
            ],
        },
        {
            "career_id": "43-9011.00",
            "title": "Computer Operators",
            "score": 0.4685,
            "components": {
                "skill": 0.2292,
                "title": 0.5,
                "base": 0.0,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0688,
                "title": 0.2,
                "base": 0.0,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["quality control analysis", "computers and electronics"],
            "missing": [
                "operation monitoring",
                "complex problem solving",
                "systems analysis",
                "operation and control",
                "troubleshooting",
                "customer and personal service",
                "english language",
            ],
        },
        {
            "career_id": "19-4011.01",
            "title": "Agricultural Technicians",
            "score": 0.4545,
            "components": {
                "skill": 0.1603,
                "title": 0.5,
                "base": 0.0668,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0481,
                "title": 0.2,
                "base": 0.0067,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["biology"],
            "missing": [
                "complex problem solving",
                "mathematics",
                "science",
                "instructing",
                "service orientation",
                "operation monitoring",
                "chemistry",
                "administration and management",
            ],
        },
        {
            "career_id": "45-2011.00",
            "title": "Agricultural Inspectors",
            "score": 0.4267,
            "components": {
                "skill": 0.0995,
                "title": 0.5,
                "base": 0.0615,
                "zone": 0.9073,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0299,
                "title": 0.2,
                "base": 0.0062,
                "zone": 0.0907,
                "income": 0.1,
            },
            "matched": ["quality control analysis"],
            "missing": [
                "operation monitoring",
                "systems evaluation",
                "systems analysis",
                "complex problem solving",
                "instructing",
                "customer and personal service",
            ],
        },
        {
            "career_id": "15-1131.00",
            "title": "Computer Programmers",
            "score": 0.3931,
            "components": {
                "skill": 0.2292,
                "title": 0.5,
                "base": 0.0,
                "zone": 0.9127,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0688,
                "title": 0.2,
                "base": 0.0,
                "zone": 0.0913,
                "income": 0.1,
            },
            "matched": ["quality control analysis", "computers and electronics"],
            "missing": [
                "programming",
                "complex problem solving",
                "systems analysis",
                "systems evaluation",
                "operations analysis",
                "mathematics",
            ],
        },
    ],
    "electrician": [
        {
            "career_id": "47-2111.00",
            "title": "Electricians",
            "score": 0.7654,
            "components": {
                "skill": 0.3956,
                "title": 1.0,
                "base": 0.4695,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.1187,
                "title": 0.4,
                "base": 0.047,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["repairing", "installation", "equipment maintenance"],
            "missing": [
                "troubleshooting",
                "quality control analysis",
                "instructing",
                "building and construction",
                "mechanical",
                "mathematics",
                "english language",
            ],
        },
        {
            "career_id": "17-3023.03",
            "title": "Electrical Engineering Technicians",
            "score": 0.573,
            "components": {
                "skill": 0.2157,
                "title": 0.6667,
                "base": 0.4186,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0647,
                "title": 0.2667,
                "base": 0.0419,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["repairing", "operation monitoring"],
            "missing": [
                "complex problem solving",
                "troubleshooting",
                "systems analysis",
                "quality control analysis",
                "engineering and technology",
                "computers and electronics",
                "english language",
                "mathematics",
            ],
        },
        {
            "career_id": "49-9064.00",
            "title": "Watch Repairers",
            "score": 0.5401,
            "components": {
                "skill": 0.3615,
                "title": 0.5,
                "base": 0.3194,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.1085,
                "title": 0.2,
                "base": 0.0319,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["repairing", "operation monitoring", "equipment maintenance"],
            "missing": [
                "troubleshooting",
                "quality control analysis",
                "complex problem solving",
                "customer and personal service",
                "administration and management",
                "mechanical",
            ],
        },
        {
            "career_id": "47-3013.00",
            "title": "Helpers--Electricians",
            "score": 0.5367,
            "components": {
                "skill": 0.3697,
                "title": 0.5,
                "base": 0.3507,
                "zone": 0.9073,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.1109,
                "title": 0.2,
                "base": 0.0351,
                "zone": 0.0907,
                "income": 0.1,
            },
            "matched": ["repairing", "installation"],
            "missing": [
                "quality control analysis",
                "troubleshooting",
                "complex problem solving",
                "operation and control",
                "english language",
                "mechanical",
            ],
        },
        {
            "career_id": "49-2091.00",
            "title": "Avionics Technicians",
            "score": 0.5342,
            "components": {
                "skill": 0.3261,
                "title": 0.5,
                "base": 0.3663,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0978,
                "title": 0.2,
                "base": 0.0366,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["repairing", "equipment maintenance", "operation monitoring"],
            "missing": [
                "troubleshooting",
                "quality control analysis",
                "complex problem solving",
                "computers and electronics",
                "mechanical",
                "english language",
                "engineering and technology",
            ],
        },
    ],
    "tailor": [
        {
            "career_id": "27-1022.00",
            "title": "Fashion Designers",
            "score": 0.6119,
            "components": {
                "skill": 0.165,
                "title": 1.0,
                "base": 0.429,
                "zone": 0.9352,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0495,
                "title": 0.4,
                "base": 0.0429,
                "zone": 0.0935,
                "income": 0.1,
            },
            "matched": ["design"],
            "missing": [
                "management of personnel resources",
                "complex problem solving",
                "service orientation",
                "persuasion",
                "negotiation",
                "instructing",
            ],
        },
        {
            "career_id": "27-1023.00",
            "title": "Floral Designers",
            "score": 0.4723,
            "components": {
                "skill": 0.1419,
                "title": 0.5,
                "base": 0.3223,
                "zone": 0.9748,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0426,
                "title": 0.2,
                "base": 0.0322,
                "zone": 0.0975,
                "income": 0.1,
            },
            "matched": ["production and processing"],
            "missing": [
                "service orientation",
                "operations analysis",
                "active listening",
                "speaking",
                "persuasion",
                "management of material resources",
                "customer and personal service",
            ],
        },
        {
            "career_id": "51-9081.00",
            "title": "Dental Laboratory Technicians",
            "score": 0.3293,
            "components": {
                "skill": 0.3156,
                "title": 0.0,
                "base": 0.3716,
                "zone": 0.9748,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0947,
                "title": 0.0,
                "base": 0.0372,
                "zone": 0.0975,
                "income": 0.1,
            },
            "matched": ["production and processing", "design"],
            "missing": [
                "quality control analysis",
                "operation monitoring",
                "complex problem solving",
                "operation and control",
                "instructing",
                "medicine and dentistry",
                "customer and personal service",
            ],
        },
        {
            "career_id": "51-9195.04",
            "title": "Glass Blowers, Molders, Benders, and Finishers",
            "score": 0.3292,
            "components": {
                "skill": 0.316,
                "title": 0.0,
                "base": 0.3693,
                "zone": 0.9748,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0948,
                "title": 0.0,
                "base": 0.0369,
                "zone": 0.0975,
                "income": 0.1,
            },
            "matched": ["production and processing", "design"],
            "missing": [
                "quality control analysis",
                "operation and control",
                "operation monitoring",
                "complex problem solving",
                "mathematics",
                "troubleshooting",
            ],
        },
        {
            "career_id": "27-1013.00",
            "title": "Fine Artists, Including Painters, Sculptors, and Illustrators",
            "score": 0.2894,
            "components": {
                "skill": 0.316,
                "title": 0.0,
                "base": 0.3611,
                "zone": 0.9352,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0948,
                "title": 0.0,
                "base": 0.0361,
                "zone": 0.0935,
                "income": 0.1,
            },
            "matched": ["design", "production and processing"],
            "missing": [
                "complex problem solving",
                "operations analysis",
                "service orientation",
                "computers and electronics",
                "english language",
            ],
        },
    ],
    "high_income": [
        {
            "career_id": "43-9021.00",
            "title": "Data Entry Keyers",
            "score": 0.5088,
            "components": {
                "skill": 0.1714,
                "title": 0.6667,
                "base": 0.0,
                "zone": 0.9073,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0514,
                "title": 0.2667,
                "base": 0.0,
                "zone": 0.0907,
                "income": 0.1,
            },
            "matched": ["clerical"],
            "missing": [
                "complex problem solving",
                "service orientation",
                "reading comprehension",
                "management of personnel resources",
                "instructing",
                "english language",
                "customer and personal service",
                "law and government",
            ],
        },
        {
            "career_id": "19-4011.01",
            "title": "Agricultural Technicians",
            "score": 0.4545,
            "components": {
                "skill": 0.1603,
                "title": 0.5,
                "base": 0.0668,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0481,
                "title": 0.2,
                "base": 0.0067,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": ["biology"],
            "missing": [
                "complex problem solving",
                "mathematics",
                "science",
                "instructing",
                "service orientation",
                "operation monitoring",
                "chemistry",
                "administration and management",
            ],
        },
        {
            "career_id": "43-9011.00",
            "title": "Computer Operators",
            "score": 0.4385,
            "components": {
                "skill": 0.2292,
                "title": 0.5,
                "base": 0.0,
                "zone": 0.9973,
                "income": 0.7,
            },
            "contributions": {
                "skill": 0.0688,
                "title": 0.2,
                "base": 0.0,
                "zone": 0.0997,
                "income": 0.07,
            },
            "matched": ["quality control analysis", "computers and electronics"],
            "missing": [
                "operation monitoring",
                "complex problem solving",
                "systems analysis",
                "operation and control",
                "troubleshooting",
                "customer and personal service",
                "english language",
            ],
        },
        {
            "career_id": "45-2011.00",
            "title": "Agricultural Inspectors",
            "score": 0.3967,
            "components": {
                "skill": 0.0995,
                "title": 0.5,
                "base": 0.0615,
                "zone": 0.9073,
                "income": 0.7,
            },
            "contributions": {
                "skill": 0.0299,
                "title": 0.2,
                "base": 0.0062,
                "zone": 0.0907,
                "income": 0.07,
            },
            "matched": ["quality control analysis"],
            "missing": [
                "operation monitoring",
                "systems evaluation",
                "systems analysis",
                "complex problem solving",
                "instructing",
                "customer and personal service",
            ],
        },
        {
            "career_id": "15-1131.00",
            "title": "Computer Programmers",
            "score": 0.3931,
            "components": {
                "skill": 0.2292,
                "title": 0.5,
                "base": 0.0,
                "zone": 0.9127,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0688,
                "title": 0.2,
                "base": 0.0,
                "zone": 0.0913,
                "income": 0.1,
            },
            "matched": ["quality control analysis", "computers and electronics"],
            "missing": [
                "programming",
                "complex problem solving",
                "systems analysis",
                "systems evaluation",
                "operations analysis",
                "mathematics",
            ],
        },
    ],
    "empty": [
        {
            "career_id": "11-2011.01",
            "title": "Green Marketers",
            "score": 0.2066,
            "components": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0691,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0069,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": [],
            "missing": [],
        },
        {
            "career_id": "39-1021.01",
            "title": "Spa Managers",
            "score": 0.2065,
            "components": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0672,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0067,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": [],
            "missing": [
                "service orientation",
                "management of personnel resources",
                "persuasion",
                "instructing",
                "systems analysis",
                "complex problem solving",
                "clerical",
                "customer and personal service",
                "administration and management",
                "english language",
            ],
        },
        {
            "career_id": "25-9041.00",
            "title": "Teacher Assistants",
            "score": 0.206,
            "components": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0629,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0063,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": [],
            "missing": [
                "instructing",
                "service orientation",
                "speaking",
                "persuasion",
                "complex problem solving",
                "active listening",
                "english language",
                "education and training",
            ],
        },
        {
            "career_id": "25-1194.00",
            "title": "Vocational Education Teachers, Postsecondary",
            "score": 0.206,
            "components": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0625,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0062,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": [],
            "missing": [
                "instructing",
                "complex problem solving",
                "service orientation",
                "persuasion",
                "negotiation",
                "learning strategies",
                "education and training",
                "english language",
                "mechanical",
                "mathematics",
            ],
        },
        {
            "career_id": "29-2055.00",
            "title": "Surgical Technologists",
            "score": 0.2058,
            "components": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0611,
                "zone": 0.9973,
                "income": 1.0,
            },
            "contributions": {
                "skill": 0.0,
                "title": 0.0,
                "base": 0.0061,
                "zone": 0.0997,
                "income": 0.1,
            },
            "matched": [],
            "missing": [
                "operation monitoring",
                "service orientation",
                "operation and control",
                "management of material resources",
                "instructing",
                "equipment maintenance",
                "customer and personal service",
                "medicine and dentistry",
            ],
        },
    ],
}


@pytest.fixture(scope="module")
def scorer():
    return KVScorer()


class TestTitlePurityEquivalence:
    def test_indexed_core_matches_reference_on_all_occupations(self, scorer):
        """Every occupation x every probe phrase list: indexed == reference."""
        phrase_lists = [
            scorer.phrases_for(PROFILES["demo"]),
            scorer.phrases_for(PROFILES["electrician"]),
            scorer.phrases_for(PROFILES["tailor"]),
            scorer.phrases_for(_profile(skills=["nursing"], interests="patient care")),
            scorer.phrases_for(_profile(skills=["welding"], interests="fabrication work")),
            [[{"farm"}]],
            [[{"farmworker"}]],
            [[{"electric"}]],
            [[{"data"}, {"entry"}]],
            [[{"analysts"}]],
            [[{"nurse"}]],
            [[{"weld"}]],
            [[{"mechanic"}]],
            [[{"teacher"}]],
            [[{"driver"}]],
            [[{"comp"}]],
            [[{"er"}]],
            [[{"man"}]],
            [[{"worker"}]],
            [[{"workers"}]],
            [[{"s"}]],
            [[{"ing"}]],
        ]
        mismatches = []
        for occ in scorer.taxonomy.occupations:
            terms = tokenize(occ.title)
            keys = title_match_keys(terms)
            for phrases in phrase_lists:
                indexed = _title_purity_indexed(keys, len(terms), phrases)
                reference = _reference_title_purity(occ.title, phrases)
                if indexed != reference:
                    mismatches.append((occ.title, phrases, indexed, reference))
        assert mismatches == [], f"{len(mismatches)} mismatches, first 5: {mismatches[:5]}"

    def test_public_title_purity_matches_reference(self):
        for title in [
            "Data Entry Keyers",
            "Farmworkers, Farm, Ranch, and Aquacultural Animals",
            "Electricians",
            "Fashion Designers",
            "Registered Nurses",
            "Welders, Cutters, Solderers, and Brazers",
            "Chief Executives",
        ]:
            for phrases in [
                [[{"farm"}], [{"data"}, {"entry"}]],
                [[{"farm"}]],
                [[{"electric"}]],
                [[{"data"}, {"entry"}]],
            ]:
                assert title_purity(title, phrases) == _reference_title_purity(title, phrases)

    def test_title_match_keys_covers_all_three_match_branches(self):
        # Equality: q == t. Suffix: q a suffix of t, len >= 4.
        # Compound prefix: q a prefix of t whose remainder is a
        # compound remainder ("farm" + "worker" -> "farmworker").
        keys = title_match_keys(tokenize("Farmworkers"))
        assert "farmworker" in keys  # equality (tokenize stems the plural)
        assert "worker" in keys  # suffix branch
        assert "farm" in keys  # compound-prefix branch
        assert keys["farm"] == {"farmworker"}

    def test_indexed_core_empty_title_returns_zero(self):
        # Defensive guard: the public title_purity returns 0.0 before
        # reaching the core for an empty title, so pin the core's own
        # guard directly.
        assert _title_purity_indexed({}, 0, [[{"farm"}]]) == 0.0

    def test_indexed_core_skips_empty_phrases(self):
        keys = title_match_keys(tokenize("Data Entry Keyers"))
        with_empty = _title_purity_indexed(keys, 3, [[], [{"data"}, {"entry"}]])
        without_empty = _title_purity_indexed(keys, 3, [[{"data"}, {"entry"}]])
        assert with_empty == without_empty == 2 / 3


class TestPrecomputedTables:
    def test_income_bands_match_snapshot_for_all_occupations(self, scorer):
        for occ in scorer.taxonomy.occupations:
            snap = scorer.seed.snapshot(occ, "in")
            assert scorer._income_band[occ.id] == (snap.salary_p50, snap.salary_p75)

    def test_income_fit_from_band_matches_income_fit(self, scorer):
        for occ in scorer.taxonomy.occupations[:50]:
            p50, p75 = scorer._income_band[occ.id]
            for need in (None, 12000, 15000, 60000, 100000):
                assert _income_fit_from_band(p50, p75, need) == income_fit(occ, need, scorer.seed)

    def test_income_fit_from_band_no_band_never_punishes(self):
        # No band data must never punish a match — 1.0 whatever the
        # need, even when p75 exists without a p50.
        assert _income_fit_from_band(None, None, 15000) == 1.0
        assert _income_fit_from_band(None, 500000, 15000) == 1.0
        assert _income_fit_from_band(None, None, None) == 1.0

    def test_core_totals_match_per_request_sum(self, scorer):
        for oid, core in scorer._core.items():
            expected = max(sum(scorer._idf[c] for c in core), scorer._median_total)
            assert scorer._core_total[oid] == expected


class TestBaseScoreCache:
    def test_repeat_profile_hits_cache_with_identical_dict(self, scorer):
        profile = PROFILES["demo"]
        first = scorer._base_scores(profile)
        before = scorer._base_cache.stats()
        second = scorer._base_scores(profile)
        after = scorer._base_cache.stats()
        assert second == first
        assert after.hits == before.hits + 1

    def test_different_profile_misses_cache(self, scorer):
        scorer._base_scores(PROFILES["demo"])
        before = scorer._base_cache.stats()
        scorer._base_scores(PROFILES["electrician"])
        after = scorer._base_cache.stats()
        assert after.misses == before.misses + 1

    def test_income_only_difference_shares_cache_entry(self, scorer):
        # Income is scored by the dedicated income-fit component, not
        # the base matcher — the cache key correctly excludes it.
        scorer._base_cache.clear()
        demo = scorer._base_scores(PROFILES["demo"])
        before = scorer._base_cache.stats()
        high_income = scorer._base_scores(PROFILES["high_income"])
        after = scorer._base_cache.stats()
        assert high_income == demo
        assert after.hits == before.hits + 1

    def test_education_difference_misses_cache(self, scorer):
        scorer._base_cache.clear()
        scorer._base_scores(PROFILES["demo"])
        before = scorer._base_cache.stats()
        other = _profile(education="10th pass")
        scorer._base_scores(other)
        after = scorer._base_cache.stats()
        assert after.misses == before.misses + 1

    def test_cached_dict_equals_fresh_matcher_output(self, scorer):
        # A second scorer (empty cache) computes the same dict the
        # first scorer cached — the cache returns the matcher's own
        # output, not a stale copy.
        fresh = KVScorer()
        for name, profile in PROFILES.items():
            assert scorer._base_scores(profile) == fresh._base_scores(profile), name


class TestFullRankIdentity:
    @pytest.mark.parametrize("name", list(PROFILES))
    def test_top5_matches_pre_optimisation_fingerprint(self, scorer, name):
        ranked, _meta = scorer.rank(PROFILES[name], top_k=5)
        assert len(ranked) == 5
        actual = [
            {
                "career_id": m.occupation.id,
                "title": m.occupation.title,
                "score": round(m.score, 4),
                "components": {k: round(v, 4) for k, v in m.components.items()},
                "contributions": {k: round(v, 4) for k, v in m.contributions.items()},
                "matched": m.matched,
                "missing": m.missing,
            }
            for m in ranked
        ]
        assert actual == EXPECTED_TOP5[name]
