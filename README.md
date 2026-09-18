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
| **AI mode** | With `OPENAI_API_KEY`: grounded explanations validated against a strict schema, automatic fallback to offline mode. |
| **UI** | Next.js 15 + React 19 + Motion + Tailwind 4, Motion-Primitives-style animations, honours `prefers-reduced-motion`, PWA manifest, 3 languages. |

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

**Anonymous use is first-class** — recommendations, quiz, job fit and
server-side history all work without an account.

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
| GET | `/health`, `/meta` | Status, mode, catalog size |
| POST | `/recommend` | Profile → 5 recommendations (rate-limited 30/min) |
| POST | `/resume/extract` | Upload résumé → text + detected skills |
| GET | `/skills/suggest?q=` · `/careers/search?q=` · `/careers/{id}` | Autocomplete & career detail |
| GET/POST | `/assessment/questions` · `/assessment` | RIASEC quiz |
| POST | `/jobs/fit` | Job-description readiness |
| GET/DELETE | `/history` · `/export/{run_id}.{md,json}` · `/export/history.{md,json}` | History (scoped to user when signed in) |
| GET/POST | `/auth/providers` · `/auth/firebase` · `/auth/me` · `/auth/logout` · `/auth/magic-link…` | Authentication |
| GET/POST/PUT/DELETE | `/me/runs` · `/me/progress` · `/me/prefs` · `/me/feedback` · `/me` | Account (auth required) |
| GET/PATCH/PUT/DELETE | `/admin/overview` · `/admin/users…` · `/admin/runs…` · `/admin/feedback…` · `/admin/resources…` · `/admin/audit` | Admin (admin role required) |

The recommendation contract (`run_id`, `provider`, `is_demo`, `priority_skills`,
`recommendations[]` with `match_score`, `matching/missing_skills`,
`learning_path`, `next_steps`, `market`, `resources`, `provenance`) is frozen
in [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md#4-api-contract-frozen-at-end-of-p0).

## Quality gates

```bash
make lint      # ruff check + format, eslint, tsc
make test      # 80 pytest tests (core, API, auth, admin, Firebase token verification, golden set)
make eval      # offline matcher on 50 golden profiles → Hit@5 / MRR / p95 latency
```

Current numbers: **Hit@5 0.98 · MRR 0.83 · p95 ≈ 100 ms**; static first-load JS ≈ 225 kB.
CI (`.github/workflows/ci.yml`) runs all three on every push and PR, and fails
if Hit@5 drops below 0.70.

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

- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — acceptance criteria R1–R10 (all met), workstreams, API contract, status table.
- [`docs/RESEARCH_ROADMAP.md`](docs/RESEARCH_ROADMAP.md) — research directions (ESCO/CareerBERT embeddings, RAG grounding, market data).

Data: O*NET® is a trademark of the U.S. Department of Labor; content used under
its Creative Commons licence. Learning resources are hand-curated links to
public course pages.

## License

No license file has been added yet — all rights reserved by the repository owner until one is chosen.
