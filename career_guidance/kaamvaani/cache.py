"""Kaam-Vaani caches (Step 8.6).

Four caches, one eviction policy (LRU, bounded, thread-safe), and an
invalidation rule per cache. The rule for every cache is the same
principle: **a cache entry is keyed by everything that determines its
value, so a stale entry is unreachable, not merely unlikely.**

1. **Translation cache** (``translation_cache``) — ``translate_query``
   results, keyed by the raw query string. The glossary is loaded once
   per process (``translate._load_glossary`` is ``lru_cache``d), so
   within a process translation is a pure function of the query: no
   invalidation is possible or needed. A glossary edit takes effect on
   restart, like every other process-lifetime load in the app.
2. **Answer / search cache** — owned by the RAG router
   (``backend/kv_rag.py``), keyed by ``(snapshot_versions, kind,
   query, top_k, filters)``. The snapshot version is IN the key, so a
   re-ingest can never serve a pre-ingest answer: old entries become
   unreachable and age out by LRU. Values are deep-copied on read so a
   caller mutating a returned dict cannot poison the cache.
3. **Profile cache** (``profile_cache``) — the voice router's
   ``/extract`` results, keyed by ``(payload, prompt_version)`` where
   the payload is the transcript or the guided-flow answers. The
   cache lives in the router, not in ``extract_profile_smart``: the
   router owns one fixed completer and the process vocabulary, so
   (payload, prompt version) fully determines the result, while the
   bare function takes an explicit completer/vocab. The deterministic
   path keys on prompt version ``""`` (it never reads the prompt); the
   LLM path keys on the versioned prompt, so a prompt edit naturally
   misses. The cached ``method`` is the provenance of the profile (it
   really was produced by that path on first call).
4. **LLM-result cache** — :class:`CachingCompleter` wraps any
   :class:`~career_guidance.providers.ChatCompleter` and caches
   ``complete(system_prompt, user_content)`` by the SHA-256 of both
   strings, with a 1-hour TTL. The TTL bounds staleness if the model
   behind a URL is swapped (e.g. an Ollama model re-pulled) without a
   restart; the settings (provider, model name, base URL) are fixed
   per process. Failures are NEVER cached: a ``ProviderError`` passes
   through and the next call retries the provider.

All four caches are **per-process, in-memory** (LIMITATIONS.md L59):
nothing is shared across workers or restarts, and nothing is written
to disk. Sizes are small by design (a few hundred entries of short
strings / small dicts) — the pilot's repeated questions (many workers
ask the same scheme questions) are what the caches serve, not
first-time questions. Hit rates and latency are measured in
ARCHITECTURE.md §7.10.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from career_guidance.config import Settings
from career_guidance.providers import ChatCompleter, ProviderFactory

# Default bounds. An answer dict is ~1-2 KB (a 600-char quote + a few
# hit dicts); 256 entries is well under 1 MB. A translation entry is a
# short string pair; 512 entries is tens of KB. A profile is a small
# Pydantic model; 256 entries is well under 1 MB.
TRANSLATION_CACHE_MAXSIZE = 512
ANSWER_CACHE_MAXSIZE = 256
PROFILE_CACHE_MAXSIZE = 256
LLM_CACHE_MAXSIZE = 256
# LLM results: 1 hour. Extraction prompts are stable, but the model
# behind a local URL can be re-pulled without a restart — the TTL caps
# how long a pre-swap answer can be served.
LLM_CACHE_TTL_SECONDS = 3600.0


def cache_key(*parts: Any) -> str:
    """A stable cache key: the SHA-256 of the JSON of ``parts``.

    Parts must be JSON-serialisable (strings, numbers, tuples/lists of
    them). Two calls with equal parts produce equal keys; different
    parts (including a different snapshot version) produce different
    keys with overwhelming probability.
    """
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CacheStats:
    """Hit/miss accounting for one cache. ``hit_rate`` is None until
    the first lookup (no lookups yet is not a 0% hit rate)."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    maxsize: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        if self.lookups == 0:
            return None
        return self.hits / self.lookups

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "maxsize": self.maxsize,
            "hit_rate": self.hit_rate,
        }


