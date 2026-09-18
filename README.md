# 🎓 Career Guidance AI

A career intelligence platform that turns a user's profile
(skills, interests, education, experience, goals, and optionally a resume)
into structured, actionable career recommendations — grounded in the
**O*NET taxonomy (974 occupations)**, with skill-gap analysis, learning
roadmaps, salary/demand signals, a RIASEC interest quiz, and job-description fit.

**v2 stack:** FastAPI backend (`backend/`) + animated Next.js / Motion / Tailwind
front end (`frontend/`, Motion-Primitives style), available in English, Tamil and
Hindi. The legacy Streamlit UI (`app.py`) is kept only for reference.

## Quick start (one command)

```bash
docker compose up --build        # → http://localhost:8000
```

## Quick start (dev)

```bash
make install                     # python deps + frontend npm install
make api                         # FastAPI on :8000  (docs at /api/docs)
make web                         # Next.js dev on :3000 (proxies /api → :8000)
```

Quality gates: `make test` (pytest + golden-set Hit@5 ≥ 0.70), `make lint`,
`make eval` (prints Hit@5 / MRR / p95 latency; currently **Hit@5 0.98**).

It runs in two clearly separated modes:

- **AI mode**: with `OPENAI_API_KEY` configured, an LLM generates structured
  recommendations that are schema-validated before display.
- **Demo mode**: without a key, the app performs genuine offline keyword-based
  skill matching against a curated career catalog, clearly labeled as demo.
  If the AI service fails, the app automatically falls back and tells you.

## User workflow

1. **Build a career profile**: skills (required), interests, education,
   experience level, career goals, and an optional resume upload
   (.txt / .md / .pdf, max 5 MB, extracted safely in memory).
2. **Get recommendations**: 5 career paths, each with:
   - why it matches your profile
   - matching skills you already have
   - missing skills (skill-gap analysis)
   - suitability level (beginner / intermediate / advanced)
   - an ordered learning path
   - practical short-term next steps (projects, certifications, actions)
3. **Review history**: every run is persisted to SQLite; export as
   Markdown or JSON, or clear it.
4. **Analytics**: real metrics from your stored runs only - totals,
   most recommended careers, most common skill gaps, runs per day.

## Architecture

```
├── app.py                     # Streamlit UI (Recommendations, History, Analytics, About)
├── career_guidance/           # Core package (UI-agnostic)
│   ├── config.py              # Settings & logging (env-based)
│   ├── models.py              # Domain models & exceptions
│   ├── profile.py             # Career profile: validation & prompt building
│   ├── resume.py              # Safe resume text extraction (.txt/.md/.pdf)
│   ├── providers.py           # Backends: OpenAI (structured JSON) + offline matching
│   ├── suggestions.py         # Orchestration, validation, fallback
│   ├── storage.py             # SQLite persistence (swappable Database class)
│   └── analytics.py           # Metrics computed from real stored data
├── tests/                     # Unit tests (pytest)
├── Dockerfile                 # Container image for deployment
├── .env.example               # Documented environment variables
└── .gitlab-ci.yml             # CI pipeline (lint, test)
```

### AI architecture

- The UI never calls external APIs directly; it calls `generate_recommendations`,
  which validates the profile, selects a provider, and handles failures.
- The **OpenAI provider** sends the profile with a strict system prompt that
  requires a JSON array of 5 recommendation objects. Responses are parsed and
  **validated against the expected schema**; invalid suitability values are
  normalized, and unparseable responses raise a `ProviderError`.
- On any provider failure the app **falls back to offline matching** and shows
  a clear notice - AI results are never fabricated.
- API keys come only from environment variables and are never logged or stored.

### Database architecture

- `storage.Database` encapsulates all SQLite access (single table
  `recommendation_runs` with an index on `created_at`). Runs store the
  provider, demo flag, profile snapshot, and recommendations as JSON.
- The path is configurable via `DATABASE_PATH` (default `data/career_guidance.db`,
  gitignored). Only a short resume excerpt is stored, not the full resume.
- Because all storage goes through one class, SQLite can be swapped for
  Postgres or another backend without touching the UI or core logic.
- Note: on ephemeral hosts (e.g. Streamlit Community Cloud) the local database
  resets on redeploy; point `DATABASE_PATH` at a persistent volume for
  durable history.

## Requirements

- Python 3.10+
- pip

## Setup

```bash
git clone https://gitlab.com/avenger-claude-group/career_guidance_llm_app.git
cd career_guidance_llm_app
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit values as needed
```

## Run the app

```bash
uvicorn backend.main:app --reload          # API + (after `make build`) the static UI
cd frontend && npm run dev                 # animated UI with hot reload
streamlit run app.py                       # legacy UI
```

