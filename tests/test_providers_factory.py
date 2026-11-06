"""Phase 7 multi-provider factory: selection, mocked transports, retry, parsing."""

from __future__ import annotations

import json

import httpx
import pytest

from career_guidance.config import Settings
from career_guidance.models import ProviderError
from career_guidance.providers import (
    GeminiCompleter,
    GeminiProvider,
    OllamaCompleter,
    OllamaProvider,
    ProviderFactory,
    get_provider,
)

FAKE_GEMINI_KEY = "fake-gemini-key-for-tests"
FAKE_OPENAI_KEY = "fake-openai-key-for-tests"

SUGGESTIONS_JSON = json.dumps([{"title": "Dev", "rationale": "Codes well."}])
RECOMMEND_JSON = json.dumps(
    [
        {
            "title": "Data Analyst",
            "match_reason": "Fits.",
            "suitability": "beginner",
            "matching_skills": ["sql"],
            "missing_skills": ["excel"],
            "learning_path": ["Learn SQL"],
            "next_steps": ["Build a dashboard"],
        }
    ]
)


def _gemini_transport(captured: dict, fail_times: int = 0):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        if calls["n"] <= fail_times:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": RECOMMEND_JSON}]}}]},
        )

    return httpx.MockTransport(handler), calls


def test_factory_defaults_to_openai_when_only_openai_key():
    settings = Settings(openai_api_key=FAKE_OPENAI_KEY)
    assert ProviderFactory.selected_name(settings) == "openai"
    completer = ProviderFactory.create_completer(settings)
    assert completer is not None and completer.name == "openai"


def test_factory_selects_gemini_when_only_gemini_key():
    settings = Settings(gemini_api_key=FAKE_GEMINI_KEY)
    assert ProviderFactory.selected_name(settings) == "gemini"


def test_factory_explicit_provider_wins_and_requires_key():
    settings = Settings(
        llm_provider="gemini", openai_api_key=FAKE_OPENAI_KEY, gemini_api_key=FAKE_GEMINI_KEY
    )
    assert ProviderFactory.selected_name(settings) == "gemini"
    # Explicit gemini without its key -> offline, not a silent OpenAI swap.
    settings2 = Settings(llm_provider="gemini", openai_api_key=FAKE_OPENAI_KEY)
    assert ProviderFactory.selected_name(settings2) is None


def test_factory_ollama_needs_no_key_and_unknown_is_offline():
    assert ProviderFactory.selected_name(Settings(llm_provider="ollama")) == "ollama"
    assert ProviderFactory.selected_name(Settings(llm_provider="bogus")) is None
    assert ProviderFactory.selected_name(Settings()) is None
    assert ProviderFactory.create_completer(Settings()) is None


def test_get_provider_grounded_for_gemini_and_ollama():
    gemini = get_provider(Settings(gemini_api_key=FAKE_GEMINI_KEY))
    assert gemini.is_demo is False and "Gemini" in gemini.name
    ollama = get_provider(Settings(llm_provider="ollama"))
    assert ollama.is_demo is False and "Ollama" in ollama.name
    offline = get_provider(Settings())
    assert offline.is_demo is True


def test_gemini_completer_parses_and_sends_key_in_header_not_url():
    captured: dict = {}
    transport, _ = _gemini_transport(captured)
    completer = GeminiCompleter(Settings(gemini_api_key=FAKE_GEMINI_KEY), transport=transport)
    text = completer.complete("sys prompt", "user prompt")
    assert text == RECOMMEND_JSON
    assert captured["headers"].get("x-goog-api-key") == FAKE_GEMINI_KEY
    assert FAKE_GEMINI_KEY not in captured["url"]
    assert "generateContent" in captured["url"]
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "sys prompt"


def test_gemini_completer_retries_once_on_transient_503():
    captured: dict = {}
    transport, calls = _gemini_transport(captured, fail_times=1)
    completer = GeminiCompleter(Settings(gemini_api_key=FAKE_GEMINI_KEY), transport=transport)
    assert completer.complete("s", "u") == RECOMMEND_JSON
    assert calls["n"] == 2


def test_gemini_completer_fails_after_retry_exhausted():
    captured: dict = {}
    transport, calls = _gemini_transport(captured, fail_times=99)
    completer = GeminiCompleter(Settings(gemini_api_key=FAKE_GEMINI_KEY), transport=transport)
    with pytest.raises(ProviderError):
        completer.complete("s", "u")
    assert calls["n"] == 2  # initial + exactly one retry


def test_gemini_completer_rejects_malformed_payload():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"nope": []}))
    completer = GeminiCompleter(Settings(gemini_api_key=FAKE_GEMINI_KEY), transport=transport)
    with pytest.raises(ProviderError):
        completer.complete("s", "u")


def test_gemini_provider_recommend_uses_shared_schema_validation():
    captured: dict = {}
    transport, _ = _gemini_transport(captured)
    provider = GeminiProvider(Settings(gemini_api_key=FAKE_GEMINI_KEY), transport=transport)
    from career_guidance.profile import CareerProfile

    recs = provider.recommend(CareerProfile(skills="sql"))
    assert recs[0].title == "Data Analyst" and recs[0].matching_skills == ["sql"]


def test_gemini_provider_rejects_garbage_output():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
        )
    )
    provider = GeminiProvider(Settings(gemini_api_key=FAKE_GEMINI_KEY), transport=transport)
    from career_guidance.profile import CareerProfile

    with pytest.raises(ProviderError):
        provider.recommend(CareerProfile(skills="sql"))


def _ollama_transport(captured: dict, text: str = SUGGESTIONS_JSON):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": text}})

    return httpx.MockTransport(handler)


def test_ollama_completer_uses_local_api_and_model_env():
    captured: dict = {}
    completer = OllamaCompleter(
        Settings(ollama_base_url="http://localhost:11434", ollama_model="mistral-test"),
        transport=_ollama_transport(captured),
    )
    assert completer.complete("s", "u") == SUGGESTIONS_JSON
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["body"]["model"] == "mistral-test"
    assert captured["body"]["stream"] is False


def test_ollama_provider_suggest_parses_shared_schema():
    provider = OllamaProvider(Settings(), transport=_ollama_transport({}))
    suggestions = provider.suggest("python")
    assert suggestions[0].title == "Dev"


def test_ollama_unreachable_raises_provider_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    completer = OllamaCompleter(Settings(), transport=httpx.MockTransport(boom))
    with pytest.raises(ProviderError):
        completer.complete("s", "u")
