"""Kaam-Vaani voice router (Stages 1 + 3).

Mounted under ``/api/v1/kv/voice/*`` ONLY when the ``KV_VOICE`` flag is on
(see ``backend/main.py``) — flag off means the route 404s as if it never
existed.

Endpoints
---------
* ``GET /status`` — which voice capabilities are live and how they are
  provided (STT/TTS gateway: configured vs effective provider;
  extraction: "llm" when a provider is configured, else
  "deterministic"; the guided-flow question ids).
* ``POST /extract`` — transcript text in, structured
  :class:`VoiceProfile` out (LLM structured output when configured,
  deterministic fallback otherwise — see
  ``career_guidance.kaamvaani.profile``). Audio is never sent here:
  transcription happens in the browser (Web Speech API) or via a
  hosted STT provider the client calls directly.
* ``POST /confirm`` — the client round-trips its
  :class:`VoiceSession` plus the user-confirmed (possibly edited)
  profile; the server validates the state-machine transition and
  returns the session in its next state. The profile is confirmed by
  the user (voice or tap) before anything uses it — nothing is
  extracted-and-used silently.

Public (no session): the voice flow is guest-first, like ``/health`` and
``POST /recommend``. The server stores no session and no transcript —
the client holds the session in ``sessionStorage`` (resume if
interrupted) and only the confirmed profile leaves the device, to the
same anonymous ``POST /recommend`` the guest flow uses.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from backend.kv_ratelimit import client_key, kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.cache import (
    cached_completer,
    profile_cache,
    profile_cache_key,
)
from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.profile import (
    QUESTION_IDS,
    VoiceSession,
    extract_profile_guided,
    extract_profile_smart,
    load_prompt,
    transition,
)
from career_guidance.kaamvaani.trace import Trace, get_sink, hash_query
from career_guidance.kaamvaani.voice import describe_gateway
from career_guidance.providers import ProviderFactory

# Languages the voice UI supports (see frontend/lib/speech.ts + the
# voice_* i18n keys). The device must have a voice for a language before
# the UI offers to speak it — the frontend checks that itself.
VOICE_LANGUAGES: tuple[str, ...] = ("en", "hi", "ta")


class ExtractRequest(BaseModel):
    """One transcript (spoken or typed) to extract a profile from — or
    the guided flow's per-question answers, which the extractor uses
    for question-context precision (a bare "Madurai" to the city
    question counts as Madurai). At least one of ``text`` / ``answers``
    is required; when both are given, ``answers`` wins."""

    text: str | None = Field(default=None, min_length=1, max_length=4000)
    answers: dict[str, str] | None = None
    language: Literal["en", "hi", "ta"] = "en"

    @model_validator(mode="after")
    def _require_text_or_answers(self) -> ExtractRequest:
        if not self.text and not self.answers:
            raise ValueError("either text or answers is required")
        if self.answers is not None:
            unknown = sorted(set(self.answers) - set(QUESTION_IDS))
            if unknown:
                raise ValueError(f"unknown question ids: {unknown}")
            for question_id, answer in self.answers.items():
                if len(answer) > 1000:
                    raise ValueError(f"answer to {question_id!r} is too long")
        return self


class ConfirmRequest(BaseModel):
    """The client's session plus the profile the user confirmed (or
    declined). The profile is the user-edited one — the user's edits
    win over the extracted values."""

    session: VoiceSession
    profile: VoiceProfile
    confirmed: bool = True


# Step 9.4: anonymous voice calls are 30/min per IP (combined
# /extract + /confirm).
_LIMITER = kv_limiter(max_calls=30, per_seconds=60)


def build_router(settings: Settings) -> APIRouter:
    """Return the voice router. ``settings`` selects the providers."""
    router = APIRouter(prefix="/api/v1/kv/voice", tags=["kaam-vaani-voice"])
    # The completer is wrapped in the shared LLM cache (Step 8.6):
    # a repeated transcript reuses the completion instead of calling
    # the provider again. No LLM configured → None → deterministic.
    completer = cached_completer(settings)
    llm_name = ProviderFactory.selected_name(settings)
    # Agent trace log (Step 8.9): the process-wide sink, shared with
    # the RAG + matching routers and read by the admin endpoint.
    sink = get_sink(settings)

    @router.get("/status")
    def status() -> dict:
        """Which voice capabilities are live and how they are provided.

        ``stt``/``tts`` name the EFFECTIVE provider ("browser" = the
        device's Web Speech API, free, no key); ``gateway`` reports the
        configured vs effective provider plus availability, so a hosted
        provider configured without its key shows as fallen back, never
        as live. ``extraction`` is "llm" only when an LLM provider is
        configured — otherwise "deterministic". No audio is ever sent
        to this endpoint.
        """
        gateway = describe_gateway(settings)
        return {
            "enabled": True,
            "stt": gateway["stt"]["effective"],
            "tts": gateway["tts"]["effective"],
            "gateway": gateway,
            "extraction": "llm" if completer is not None else "deterministic",
            "llm_provider": llm_name,
            "languages": list(VOICE_LANGUAGES),
            "questions": list(QUESTION_IDS),
            # Profile-extraction cache stats (Step 8.6): repeated
            # transcripts reuse the extracted profile.
            "profile_cache": profile_cache.stats().to_dict(),
        }

    @router.post("/extract")
    def extract(request: Request, body: ExtractRequest) -> dict:
        """Extract a structured profile from one transcript (or the
        guided flow's per-question answers). The ``method`` field says
        honestly which path produced it ("llm", "llm-repaired",
        "deterministic", "deterministic-fallback"). The profile is NOT
        used until the user confirms it (see /confirm). A repeated
        identical transcript/answers set is served from the profile
        cache (Step 8.6): the router owns one fixed completer and the
        process vocabulary, so (payload, prompt version) fully
        determines the result — a cached profile is identical to a
        fresh one, and a prompt edit naturally misses. Every call is
        traced (Step 8.9): the response carries ``trace_id``; the
        trace records the extraction method and skill count only,
        never the transcript or the profile."""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        if body.answers:
            payload = ("answers", body.answers)
        else:
            payload = ("text", body.text or "")
        # Trace (Step 8.9): the transcript is identified by its hash
        # only — the trace never carries the transcript or the profile.
        trace = Trace(
            "/api/v1/kv/voice/extract",
            query_hash=hash_query(repr(payload)),
        )
        # The deterministic path never reads the prompt, so it keys on
        # "" — a missing prompt file must not break deterministic
        # extraction. The LLM path reads the prompt anyway.
        prompt_version = load_prompt("profile-extractor").version if completer is not None else ""
        key = profile_cache_key(payload, prompt_version)
        cached = profile_cache.get(key)
        if cached is not None:
            profile, method = cached
            trace.cache_hit = True
            sink.store(trace.finish(status="ok", outcome="cache_hit"))
            return {
                "profile": profile.model_dump(mode="json"),
                "method": method,
                "language": body.language,
                "trace_id": trace.trace_id,
            }
        try:
            with trace.span("extract") as span:
                if body.answers:
                    profile, method = extract_profile_guided(
                        body.answers, settings, completer=completer
                    )
                else:
                    profile, method = extract_profile_smart(
                        body.text or "", settings, completer=completer
                    )
                # Counts and the method only — never profile content.
                span.detail["method"] = method
                span.detail["skills_count"] = len(profile.skills)
                span.detail["guided"] = bool(body.answers)
        except Exception:
            sink.store(trace.finish(status="error", outcome="error"))
            raise
        profile_cache.put(key, (profile, method))
        sink.store(trace.finish(status="ok", outcome="extracted"))
        return {
            "profile": profile.model_dump(mode="json"),
            "method": method,
            "language": body.language,
            "trace_id": trace.trace_id,
        }

    @router.post("/confirm")
    def confirm(request: Request, body: ConfirmRequest) -> dict:
        """Validate the confirmation transition and return the session
        in its next state. ``confirmed=true`` moves the session to
        "matches" (via "confirm" from "questions" or "confirm"); the
        confirmed profile stored is the one in the request — the user's
        edits win. ``confirmed=false`` moves it back to "questions" so
        the user can fix an answer. An illegal transition (e.g. a
        session that never answered the questions, or a state that is
        not questions/confirm) is a 400, never a silent accept."""
        if not _LIMITER.allow(client_key(request)):
            raise HTTPException(429, "Too many requests — please wait a minute.")
        session = body.session
        try:
            if body.confirmed:
                if session.state == "questions":
                    session = transition(session, "extracted", profile=body.profile)
                elif session.state != "confirm":
                    raise ValueError(
                        f"confirm is only legal from questions or confirm, not {session.state}"
                    )
                # The user's confirmed (possibly edited) profile is the
                # one that counts — replace before confirming.
                session = session.model_copy(update={"profile": body.profile})
                session = transition(session, "confirm", confirmed=True)
            else:
                if session.state == "confirm":
                    session = transition(session, "decline")
                elif session.state != "questions":
                    raise ValueError(
                        f"decline is only legal from questions or confirm, not {session.state}"
                    )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "session": session.model_dump(mode="json"),
            "next_state": session.state,
        }

    return router
