"""Phase 10: public catalog response cache + catalog loaded once.

The cache memoises /meta, /skills/suggest, /careers/search and
/careers/{id} payloads (TTL in career_guidance.cache). These tests prove
the underlying work runs once across repeated identical requests, that
results stay correct, that distinct parameters stay distinct, that the
taxonomy JSON is loaded once per process (lru_cache), and that platform
admins bypass the career-detail cache.
"""

from __future__ import annotations

import pytest

from career_guidance.cache import PUBLIC_CACHE, TTLCache
from tests.conftest import login


@pytest.fixture(autouse=True)
def _clean_cache():
    PUBLIC_CACHE.clear()
    yield
    PUBLIC_CACHE.clear()


def test_ttl_cache_expires_and_evicts():
    import career_guidance.cache as cache_mod

    cache = TTLCache(ttl=60, max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)  # evicts "a" (LRU)
    assert cache.get("a") is None
    assert cache.get("c") == 3

    short = TTLCache(ttl=0.05, max_entries=4)
    short.set("x", 9)
    assert short.get("x") == 9
    import time

    time.sleep(0.06)
    assert short.get("x") is None
    assert cache_mod.TTL_SECONDS == 300


def test_careers_search_cached_and_correct(client, monkeypatch):
    import career_guidance.taxonomy as taxonomy

    calls = {"n": 0}
    original = taxonomy.Taxonomy.search

    def counting(self, query, limit=10):
        calls["n"] += 1
        return original(self, query, limit)

    monkeypatch.setattr(taxonomy.Taxonomy, "search", counting)

    first = client.get("/api/v1/careers/search", params={"q": "data", "limit": 5})
    assert first.status_code == 200
    second = client.get("/api/v1/careers/search", params={"q": " Data ", "limit": 5})
    assert second.status_code == 200
    assert second.json() == first.json()  # normalised key, identical payload
    assert calls["n"] == 1  # taxonomy searched once across both requests

    third = client.get("/api/v1/careers/search", params={"q": "nurse", "limit": 5})
    assert third.status_code == 200
    assert calls["n"] == 2  # a different query is a different entry
    assert third.json() != first.json()


def test_meta_and_skills_suggest_cached(client):
    meta1 = client.get("/api/v1/meta").json()
    assert PUBLIC_CACHE.get("meta") == meta1
    meta2 = client.get("/api/v1/meta").json()
    assert meta2 == meta1

    s1 = client.get("/api/v1/skills/suggest", params={"q": "pyth"}).json()
    assert s1["suggestions"]
    assert client.get("/api/v1/skills/suggest", params={"q": "pyth"}).json() == s1
    assert PUBLIC_CACHE.hits >= 1


def test_taxonomy_loaded_once_per_process(client):
    from career_guidance.taxonomy import load_taxonomy

    before = load_taxonomy.cache_info()
    for _ in range(3):
        assert client.get("/api/v1/careers/search", params={"q": "engineer"}).status_code == 200
    after = load_taxonomy.cache_info()
    # No additional disk loads (misses) across the repeated requests:
    # the catalog was loaded once and is reused process-wide.
    assert after.misses == before.misses


def test_career_detail_cached_for_users_admin_bypasses(auth_client, client, monkeypatch):
    import backend.journey as journey

    search = auth_client.get("/api/v1/careers/search", params={"q": "data analyst"})
    career_id = search.json()["results"][0]["id"]

    calls = {"n": 0}
    original = journey.career_extras

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(journey, "career_extras", counting)

    one = auth_client.get(f"/api/v1/careers/{career_id}")
    assert one.status_code == 200
    two = auth_client.get(f"/api/v1/careers/{career_id}")
    assert two.json() == one.json()
    assert calls["n"] == 1  # second response served from the cache

    # A platform admin bypasses the cache entirely (fresh catalog edits).
    admin_client = client
    login(admin_client, "boss@example.com")
    three = admin_client.get(f"/api/v1/careers/{career_id}")
    assert three.status_code == 200
    assert three.json()["id"] == career_id
    assert calls["n"] == 2
