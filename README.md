# 🎓 Career Guidance AI App

A **Streamlit** application that suggests career paths based on your resume
summary, skills, or interests.

The current release returns a curated set of suggestions and runs fully
offline. The core logic is UI-agnostic, so an LLM-backed provider can be
plugged in later without changing the interface.

## Features

- Accepts a resume summary or skill list with input validation
- Returns five career suggestions with rationale
- Runs fully offline (no API key or internet required)
- Structured logging and environment-based configuration
- Unit-tested core logic and CI pipeline (lint + tests)

## Project structure

```
├── app.py                     # Streamlit entry point
├── career_guidance/           # Core package (UI-agnostic)
│   ├── config.py              # Settings & logging
│   └── suggestions.py         # Validation & suggestion logic
├── tests/                     # Unit tests (pytest)
├── requirements.txt           # Runtime dependencies
├── requirements-dev.txt       # Development dependencies
├── pyproject.toml             # Packaging & tool configuration
└── .gitlab-ci.yml             # CI pipeline (lint, test)
```

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
```

## Run the app

```bash
streamlit run app.py
```

## Configuration

| Variable           | Default       | Description                          |
| ------------------ | ------------- | ------------------------------------ |
| `APP_ENV`          | `development` | Deployment environment name          |
| `LOG_LEVEL`        | `INFO`        | Logging verbosity                    |
| `MIN_INPUT_LENGTH` | `3`           | Minimum accepted input length        |
| `MAX_INPUT_LENGTH` | `10000`       | Maximum accepted input length        |

## Development

```bash
pip install -r requirements-dev.txt
ruff check .    # lint
pytest          # run tests
```

## Versioning

This project follows [Semantic Versioning](https://semver.org). See
[CHANGELOG.md](CHANGELOG.md) for release history. The current version is
defined in `career_guidance/__init__.py` and `pyproject.toml`.
