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
    """

    app_env: str = "development"
    log_level: str = "INFO"
    min_input_length: int = 3
    max_input_length: int = 10_000


def load_settings() -> Settings:
    """Build settings from environment variables with safe defaults."""
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        min_input_length=int(os.getenv("MIN_INPUT_LENGTH", "3")),
        max_input_length=int(os.getenv("MAX_INPUT_LENGTH", "10000")),
    )


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure and return the application logger."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return logging.getLogger("career_guidance")
