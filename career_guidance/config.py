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
    # else Gemini when its key is set, else offline); or
    # openai|gemini|ollama|llamacpp. ollama needs a local Ollama server;
    # llamacpp loads a GGUF file in-process via llama-cpp-python (Step
    # 8.7, docs/LOCAL_LLM_SETUP.md) and needs LLAMACPP_MODEL_PATH.
    llm_provider: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    # Step 8.7: in-process GGUF model via llama-cpp-python (no server,
    # no key). Empty model path = the provider is not configured.
    # Measured with Qwen2.5-0.5B-Instruct Q4_K_M: ~670 MB peak RSS at
    # n_ctx 2048, ~10 tokens/s generation on 4 CPU threads; the
    # production profile-extractor prompt needs ~1440 tokens, so the
    # default context is 2048 (512 is too small — see
    # docs/LOCAL_LLM_SETUP.md).
    llamacpp_model_path: str = ""
    llamacpp_n_ctx: int = 2048
    llamacpp_n_threads: int = 4
    llamacpp_max_tokens: int = 512
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
    # Kaam-Vaani feature flags (Stage 1). Each flag gates one Kaam-Vaani
    # router (/api/v1/kv/*) and its UI: flag off = the route 404s as if it
    # never existed. Default: ON unless APP_ENV=production (explicit env
    # always wins) — see load_settings. Production stays OFF until staged.
    kv_voice: bool = True
    kv_rag: bool = True
    kv_employers: bool = True
    kv_consent: bool = True
    kv_video_check: bool = True
    kv_pilot: bool = True
    # Kaam-Vaani provider placeholders (Stage 3/8 interfaces). "browser"
    # means the browser-native Web Speech API (free, no key); hosted
    # providers are selected by name here and need their own env keys.
    kv_stt_provider: str = "browser"
    kv_tts_provider: str = "browser"
    kv_share_provider: str = ""
    # Kaam-Vaani dense retrieval (Step 7A). "" = hybrid only (default);
    # a sentence-transformers model id (e.g.
    # "intfloat/multilingual-e5-small") fuses dense rankings with the
    # hybrid by RRF. Needs the sentence-transformers + torch packages;
    # without them the router logs a warning and stays hybrid-only.
    kv_dense_model: str = ""
    # Step 8.9: agent trace log. Empty file path = memory ring only
    # (no file sink); a path enables the size-rotated JSONL sink.
    kv_trace_file: str = ""
    kv_trace_max_traces: int = 200

    @property
    def database_target(self) -> str:
        """The path-or-URL handed to the storage/migration layer."""
        return self.database_url or self.database_path


def load_settings() -> Settings:
    """Build settings from environment variables with safe defaults."""
    app_env = os.getenv("APP_ENV", "development")

    def kv_flag(name: str) -> bool:
        """One Kaam-Vaani flag: explicit env wins; unset = ON unless production."""
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            return app_env != "production"
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    return Settings(
        app_env=app_env,
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
        llamacpp_model_path=os.getenv("LLAMACPP_MODEL_PATH", "").strip(),
        llamacpp_n_ctx=int(os.getenv("LLAMACPP_N_CTX", "2048")),
        llamacpp_n_threads=int(os.getenv("LLAMACPP_N_THREADS", "4")),
        llamacpp_max_tokens=int(os.getenv("LLAMACPP_MAX_TOKENS", "512")),
        llm_timeout_seconds=float(
            os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
        ),
        semantic_matching_enabled=os.getenv("SEMANTIC_MATCHING_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"},
        semantic_blend_weight=float(os.getenv("SEMANTIC_BLEND_WEIGHT", "0.25")),
        semantic_embedding_model=os.getenv("SEMANTIC_EMBEDDING_MODEL", ""),
        kv_voice=kv_flag("KV_VOICE"),
        kv_rag=kv_flag("KV_RAG"),
        kv_employers=kv_flag("KV_EMPLOYERS"),
        kv_consent=kv_flag("KV_CONSENT"),
        kv_video_check=kv_flag("KV_VIDEO_CHECK"),
        kv_pilot=kv_flag("KV_PILOT"),
        kv_stt_provider=os.getenv("KV_STT_PROVIDER", "browser").strip().lower() or "browser",
        kv_tts_provider=os.getenv("KV_TTS_PROVIDER", "browser").strip().lower() or "browser",
        kv_share_provider=os.getenv("KV_SHARE_PROVIDER", "").strip().lower(),
        kv_dense_model=os.getenv("KV_DENSE_MODEL", "").strip(),
        kv_trace_file=os.getenv("KV_TRACE_FILE", "").strip(),
        kv_trace_max_traces=int(os.getenv("KV_TRACE_MAX_TRACES", "200")),
    )


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure and return the application logger."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return logging.getLogger("career_guidance")
