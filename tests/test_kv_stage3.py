"""Kaam-Vaani Stage 3: STT/TTS gateway, LLM profile extraction, state machine,
voice router (extract/confirm), and the frontend parity port.

Covers: the provider-agnostic voice gateway (browser fallback + OpenAI
Whisper/TTS via MockTransport, factory selection + graceful degradation),
the versioned prompt library loader, LLM structured-output extraction
(valid/repair/failure paths, vocabulary normalisation, deterministic
fallback), the conversation state machine (full path, illegal transitions,
serialisation round-trip), and the kv_voice router (status/extract/confirm,
flag-off 404s). The golden eval still measures the deterministic path —
see eval/run_kv.py; LLM quality is unmeasured until a key exists (L1).
"""

from __future__ import annotations

import importlib
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.kv_voice import build_router as build_kv_voice_router
from career_guidance.config import Settings
from career_guidance.kaamvaani import profile as profile_module
from career_guidance.kaamvaani.extract import VoiceProfile, extract_profile
from career_guidance.kaamvaani.profile import (
    QUESTION_IDS,
    ExtractionError,
    VoiceSession,
    combined_transcript,
    extract_profile_guided,
    extract_profile_llm,
    extract_profile_smart,
    load_prompt,
    match_city_bare,
    new_session,
    normalise_llm_profile,
    transition,
)
from career_guidance.kaamvaani.voice import (
    BrowserSTTProvider,
    BrowserTTSProvider,
    OpenAITTSProvider,
    OpenAIWhisperSTTProvider,
    Transcription,
    describe_gateway,
    get_stt_provider,
    get_tts_provider,
)
from career_guidance.models import ProviderError
from career_guidance.providers import ChatCompleter


class FakeCompleter(ChatCompleter):
    """Scripted completer: replies (or exceptions) in order, calls recorded."""

    name = "fake"

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_content: str) -> str:
        self.calls.append((system_prompt, user_content))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _llm_json(**overrides) -> str:
    payload = {
        "skills": ["farming"],
        "interests": "",
        "education": "12th pass",
        "city": "Madurai",
        "income_text": "₹15,000 / month",
        "income_monthly": 15000,
        "goal_type": "job_6_months",
    }
    payload.update(overrides)
    return json.dumps(payload)


# --------------------------------------------------------------------------- #
# STT/TTS gateway — browser providers
# --------------------------------------------------------------------------- #


def test_browser_providers_are_client_side_and_available():
    settings = Settings()
    stt, tts = BrowserSTTProvider(), BrowserTTSProvider()
    assert stt.name == "browser" and stt.client_side is True
    assert tts.name == "browser" and tts.client_side is True
    assert stt.available(settings) is True
    assert tts.available(settings) is True
    assert stt.describe(settings) == {
        "provider": "browser",
        "client_side": True,
        "available": True,
    }
    assert tts.describe(settings) == {
        "provider": "browser",
        "client_side": True,
        "available": True,
    }
    # Server-side transcribe/synthesise refuse BY DESIGN: audio never
    # reaches this server; the browser does the work.
    with pytest.raises(ProviderError, match="client-side"):
        stt.transcribe(b"audio", "en")
    with pytest.raises(ProviderError, match="client-side"):
        tts.synthesize("hello", "en")


def test_gateway_factory_defaults_to_browser():
    settings = Settings()
    assert isinstance(get_stt_provider(settings), BrowserSTTProvider)
    assert isinstance(get_tts_provider(settings), BrowserTTSProvider)
    gateway = describe_gateway(settings)
    assert gateway["stt"] == {
        "configured": "browser",
        "effective": "browser",
        "provider": "browser",
        "client_side": True,
        "available": True,
    }
    assert gateway["tts"]["effective"] == "browser"