class LruCache:
    """A bounded, thread-safe LRU cache with optional per-entry TTL.

    ``maxsize`` bounds memory: inserting past it evicts the
    least-recently-used entry (counted in ``stats().evictions``).
    ``ttl_seconds`` (None = no expiry) bounds staleness: an expired
    entry counts as a miss and is dropped on lookup. ``clock`` is
    injectable (``time.monotonic`` by default) so TTL tests are
    deterministic instead of sleeping. ``deepcopy_values`` deep-copies
    values on read — on for caches whose values are mutable dicts
    (answers), off for immutable values (frozen dataclasses, strings).
    """

    def __init__(
        self,
        maxsize: int = 256,
        *,
        ttl_seconds: float | None = None,
        deepcopy_values: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._deepcopy = deepcopy_values
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def _expired(self, stored_at: float, now: float) -> bool:
        return self._ttl is not None and now - stored_at > self._ttl

    def get(self, key: str) -> Any | None:
        """The cached value, or None on a miss (expired counts as a
        miss). A hit refreshes the entry's LRU position."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, stored_at = entry
            if self._expired(stored_at, now):
                del self._entries[key]
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return copy.deepcopy(value) if self._deepcopy else value

    def put(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``, evicting LRU entries past
        ``maxsize``. Re-putting an existing key refreshes it. With
        ``deepcopy_values`` the stored value is a copy, so mutating
        the caller's object after ``put`` cannot change the cache —
        the router puts a dict and returns that same dict, so the
        stored copy must be independent of the returned one."""
        now = self._clock()
        stored = copy.deepcopy(value) if self._deepcopy else value
        with self._lock:
            if key in self._entries:
                del self._entries[key]
            self._entries[key] = (stored, now)
            while len(self._entries) > self._maxsize:
                self._entries.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        """Drop all entries (stats are kept — they describe the cache's
        lifetime, not its current contents)."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def ttl_seconds(self) -> float | None:
        """The per-entry TTL this cache was built with (None = no expiry)."""
        return self._ttl

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                size=len(self._entries),
                maxsize=self._maxsize,
            )


# --------------------------------------------------------------------------- #
# The four caches (process-wide instances; the answer cache is owned by
# the RAG router instead — it needs the router's snapshot versions — and
# is an LruCache created in backend/kv_rag.py with ANSWER_CACHE_MAXSIZE
# and deepcopy_values=True).
# --------------------------------------------------------------------------- #

# Translation results: TranslatedQuery is a frozen dataclass, so values
# are safe to share without copying.
translation_cache = LruCache(maxsize=TRANSLATION_CACHE_MAXSIZE)

# Profile extraction results: (VoiceProfile, method) tuples. VoiceProfile
# is a Pydantic model — callers treat it as read-only (the voice router
# serialises it; the guided flow uses model_copy for edits), so no copy
# on read. The profile cache stores the tuple as returned.
profile_cache = LruCache(maxsize=PROFILE_CACHE_MAXSIZE)

# LLM completions: response strings, immutable, TTL-bounded.
llm_cache = LruCache(maxsize=LLM_CACHE_MAXSIZE, ttl_seconds=LLM_CACHE_TTL_SECONDS)


def clear_all_caches() -> None:
    """Drop every process-wide cache entry (tests + manual invalidation).
    The router-owned answer cache is cleared by rebuilding the router
    (its snapshot-version keying makes explicit clearing unnecessary).
    """
    translation_cache.clear()
    profile_cache.clear()
    llm_cache.clear()


def profile_cache_key(payload: Any, prompt_version: str) -> str:
    """Key for a profile-extraction result: the request payload (the
    transcript, or ``("answers", {...})`` for the guided flow) plus
    the version of the extraction prompt that produced it. The
    deterministic path passes ``""`` — it never reads the prompt."""
    return cache_key("profile", payload, prompt_version)


class CachingCompleter(ChatCompleter):
    """A :class:`ChatCompleter` that caches completions by the hash of
    (system prompt, user content) in the shared ``llm_cache``.

    Wrapping is transparent: same interface, same errors. A failed call
    (``ProviderError`` or anything else) is never cached — the next
    call retries the provider. ``name``/``display_name`` delegate to
    the wrapped completer so status endpoints still report the real
    provider.
    """

    def __init__(self, inner: ChatCompleter, cache: LruCache | None = None) -> None:
        if isinstance(inner, CachingCompleter):
            raise ValueError("do not wrap a CachingCompleter in another one")
        self._inner = inner
        # NOTE: ``cache or llm_cache`` would be wrong here — an empty
        # LruCache is falsy (it defines __len__), so a fresh cache
        # passed in would be silently replaced by the shared one.
        self._cache = llm_cache if cache is None else cache
        self.name = inner.name
        self.display_name = inner.display_name

    @property
    def inner(self) -> ChatCompleter:
        """The wrapped completer (tests + introspection)."""
        return self._inner

    def complete(self, system_prompt: str, user_content: str) -> str:
        key = cache_key("llm", system_prompt, user_content)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        # Not cached — and a failure here must not poison the cache:
        # only a returned string is stored.
        result = self._inner.complete(system_prompt, user_content)
        self._cache.put(key, result)
        return result


def cached_completer(settings: Settings) -> ChatCompleter | None:
    """The configured completer wrapped in the shared LLM cache, or
    None when no LLM is configured (callers fall back to deterministic
    paths). Each call builds a fresh wrapper, but all wrappers share
    the module-level ``llm_cache``, so a completion cached through one
    wrapper is a hit through another. Callers pass ``settings`` (never
    an already-built completer), so double-wrapping cannot happen."""
    completer = ProviderFactory.create_completer(settings)
    if completer is None:
        return None
    return CachingCompleter(completer)
