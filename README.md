# 🎓 Career Guidance AI

A **Streamlit** career intelligence platform that turns a user's profile
(skills, interests, education, experience, goals, and optionally a resume)
into structured, actionable career recommendations.

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
streamlit run app.py
```

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

## Development & testing

```bash
pip install -r requirements-dev.txt
ruff check .    # lint
pytest          # run tests
```

The GitLab CI pipeline runs the same lint and test stages on every push.

## Deployment

### Streamlit Community Cloud (simplest)

1. Connect the repository at https://share.streamlit.io
2. Select `app.py` as the entry point.
3. Add `OPENAI_API_KEY` (optional) under app **Secrets**.

### Docker (Render, Railway, Fly.io, any container host)

```bash
docker build -t career-guidance-app .
docker run -p 8501:8501 --env-file .env career-guidance-app
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
