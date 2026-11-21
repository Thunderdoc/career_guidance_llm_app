"""Kaam-Vaani feature flags (Stage 1).

Backend flags live on :class:`career_guidance.config.Settings` (``KV_*``
env vars, default ON unless ``APP_ENV=production``). This module is the
single place that maps a flag NAME to its setting, so routers and tests
never spell out attribute names twice.

Flag names (env var in brackets): voice (``KV_VOICE``), rag (``KV_RAG``),
employers (``KV_EMPLOYERS``), consent (``KV_CONSENT``), video_check
(``KV_VIDEO_CHECK``), pilot (``KV_PILOT``). The frontend mirrors them in
``frontend/lib/flags.ts`` (``NEXT_PUBLIC_KV_*``).
"""

from __future__ import annotations

from career_guidance.config import Settings

# Canonical flag names, in the order the stages build them.
FEATURE_FLAGS: tuple[str, ...] = (
    "voice",
    "rag",
    "employers",
    "consent",
    "video_check",
    "pilot",
)

_FLAG_ATTRS: dict[str, str] = {
    "voice": "kv_voice",
    "rag": "kv_rag",
    "employers": "kv_employers",
    "consent": "kv_consent",
    "video_check": "kv_video_check",
    "pilot": "kv_pilot",
}


def is_enabled(settings: Settings, flag: str) -> bool:
    """True when the named Kaam-Vaani flag is on. Raises ValueError on an
    unknown flag name (a typo must fail loudly, never silently disable)."""
    attr = _FLAG_ATTRS.get(flag)
    if attr is None:
        raise ValueError(f"Unknown Kaam-Vaani flag: {flag!r} (expected one of {FEATURE_FLAGS})")
    return bool(getattr(settings, attr))


def describe(settings: Settings) -> dict[str, bool]:
    """All flags as ``{name: on/off}`` — for status endpoints and logs."""
    return {flag: is_enabled(settings, flag) for flag in FEATURE_FLAGS}
