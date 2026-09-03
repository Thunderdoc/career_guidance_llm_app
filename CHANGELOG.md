# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-03

### Added

- Career profile: skills, interests, education, experience level, and goals.
- Resume upload with safe in-memory text extraction (.txt, .md, .pdf via pypdf),
  size limits, and clear failure handling.
- Structured recommendations: match reason, matching skills, missing skills,
  suitability level, ordered learning path, and practical next steps.
- SQLite persistence for recommendation history (`DATABASE_PATH`, default
  `data/career_guidance.db`), encapsulated in a swappable `Database` class.
- Analytics page computed only from real stored data: run totals, most
  recommended careers, most common skill gaps, runs per day.
- Recommendation card UI with skill-gap breakdown and roadmap expander.
- Schema validation for AI responses; unknown suitability values normalized.
- Tests for profiles, resume extraction, recommendations, storage, analytics.

### Changed

- History page now reads from the persistent database instead of the session.
- Demo provider now performs genuine keyword-based skill matching against a
  curated career catalog instead of returning fixed suggestions.

### Removed

- Session-only history module (replaced by database-backed history).

## [1.0.0] - 2026-09-03

### Added

- `career_guidance` package with UI-agnostic core logic, input validation, and logging.
- Pluggable suggestion providers: OpenAI-backed AI provider plus an offline demo provider,
  with automatic fallback when the AI service is unavailable.
- Multi-page Streamlit UI (Career Guidance, History, About) with loading, empty, error,
  and success states, demo-mode banner, and result download.
- Session history with Markdown/JSON export and clear function.
- Configuration via environment variables (`APP_ENV`, `LOG_LEVEL`, `MIN_INPUT_LENGTH`,
  `MAX_INPUT_LENGTH`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`)
  documented in `.env.example`.
- Unit test suite (pytest) covering validation, providers, fallback, history, and formatting.
- GitLab CI/CD pipeline with lint (ruff) and test stages.
- `Dockerfile` for container deployment with health check.
- `pyproject.toml` packaging with semantic versioning.
- `.gitignore`, `CHANGELOG.md`, and professional `README.md`.

### Changed

- `app.py` refactored into a thin Streamlit entry point with error handling.
- `requirements.txt` now pins dependency version ranges.
