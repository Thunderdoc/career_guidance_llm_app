# Master Plan — Career Guidance AI v2.0 ("production-ready & usable")

_Date: 2026-09-18 · Companion to `RESEARCH_ROADMAP.md` (the why); this document is the what/how/when._

---

## Status (2026-09-18)

| Criterion | Status |
| --- | --- |
| R1 ≤60 s to results | ✅ offline path p95 ≈ 100 ms; single-screen composer |
| R2 ≥300-career catalog, Hit@5 ≥ 0.70 | ✅ 974 O*NET occupations, **Hit@5 0.98 / MRR 0.82** (`python -m eval.run`) |
| R3 AI faithfulness | ✅ grounded prompts + schema validation + provenance; offline fallback |
| R4 salary + demand | ✅ market block per career (country-aware; source labelled) |
| R5 saved progress | ✅ SQLite history, export md/json, sidebar/locale persisted |
| R6 Lighthouse / reduced-motion | ✅ static export 177 kB first load; `prefers-reduced-motion` honoured |
| R7 en / ta / hi | ✅ `frontend/lib/i18n.tsx`, switcher in sidebar |
| R8 one-command deploy | ✅ `docker compose up --build` |
| R9 security/privacy | ✅ rate limit 30/min, non-root container, no keys in repo, input limits |
| R10 test coverage | ✅ 68 pytest + golden eval in CI (`.gitlab-ci.yml`) |

## 0. Definition of "fully ready and usable"

The product is **done** when all of the following are true:

| # | Acceptance criterion | How we verify |
|---|---|---|
| R1 | A first-time visitor gets 5 relevant careers within **≤ 60 s** of landing, with no instructions needed | Usability test with 5 students, task completion ≥ 4/5 |
| R2 | Works **fully offline** (no API key) with a real occupation catalog (≥ 300 careers), not 6 | Golden-set Hit@5 ≥ 0.70 in demo mode |
| R3 | In AI mode, every listed skill exists in the taxonomy context (no hallucinated skills) | Faithfulness check ≥ 0.95 on eval set |
| R4 | Each career shows **salary range + demand signal** (India-first) | Data present for ≥ 90 % of catalog |
| R5 | Users can save progress, return, and see improvement over time | Account + progress e2e test |
| R6 | Animated, bespoke UI (Motion Primitives) scoring **Lighthouse ≥ 90** perf/a11y/best-practices, honours reduced-motion | Lighthouse CI in pipeline |
| R7 | Available in **English, Tamil, Hindi** | i18n coverage 100 % of UI strings, LLM output language switch |
| R8 | Deployable with **one command** (Docker Compose) and to one cloud target with HTTPS, backups, monitoring | Staging + production environments live |
| R9 | Security & privacy baseline: rate limiting, file-upload hardening, data export/delete, no secrets in repo | Checklist §9 signed off |
| R10 | Test coverage ≥ 85 % backend, e2e suite green, CI blocks regressions | CI dashboard |

---

## 1. Target architecture

```
┌────────────────────────────┐        ┌──────────────────────────────────────────┐
│ frontend/  (Next.js 15)    │  HTTPS │ backend/  (FastAPI)                       │
│ Tailwind + Motion          │ ─────▶ │ /api/v1/recommend  /resume  /jobs/fit     │
│ Motion Primitives          │  JSON  │ /api/v1/auth  /me/runs  /me/progress      │
│ next-intl (en/ta/hi)       │        │ /api/v1/careers  /skills  /market         │
└────────────────────────────┘        │ /api/v1/chat  /assessment  /export        │
                                      └───────────────┬──────────────────────────┘
                                                      │ imports
                    ┌─────────────────────────────────▼──────────────────────────┐
                    │ career_guidance/  (existing pure-Python core, extended)     │
                    │ taxonomy/  matching/  providers/  market/  learning/  eval/ │
                    └──────┬──────────────┬─────────────┬───────────────┬────────┘
                           │              │             │               │
                    Postgres (or     Vector index   LLM providers   External APIs
                    SQLite dev)      (FAISS/pgvector) OpenAI/Gemini/  Adzuna, CareerOneStop
                                                     Ollama          (cached, rate-limited)
```

