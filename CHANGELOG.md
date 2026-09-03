# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