def test_gateway_factory_openai_without_key_falls_back_to_browser(caplog):
    settings = Settings(kv_stt_provider="openai", kv_tts_provider="openai")
    assert isinstance(get_stt_provider(settings), BrowserSTTProvider)
    assert isinstance(get_tts_provider(settings), BrowserTTSProvider)
    gateway = describe_gateway(settings)
    # Honest: configured=openai, effective=browser (the key is missing).
    assert gateway["stt"]["configured"] == "openai"
    assert gateway["stt"]["effective"] == "browser"
    assert "OPENAI_API_KEY" in caplog.text


def test_gateway_factory_unknown_provider_falls_back_to_browser(caplog):
    settings = Settings(kv_stt_provider="no-such-provider", kv_tts_provider="nope")
    assert isinstance(get_stt_provider(settings), BrowserSTTProvider)
    assert isinstance(get_tts_provider(settings), BrowserTTSProvider)
    assert "Unknown KV_STT_PROVIDER" in caplog.text
    assert "Unknown KV_TTS_PROVIDER" in caplog.text


def test_gateway_factory_openai_with_key_selects_openai():
    settings = Settings(
        openai_api_key="sk-test",
        kv_stt_provider="openai",
        kv_tts_provider="openai",
    )
    assert isinstance(get_stt_provider(settings), OpenAIWhisperSTTProvider)
    assert isinstance(get_tts_provider(settings), OpenAITTSProvider)
    gateway = describe_gateway(settings)
    assert gateway["stt"]["effective"] == "openai"
    assert gateway["stt"]["available"] is True
    assert gateway["tts"]["effective"] == "openai"


# --------------------------------------------------------------------------- #
# STT/TTS gateway — OpenAI providers (MockTransport; no live key exists)
# --------------------------------------------------------------------------- #


def _openai_settings() -> Settings:
    return Settings(openai_api_key="sk-test")


def test_whisper_transcribe_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["Authorization"] == "Bearer sk-test"
        assert b"whisper-1" in request.content
        return httpx.Response(200, json={"text": "I am a carpenter in Madurai"})

    provider = OpenAIWhisperSTTProvider(_openai_settings(), transport=httpx.MockTransport(handler))
    result = provider.transcribe(b"fake-audio-bytes", "ta")
    assert isinstance(result, Transcription)
    assert result.text == "I am a carpenter in Madurai"


def test_whisper_transcribe_retries_transient_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"text": "hello"})

    provider = OpenAIWhisperSTTProvider(_openai_settings(), transport=httpx.MockTransport(handler))
    assert provider.transcribe(b"audio", "en").text == "hello"
    assert calls["n"] == 2


def test_whisper_transcribe_failures():
    settings = _openai_settings()
    # No key: refused before any network call.
    assert OpenAIWhisperSTTProvider(Settings()).available(Settings()) is False
    with pytest.raises(ProviderError, match="not configured"):
        OpenAIWhisperSTTProvider(Settings()).transcribe(b"audio", "en")
    # Empty audio.
    with pytest.raises(ProviderError, match="No audio"):
        OpenAIWhisperSTTProvider(settings).transcribe(b"", "en")
    # Auth failure (non-transient): no retry, ProviderError.
    calls = {"n": 0}

    def auth_fail(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(ProviderError, match="HTTP 401"):
        OpenAIWhisperSTTProvider(settings, transport=httpx.MockTransport(auth_fail)).transcribe(
            b"audio", "en"
        )
    assert calls["n"] == 1
    # Empty text in a 200 response.
    empty = httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "  "}))
    with pytest.raises(ProviderError, match="no text"):
        OpenAIWhisperSTTProvider(settings, transport=empty).transcribe(b"audio", "en")