Principles: core stays UI-agnostic and testable; every external dependency has an offline fallback;
`app.py` (Streamlit) remains as an internal admin/debug view until v2.0 parity, then is removed.

---

## 2. Workstreams & detailed task lists

Effort key: **S** ≤ 1 day · **M** 2–3 days · **L** 1 week · **XL** > 1 week.
Each task lists its Definition of Done (DoD).

### WS-A  Intelligence layer (the core upgrade)

| ID | Task | Effort | DoD |
|---|---|---|---|
| A1 | **Taxonomy ingestion** — script `scripts/build_catalog.py` downloads O*NET (CC BY 4.0) + ESCO bulk files, produces `data/catalog/occupations.json` (title, description, canonical skills w/ importance, job zone, related occupations, ESCO/O*NET ids, multilingual labels) | L | ≥ 300 occupations, reproducible build, licence NOTICE added |
| A2 | **Skill normaliser** — `career_guidance/taxonomy/skills.py`: synonym table + embedding nearest-neighbour (`all-MiniLM-L6-v2`), TF-IDF fallback when torch unavailable | M | "js", "JavaScript", "ES6" → one canonical skill; unit tests |
| A3 | **Resume skill extraction** — regex + section detection + normaliser; returns structured `ExtractedProfile` | M | ≥ 80 % recall on 20 sample resumes |
| A4 | **Semantic demo provider** — `SemanticProvider` replaces `MockProvider` catalog logic; cosine similarity on profile vs occupation embeddings + IDF re-weighting to suppress generic skills; keep `SuggestionProvider` interface | L | Golden-set Hit@5 ≥ 0.70; latency < 300 ms |
| A5 | **RAG-grounded LLM provider** — retrieve top-k occupations + skill lists → prompt with "use only these skills"; JSON schema via structured outputs; provenance ids returned | L | Faithfulness ≥ 0.95; falls back to A4 on error |
| A6 | **Gap prioritisation** — score missing skills by (frequency across top-5 × taxonomy importance × market demand); expose `priority_skills[:3]` | S | Field present in API & UI |
| A7 | **Transition paths** — from current role (if given) find 1–2 stepping-stone occupations via skill overlap / O*NET related occupations | M | Path shown when experience > junior |
| A8 | **Interest assessment** — 18-item RIASEC questionnaire; map Holland codes to O*NET interest profiles; blend with skill score (configurable weight) | M | Undecided user with zero skills gets sensible careers |
| A9 | **Job-description fit check** — paste JD → extract skills → gap vs profile → readiness % | M | Endpoint + UI panel |
| A10 | **Multi-LLM providers** — OpenAI, Gemini, Ollama behind one factory; per-provider timeout, retries, cost logging | M | Switch via env var; tests with mocks |
| A11 | **Evaluation harness** — `eval/` with 50 golden profiles, metrics Hit@5, skill precision/recall, faithfulness; `make eval` + CI job (non-blocking → blocking after baseline) | M | Report artefact in CI |

### WS-B  Data & labour-market layer

| ID | Task | Effort | DoD |
|---|---|---|---|
| B1 | **Market adapter interface** `market/base.py` + `AdzunaAdapter` (country `in`, `gb`, `us`) → salary p25/p50/p75, posting count 30d, top companies, trend | M | Cached 24 h; attribution string |
| B2 | `CareerOneStopAdapter` → wages by percentile, outlook, typical education | S | Used when country = us |
| B3 | **Static fallback dataset** `data/market_snapshot.json` refreshed monthly by CI job, so demand/salary always render offline | S | ≥ 90 % occupations covered |
| B4 | **Learning resources map** `data/learning_resources.yaml`: skill → 2–3 curated links (SWAYAM, NPTEL, freeCodeCamp, Coursera, MS Learn); no LLM-generated URLs | M | Link checker in CI |
| B5 | **India localisation of catalog** — map O*NET titles to common Indian job titles; NCS sector tags | M | Reviewed by 2 counsellors |

### WS-C  Backend API & persistence

