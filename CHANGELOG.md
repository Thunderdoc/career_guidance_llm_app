# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-03

### Added

- `career_guidance` package with UI-agnostic suggestion logic, input validation, and logging.
- Configuration via environment variables (`APP_ENV`, `LOG_LEVEL`, `MIN_INPUT_LENGTH`, `MAX_INPUT_LENGTH`).
- Unit test suite (pytest) covering validation, suggestions, and Markdown formatting.
- GitLab CI/CD pipeline with lint (ruff) and test stages.
- `pyproject.toml` packaging with semantic versioning.
- `.gitignore`, `CHANGELOG.md`, and professional `README.md`.

### Changed

- `app.py` refactored into a thin Streamlit entry point with error handling.
- `requirements.txt` now pins dependency version ranges.

### Removed

- Unused `openai` dependency (the current version runs fully offline).
