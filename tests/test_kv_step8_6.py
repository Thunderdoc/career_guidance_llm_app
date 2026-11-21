"""Step 8.6 tests: the four Kaam-Vaani caches (LRU core, translation,
answer/search, profile, LLM-result) — eviction, invalidation, stats,
thread safety, and the router wiring.

Cache tests are order-independent by construction: unit tests use fresh
LruCache instances, and router tests assert stat DELTAS (the module
caches are shared across the pytest process, so absolute counts depend
on what ran before).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.kv_rag import build_router as build_kv_rag_router
from backend.kv_voice import build_router as build_kv_voice_router
from career_guidance.config import Settings
from career_guidance.kaamvaani.cache import (
    CacheStats,
    CachingCompleter,
    LruCache,
    cache_key,
    cached_completer,
    clear_all_caches,
    llm_cache,
    profile_cache,
    profile_cache_key,
    translation_cache,
)
from career_guidance.kaamvaani.rag import RagStore, load_snapshot_file
from career_guidance.kaamvaani.translate import (
    _translate_query_uncached,
    translate_query,
)
from career_guidance.migrations import migrate
from career_guidance.models import ProviderError
from career_guidance.providers import ChatCompleter

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# LruCache core
# --------------------------------------------------------------------------- #


def test_put_get_roundtrip_and_stats():
    cache = LruCache(maxsize=4)
    assert cache.stats().hit_rate is None  # no lookups yet, not 0%
    assert cache.get("missing") is None
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("a") == 1
    stats = cache.stats()
    assert stats.hits == 2
    assert stats.misses == 1
    assert stats.size == 1
    assert stats.maxsize == 4
    assert stats.lookups == 3
    assert stats.hit_rate == pytest.approx(2 / 3)
    assert len(cache) == 1


def test_lru_eviction_order():
    cache = LruCache(maxsize=3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") == 1  # refreshes a: order is now b, c, a
    cache.put("d", 4)  # evicts b (least recently used)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("d") == 4
    assert cache.stats().evictions == 1
    assert len(cache) == 3


def test_reput_refreshes_entry():
    cache = LruCache(maxsize=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)  # refresh: order is now b, a
    cache.put("c", 3)  # evicts b
    assert cache.get("a") == 10
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_maxsize_one_keeps_only_latest():
    cache = LruCache(maxsize=1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.stats().evictions == 1


def test_maxsize_zero_raises():
    with pytest.raises(ValueError):
        LruCache(maxsize=0)


def test_ttl_expiry_with_injected_clock():
    now = [1000.0]
    cache = LruCache(maxsize=4, ttl_seconds=60.0, clock=lambda: now[0])
    cache.put("a", 1)
    now[0] = 1059.0
    assert cache.get("a") == 1  # still fresh
    now[0] = 1061.0
    assert cache.get("a") is None  # expired: a miss, and dropped
    assert len(cache) == 0
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1


def test_no_ttl_never_expires():
    now = [1000.0]
    cache = LruCache(maxsize=4, clock=lambda: now[0])
    cache.put("a", 1)
    now[0] = 1000.0 + 10 * 365 * 24 * 3600  # ten years later
    assert cache.get("a") == 1


def test_deepcopy_values_isolates_both_directions():
    cache = LruCache(maxsize=4, deepcopy_values=True)
    original = {"hits": [{"score": 0.9}], "refused": False}
    cache.put("k", original)
    original["refused"] = True  # mutating the caller's dict after put
    original["hits"][0]["score"] = 0.0
    stored = cache.get("k")
    assert stored == {"hits": [{"score": 0.9}], "refused": False}
    stored["hits"][0]["score"] = 0.0  # mutating the returned dict
    assert cache.get("k")["hits"][0]["score"] == 0.9


def test_clear_empties_but_keeps_stats():
    cache = LruCache(maxsize=4)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None
    stats = cache.stats()
    assert stats.hits == 1  # lifetime accounting survives the clear
    assert stats.misses == 2


def test_thread_safety_smoke():
    cache = LruCache(maxsize=50)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(200):
                key = f"w{n}-{i % 20}"
                cache.put(key, i)
                cache.get(key)
                cache.get(f"missing-{i}")
        except BaseException as exc:  # noqa: BLE001 - collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(cache) <= 50
    stats = cache.stats()
    assert stats.lookups == 4 * 200 * 2  # every get counted exactly once


def test_cache_key_stable_and_version_sensitive():
    key1 = cache_key("ask", ("v2",), "what is the NCS helpline number")
    key2 = cache_key("ask", ("v2",), "what is the NCS helpline number")
    key3 = cache_key("ask", ("v3",), "what is the NCS helpline number")
    key4 = cache_key("search", ("v2",), "what is the NCS helpline number")
    assert key1 == key2
    assert key1 != key3  # a snapshot version bump is a different key
    assert key1 != key4  # ask and search never collide
    assert len(key1) == 64 and all(c in "0123456789abcdef" for c in key1)


def test_cache_stats_to_dict():
    stats = CacheStats(hits=3, misses=1, evictions=0, size=2, maxsize=8)
    assert stats.to_dict() == {
        "hits": 3,
        "misses": 1,
        "evictions": 0,
        "size": 2,
        "maxsize": 8,
        "hit_rate": 0.75,
    }


# --------------------------------------------------------------------------- #
# Translation cache
# --------------------------------------------------------------------------- #


def test_translate_cached_second_call_is_hit():
    clear_all_caches()
    before = translation_cache.stats()
    first = translate_query("மின் பணியாளர் வேலை")
    second = translate_query("மின் பணியாளர் வேலை")
    assert first == second
    after = translation_cache.stats()
    assert after.misses - before.misses == 1
    assert after.hits - before.hits == 1


def test_translate_cache_does_not_change_result():
    clear_all_caches()
    for query in (
        "how do i become an electrician",
        "மின் பணியாளர் வேலை",
        "बिजली का काम",
        "electrician velai Madurai",
        "",
    ):
        assert translate_query(query) == _translate_query_uncached(query)


# --------------------------------------------------------------------------- #
# CachingCompleter (LLM-result cache)
# --------------------------------------------------------------------------- #


class _CountingCompleter(ChatCompleter):
    """A mock completer that counts calls and can fail on demand."""

    name = "mock"
    display_name = "Mock"

    def __init__(self) -> None:
        self.calls = 0
        self.fail_next = 0

    def complete(self, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ProviderError("mock failure")
        return f"[{system_prompt[:8]}] {user_content}"


def test_caching_completer_calls_inner_once():
    inner = _CountingCompleter()
    cached = CachingCompleter(inner, cache=LruCache(maxsize=16))
    first = cached.complete("sys-prompt", "hello")
    second = cached.complete("sys-prompt", "hello")
    assert first == second
    assert inner.calls == 1


def test_caching_completer_distinct_prompts_are_distinct():
    inner = _CountingCompleter()
    cached = CachingCompleter(inner, cache=LruCache(maxsize=16))
    cached.complete("sys-prompt", "hello")
    cached.complete("sys-prompt", "goodbye")
    cached.complete("other-system", "hello")
    assert inner.calls == 3


def test_caching_completer_does_not_cache_failures():
    inner = _CountingCompleter()
    inner.fail_next = 1
    cached = CachingCompleter(inner, cache=LruCache(maxsize=16))
    with pytest.raises(ProviderError):
        cached.complete("sys", "hello")
    assert cached.complete("sys", "hello") == "[sys] hello"  # retried, succeeded
    assert cached.complete("sys", "hello") == "[sys] hello"  # now a hit
    assert inner.calls == 2  # the failure + the success, nothing more


def test_caching_completer_rejects_double_wrap():
    inner = _CountingCompleter()
    wrapped = CachingCompleter(inner, cache=LruCache(maxsize=16))
    with pytest.raises(ValueError):
        CachingCompleter(wrapped, cache=LruCache(maxsize=16))


def test_caching_completer_delegates_name():
    inner = _CountingCompleter()
    cached = CachingCompleter(inner, cache=LruCache(maxsize=16))
    assert cached.name == "mock"
    assert cached.display_name == "Mock"
    assert cached.inner is inner


def test_caching_completer_ttl_expires():
    now = [1000.0]
    inner = _CountingCompleter()
    cache = LruCache(maxsize=16, ttl_seconds=60.0, clock=lambda: now[0])
    cached = CachingCompleter(inner, cache=cache)
    cached.complete("sys", "hello")
    now[0] = 2000.0  # past the TTL: the provider is called again
    cached.complete("sys", "hello")
    assert inner.calls == 2


def test_cached_completer_none_without_config():
    assert cached_completer(Settings()) is None


def test_llm_cache_shared_instance_has_ttl():
    # The process-wide LLM cache is TTL-bounded (a model swapped
    # behind a URL must not be served forever).
    assert llm_cache.stats().maxsize == 256
    assert llm_cache.ttl_seconds == 3600.0


# --------------------------------------------------------------------------- #
# Profile cache key
# --------------------------------------------------------------------------- #


def test_profile_cache_key_prompt_version_matters():
    key1 = profile_cache_key("I know farming", "1.0.0")
    key2 = profile_cache_key("I know farming", "1.0.0")
    key3 = profile_cache_key("I know farming", "1.1.0")
    key4 = profile_cache_key(("answers", {"skills": "farming"}), "1.0.0")
    assert key1 == key2
    assert key1 != key3  # a prompt edit naturally misses
    assert key1 != key4  # text and answers payloads never collide


# --------------------------------------------------------------------------- #
# Router wiring: RAG answer/search cache
# --------------------------------------------------------------------------- #


@pytest.fixture()
def populated_rag_client(tmp_path):
    """A standalone app with only the kv_rag router, over a scratch DB
    holding the real snapshot v2 (same fixture shape as Stage 2)."""
    db = str(tmp_path / "rag.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_rag_router(settings))
    with TestClient(app) as client:
        yield client


def _rag_cache_stats(client) -> dict:
    return client.get("/api/v1/kv/rag/status").json()["cache"]


def _payload(body: dict) -> dict:
    """The response payload without the per-request trace id (Step
    8.9): two calls for the same request share the cached payload
    but each carries its own trace."""
    return {k: v for k, v in body.items() if k != "trace_id"}


def test_rag_ask_cached_second_call_is_hit(populated_rag_client):
    client = populated_rag_client
    before = _rag_cache_stats(client)
    first = client.post("/api/v1/kv/rag/ask", json={"question": "what is the NCS helpline number"})
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/kv/rag/ask", json={"question": "what is the NCS helpline number"})
    assert second.status_code == 200, second.text
    assert _payload(second.json()) == _payload(first.json())
    assert second.json()["trace_id"] != first.json()["trace_id"]
    after = _rag_cache_stats(client)
    assert after["misses"] - before["misses"] == 1
    assert after["hits"] - before["hits"] == 1
    assert after["size"] == before["size"] + 1


def test_rag_search_cached_second_call_is_hit(populated_rag_client):
    client = populated_rag_client
    before = _rag_cache_stats(client)
    first = client.post("/api/v1/kv/rag/search", json={"query": "how do i become an electrician"})
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/kv/rag/search", json={"query": "how do i become an electrician"})
    assert _payload(second.json()) == _payload(first.json())
    assert second.json()["trace_id"] != first.json()["trace_id"]
    after = _rag_cache_stats(client)
    assert after["misses"] - before["misses"] == 1
    assert after["hits"] - before["hits"] == 1


def test_rag_cache_keyed_by_filters_and_top_k(populated_rag_client):
    client = populated_rag_client
    before = _rag_cache_stats(client)
    client.post("/api/v1/kv/rag/search", json={"query": "electrician", "top_k": 5})
    client.post("/api/v1/kv/rag/search", json={"query": "electrician", "top_k": 3})
    client.post(
        "/api/v1/kv/rag/search",
        json={"query": "electrician", "top_k": 5, "topic": "occupation"},
    )
    after = _rag_cache_stats(client)
    # Three distinct keys: no hits, three misses.
    assert after["hits"] - before["hits"] == 0
    assert after["misses"] - before["misses"] == 3


def test_rag_cache_invalidated_by_snapshot_version(tmp_path):
    """A re-ingest under a new snapshot version misses the cache: the
    old answer is unreachable, never served stale."""
    db = str(tmp_path / "rag.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    store = RagStore(db)
    store.replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_rag_router(settings))
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/kv/rag/ask", json={"question": "what is the NCS helpline number"}
        )
        assert first.status_code == 200, first.text
        before = _rag_cache_stats(client)
        # Re-ingest the SAME chunks under a new version: the content
        # is identical, but the key changes, so the cache must miss.
        store.replace_snapshot(chunks, "v3")
        second = client.post(
            "/api/v1/kv/rag/ask", json={"question": "what is the NCS helpline number"}
        )
        assert second.status_code == 200, second.text
        # Same answer content — but the retrieved chunks carry the NEW
        # snapshot version, which proves the lookup was fresh (a stale
        # cached answer would still say v2).
        assert second.json()["answer"] == first.json()["answer"]
        assert second.json()["citations"] == first.json()["citations"]
        assert second.json()["top_score"] == first.json()["top_score"]
        assert all(hit["chunk"]["snapshot_version"] == "v3" for hit in second.json()["retrieved"])
        after = _rag_cache_stats(client)
        assert after["hits"] - before["hits"] == 0
        assert after["misses"] - before["misses"] == 1


def test_rag_status_reports_cache_stats(populated_rag_client):
    body = populated_rag_client.get("/api/v1/kv/rag/status").json()
    assert body["cache"]["maxsize"] == 256
    assert body["cache"]["hits"] >= 0
    assert body["cache"]["misses"] >= 0
    assert body["cache"]["hit_rate"] is None or 0.0 <= body["cache"]["hit_rate"] <= 1.0


# --------------------------------------------------------------------------- #
# Router wiring: voice profile cache
# --------------------------------------------------------------------------- #


@pytest.fixture()
def voice_client():
    settings = Settings()
    app = FastAPI()
    app.include_router(build_kv_voice_router(settings))
    with TestClient(app) as client:
        yield client


def test_voice_extract_cached_second_call_is_hit(voice_client):
    clear_all_caches()  # the profile cache is process-shared; start empty
    before = profile_cache.stats()
    payload = {
        "text": "I finished 10th in Dindigul. I know tailoring and stitching. "
        "I need a job, 12000 a month.",
        "language": "en",
    }
    first = voice_client.post("/api/v1/kv/voice/extract", json=payload)
    assert first.status_code == 200, first.text
    second = voice_client.post("/api/v1/kv/voice/extract", json=payload)
    assert second.status_code == 200, second.text
    assert _payload(second.json()) == _payload(first.json())
    assert second.json()["trace_id"] != first.json()["trace_id"]
    after = profile_cache.stats()
    assert after.misses - before.misses == 1
    assert after.hits - before.hits == 1


def test_voice_extract_answers_cached(voice_client):
    clear_all_caches()  # the profile cache is process-shared; start empty
    before = profile_cache.stats()
    payload = {
        "answers": {
            "skills": "tailoring and stitching",
            "education": "10th pass",
            "city": "Dindigul",
            "income": "12000 a month",
            "goal": "I need a job",
        },
        "language": "en",
    }
    first = voice_client.post("/api/v1/kv/voice/extract", json=payload)
    assert first.status_code == 200, first.text
    second = voice_client.post("/api/v1/kv/voice/extract", json=payload)
    assert _payload(second.json()) == _payload(first.json())
    assert second.json()["trace_id"] != first.json()["trace_id"]
    after = profile_cache.stats()
    assert after.misses - before.misses == 1
    assert after.hits - before.hits == 1


def test_voice_status_reports_profile_cache(voice_client):
    body = voice_client.get("/api/v1/kv/voice/status").json()
    assert body["profile_cache"]["maxsize"] == 256
    assert body["profile_cache"]["hits"] >= 0
    assert body["profile_cache"]["misses"] >= 0