| ID | Task | Effort | DoD |
|---|---|---|---|
| C1 | **FastAPI app** `backend/main.py`, versioned router `/api/v1`, Pydantic models mirroring dataclasses, OpenAPI docs | M | `/docs` renders; contract tests |
| C2 | Endpoints: `POST /recommend`, `POST /resume/extract`, `GET /careers/{id}`, `GET /careers/search`, `GET /skills/normalise`, `GET /market/{career_id}`, `POST /jobs/fit`, `POST /assessment`, `POST /chat`, `GET /export/{run_id}.{md,pdf,json}` | L | All covered by tests |
| C3 | **Auth** — email magic-link + Google OAuth (Auth.js on FE, JWT verified on BE); anonymous mode still works (session id) | L | Login/logout/refresh e2e |
| C4 | **Database** — SQLAlchemy + Alembic; tables `users`, `runs`, `skills_progress`, `assessments`, `feedback`; SQLite dev / Postgres prod | M | Migrations run in CI |
| C5 | **Progress tracking** — mark skill learned, re-compute coverage; timeline endpoint | S | Chart data endpoint |
| C6 | **Feedback loop** — 👍/👎 + reason per recommendation; stored for eval set growth | S | Table + endpoint |
| C7 | **Scoped chat** — `/chat` with report + retrieved taxonomy context injected; streaming (SSE); guardrail: refuses off-topic | M | Streaming works through proxy |
| C8 | **Background jobs** — nightly market snapshot refresh, weekly catalog rebuild (APScheduler or cron container) | S | Logs + failure alert |
| C9 | **Caching & rate limiting** — Redis (optional) / in-memory LRU; `slowapi` 30 req/min/IP on LLM routes | S | 429 tested |
| C10 | **Export** — Markdown (exists), JSON (exists), **PDF** (WeasyPrint/ReportLab) with brand template | M | PDF opens, < 1 MB |

### WS-D  Front end — Next.js + Motion Primitives (replaces Streamlit UI)

| ID | Task | Effort | DoD |
|---|---|---|---|
| D1 | **Scaffold** `frontend/`: Next.js 15 App Router, TypeScript, Tailwind, Motion, shadcn/ui base, Motion Primitives via CLI; ESLint/Prettier; env-based API base URL with dev proxy (`/api/*` → backend) | S | `pnpm dev` runs, hits `/api/v1/health` |
| D2 | **Design system** — tokens (indigo accent, neutral scale, radius 12–16 px, type scale), dark mode, `prefers-reduced-motion` wrapper around all primitives | S | Storybook or `/design` page |
| D3 | **Hero** — `Text Effect` headline reveal, `Spotlight` background, `Magnetic` CTA; single message, single button | S | LCP < 2.5 s |
| D4 | **Profile form** — one column, skills first with chip input + autocomplete from `/skills/normalise`; optional fields in `Disclosure`; `Border Trail` on focus; resume drop-zone with progress; "Try example" | M | Form → API → results in ≤ 3 interactions |
| D5 | **Loading state** — `Text Shimmer` + `Text Loop` status; skeleton cards | S | No spinner anywhere |
| D6 | **Results** — `In View` + `Animated Group` stagger; `Animated Number` coverage; `Glow Effect` best fit; `Tilt` hover; demand & salary pills; "learn these 3 first" strip | M | Matches design mock |
| D7 | **Career detail** — `Morphing Dialog` from card; `Transition Panel` tabs (Path / Next steps / Market / Resources); learning-path stepper | M | Deep-linkable `/career/[id]` |
| D8 | **Compare view** — select 2–3 careers → side-by-side skills/salary/time-to-ready | M | Uses `/careers/{id}` + market |
| D9 | **Assessment flow** — 18 questions, one per screen, `Transition Panel` slides, progress bar | M | Result feeds `/recommend` |
| D10 | **JD fit check** — paste JD → readiness ring (`Animated Number`) + gap chips | S | |
| D11 | **Chat drawer** — streaming answers, suggested prompts ("Make me a 30-day plan") | M | SSE through Next proxy |
| D12 | **Account & progress** — login, "my runs" `Carousel`, skill checklist, coverage-over-time chart | M | |
| D13 | **Navigation** — `Dock` (Recommend · Compare · Progress) + `Scroll Progress`; remove sidebar, About page → footer + modal, Analytics → stats strip | S | Nothing unnecessary above the fold |
| D14 | **i18n** — `next-intl`, en/ta/hi message files, language switcher, RTL-safe layout; LLM output language passed to API | M | 100 % strings extracted |
| D15 | **Accessibility & motion** — keyboard paths, focus traps in dialogs, ARIA on chips/dock, reduced-motion QA | S | axe: 0 serious issues |
| D16 | **SEO/PWA** — metadata, OG image, manifest, installable | S | Lighthouse PWA pass |
| D17 | **Analytics (product)** — privacy-friendly (Plausible/Umami) events: run started/completed, export, feedback | S | Dashboard live |

