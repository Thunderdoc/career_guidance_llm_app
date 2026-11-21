"""STT/TTS gateway (Kaam-Vaani Stage 3).

Provider-agnostic speech interfaces (master prompt §4.2): the voice
flow swaps speech-to-text and text-to-speech providers via the
``KV_STT_PROVIDER`` / ``KV_TTS_PROVIDER`` env vars, default ``browser``.

Providers
---------
* ``browser`` — the device's Web Speech API (``SpeechRecognition`` +
  ``speechSynthesis``), free, no key. Transcription and synthesis run
  IN THE BROWSER; audio never reaches this server. The server-side
  provider objects therefore describe the capability (so the frontend
  and the status endpoint know what is live) and refuse to transcribe
  or synthesise server-side — that refusal is by design, not a gap.
* ``openai`` — OpenAI Whisper (STT) and OpenAI TTS, over plain HTTPS
  with ``httpx`` (no new dependency), reusing the existing
  ``OPENAI_API_KEY``. Available only when the key is set; with no key
  the factory falls back to ``browser`` and says so (never a fake
  "configured" state). Both are mock-tested only — no key exists in
  this build, so no live vendor call has ever been made (see
  ``LIMITATIONS.md``).

Selection mirrors ``career_guidance.providers.ProviderFactory``: an
unknown provider name logs a warning and falls back to ``browser``;
a named hosted provider without its key does the same. Callers use
:func:`describe_gateway` to report the configured vs effective
provider honestly — the status endpoint shows both.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from career_guidance.config import Settings
from career_guidance.models import ProviderError

logger = logging.getLogger("career_guidance.kaamvaani.voice")

OPENAI_STT_MODEL = "whisper-1"
OPENAI_TTS_MODEL = "tts-1"
OPENAI_TTS_VOICE = "alloy"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# BCP-47 tags the hosted providers accept per app locale (same Indian
# variants the browser path uses — see frontend/lib/speech.ts).
SPEECH_LANG = {"en": "en-IN", "hi": "hi-IN", "ta": "ta-IN"}


@dataclass(frozen=True)
class Transcription:
    """One transcription result: the text plus the provider's
    confidence when it reports one (None for providers that do not)."""

    text: str
    confidence: float | None = None


class STTProvider(ABC):
    """Speech-to-text: audio bytes in, transcript out."""

    name: str = "base"
    # True when transcription runs on the user's device, not here.
    client_side: bool = False

    @abstractmethod
    def available(self, settings: Settings) -> bool:
        """True when this provider can serve right now (key present,
        endpoint reachable — checked cheaply, no network call)."""

    @abstractmethod
    def transcribe(self, audio: bytes, language: str) -> Transcription:
        """Transcribe ``audio`` (any format the provider accepts) spoken
        in ``language`` (an app locale: en/hi/ta). Raises
        :class:`ProviderError` when the provider cannot serve."""

    def describe(self, settings: Settings) -> dict:
        """Capability dict for the status endpoint and the frontend."""
        return {
            "provider": self.name,
            "client_side": self.client_side,
            "available": self.available(settings),
        }


class TTSProvider(ABC):
    """Text-to-speech: text in, audio bytes out."""

    name: str = "base"
    client_side: bool = False

    @abstractmethod
    def available(self, settings: Settings) -> bool:
        """True when this provider can serve right now."""

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Speak ``text`` in ``language``; returns audio bytes (mp3 for
        the OpenAI provider). Raises :class:`ProviderError` when the
        provider cannot serve."""

    def describe(self, settings: Settings) -> dict:
        """Capability dict for the status endpoint and the frontend."""
        return {
            "provider": self.name,
            "client_side": self.client_side,
            "available": self.available(settings),
        }


class BrowserSTTProvider(STTProvider):
    """The browser's Web Speech API: transcription runs on the device
    (in Chrome, via Google's speech service — see the privacy note in
    the voice UI). No key, always available where the browser supports
    it. ``transcribe`` refuses by design: this server never receives
    audio, so there is nothing to transcribe here."""

    name = "browser"
    client_side = True

    def available(self, settings: Settings) -> bool:
        return True

    def transcribe(self, audio: bytes, language: str) -> Transcription:
        raise ProviderError(
            "Browser STT runs client-side (Web Speech API) — send the "
            "transcript text to /api/v1/kv/voice/extract, not audio."
        )


class BrowserTTSProvider(TTSProvider):
    """The browser's speechSynthesis: synthesis runs on the device.
    ``synthesize`` refuses by design — the frontend speaks the text
    itself (see frontend/lib/speech.ts)."""

    name = "browser"
    client_side = True

    def available(self, settings: Settings) -> bool:
        return True

    def synthesize(self, text: str, language: str) -> bytes:
        raise ProviderError(
            "Browser TTS runs client-side (speechSynthesis) — the frontend speaks the text itself."
        )


