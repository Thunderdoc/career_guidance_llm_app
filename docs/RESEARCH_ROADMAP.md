# Research & Improvement Roadmap — Career Guidance AI

_Date: 2026-09-18_

## 1. Where the app stands today (code audit)

| Area | Current state | Limitation |
|---|---|---|
| Recommendation engine (offline) | Keyword matching against a **6-career** hard-coded catalog (`providers.py`) | Tiny coverage; brittle to synonyms ("JS" vs "JavaScript"); ranks generic careers for everyone |
| Recommendation engine (AI) | Single-shot `gpt-4o-mini` prompt, schema-validated | No grounding in real occupation/skill data → hallucinated or generic skills; no citations |
| Inputs | Free-text skills + resume | No structured skill extraction, no interest/personality assessment |
| Outputs | 5 careers, gaps, learning path, next steps | No salary/demand data, no course links, no "what to do this week", no comparison view |
| Memory | SQLite history + analytics | Runs are isolated; no user identity or progress tracking |
| Locale | English, US-neutral | No Indian labour-market context or regional languages |

## 2. What the field is doing (literature & products)

**Taxonomy-grounded matching is the state of the art.** Recent systems embed resumes and
occupations into a shared space anchored to the ESCO or O*NET taxonomies — e.g. CareerBERT
(Expert Systems With Applications 2025) matches resumes to ESCO jobs in a shared embedding
space, and SkillAlign combines the ESCO knowledge graph with transformer embeddings and FAISS
vector search. Alonso et al. (2025) show that anchoring a transformer to the expert-curated
O*NET database yields better alignment between job descriptions and required skills than text
alone. A known pitfall of pure-embedding approaches is a bias toward frequent generic skills
("Excel", "Communication") over domain-specific ones, mitigated by skill-frequency reweighting.

**Career *trajectories*, not just careers.** STEP (2026) frames next-job prediction as ranking
over ESCO occupations using time-aware sequence models trained on 355k real career paths, and
notably recommends transitions at greater "ESCO distance" — closer to where people actually move.
LLM+knowledge-graph hybrids for job-mobility prediction retrieve a job-related sub-graph before
generation specifically to curb hallucination from insufficient domain knowledge.

**Commercial tools bundle assessment + labour-market data.** Lightcast Career Coach combines an
interest assessment, a skills inventory, guided exploration, recommended educational offerings
and local job postings, backed by a 32,000-skill library derived from employer postings with
monthly updates. LinkedIn's AI coach differentiates on skill-gap analysis against *specific job
postings*; Eightfold on "where people with similar backgrounds ended up five years later"; other
tools on adjacent-skill "reskilling navigators".

**Trustworthy LLM output = retrieval + faithfulness checks.** RAG evaluations across domains
report that instructing the model to answer *only* from retrieved context, returning an explicit
"insufficient information" message otherwise, and scoring faithfulness/answer-relevancy (RAGAS)
materially reduces hallucination; trust is consistently the lowest-rated dimension by users,
so provenance matters.

**India context.** India faces an acute shortage of trained career counsellors; the National
Career Service portal offers counselling and a call-centre in seven languages including Tamil,
and NCS/NICS explicitly promote psychometric tests, skilling, and Model Career Centres.
A low-cost, multilingual, self-serve tool is directly aligned with this gap.

## 3. Freely usable data sources

| Source | What it gives | Access |
|---|---|---|
| **O*NET** (CC BY 4.0) | ~1,000 occupations, skills/knowledge/abilities, tasks, tools & tech, job zones, related occupations | Bulk download / web services |
| **ESCO** (EU, open) | 3,000+ occupations, 13,900 skills, multilingual labels, occupation↔skill graph | Bulk download / REST API |
| **CareerOneStop APIs** | Wages by percentile, outlook, typical training, **skill-gap between two occupations** | Free key |
| **Adzuna API** | Live postings, salary histograms, top companies, trends (has an `in` country code) | Free tier |
| **NCS (ncs.gov.in)** | Indian job postings, counsellors, skill providers | Portal (scrape/partner) |

## 4. Feature backlog, prioritised

### Tier 1 — highest value / lowest effort (next 2–4 weeks)
1. **Replace the 6-career catalog with an O*NET/ESCO-backed catalog** (hundreds of occupations,
   canonical skill lists). Ship a pre-processed JSON/SQLite snapshot in `data/` so demo mode still
   works offline.
