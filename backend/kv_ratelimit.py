"""Shared rate-limit plumbing for the Kaam-Vaani routers (Step 9.4).

Every Kaam-Vaani limiter is created through :func:`kv_limiter`,
which registers it so the test suite can reset all of them
between tests (an autouse fixture in ``tests/conftest.py`` calls
:func:`reset_all_kv_limiters`). Without the reset, the suite's
own calls from the single TestClient IP would trip the limits.

Honest limits of this design (recorded in SECURITY.md and A65):
the limiter is per-process in-memory, so a multi-worker deploy
has one limit per worker, not one global limit; and
:func:`client_key` trusts the first ``X-Forwarded-For`` entry,
which a client can spoof to rotate keys. This is friction
against casual abuse, not a hard abuse boundary — true
protection belongs at the platform edge.
"""

from __future__ import annotations

from fastapi import Request

from backend.ratelimit import RateLimiter

_LIMITERS: list[RateLimiter] = []


def client_key(request: Request) -> str:
    """Per-IP key for anonymous endpoints: first X-Forwarded-For
    entry, else the direct client host. Same rule as main.py's
    ``_client`` (duplicated here because routers cannot import
    from main without a cycle)."""
    return request.headers.get(
        "x-forwarded-for", request.client.host if request.client else "?"
    ).split(",")[0]


def kv_limiter(max_calls: int, per_seconds: int) -> RateLimiter:
    """Create a limiter and register it for test resets."""
    limiter = RateLimiter(max_calls, per_seconds)
    _LIMITERS.append(limiter)
    return limiter


def reset_all_kv_limiters() -> None:
    """Drop every recorded hit on every registered KV limiter."""
    for limiter in _LIMITERS:
        limiter.reset()