## Accounts & admin console

Anonymous use is first-class — nothing requires sign-in. Signing in at `/login`
(**Firebase Authentication**: Google or e-mail + password; e-mail magic link is
the no-dependency fallback when Firebase is not configured) keeps your runs across devices, adds a skill-progress
checklist, and lets you delete your data. Any e-mail listed in `ADMIN_EMAILS`
becomes an **admin** and sees the **Admin** section in the sidebar:

| Tab | What it does |
| --- | --- |
| Overview | users / runs / feedback KPIs, runs-per-day, top careers, most-missing skills, system info |
| Users | search, promote/demote admin, disable/enable, delete user + their data |
| Runs | every recommendation run (user or anonymous), delete |
| Feedback | 1–5★ ratings & comments from users, triage new → reviewed → resolved |
| Content | edit the learning resources shown per skill (DB overrides on top of `data/learning_resources.yaml`) |
| Audit | log of logins and admin actions |

**E-mail verification is enforced**: after sign-up Firebase sends a verification
link; the client signs the user out until it is clicked, and the backend
independently rejects any email/password ID token whose `email_verified` is not
true. Google users are already verified by Google. Protected pages use the
`<RequireAuth>` guard (`/admin` also needs `admin`), and every `/api/v1/me/*`
and `/api/v1/admin/*` route enforces authentication/authorisation server-side
(role is read from the database, never from the client).

Set-up (see `.env.example` and `frontend/.env.example`): `FIREBASE_PROJECT_ID`
+ `NEXT_PUBLIC_FIREBASE_*` public web config, `SESSION_SECRET`, `ADMIN_EMAILS`. In the Firebase console enable **Authentication → Sign-in
method → Google** and **Email/Password**, and add your domain under
**Authentication → Settings → Authorised domains**. The backend verifies Firebase
ID tokens against Google's public certificates and issues its own HttpOnly
session cookie; no service account is required for that. Keep any
service-account JSON under `secrets/` (git-ignored).
Without SMTP the magic link is printed to the server log and, outside
production, shown in the sign-in dialog so you can test locally.

## Configuration

All configuration is via environment variables (see `.env.example`).
**Never commit real API keys.**

| Variable                 | Default                    | Description                                |
| ------------------------ | -------------------------- | ------------------------------------------ |
| `APP_ENV`                | `development`              | Deployment environment name                |
| `LOG_LEVEL`              | `INFO`                     | Logging verbosity                          |
| `MIN_INPUT_LENGTH`       | `3`                        | Minimum accepted profile length            |
| `MAX_INPUT_LENGTH`       | `10000`                    | Maximum accepted profile length            |
| `OPENAI_API_KEY`         | *(empty)*                  | Enables AI mode; empty = offline demo mode |
| `OPENAI_MODEL`           | `gpt-4o-mini`              | Model used for AI recommendations          |
| `OPENAI_TIMEOUT_SECONDS` | `30`                       | Timeout for AI requests                    |
| `DATABASE_PATH`          | `data/career_guidance.db`  | SQLite database location                   |
| `SESSION_SECRET`         | *(dev default)*            | Signs session cookies — set in production  |
| `PUBLIC_URL`             | *(derived from request)*   | Public origin for OAuth/e-mail links       |
| `ADMIN_EMAILS`           | *(empty)*                  | Comma-separated admin e-mails              |
| `GOOGLE_CLIENT_ID/SECRET`| *(empty)*                  | Enables "Continue with Google"             |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | *(empty)*       | Sends magic-link e-mails                   |

## Development & testing

```bash
pip install -r requirements-dev.txt
ruff check .    # lint
pytest          # run tests
```

The GitLab CI pipeline runs the same lint and test stages on every push.

## Deployment

### Docker (Render, Railway, Fly.io, any container host)

The multi-stage `Dockerfile` builds the static Next.js export and serves it,
together with the API, from a single uvicorn process on port **8000**.

```bash
docker build -t career-guidance-app .
docker run -p 8000:8000 --env-file .env career-guidance-app
```

Mount a volume and set `DATABASE_PATH` to keep history across restarts.
Configure secrets through your platform's secret management, never in the
image or repository.

## Versioning

This project follows [Semantic Versioning](https://semver.org). See
[CHANGELOG.md](CHANGELOG.md) for release history. The current version is
defined in `career_guidance/__init__.py` and `pyproject.toml`.

## Future improvements

- User accounts with per-user history (requires authentication design)
- Additional LLM providers and provider selection in the UI
- Career comparison view and richer skill-gap visualization
- REST API for programmatic access