2. **Skill normalisation & extraction**: map free-text/resume skills to canonical taxonomy skills
   (synonym table + sentence-embedding nearest neighbour). Fixes "JS ≠ JavaScript" and gives
   honest coverage percentages.
3. **Semantic matching in demo mode**: embed profile and occupations (e.g. `all-MiniLM-L6-v2`
   via `sentence-transformers`, or TF-IDF as a zero-dependency fallback) instead of substring
   matching. Add IDF-style reweighting so generic skills don't dominate.
4. **Ground the LLM (RAG)**: retrieve top-k taxonomy occupations + their skill lists and pass them
   as context; instruct the model to only name skills present in context. Show a "Based on
   O*NET/ESCO" provenance line on every card.
5. **Skill-gap prioritisation**: rank missing skills by (frequency across recommended careers ×
   taxonomy importance) and surface "learn these 3 first".

### Tier 2 — differentiation (1–2 months)
6. **Labour-market layer**: salary range, demand trend and top hiring companies per career via
   Adzuna (`in` for India) / CareerOneStop, cached daily. Show a "Demand" pill next to suitability.
7. **Career comparison view**: pick 2–3 recommended careers and see skills/salary/time-to-ready
   side by side (CareerOneStop's occupation skill-gap endpoint can power this).
8. **Interest / work-style mini-assessment** (RIASEC-style, 12–18 questions) to guide users who
   don't yet know their skills — the "undecided student" persona Lightcast targets.
9. **Learning-resource links**: map each missing skill to free/low-cost courses (SWAYAM, NPTEL,
   Coursera, freeCodeCamp) via a curated mapping file; avoid LLM-invented URLs.
10. **Adjacent-career / transition paths**: use O*NET "related occupations" and ESCO skill overlap
    to show "from your current role → 2 stepping-stone roles → target role".
11. **Conversational follow-up**: a chat panel scoped to the generated report ("Why not data
    engineer?", "Make a 30-day plan") with the report + taxonomy context injected.

### Tier 3 — platform maturity
12. **User accounts & progress**: mark skills as learned, re-run, and chart coverage over time.
13. **Multilingual UI & inputs** (Tamil, Hindi first): ESCO labels are already multilingual;
    LLM prompts can request output language.
14. **Job-posting fit check**: paste a JD → gap analysis against the profile (LinkedIn's most
    praised feature).
15. **Evaluation harness**: golden set of ~50 profiles with expected careers; measure Hit@5,
    skill precision, and LLM faithfulness (RAGAS-style) in CI to stop regressions.
16. **Pluggable LLM providers** (Gemini, local Ollama) plus caching and cost/latency telemetry.
17. **Export/share**: PDF report; shareable read-only link; counsellor mode that batch-processes
    a class of students.

## 5. Risks & guardrails
- **Bias & fairness**: taxonomy grounding reduces but does not remove LLM bias; never use
  demographics as features; log and review recommendations by experience level.
- **Over-trust**: always label AI vs demo mode (already done), show provenance, add a
  "This is guidance, not a guarantee" note.
- **Data freshness & licensing**: O*NET (CC BY), ESCO (EU open licence) are fine to bundle;
  Adzuna requires attribution; cache and rate-limit external calls.
- **Privacy**: keep resume text in memory only (current behaviour); if accounts are added, add
  export/delete.

## 6. Conclusion

The current app has a clean architecture and good UX, but its **intelligence layer is the
bottleneck**: a 6-career keyword catalog offline and an ungrounded single prompt online.
Everything the field and the market reward — accuracy, trust, explainability, market relevance —
comes from one architectural move: **ground both modes in an open occupation/skill taxonomy
(O*NET + ESCO) with semantic matching, then layer live labour-market data on top.**

Recommended sequence:
1. Taxonomy-backed catalog + skill normalisation + semantic demo matching (makes demo mode
   genuinely useful and gives the LLM something to retrieve).
2. RAG-grounded LLM with provenance and a small evaluation set.
3. Salary/demand data (India-first via Adzuna) and career comparison.
4. Interest assessment, curated learning links, transition paths, and a scoped chat.
5. Accounts/progress, Tamil/Hindi, JD fit-check, counsellor mode.

This order delivers visible quality gains within weeks, keeps the app fully functional offline,
and positions it well for India's under-served, multilingual career-guidance need.