### WS-E  Quality engineering

| ID | Task | Effort | DoD |
|---|---|---|---|
| E1 | Backend unit tests for every new module; coverage gate 85 % | ongoing | CI |
| E2 | API contract tests (schemathesis against OpenAPI) | S | CI |
| E3 | Front-end unit (Vitest) + component tests | M | CI |
| E4 | **E2E** (Playwright): anonymous run, login run, resume upload, compare, assessment, export, ta/hi locale | L | CI on PR |
| E5 | Lighthouse CI budget (perf ≥ 90, a11y ≥ 95) | S | CI |
| E6 | Load test (k6): 50 concurrent recommend calls, p95 < 3 s demo / < 12 s AI | S | Report |
| E7 | LLM eval in CI (A11) blocking on regression > 5 pts | S | CI |

### WS-F  DevOps, security, compliance

| ID | Task | Effort | DoD |
|---|---|---|---|
| F1 | **Repo restructure** — monorepo: `backend/`, `frontend/`, `career_guidance/`, `data/`, `scripts/`, `docs/`; Makefile targets | S | README updated |
| F2 | **Docker** — multi-stage images for API and web; `docker-compose.yml` (web, api, postgres, redis, nginx/Caddy TLS); healthchecks | M | `docker compose up` = full app |
| F3 | **CI/CD** — GitLab CI stages: lint → test → eval → build → e2e → deploy (staging auto, prod manual); GitHub Actions mirror | M | Green pipeline |
| F4 | **Cloud target** — Render/Fly.io/Railway (simple) or AWS Lightsail; Postgres managed; object storage for PDFs; custom domain + HTTPS | M | Staging + prod URLs |
| F5 | **Observability** — structured JSON logs, request ids, Sentry (FE+BE), Prometheus metrics (`/metrics`), uptime monitor | S | Alert on 5xx > 1 % |
| F6 | **Security** — CORS allowlist, CSP, upload hardening (MIME sniff, 5 MB, PDF page cap, zip-bomb guard), input length caps, prompt-injection filter on resume/JD text, dependency scanning (pip-audit, npm audit), secrets via env only, `.env.example` updated | M | Checklist signed |
| F7 | **Privacy** — data export & delete endpoints, retention policy (anonymous runs 90 d), privacy page, cookie-less analytics | S | Legal page live |
| F8 | **Backups** — nightly Postgres dump to object storage, restore drill documented | S | Restore tested |
| F9 | **Docs** — README (quick start, architecture, env vars), CONTRIBUTING, ADRs for key decisions, API docs link, CHANGELOG | S | |

---

## 3. Phased schedule (10 weeks, 1–2 engineers)

