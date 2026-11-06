"""Application configuration loaded from environment variables."""

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Immutable application settings.

    Attributes:
        app_env: Deployment environment (development, staging, production).
        log_level: Logging verbosity level.
        min_input_length: Minimum number of characters required in user input.
        max_input_length: Maximum number of characters accepted in user input.
        openai_api_key: Optional OpenAI API key; empty means offline demo mode.
        openai_model: OpenAI model used for AI-powered suggestions.
        openai_timeout_seconds: Timeout for OpenAI API requests.
    """

    app_env: str = "development"
    log_level: str = "INFO"
    min_input_length: int = 3
    max_input_length: int = 10_000
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    database_path: str = "data/career_guidance.db"
    # Phase 6: when DATABASE_URL is set it wins over DATABASE_PATH
    # (postgres://… selects Postgres via career_guidance.db; see docs).
    database_url: str = ""
    # Phase 7: multi-provider LLM factory (career_guidance.providers).
    # llm_provider: "" = legacy auto behaviour (OpenAI when its key is set,
    # else Gemini when its key is set, else offline); or openai|gemini|ollama.
    llm_provider: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    llm_timeout_seconds: float = 30.0
    # Phase 7: semantic blend (career_guidance.semantic). Shipping rule:
    # default ON only if the golden eval strictly improves MRR without
    # dropping Hit@5 AND the full test suite stays green with it on.
    # Measured at Phase 7 (TF-IDF blend, w=0.25, three runs incl. a
    # different hash seed, all identical): Hit@5 1.0 → 1.0, MRR
    # 0.827 → 0.888, interests Hit@5 1.0 → 1.0 — the golden rule was met,
    # BUT default-ON broke an existing sanity gate
    # (test_core_v2 skills-only top pick fell to 49.2% match and changed
    # character), so the flag ships OFF by default; opt in per deployment
    # with SEMANTIC_MATCHING_ENABLED=true. See semantic.py docstring.
    semantic_matching_enabled: bool = False
    semantic_blend_weight: float = 0.25
    semantic_embedding_model: str = ""

    @property
    def database_target(self) -> str:
        """The path-or-URL handed to the storage/migration layer."""
        return self.database_url or self.database_path


def load_settings() -> Settings:
    """Build settings from environment variables with safe defaults."""
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        min_input_length=int(os.getenv("MIN_INPUT_LENGTH", "3")),
        max_input_length=int(os.getenv("MAX_INPUT_LENGTH", "10000")),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
        database_path=os.getenv("DATABASE_PATH", "data/career_guidance.db"),
        database_url=os.getenv("DATABASE_URL", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        llm_timeout_seconds=float(
            os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
        ),
        semantic_matching_enabled=os.getenv("SEMANTIC_MATCHING_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"},
        semantic_blend_weight=float(os.getenv("SEMANTIC_BLEND_WEIGHT", "0.25")),
        semantic_embedding_model=os.getenv("SEMANTIC_EMBEDDING_MODEL", ""),
    )


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure and return the application logger."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return logging.getLogger("career_guidance")