def test_openai_tts_success_and_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        body = json.loads(request.content)
        assert body["model"] == "tts-1"
        assert body["input"] == "Hello, Madurai"
        return httpx.Response(200, content=b"\xff\xfb fake mp3")

    settings = _openai_settings()
    provider = OpenAITTSProvider(settings, transport=httpx.MockTransport(handler))
    assert provider.synthesize("Hello, Madurai", "en") == b"\xff\xfb fake mp3"

    assert OpenAITTSProvider(Settings()).available(Settings()) is False
    with pytest.raises(ProviderError, match="not configured"):
        OpenAITTSProvider(Settings()).synthesize("hi", "en")
    with pytest.raises(ProviderError, match="No text"):
        OpenAITTSProvider(settings).synthesize("   ", "en")
    empty = httpx.MockTransport(lambda r: httpx.Response(200, content=b""))
    with pytest.raises(ProviderError, match="no audio"):
        OpenAITTSProvider(settings, transport=empty).synthesize("hi", "en")
    bad = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(ProviderError, match="HTTP 400"):
        OpenAITTSProvider(settings, transport=bad).synthesize("hi", "en")


# --------------------------------------------------------------------------- #
# Prompt library
# --------------------------------------------------------------------------- #


def test_load_prompt_profile_extractor_is_versioned_and_testable():
    prompt = load_prompt("profile-extractor")
    assert prompt.name == "profile-extractor"
    assert prompt.version == "1.0.0"
    # The schema in the prompt matches the VoiceProfile contract.
    for field in (
        "skills",
        "interests",
        "education",
        "city",
        "income_text",
        "income_monthly",
        "goal_type",
    ):
        assert f'"{field}"' in prompt.system_prompt, field
    assert "ONLY with a single JSON object" in prompt.system_prompt


def test_load_prompt_unknown_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_prompt("no-such-prompt")


