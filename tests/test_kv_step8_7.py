"""Step 8.7 tests: the local llama.cpp provider (factory selection, lazy
load, error paths) with a stubbed ``llama_cpp`` module, plus one live
test that runs only when ``KV_TEST_LLAMACPP_MODEL`` points at a real
GGUF file (mirrors the Postgres live-test pattern in test_kv_step7c.py).

The project venv HAS llama-cpp-python installed (Step 8.7), so the
missing-package path is simulated by putting ``None`` in
``sys.modules`` — ``from llama_cpp import Llama`` then raises
ImportError exactly as a missing package would.
"""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

from career_guidance.config import Settings
from career_guidance.models import ProviderError
from career_guidance.providers import (
    LlamaCppCompleter,
    LlamaCppProvider,
    ProviderFactory,
)

LIVE_MODEL = os.environ.get("KV_TEST_LLAMACPP_MODEL", "")

# Live-test transcript: deliberately NOT one of the examples in
# prompts/profile-extractor.md, so the test exercises real extraction
# rather than example recall.
LIVE_TRANSCRIPT = (
    "I am a tailor in Salem. I finished 10th class. I need a job that pays 20000 rupees a month."
)


# --------------------------------------------------------------------------- #
# Factory selection
# --------------------------------------------------------------------------- #


def test_factory_selects_llamacpp_with_path():
    settings = Settings(llm_provider="llamacpp", llamacpp_model_path="/x/model.gguf")
    assert ProviderFactory.selected_name(settings) == "llamacpp"
    assert isinstance(ProviderFactory.create_completer(settings), LlamaCppCompleter)
    assert isinstance(ProviderFactory.create_provider(settings), LlamaCppProvider)


def test_factory_llamacpp_without_path_is_none():
    settings = Settings(llm_provider="llamacpp", llamacpp_model_path="")
    assert ProviderFactory.selected_name(settings) is None
    assert ProviderFactory.create_completer(settings) is None
    assert ProviderFactory.create_provider(settings) is None


def test_factory_llamacpp_case_insensitive():
    settings = Settings(llm_provider="LlamaCpp", llamacpp_model_path="/x/model.gguf")
    assert ProviderFactory.selected_name(settings) == "llamacpp"


def test_factory_unknown_provider_is_none():
    settings = Settings(llm_provider="not-a-provider")
    assert ProviderFactory.selected_name(settings) is None


# --------------------------------------------------------------------------- #
# Stub llama_cpp module (monkeypatched into sys.modules)
# --------------------------------------------------------------------------- #