def _request_with_retry(call, label: str):
    """Run ``call`` with one retry on transient failure (2 attempts
    total), mirroring ``career_guidance.providers._with_retry``."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return call()
        except _NonTransient:
            raise
        except Exception as error:  # noqa: BLE001 - normalised below
            last_error = error
            if attempt == 0:
                time.sleep(0.05)
    raise ProviderError(f"{label} request failed: {last_error}") from last_error


class _NonTransient(Exception):
    """Internal marker: do not retry this failure."""


class OpenAIWhisperSTTProvider(STTProvider):
    """OpenAI Whisper via the ``/audio/transcriptions`` REST endpoint
    (plain ``httpx`` multipart — no new dependency). The key is the
    existing ``OPENAI_API_KEY``; ``transport`` is injectable so tests
    use ``httpx.MockTransport``. Available only with the key set."""

    name = "openai"
    client_side = False

    def __init__(self, settings: Settings, transport=None) -> None:
        self._settings = settings
        self._transport = transport

    def available(self, settings: Settings) -> bool:
        return bool(settings.openai_api_key)

    def transcribe(self, audio: bytes, language: str) -> Transcription:
        import httpx

        settings = self._settings
        if not settings.openai_api_key:
            raise ProviderError("OpenAI STT is not configured (no OPENAI_API_KEY).")
        if not audio:
            raise ProviderError("No audio to transcribe.")

        def attempt() -> dict:
            with httpx.Client(
                timeout=settings.llm_timeout_seconds or settings.openai_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{OPENAI_BASE_URL}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    files={"file": ("speech.webm", audio, "audio/webm")},
                    data={
                        "model": OPENAI_STT_MODEL,
                        "language": SPEECH_LANG.get(language, language)[:2],
                    },
                )
            if response.status_code in (429, 500, 502, 503, 504):
                raise ProviderError(f"transient HTTP {response.status_code}")
            if response.status_code >= 400:
                raise _NonTransient(f"HTTP {response.status_code}")
            return response.json()

        try:
            data = _request_with_retry(attempt, "OpenAI STT")
        except _NonTransient as error:
            raise ProviderError(f"OpenAI STT request failed: {error}") from error
        text = str(data.get("text", "")).strip()
        if not text:
            raise ProviderError("The OpenAI STT response contained no text.")
        return Transcription(text=text)


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS via the ``/audio/speech`` REST endpoint (plain
    ``httpx``). Returns mp3 bytes. The key is the existing
    ``OPENAI_API_KEY``; available only with the key set."""

    name = "openai"
    client_side = False

    def __init__(self, settings: Settings, transport=None) -> None:
        self._settings = settings
        self._transport = transport

    def available(self, settings: Settings) -> bool:
        return bool(settings.openai_api_key)

    def synthesize(self, text: str, language: str) -> bytes:
        import httpx

        settings = self._settings
        if not settings.openai_api_key:
            raise ProviderError("OpenAI TTS is not configured (no OPENAI_API_KEY).")
        if not text.strip():
            raise ProviderError("No text to speak.")

        def attempt() -> bytes:
            with httpx.Client(
                timeout=settings.llm_timeout_seconds or settings.openai_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{OPENAI_BASE_URL}/audio/speech",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": OPENAI_TTS_MODEL,
                        "voice": OPENAI_TTS_VOICE,
                        "input": text,
                    },
                )
            if response.status_code in (429, 500, 502, 503, 504):
                raise ProviderError(f"transient HTTP {response.status_code}")
            if response.status_code >= 400:
                raise _NonTransient(f"HTTP {response.status_code}")
            return response.content

        try:
            audio = _request_with_retry(attempt, "OpenAI TTS")
        except _NonTransient as error:
            raise ProviderError(f"OpenAI TTS request failed: {error}") from error
        if not audio:
            raise ProviderError("The OpenAI TTS response contained no audio.")
        return audio


def get_stt_provider(settings: Settings, transport=None) -> STTProvider:
    """The effective STT provider for ``settings``: the configured
    hosted provider when it can serve, else the browser fallback (with
    a warning logged, so a misconfiguration is visible in the logs)."""
    configured = (settings.kv_stt_provider or "browser").strip().lower()
    if configured == "openai":
        provider = OpenAIWhisperSTTProvider(settings, transport=transport)
        if provider.available(settings):
            return provider
        logger.warning("KV_STT_PROVIDER=openai but no OPENAI_API_KEY; using browser STT")
        return BrowserSTTProvider()
    if configured != "browser":
        logger.warning("Unknown KV_STT_PROVIDER %r; using browser STT", configured)
    return BrowserSTTProvider()


def get_tts_provider(settings: Settings, transport=None) -> TTSProvider:
    """The effective TTS provider for ``settings`` (same fallback rules
    as :func:`get_stt_provider`)."""
    configured = (settings.kv_tts_provider or "browser").strip().lower()
    if configured == "openai":
        provider = OpenAITTSProvider(settings, transport=transport)
        if provider.available(settings):
            return provider
        logger.warning("KV_TTS_PROVIDER=openai but no OPENAI_API_KEY; using browser TTS")
        return BrowserTTSProvider()
    if configured != "browser":
        logger.warning("Unknown KV_TTS_PROVIDER %r; using browser TTS", configured)
    return BrowserTTSProvider()


def describe_gateway(settings: Settings) -> dict:
    """Configured vs effective provider for STT and TTS, honestly: when
    a hosted provider is configured but unusable (no key), the report
    says so instead of pretending the hosted path is live."""
    stt = get_stt_provider(settings)
    tts = get_tts_provider(settings)
    return {
        "stt": {
            "configured": (settings.kv_stt_provider or "browser").strip().lower(),
            "effective": stt.name,
            **stt.describe(settings),
        },
        "tts": {
            "configured": (settings.kv_tts_provider or "browser").strip().lower(),
            "effective": tts.name,
            **tts.describe(settings),
        },
    }
