# 🎓 Career Guidance AI

[![CI](https://github.com/Thunderdoc/career_guidance_llm_app/actions/workflows/ci.yml/badge.svg)](https://github.com/Thunderdoc/career_guidance_llm_app/actions/workflows/ci.yml)

Career Guidance AI turns a person's profile — skills, interests, education,
experience, goals and optionally a résumé — into **structured, explainable
career recommendations** grounded in the **O*NET occupational taxonomy
(974 occupations)**.

For each match it shows the skills you already have, the gaps to close (ranked
by impact), an ordered learning path with free courses, salary bands and demand
signals, and concrete next steps. It also offers a RIASEC interest quiz,
job-description fit scoring, per-user progress tracking, and an admin console.

Available in **English, தமிழ் and हिन्दी**. Works fully offline; adds
LLM-written explanations when an OpenAI key is configured.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Authentication & admin](#authentication--admin)
- [API](#api)
- [Quality gates](#quality-gates)
- [Deployment](#deployment)
- [Project layout](#project-layout)
- [Roadmap & docs](#roadmap--docs)

---

## Features

| Area | What you get |
| --- | --- |
| **Recommendations** | Top-5 occupations from 974 O*NET entries via a hybrid matcher (competency overlap × IDF, technology overlap, coverage, TF-IDF semantics, job-zone fit, title/alias intent). Golden-set **Hit@5 = 0.98**. |
| **Skill-gap analysis** | Matching vs. missing skills per career, cross-career *priority skills* ("learn these first"), one-click "add this skill and re-run". |
| **Learning path** | Ordered steps + curated free resources (NPTEL, freeCodeCamp, MDN, edX …) editable by admins. |
| **Market signals** | Salary p25/p50/p75, postings trend and demand per career (India/UK/US), source-labelled. Adzuna live data when keys are set. |
| **Interest quiz** | 18-question RIASEC assessment → Holland code, fed back into matching. |
| **Job fit** | Paste a job description → readiness %, matched/missing skills, resources. |
| **Résumé upload** | .pdf / .txt / .md parsed in memory (≤ 5 MB), skills auto-detected. |
| **Accounts** | Firebase Authentication (Google, e-mail + password with enforced verification). Per-user history, skill-progress checklist, export, delete-my-data. Anonymous use always works. |
| **Admin console** | Users, runs, feedback triage, learning-resource content management, audit log, KPIs. Role verified server-side. |
| **Billing & selling** | Free / Pro / Institute plans, one-time Pro trial, Razorpay checkout + signature-verified webhook, roadmap PDF as the Pro feature, public landing + pricing page, in-app `/billing` page, Terms / Privacy / Refund pages. Phase 9 adds Razorpay **subscriptions** (additional auto-renew option), admin-created **coupons** and **referral attribution** — see the Billing section in [`SELLING.md`](SELLING.md). |
| **AI mode** | With `OPENAI_API_KEY`: grounded explanations validated against a strict schema, automatic fallback to offline mode. |
| **UI** | Next.js 15 + React 19 + Motion + Tailwind 4, Motion-Primitives-style animations, honours `prefers-reduced-motion`, PWA manifest, 3 languages. |
| **Sharing (Phase 8)** | Revocable, expiring share links for any report (`/shared/[token]`): owner creates from the report page, anyone with the link sees a read-only, source-labelled view of the share-safe fields only. See `docs/SECURITY.md` → Share tokens. |
| **PWA & low-bandwidth (Phase 8)** | Installable PWA: completed manifest, hand-written service worker (app-shell precache, static cache-first, `/api` never cached, offline fallback, update-available toast), `/offline` page. Low-bandwidth mode (Settings toggle + header chips, auto-on with Save-Data): kills animations, hides decorative layers, defers the chat/share panels until asked. |

## Architecture

```
 Browser ──► Next.js 15 (frontend/)  ──/api/*──►  FastAPI (backend/)  ──►  career_guidance/ (core)
             Motion + Tailwind UI                   auth, admin, rate-limit      matcher · taxonomy · market
             Firebase Auth SDK                      Firebase ID-token verify     learning · providers · storage
                                                    HttpOnly session cookie      SQLite (runs, users, progress…)
```

- **`career_guidance/`** is UI-agnostic and has no web dependencies.
- **`backend/`** is a thin FastAPI adapter (also serves the static export in production).
- **`frontend/`** talks only to relative `/api/*` URLs (proxied by `next dev`, same-origin in Docker).
- Authentication issues **our own signed HttpOnly session** after verifying a
  Firebase ID token — the Firebase private key is never needed by the app.

## Quick start

### One command (Docker)

```bash
cp .env.example .env          # fill in what you need (see Configuration)
docker compose up --build     # → http://localhost:8000
```

### Development

```bash
make install                  # pip deps + npm ci
cp .env.example .env          # backend settings
cp frontend/.env.example frontend/.env.local   # public Firebase web config
make api                      # FastAPI  → http://localhost:8000  (docs: /api/docs)
make web                      # Next.js  → http://localhost:3000  (proxies /api → :8000)
```

Requirements: Python 3.10+, Node 20+. `pip` on Debian/Ubuntu may need
`--break-system-packages` or a virtualenv.

## Configuration

All configuration is via environment variables. **Never commit `.env`,
`frontend/.env.local`, or anything under `secrets/`** — they are git-ignored.

### Backend (`.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` disables dev-only helpers (e.g. magic-link preview) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATABASE_PATH` | `data/career_guidance.db` | SQLite file (runs, users, progress, feedback, overrides, audit) |
| `MIN_INPUT_LENGTH` / `MAX_INPUT_LENGTH` | `3` / `10000` | Profile validation bounds |
| `OPENAI_API_KEY` | *(empty)* | Enables AI explanations; empty = offline mode |
| `OPENAI_MODEL` / `OPENAI_TIMEOUT_SECONDS` | `gpt-4o-mini` / `30` | LLM settings |
| `LLM_PROVIDER` | *(empty = auto)* | Phase 7 provider factory: `openai` \| `gemini` \| `ollama`; empty = OpenAI key, else Gemini key, else offline |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | *(empty)* / `gemini-2.0-flash` | Gemini provider (plain HTTPS, key in header) |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `llama3.1` | Local Ollama provider (no key) |
| `SEMANTIC_MATCHING_ENABLED` / `SEMANTIC_BLEND_WEIGHT` / `SEMANTIC_EMBEDDING_MODEL` | `false` / `0.25` / *(empty)* | Phase 7 semantic blend at the MatcherV2 seam; embedding model optional, fails soft to TF-IDF |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | *(empty)* | Live salary/postings data |
| `SESSION_SECRET` | *(dev default)* | Signs session cookies — **required in production** |
| `PUBLIC_URL` | *(derived from request)* | Public origin, used in e-mailed links |
| `ADMIN_EMAILS` | *(empty)* | Comma-separated e-mails granted the admin role on first sign-in |
| `FIREBASE_PROJECT_ID` | *(empty)* | Enables Firebase sign-in (`/api/v1/auth/firebase`) |
| `FIREBASE_SERVICE_ACCOUNT_FILE` | *(empty)* | Optional; reserved for admin-side Firebase operations. Keep under `secrets/` |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | *(empty)* | Only for the fallback e-mail magic link |
| `GOOGLE_CLIENT_ID/SECRET` | *(empty)* | Only for the legacy non-Firebase Google OAuth path |

### Frontend (`frontend/.env.local`, also passed as Docker build args)

```
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
```

These come from *Firebase console → Project settings → Your apps → SDK setup*
and are public by design.

## Authentication & admin

**The app is public-first with gated depth** (Phase 1): the landing page,
career search and a visitor's **first recommendation run** work without
signing in — `POST /api/v1/recommend` accepts anonymous, rate-limited runs
(30/min/IP), stored with no account attached and flagged `anonymous`.
Sign-in is required for everything that *saves* or *belongs to* a user:
history, exports, plans, progress, the full journey tools, saved reports
and the admin console all return **401** without a valid session, and
`/api/v1/admin/*` additionally re-checks the admin role server-side
(403 for non-admins). Anonymous runs never appear in any user's history
or exports. Setting `PUBLIC_APP=true` (or the `public_app` admin flag)
additionally serves the other content routes to guests as before; see
[`docs/ROUTES.md`](docs/ROUTES.md) for the full route/access map and
[`docs/SOURCES.md`](docs/SOURCES.md) for the source of every displayed
figure.

Signing in at **`/login`** (Firebase Authentication):

- **Google** — verified by Google, no extra step.
- **E-mail + password** — after sign-up Firebase sends a verification link.
  The client signs the user out until it is clicked and offers *Resend
  verification e-mail*; the backend independently **rejects any
  email/password token whose `email_verified` is not true**.
- An e-mail **magic link** remains as a no-dependency fallback when Firebase is
  not configured (links are logged / shown in dev when SMTP is absent).

Signed-in users get history across devices, a **learning-progress checklist**
(History tab), feedback, and *Delete my account*.

**Authorisation is separate from authentication.** Role lives in the database;
e-mails in `ADMIN_EMAILS` become `admin` on first login and admins can promote
others. The `<RequireAuth admin>` guard protects `/admin` in the UI, and **every
`/api/v1/admin/*` route re-checks the role server-side** (401 unauthenticated,
403 not admin). Never trust a client-side flag.

Firebase console checklist:
1. *Authentication → Sign-in method*: enable **Google** and **Email/Password**.
2. *Authentication → Settings → Authorised domains*: add every domain you serve from.

## API

Interactive docs at **`/api/docs`**. All routes are under `/api/v1`.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health`, `/meta` | Liveness: status, mode, catalog size |
| GET | `/ready` | Readiness (Phase 6): DB + catalog checks, `503` with component breakdown when not ready |
| POST | `/recommend` | Profile → 5 recommendations (rate-limited 30/min; anonymous guest runs allowed, saved-data routes stay signed-in only) |
| POST | `/chat` | Phase 7 scoped chat over one stored run `{run_id, message}` → `{answer, mode, refused, refusal_key}` (rate-limited 20/min; signed-in = own or anonymous run, guest = anonymous run only, other users' runs 404; answers grounded only in that run + named taxonomy entries, deterministic off-topic refusal, offline fallback with no LLM key) |
| POST | `/resume/extract` | Upload résumé → text + detected skills |
| GET | `/skills/suggest?q=` · `/careers/search?q=` · `/careers/{id}` | Autocomplete & career detail |
| GET/POST | `/assessment/questions` · `/assessment` | RIASEC quiz |
| POST | `/jobs/fit` | Job-description readiness |
| GET/DELETE | `/history` · `/export/{run_id}.{md,json}` · `/export/history.{md,json}` | History (scoped to user when signed in) |
| GET/POST | `/auth/providers` · `/auth/firebase` · `/auth/me` · `/auth/logout` · `/auth/magic-link…` | Authentication |
| GET/POST/PUT/DELETE | `/me/runs` · `/me/progress` · `/me/prefs` · `/me/feedback` · `/me` | Account (auth required) |
| GET/POST | `/billing/plans` · `/billing/me` · `/billing/trial/start` · `/billing/checkout` · `/billing/webhook` · `/billing/demo-request` | Plans, trial, Razorpay checkout + webhook (501 while keys are unset); demo-request stores an institute lead (admin reads via `/billing/demo-requests`) |
| POST/GET | `/billing/subscribe` · `/billing/coupon/validate` · `/billing/admin/coupons` · `/me/referral` | Phase 9: Razorpay subscriptions (501 while keys unset, 409 while the plan's `RAZORPAY_*_PLAN_ID` is unset; webhook handles `subscription.*` events idempotently); coupon preview (no state change — redemption happens atomically inside checkout); coupon create/list/deactivate is platform-admin only + audit-logged; `/me/referral` returns my referral code + attribution counts (referrals are attribution-only — no discount exists unless an admin creates a coupon) |
| GET/PATCH/PUT/DELETE | `/admin/overview` · `/admin/users…` · `/admin/runs…` · `/admin/feedback…` · `/admin/resources…` · `/admin/audit` | Admin (admin role required) |
| GET/POST | `/skills/verify/quizzes` · `/skills/verify/{skill}/quiz` · `/skills/verify/{skill}/submit` · `/skills/verify/{skill}/project` · `/skills/verify/mine` | Phase 3 skill verification (auth required; answer keys never leave the server) |
| POST | `/skills/verify/admin/review` | Approve/reject a submitted project (platform admin, or an institute_admin/counsellor for a student of their own institute) |
| GET/POST/PATCH/DELETE | `/institutes` · `/institutes/mine` · `/institutes/{id}/members` · `/institutes/{id}/invites` · `/institutes/{id}/invites/csv` · `/institutes/{id}/cohort` · `/institutes/{id}/students…` · `/institutes/{id}/cohort/report.{csv,pdf}` · `/institutes/{id}/review-queue` · `/institutes/{id}/runs/{run_id}/review` · `/institutes/invites/claim` · `/institutes/reviews/mine` | Phase 4 institute portal: one institute per user, seat-limited invites (pending invites reserve a seat; default seat limit is a documented constant until the owner sets plan config), aggregate-first cohort (no e-mails), counsellor run reviews labelled "Reviewed by counsellor". Phase 9 analytics v2: `cohort?period=current\|previous` adds term-over-term comparison (a term is a **calendar quarter**; current vs previous quarter aggregates + deltas, honest zeros for an empty period), review-queue returns unreviewed runs only (oldest first, `limit`/`offset`), and `PATCH /institutes/{id}` accepts `report_schedule` (`none\|weekly\|monthly` — a preference record with a nominal `next_run`; **no scheduler sends reports yet**) |
| POST/GET/DELETE | `/institutes/{id}/api-keys` | Phase 10 institute API keys: create (raw `cgk_…` key returned ONCE; only its SHA-256 hash is stored), list metadata, revoke — institute_admin of that institute or a platform admin, audit-logged |
| GET | `/public/institutes/{slug}/cohort` · `/public/institutes/{slug}/top-careers` | Phase 10 public institute API: `X-API-Key` header ONLY (a session cookie does not authenticate); the key must belong to the institute named by `{slug}` (valid key + wrong slug → 404); aggregates only — the Phase 4 cohort payload with the needs-attention list reduced to a count, never e-mails/names/user ids; 401 missing/wrong/revoked key; rate-limited 30/min per key |
| GET | `/p/{handle}` | Public profile (opt-in only; 404 for non-opted-in users and minors) |
| PUT | `/me/public-profile` | Set profile handle, opt-in and under-18 flag (auth required) |
| POST/GET/PATCH | `/plan/90day` · `/plan/90day/{id}/tasks` · `/plan/90day/export.{md,ics}` | 90-day plan from a recommendation run (auth required) |
| GET/PUT | `/me/age-declaration` · `/me/consent` · `/me/consent/request` · `/me/consent/revoke` · `/consent/confirm/{token}` | Phase 5 privacy: least-data age declaration + versioned parental-consent flow (confirm link is public, token-secured) |
| GET/PUT | `/admin/india-market` | Phase 2 India market overrides editor (admin only, audit-logged); Reality Score data layer in `career_guidance/india.py` + `reality.py` |
| POST/GET/DELETE | `/runs/{run_id}/share` · `/runs/{run_id}/shares` · `/runs/{run_id}/share/{token_id}` | Phase 8 share links (owner only; guest session for anonymous runs): create (expiry 1–30 days, default 7), list, revoke. Token stored as SHA-256 hash only, raw token shown once |
| GET | `/shared/{token}` | Phase 8 public shared-report view — rate-limited, built from a field allowlist (titles, match %, skills, Reality Score, labelled-estimate salary ladder, learning path); never owner identity/constraints/profile text. 404 unknown, 410 expired/revoked |

The recommendation contract (`run_id`, `provider`, `is_demo`, `priority_skills`,
`recommendations[]` with `match_score`, `matching/missing_skills`,
`learning_path`, `next_steps`, `market`, `resources`, `provenance`) is frozen
in [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md#4-api-contract-frozen-at-end-of-p0).

## PWA & offline (Phase 8)

The app is an installable PWA. `frontend/public/manifest.webmanifest`
(name, icons 192/512/maskable/SVG, theme `#0f0f0f` matching
`styles/tokens.css`, `start_url: /`) and the hand-written service worker
`frontend/public/sw.js` (cache version `cg-v4`) ship in `frontend/public/`,
so the static export copies both verbatim — verified in the
`NEXT_EXPORT=1` build output. Caching rules, exactly as shipped:
critical shell assets are precached at install (`/`, `/explore` best
effort), static assets (`/_next/static/*`, images, fonts) are
cache-first, navigations are network-first with a cache/offline
fallback, and **`/api/*` is never cached**. The worker does not
self-activate: an update surfaces an "update available" toast and only
then skips waiting. Offline fallback is the dependency-free
`frontend/public/sw-offline.html` (named distinctly because the export
emits the localised `/offline` route to `out/offline.html`); the backend
SPA fallback serves `sw.js` with `Cache-Control: no-cache`. The worker
is same-origin, covered by the report-only CSP's `script-src 'self'`
(see `docs/SECURITY.md`).

## Quality gates

```bash
make ci           # lint + test + coverage gate (≥ 85 %) + eval — the CI round
make lint         # ruff check + format, eslint, tsc --noEmit
make test         # 468 pytest tests (core, API, auth, admin, journey, golden set, phases 1–8)
make cov          # coverage over career_guidance + backend, fails under 85 %
make eval         # offline matcher: 50 golden profiles + 7 interest profiles, then the Phase 7 faithfulness + chat-grounding eval (eval/run_chat_eval.py; also `make eval-chat`)
make blackbox     # 43-check HTTP round against a running API (add API=https://…)
make blackbox-prod  # the same round against Render and the Vercel origin
```

Current numbers (Phase 8 gate run, 2026-11-06): **468 pytest passed · skills Hit@5 1.0
(MRR 0.827) · interests Hit@5 1.0 · eval p95 ≈ 128 ms · coverage 91 % (91.23 %; new
Phase 8 modules: `career_guidance/sharing.py` 96 %, `backend/sharing.py` 97 %)** ·
faithfulness 4/4, chat grounding 8/8 (`eval/run_chat_eval.py`). Semantic blend
(Phase 7, opt-in `SEMANTIC_MATCHING_ENABLED`, TF-IDF w=0.25) measured separately:
Hit@5 1.0, MRR 0.888 — ships OFF by default (see `career_guidance/semantic.py`).
First-load JS (export build table): `/` 257 kB, `/report/[runId]` 259 kB (chat +
share panels code-split into lazy chunks), **`/shared/[token]` 218 kB and
`/offline` 155 kB — within the 245 kB budget**. Most other app routes sit at
**253–268 kB — over the 245 kB budget** — driven by the ~103 kB shared bundle
(i18n dictionary included); within budget: `/methodology` 206 kB, `/p/[handle]` 211 kB,
`/start` 216 kB, `/privacy` 149 kB. Splitting the shared i18n bundle is the known
Phase 10 fix; the overage is structural and pre-dates Phase 6.
CI (`.github/workflows/ci.yml`) runs lint, tests, the coverage gate and the eval on
every push and PR, and fails if Hit@5 drops below 0.75.

Every number above is reproducible; the sandbox-side limits (no browser, no
Firebase) and the manual steps that close them are listed in
[`docs/TEST_REPORT.md`](docs/TEST_REPORT.md).

## Deployment

The multi-stage `Dockerfile` builds the static Next.js export and serves it
with the API from one uvicorn process on port **8000** (non-root, healthcheck,
proxy headers enabled). `docker-compose.yml` adds a persistent volume for the
SQLite database and forwards the `NEXT_PUBLIC_FIREBASE_*` build args from `.env`.

```bash
docker compose up --build -d
```

Any container host (Render, Railway, Fly.io, a VPS) works — set the env vars
from the table above through the host's secret manager, and mount a volume at
`/app/data`. Set `APP_ENV=production` and a strong `SESSION_SECRET`.

**Run / deploy / rollback** — the full runbook (Render + Vercel steps,
backup/restore scripts, readiness checks) lives in
[`docs/DEPLOY.md`](docs/DEPLOY.md). Rollback in one line: Render → redeploy
the previous deploy; Vercel → promote the previous deployment; migrations
are additive, so the database never needs rolling back with the code
(restore from `scripts/restore_db.py` only if the data itself is bad).

**Postgres option (Phase 6)** — SQLite is the default. Setting
`DATABASE_URL=postgres://…` (plus `pip install -r requirements-postgres.txt`)
moves the core recommendation store and the migration runner to Postgres
through the central dialect layer (`career_guidance/db.py`). The remaining
per-feature stores still use the SQLite file — see the decision table and
smoke procedure in `docs/DEPLOY.md` §6 before considering a cutover.

**Observability (Phase 6)** — JSON-line logs with propagated
`X-Request-ID`s; `/api/v1/health` is liveness, `/api/v1/ready` is
readiness (DB + catalog, 503 with a component breakdown). Optional
`ERROR_WEBHOOK_URL` receives minimal error JSON on unhandled 500s.
The public `/status` page renders both checks live in the browser.

**Scale & trust (Phase 10)** — public catalog responses cached
in-process (300 s TTL, `career_guidance/cache.py`; details +
`/recommend` bench method in `docs/PERFORMANCE.md`); migration v10
adds per-user indexes for the hot lookups; the frontend i18n
dictionaries are split per locale (EN bundled, TA/HI lazy) so every
route's first-load JS is ≤245 kB; accessibility audit + fixes in
`docs/ACCESSIBILITY.md`. `.env.example` was re-audited against the
code in Phase 10: every env var the code reads is documented there
(frontend `NEXT_PUBLIC_*` vars live in `frontend/.env.example`).

## Project layout

```
├── backend/                 FastAPI adapter
│   ├── main.py              routes, static serving, rate limit
│   ├── auth.py              sessions, Firebase exchange, magic-link fallback, legacy Google OAuth
│   ├── firebase.py          Firebase ID-token verification (Google x509 certs, cached)
│   ├── admin.py             /me and /admin routers
│   ├── assessment.py        RIASEC questions & scoring
│   └── ratelimit.py
├── career_guidance/         core package (UI-agnostic)
│   ├── taxonomy.py          O*NET catalog loader, skill normalisation & synonyms
│   ├── matching.py          hybrid matcher + ROLE_ALIASES
│   ├── market.py            salary/demand adapters (estimates + Adzuna)
│   ├── learning.py          curated resources (+ admin overrides)
│   ├── providers.py         OpenAI (schema-validated) and offline providers
│   ├── suggestions.py       orchestration & fallback
│   ├── storage.py           runs (SQLite)      users.py  users/progress/feedback/audit
│   └── config.py · models.py · profile.py · resume.py · analytics.py
├── frontend/                Next.js 15 app
│   ├── app/                 /, /login, /admin
│   ├── components/          shell, recommend-view, results, assessment, jobfit, history,
│   │                        progress-panel, login-page, admin-view, require-auth, motion (primitives)
│   └── lib/                 api.ts, auth-context.tsx, firebase.ts, i18n.tsx (en/ta/hi), types.ts
├── data/                    catalog/occupations.json (974), learning_resources.yaml
├── eval/                    golden.json (50 profiles), run.py
├── tests/                   pytest suite
├── scripts/build_catalog.py O*NET → catalog
├── docs/                    MASTER_PLAN.md, RESEARCH_ROADMAP.md
├── Dockerfile · docker-compose.yml · Makefile · .github/workflows/ci.yml
├── app.py                   ASGI entry point (exports `app` for platform auto-detect)
└── streamlit_app.py         legacy Streamlit UI (reference only)
```

## Roadmap & docs

- [`SELLING.md`](SELLING.md) — sell-standard status and go-live checklist (prices, Razorpay keys, business details, hosting).
- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — acceptance criteria R1–R10 (all met), workstreams, API contract, status table.
- [`docs/RESEARCH_ROADMAP.md`](docs/RESEARCH_ROADMAP.md) — research directions (ESCO/CareerBERT embeddings, RAG grounding, market data).

Data: O*NET® is a trademark of the U.S. Department of Labor; content used under
its Creative Commons licence. Learning resources are hand-curated links to
public course pages.

## License

No license file has been added yet — all rights reserved by the repository owner until one is chosen.