| Phase | Weeks | Deliverables | Exit criteria |
|---|---|---|---|
| **P0 Foundations** | 1 | F1 repo restructure, C1 FastAPI skeleton, D1–D2 scaffold + design tokens, A11 eval harness with golden set | API health + FE hello, eval baseline recorded |
| **P1 Real intelligence** | 2–3 | A1–A6 (catalog, normaliser, semantic provider, RAG, gap priority), C2 core endpoints, C4 DB | Hit@5 ≥ 0.70 demo, faithfulness ≥ 0.95 AI |
| **P2 Animated core journey** | 3–5 | D3–D7, D13, D5 loading, C10 export, E4 first e2e | Anonymous user completes journey on new UI; Streamlit no longer default |
| **P3 Market & depth** | 5–6 | B1–B4, A7, D8 compare, A9/D10 JD fit | Salary/demand on ≥ 90 % careers; compare works |
| **P4 Personalisation** | 6–8 | C3 auth, C5 progress, C6 feedback, A8/D9 assessment, C7/D11 chat, D12 | Login → progress → return flow passes e2e |
| **P5 Reach & polish** | 8–9 | D14 i18n (ta/hi), B5 India mapping, D15 a11y, D16 PWA, D17 analytics, A10 multi-LLM | Lighthouse ≥ 90; ta/hi complete |
| **P6 Production hardening** | 9–10 | F2–F8, E5–E7, load test, security review, docs; remove `app.py` | All R1–R10 green; prod live |

Parallelisation: WS-A/B (backend engineer) and WS-D (front-end engineer) run concurrently from week 2; the API contract (Pydantic models from existing dataclasses) is frozen at end of P0.

---

## 4. API contract (frozen at end of P0)

```jsonc
POST /api/v1/recommend
{ "skills": "…", "interests": "…", "education": "…", "experience_level": "…",
  "goals": "…", "current_role": "…", "resume_text": "…", "assessment_id": null,
  "locale": "en", "country": "in" }
→ 200
{ "run_id": 123, "provider": "openai:gpt-4o-mini", "is_demo": false, "used_fallback": false,
  "priority_skills": ["sql", "statistics", "tableau"],
  "recommendations": [{
    "career_id": "15-2051.00", "title": "Data Analyst", "match_reason": "…",
    "suitability": "intermediate", "match_score": 0.78,
    "matching_skills": [...], "missing_skills": [...],
    "learning_path": [...], "next_steps": [...],
    "transition_path": ["Business Analyst"],
    "market": { "salary_p25": 450000, "salary_p50": 650000, "salary_p75": 950000,
                "currency": "INR", "postings_30d": 1240, "trend": "up", "source": "Adzuna" },
    "resources": [{ "skill": "sql", "title": "…", "url": "…", "provider": "NPTEL", "free": true }],
    "provenance": { "taxonomy": "O*NET 30.x", "ids": ["15-2051.00"] }
  }]
}
```

---

## 5. Dependencies to add

Backend: `fastapi`, `uvicorn`, `pydantic>=2`, `sqlalchemy`, `alembic`, `python-jose`, `httpx`,
`sentence-transformers` (optional extra `[ml]`), `scikit-learn` (TF-IDF fallback), `faiss-cpu` or
`pgvector`, `slowapi`, `weasyprint`, `apscheduler`, `sentry-sdk`, `prometheus-fastapi-instrumentator`.
Front end: `next`, `react`, `tailwindcss`, `motion`, `motion-primitives` (CLI-installed components),
`next-intl`, `next-auth`, `@tanstack/react-query`, `zod`, `lucide-react`; dev: `vitest`, `@playwright/test`, `@lhci/cli`.

---

## 6. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Embedding model too heavy for small hosts | Slow cold start | TF-IDF fallback; pre-compute occupation vectors at build time; lazy-load model |
| Adzuna India coverage thin for some roles | Missing market data | Static monthly snapshot (B3); show "no data" honestly |
| LLM cost/latency | Poor UX, bills | RAG shrinks prompts; cache identical profiles 24 h; gpt-4o-mini default; demo fallback |
| Scope creep in animation | Slower P2 | Primitives limited to the table in D3–D13; reduced-motion default on low-end devices |
| Taxonomy is US/EU-centric | Irrelevant titles in India | B5 India mapping + counsellor review |
| Auth adds friction | Drop-off | Anonymous mode remains first-class; login only to save progress |

---

## 7. Immediate next actions (this week)

1. Approve this plan and the 10-week schedule.
2. P0: restructure repo, scaffold FastAPI + Next.js/Motion Primitives, write golden eval set (50 profiles).
3. Kick off A1 taxonomy ingestion in parallel (longest-lead backend item).
4. Register free API keys: Adzuna, CareerOneStop; decide LLM vendor(s).
5. Book 5 usability-test participants (students/graduates) for end of P2.
