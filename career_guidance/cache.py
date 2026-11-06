"""Tiny in-process TTL cache for public catalog responses (Phase 10).

The public catalog endpoints (``/meta``, ``/skills/suggest``,
``/careers/search``, ``/careers/{id}``) are read-only and identical for
every caller, but each request used to re-run the taxonomy search /
market snapshot work. This cache memoises the *response payload* for
:data:`TTL_SECONDS` in a bounded, thread-safe LRU dict.

Rules (enforced at the call sites in ``backend/main.py``):
- keys are built from normalised query parameters only;
- authenticated-variant responses are never cached — the career-detail
  route bypasses the cache for platform admins (who may have just edited
  the catalog) and the payload itself contains no per-user data;
- admin catalog edits become visible to everyone else within at most
  ``TTL_SECONDS`` (documented staleness bound).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

#: Staleness bound for cached public catalog payloads, in seconds.
TTL_SECONDS = 300

#: Hard cap on entries; least-recently-used entries are evicted first.
MAX_ENTRIES = 512


class TTLCache:
    """Bounded LRU dict with per-entry TTL (monotonic clock)."""

    def __init__(self, ttl: float = TTL_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires, value = entry
            if expires <= now:
                del self._entries[key]
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)


#: Process-wide instance used by the public catalog routes.
PUBLIC_CACHE = TTLCache()