class _StubLlama:
    """A fake llama_cpp.Llama: records construction, returns canned output."""

    instances: list[_StubLlama] = []
    reply: str = '{"skills": ["farming"]}'
    fail_with: type[Exception] | None = None
    fail_on_construct: type[Exception] | None = None
    payload: dict | None = None  # when set, returned verbatim (malformed tests)

    def __init__(self, *, model_path, n_ctx, n_threads, verbose) -> None:
        if _StubLlama.fail_on_construct is not None:
            raise _StubLlama.fail_on_construct("stub load failure")
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.verbose = verbose
        self.calls: list[dict] = []
        _StubLlama.instances.append(self)

    def create_chat_completion(self, *, messages, max_tokens, temperature):
        self.calls.append(
            {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        )
        if _StubLlama.fail_with is not None:
            raise _StubLlama.fail_with("stub failure")
        if _StubLlama.payload is not None:
            return _StubLlama.payload
        return {"choices": [{"message": {"content": _StubLlama.reply}}]}


@pytest.fixture()
def stub_llama_cpp(monkeypatch):
    """Install a stub ``llama_cpp`` module; reset its class state."""
    _StubLlama.instances.clear()
    _StubLlama.reply = '{"skills": ["farming"]}'
    _StubLlama.fail_with = None
    _StubLlama.fail_on_construct = None
    _StubLlama.payload = None
    module = types.ModuleType("llama_cpp")
    module.Llama = _StubLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    return _StubLlama


@pytest.fixture()
def model_file(tmp_path):
    """An (empty) file that exists, so the is_file() check passes."""
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    return str(path)


def _settings(path: str, **overrides) -> Settings:
    values = {"llm_provider": "llamacpp", "llamacpp_model_path": path}
    values.update(overrides)
    return Settings(**values)


def test_construction_does_not_load_or_import():
    """Building the completer never touches the model file or the
    binding — loading is lazy, on first complete()."""
    completer = LlamaCppCompleter(_settings("/does/not/exist.gguf"))
    assert completer.name == "llamacpp"
    assert completer.display_name == "llama.cpp (local)"


def test_complete_with_stub_returns_content(stub_llama_cpp, model_file):
    completer = LlamaCppCompleter(_settings(model_file))
    assert completer.complete("sys", "hello") == '{"skills": ["farming"]}'
    assert len(stub_llama_cpp.instances) == 1
    instance = stub_llama_cpp.instances[0]
    assert instance.model_path == model_file
    assert instance.n_ctx == 2048  # the production prompt needs ~1440 tokens
    assert instance.n_threads == 4
    assert instance.verbose is False
    call = instance.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert call["max_tokens"] == 512
    assert call["temperature"] == 0.0  # deterministic: extraction must not vary


def test_complete_loads_model_only_once(stub_llama_cpp, model_file):
    completer = LlamaCppCompleter(_settings(model_file))
    completer.complete("sys", "one")
    completer.complete("sys", "two")
    assert len(stub_llama_cpp.instances) == 1
    assert len(stub_llama_cpp.instances[0].calls) == 2


def test_complete_empty_reply_raises(stub_llama_cpp, model_file):
    stub_llama_cpp.reply = "   "
    completer = LlamaCppCompleter(_settings(model_file))
    with pytest.raises(ProviderError, match="empty"):
        completer.complete("sys", "hello")


def test_complete_model_error_raises_provider_error(stub_llama_cpp, model_file):
    stub_llama_cpp.fail_with = RuntimeError
    completer = LlamaCppCompleter(_settings(model_file))
    with pytest.raises(ProviderError, match="completion failed"):
        completer.complete("sys", "hello")


def test_complete_provider_error_passes_through_unwrapped(stub_llama_cpp, model_file):
    """A ProviderError from the model is re-raised as-is, not wrapped
    in a second 'completion failed' message."""
    stub_llama_cpp.fail_with = ProviderError
    completer = LlamaCppCompleter(_settings(model_file))
    with pytest.raises(ProviderError, match="stub failure"):
        completer.complete("sys", "hello")


def test_complete_malformed_response_raises(stub_llama_cpp, model_file):
    stub_llama_cpp.payload = {"choices": []}
    completer = LlamaCppCompleter(_settings(model_file))
    with pytest.raises(ProviderError, match="Could not parse"):
        completer.complete("sys", "hello")


def test_load_failure_raises_provider_error(stub_llama_cpp, model_file):
    stub_llama_cpp.fail_on_construct = RuntimeError
    completer = LlamaCppCompleter(_settings(model_file))
    with pytest.raises(ProviderError, match="Could not load the local model"):
        completer.complete("sys", "hello")


def test_complete_missing_model_file_raises(stub_llama_cpp):
    completer = LlamaCppCompleter(_settings("/does/not/exist.gguf"))
    with pytest.raises(ProviderError, match="not found"):
        completer.complete("sys", "hello")


def test_complete_unset_model_path_raises(stub_llama_cpp):
    completer = LlamaCppCompleter(_settings(""))
    with pytest.raises(ProviderError, match="LLAMACPP_MODEL_PATH is not set"):
        completer.complete("sys", "hello")


def test_complete_without_package_raises(monkeypatch):
    """No llama_cpp installed: a clear error pointing at the guide.
    Simulated with sys.modules None (the project venv HAS the package
    installed since Step 8.7, so the real ImportError cannot be
    observed here)."""
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    completer = LlamaCppCompleter(_settings("/x/model.gguf"))
    with pytest.raises(ProviderError, match="llama-cpp-python.*not installed"):
        completer.complete("sys", "hello")


def test_injected_model_used_without_import():
    """A model passed to the constructor is used directly — the
    binding is never imported (works even with no package)."""
    stub = _StubLlama(model_path="/injected.gguf", n_ctx=128, n_threads=1, verbose=False)
    completer = LlamaCppCompleter(_settings("/does/not/exist.gguf"), model=stub)
    assert completer.complete("sys", "hello") == '{"skills": ["farming"]}'
    assert len(stub.calls) == 1


def test_provider_suggest_with_stub(stub_llama_cpp, model_file):
    """The SuggestionProvider side parses the stub's JSON array."""
    stub_llama_cpp.reply = json.dumps([{"title": "Electrician", "rationale": "You know wiring."}])
    provider = LlamaCppProvider(_settings(model_file))
    assert provider.name == "llama.cpp (local)"
    suggestions = provider.suggest("I know wiring and circuits")
    assert len(suggestions) == 1
    assert suggestions[0].title == "Electrician"


def test_settings_env_parsing(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "llamacpp")
    monkeypatch.setenv("LLAMACPP_MODEL_PATH", "/env/model.gguf")
    monkeypatch.setenv("LLAMACPP_N_CTX", "1024")
    monkeypatch.setenv("LLAMACPP_N_THREADS", "2")
    monkeypatch.setenv("LLAMACPP_MAX_TOKENS", "256")
    from career_guidance.config import load_settings

    settings = load_settings()
    assert settings.llm_provider == "llamacpp"
    assert settings.llamacpp_model_path == "/env/model.gguf"
    assert settings.llamacpp_n_ctx == 1024
    assert settings.llamacpp_n_threads == 2
    assert settings.llamacpp_max_tokens == 256


# --------------------------------------------------------------------------- #
# Live test (skipped unless KV_TEST_LLAMACPP_MODEL is set)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not LIVE_MODEL, reason="set KV_TEST_LLAMACPP_MODEL to run the live test")
def test_live_llamacpp_extraction():
    """The real model + the real production prompt on a transcript
    that is NOT one of the prompt's examples: the reply parses as
    JSON, carries all 7 schema keys, and gets skills / education /
    city / income right. Known 0.5B errors on this input (see L60):
    ``interests`` came back as "job_6_months" and ``goal_type`` as
    "explore" — the test deliberately does NOT assert those two,
    because pinning wrong behaviour as expected would be dishonest.
    Runs ~35 s (prompt processing dominates on CPU)."""
    from career_guidance.kaamvaani.profile import load_prompt

    settings = Settings(
        llm_provider="llamacpp",
        llamacpp_model_path=LIVE_MODEL,
        llamacpp_n_ctx=2048,
        llamacpp_max_tokens=256,
    )
    completer = LlamaCppCompleter(settings)
    prompt = load_prompt("profile-extractor")
    reply = completer.complete(
        prompt.system_prompt, f"Language: en.\nTranscript: {LIVE_TRANSCRIPT}"
    )
    data = json.loads(reply)
    assert set(data) == {
        "skills",
        "interests",
        "education",
        "city",
        "income_text",
        "income_monthly",
        "goal_type",
    }
    assert data["skills"] == ["tailoring"]
    assert data["education"] == "10th pass"
    assert data["city"] == "Salem"
    assert data["income_monthly"] == 20000
    assert data["income_text"] == "₹20,000 / month"