def test_load_prompt_without_version_header_raises(tmp_path, monkeypatch):
    (tmp_path / "bad-prompt.md").write_text("No header here.\n", encoding="utf-8")
    monkeypatch.setattr(profile_module, "PROMPTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="no valid version header"):
        load_prompt("bad-prompt")


# --------------------------------------------------------------------------- #
# LLM extraction
# --------------------------------------------------------------------------- #


def test_llm_extraction_valid_json_normalises_skills():
    completer = FakeCompleter([_llm_json(skills=["driving", "tailoring", "quantum knitting"])])
    profile, repaired = extract_profile_llm("I drive a bus, I can tailor", completer)
    assert repaired is False
    # Vocabulary-gated: driving -> automotive, tailoring -> fashion
    # design; the unknown skill is kept in interests, not invented.
    assert profile.skills == ["automotive", "fashion design"]
    assert "quantum knitting" in profile.interests
    assert profile.education == "12th pass"
    assert profile.city == "Madurai"
    assert profile.income_monthly == 15000
    assert profile.income_text == "₹15,000 / month"
    assert profile.raw_text == "I drive a bus, I can tailor"


def test_llm_extraction_parses_code_fenced_json():
    completer = FakeCompleter(["```json\n" + _llm_json() + "\n```"])
    profile, repaired = extract_profile_llm("farming in Madurai", completer)
    assert repaired is False
    assert profile.skills == ["agricultural science"]


def test_llm_extraction_repairs_invalid_output_once():
    completer = FakeCompleter(["not json at all", _llm_json(skills=["welding"])])
    profile, repaired = extract_profile_llm("welding work", completer)
    assert repaired is True
    assert profile.skills == ["welding"]
    assert len(completer.calls) == 2
    # The repair call carries the error + the bad output.
    assert "not valid" in completer.calls[1][1]
    assert "not json at all" in completer.calls[1][1]


def test_llm_extraction_invalid_twice_raises():
    completer = FakeCompleter(["garbage", "{also garbage"])
    with pytest.raises(ExtractionError):
        extract_profile_llm("welding work", completer)
    assert len(completer.calls) == 2  # exactly one repair attempt


def test_llm_extraction_schema_violation_repairs():
    # skills as a string (not a list) fails Pydantic validation.
    bad = json.dumps({"skills": "farming", "interests": ""})
    completer = FakeCompleter([bad, _llm_json()])
    profile, repaired = extract_profile_llm("farming", completer)
    assert repaired is True
    assert profile.skills == ["agricultural science"]


def test_normalise_llm_profile_income_and_goal():
    base = VoiceProfile(
        skills=[],
        interests="",
        education="  12th pass ",
        city=" Madurai ",
        income_text="",
        income_monthly=50,  # below the ₹500 floor
        goal_type="become-famous",
        raw_text="x",
    )
    out = normalise_llm_profile(base, "x")
    assert out.income_monthly is None and out.income_text == ""
    assert out.goal_type == "explore"
    assert out.education == "12th pass" and out.city == "Madurai"

    # Income text without a number is recovered by the income parser.
    out = normalise_llm_profile(
        VoiceProfile(skills=[], income_text="20000 rupees per month", income_monthly=None),
        "x",
    )
    assert out.income_monthly == 20000
    assert out.income_text == "₹20,000 / month"
    # Income above the ₹10 lakh ceiling is dropped, not clamped.
    out = normalise_llm_profile(VoiceProfile(skills=[], income_monthly=5_000_000), "x")
    assert out.income_monthly is None


def test_extract_smart_no_completer_is_deterministic():
    text = "I am a carpenter in Madurai, 10th pass, need a job"
    profile, method = extract_profile_smart(text)
    assert method == "deterministic"
    assert profile == extract_profile(text)
    # Settings without a key: same path (the factory returns None).
    profile2, method2 = extract_profile_smart(text, Settings())
    assert method2 == "deterministic"
    assert profile2 == extract_profile(text)


def test_extract_smart_llm_success_and_fallback():
    completer = FakeCompleter([_llm_json(skills=["welding"])])
    profile, method = extract_profile_smart("welding", completer=completer)
    assert method == "llm"
    assert profile.skills == ["welding"]

    failing = FakeCompleter([ProviderError("boom")])
    profile, method = extract_profile_smart("I am a carpenter in Madurai", completer=failing)
    assert method == "deterministic-fallback"
    assert profile == extract_profile("I am a carpenter in Madurai")

    invalid = FakeCompleter(["garbage", "garbage"])
    profile, method = extract_profile_smart("I am a carpenter in Madurai", completer=invalid)
    assert method == "deterministic-fallback"
    assert profile.skills == ["carpentry"]


# --------------------------------------------------------------------------- #
# Guided (per-question) extraction
# --------------------------------------------------------------------------- #


def test_match_city_bare_needs_no_preposition():
    assert match_city_bare("Madurai") == "Madurai"
    assert match_city_bare("madurai la") == "Madurai"
    assert match_city_bare("मैं मदुरै से हूँ") == "Madurai"
    assert match_city_bare("சேலம்") == "Salem"
    assert match_city_bare("I don't know") == ""
    assert match_city_bare("somewhere far away") == ""
    # Word boundaries still apply: "salem" inside another word is not Salem.
    assert match_city_bare("jerusalem") == ""


def test_extract_guided_bare_answers():
    """The guided flow's most natural answers are bare fragments —
    "Madurai", "12th", "15000" — and the question context must make
    them count. (The free-text extractor rightly ignores a bare city
    name; the guided path knows the question it answers.)"""
    profile, method = extract_profile_guided(
        {
            "skills": "farming, computer work",
            "education": "12th pass",
            "city": "Madurai",
            "income": "15000 rupees per month",
            "goal": "I want a job",
        }
    )
    assert method == "deterministic"
    assert profile.city == "Madurai"
    assert profile.education == "12th pass"
    assert profile.income_monthly == 15000
    assert "agricultural science" in profile.skills
    assert "computer literacy" in profile.skills
    assert profile.goal_type == "job_6_months"


def test_extract_guided_skips_and_unknown_city():
    profile, _ = extract_profile_guided(
        {
            "skills": "welding",
            "education": "",
            "city": "somewhere I cannot name",
            "income": "",
            "goal": "",
        }
    )
    assert profile.skills == ["welding"]
    assert profile.city == ""  # never invented
    assert profile.education == ""
    assert profile.income_monthly is None
    assert profile.goal_type == "explore"


def test_extract_guided_llm_path_uses_guided_overrides():
    """With an LLM configured, the base extraction is the LLM's — and
    the guided overrides still sharpen it (the bare city)."""
    completer = FakeCompleter(
        [_llm_json(skills=["welding"], city="", education="", income_monthly=None)]
    )
    profile, method = extract_profile_guided(
        {
            "skills": "welding work",
            "education": "",
            "city": "Salem",
            "income": "",
            "goal": "",
        },
        completer=completer,
    )
    assert method == "llm"
    assert profile.skills == ["welding"]
    assert profile.city == "Salem"  # guided override, not the LLM's ""


# --------------------------------------------------------------------------- #
# Conversation state machine
# --------------------------------------------------------------------------- #


def _answered_session() -> VoiceSession:
    session = new_session("ta")
    session = transition(session, "start")
    session = transition(session, "set_language", language="ta")
    answers = {
        "skills": ("I know farming and computer work", "voice"),
        "education": ("12th pass", "typed"),
        "city": ("I am from Madurai", "voice"),
        "income": ("15000 rupees per month", "voice"),
        "goal": ("I want a job", "typed"),
    }
    for qid, (text, source) in answers.items():
        session = transition(session, "answer", question_id=qid, transcript=text, source=source)
    return session


def test_state_machine_full_happy_path():
    session = _answered_session()
    assert session.state == "questions"
    assert session.question_index == len(QUESTION_IDS)
    assert combined_transcript(session).startswith("I know farming")
    assert "12th pass" in combined_transcript(session)

    profile = extract_profile(combined_transcript(session))
    session = transition(session, "extracted", profile=profile)
    assert session.state == "confirm"
    assert session.profile is not None and session.profile.city == "Madurai"

    session = transition(session, "confirm", confirmed=True)
    assert session.state == "matches" and session.confirmed is True

    # Later stages plug in here; the order is already enforced.
    session = transition(session, "to_gap_learning")
    assert session.state == "gap_learning"
    session = transition(session, "to_consent")
    assert session.state == "consent"
    session = transition(session, "to_next_steps")
    assert session.state == "next_steps"
    session = transition(session, "finish")
    assert session.state == "done"


def test_state_machine_transitions_are_pure():
    session = new_session()
    moved = transition(session, "start")
    assert session.state == "greet"  # the original is untouched
    assert moved.state == "language"


def test_state_machine_illegal_transitions_raise():
    session = new_session()
    with pytest.raises(ValueError, match="only legal from questions"):
        transition(session, "answer", question_id="skills", transcript="x", source="voice")
    with pytest.raises(ValueError, match="only legal from language"):
        transition(session, "set_language", language="ta")
    with pytest.raises(ValueError, match="unknown event"):
        transition(session, "explode")
    with pytest.raises(ValueError, match="unsupported language"):
        new_session("fr")
    session = transition(session, "start")
    with pytest.raises(ValueError, match="unsupported language"):
        transition(session, "set_language", language="fr")
    session = transition(session, "set_language", language="en")
    with pytest.raises(ValueError, match="unknown question"):
        transition(session, "answer", question_id="nope", transcript="x", source="voice")
    with pytest.raises(ValueError, match="unknown answer source"):
        transition(session, "answer", question_id="skills", transcript="x", source="smoke-signal")
    with pytest.raises(ValueError, match="unanswered questions"):
        transition(session, "extracted", profile=VoiceProfile())
    with pytest.raises(ValueError, match="only legal from confirm"):
        transition(session, "confirm", confirmed=True)
    with pytest.raises(ValueError, match="only legal from matches"):
        transition(session, "to_gap_learning")


def test_state_machine_skip_and_decline_and_edit():
    session = new_session()
    session = transition(session, "start")
    session = transition(session, "set_language", language="en")
    # Skipping records an empty answer and advances.
    session = transition(session, "answer", question_id="income", transcript="", source="skipped")
    assert session.answers["income"] == ""
    assert session.answer_source["income"] == "skipped"
    assert "income" not in combined_transcript(session)

    session = _answered_session()
    profile = extract_profile(combined_transcript(session))
    session = transition(session, "extracted", profile=profile)
    # Decline goes back to the questions; nothing is confirmed.
    declined = transition(session, "decline")
    assert declined.state == "questions" and declined.confirmed is False
    # Edit jumps to one question.
    edited = transition(session, "edit_answer", question_id="city")
    assert edited.state == "questions"
    assert edited.question_index == QUESTION_IDS.index("city")
    with pytest.raises(ValueError, match="unknown question"):
        transition(session, "edit_answer", question_id="nope")
    # Restart resets to greet, keeping the language.
    restarted = transition(session, "restart")
    assert restarted.state == "greet" and restarted.language == "ta"
    assert restarted.answers == {}


def test_state_machine_serialisation_round_trip():
    session = _answered_session()
    dumped = session.model_dump(mode="json")
    restored = VoiceSession.model_validate(dumped)
    assert restored == session
    # JSON round-trip (what sessionStorage holds) also preserves it.
    restored2 = VoiceSession.model_validate_json(session.model_dump_json())
    assert restored2 == session


# --------------------------------------------------------------------------- #
# kv_voice router — status / extract / confirm
# --------------------------------------------------------------------------- #


@pytest.fixture()
def voice_client():
    settings = Settings()
    app = FastAPI()
    app.include_router(build_kv_voice_router(settings))
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def voice_client_openai():
    settings = Settings(openai_api_key="sk-test")
    app = FastAPI()
    app.include_router(build_kv_voice_router(settings))
    with TestClient(app) as client:
        yield client


def test_voice_status_reports_gateway_and_extraction(voice_client):
    r = voice_client.get("/api/v1/kv/voice/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["stt"] == "browser" and body["tts"] == "browser"
    assert body["gateway"]["stt"]["effective"] == "browser"
    assert body["gateway"]["stt"]["configured"] == "browser"
    assert body["gateway"]["stt"]["available"] is True
    assert body["extraction"] == "deterministic"
    assert body["llm_provider"] is None
    assert body["languages"] == ["en", "hi", "ta"]
    assert body["questions"] == list(QUESTION_IDS)


def test_voice_status_with_llm_key_reports_llm(voice_client_openai):
    body = voice_client_openai.get("/api/v1/kv/voice/status").json()
    assert body["extraction"] == "llm"
    assert body["llm_provider"] == "openai"
    # STT/TTS are still browser (KV_STT_PROVIDER defaults to browser).
    assert body["stt"] == "browser"


def test_voice_extract_deterministic(voice_client):
    r = voice_client.post(
        "/api/v1/kv/voice/extract",
        json={
            "text": "I finished 12th in Madurai. I know farming. I need a job, 15000 a month.",
            "language": "en",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "deterministic"
    profile = body["profile"]
    assert profile["education"] == "12th pass"
    assert profile["city"] == "Madurai"
    assert profile["income_monthly"] == 15000
    assert "agricultural science" in profile["skills"]
    assert profile["goal_type"] == "job_6_months"


def test_voice_extract_validates_input(voice_client):
    assert voice_client.post("/api/v1/kv/voice/extract", json={"text": ""}).status_code == 422
    too_long = voice_client.post("/api/v1/kv/voice/extract", json={"text": "x" * 4001})
    assert too_long.status_code == 422
    assert (
        voice_client.post(
            "/api/v1/kv/voice/extract", json={"text": "hello", "language": "fr"}
        ).status_code
        == 422
    )
    # Tamil transcript: the deterministic path handles it (gold-set parity).
    r = voice_client.post(
        "/api/v1/kv/voice/extract",
        json={"text": "நான் கொத்தனார், மதுரையில் இருக்கிறேன்", "language": "ta"},
    )
    assert r.status_code == 200
    assert r.json()["profile"]["skills"] == ["masonry"]
    assert r.json()["profile"]["city"] == "Madurai"


def test_voice_extract_guided_answers(voice_client):
    r = voice_client.post(
        "/api/v1/kv/voice/extract",
        json={
            "answers": {
                "skills": "farming, computer work",
                "education": "12th pass",
                "city": "Madurai",
                "income": "15000 rupees per month",
                "goal": "I want a job",
            },
            "language": "en",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "deterministic"
    assert body["profile"]["city"] == "Madurai"
    assert body["profile"]["income_monthly"] == 15000
    assert "agricultural science" in body["profile"]["skills"]


def test_voice_extract_requires_text_or_answers(voice_client):
    assert voice_client.post("/api/v1/kv/voice/extract", json={}).status_code == 422
    assert (
        voice_client.post("/api/v1/kv/voice/extract", json={"answers": {"nope": "x"}}).status_code
        == 422
    )
    assert (
        voice_client.post(
            "/api/v1/kv/voice/extract", json={"answers": {"skills": "x" * 1001}}
        ).status_code
        == 422
    )


def _confirm_body(session: VoiceSession, profile: VoiceProfile, confirmed: bool) -> dict:
    return {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "confirmed": confirmed,
    }


def test_voice_confirm_happy_path_from_questions(voice_client):
    session = _answered_session()
    profile = extract_profile(combined_transcript(session))
    # The user edits one field on the review screen — the edit wins.
    profile.city = "Trichy"
    r = voice_client.post("/api/v1/kv/voice/confirm", json=_confirm_body(session, profile, True))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_state"] == "matches"
    assert body["session"]["state"] == "matches"
    assert body["session"]["confirmed"] is True
    assert body["session"]["profile"]["city"] == "Trichy"


def test_voice_confirm_from_confirm_state_and_decline(voice_client):
    session = _answered_session()
    profile = extract_profile(combined_transcript(session))
    session = transition(session, "extracted", profile=profile)
    assert session.state == "confirm"

    r = voice_client.post("/api/v1/kv/voice/confirm", json=_confirm_body(session, profile, True))
    assert r.status_code == 200
    assert r.json()["next_state"] == "matches"

    r = voice_client.post("/api/v1/kv/voice/confirm", json=_confirm_body(session, profile, False))
    assert r.status_code == 200
    assert r.json()["next_state"] == "questions"
    assert r.json()["session"]["confirmed"] is False


def test_voice_confirm_rejects_illegal_transitions(voice_client):
    profile = VoiceProfile()
    # A fresh session never answered anything.
    r = voice_client.post(
        "/api/v1/kv/voice/confirm",
        json=_confirm_body(new_session(), profile, True),
    )
    assert r.status_code == 400
    assert "only legal" in r.json()["detail"]
    # A session in "matches" cannot confirm again.
    session = _answered_session()
    session = transition(session, "extracted", profile=extract_profile("farming"))
    session = transition(session, "confirm", confirmed=True)
    r = voice_client.post("/api/v1/kv/voice/confirm", json=_confirm_body(session, profile, True))
    assert r.status_code == 400
    # A declined session in "matches" is equally illegal.
    r = voice_client.post("/api/v1/kv/voice/confirm", json=_confirm_body(session, profile, False))
    assert r.status_code == 400


@pytest.fixture()
def app_module_kv_voice_off(tmp_path, monkeypatch):
    """backend.main reloaded with KV_VOICE=false (dev otherwise)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_VOICE", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_voice_routes_404_when_flag_off(app_module_kv_voice_off):
    with TestClient(app_module_kv_voice_off.app) as c:
        assert c.get("/api/v1/kv/voice/status").status_code == 404
        # POSTs to an unmounted route answer 405, not 404: the SPA
        # catch-all is a GET-only route, so Starlette reports "method
        # not allowed" for the path. Either way the route is not
        # mounted — the point is that no voice endpoint answers.
        assert c.post("/api/v1/kv/voice/extract", json={"text": "hello"}).status_code in (
            404,
            405,
        )
        assert c.post(
            "/api/v1/kv/voice/confirm",
            json=_confirm_body(new_session(), VoiceProfile(), True),
        ).status_code in (404, 405)
        assert c.get("/api/v1/health").status_code == 200
