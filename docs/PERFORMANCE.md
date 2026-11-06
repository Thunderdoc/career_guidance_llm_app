# Performance — Phase 10

## Public catalog cache

`career_guidance/cache.py` — an in-process, thread-safe, bounded LRU
cache with a 300 s TTL (`TTL_SECONDS`, max 512 entries), wired into the
public catalog routes in `backend/main.py`:

| Route | Cache key | Bypass |
|---|---|---|
| `GET /api/v1/meta` | `meta` | — (no variants exist) |
| `GET /api/v1/skills/suggest` | normalised `q` + `limit` | — |
| `GET /api/v1/careers/search` | normalised `q` + `limit` (the taxonomy search itself strips/lowercases, so normalising the key cannot mix result sets) | — |
| `GET /api/v1/careers/{id}` | `career_id` + `country` | **platform admins bypass** (they may have just edited the catalog/market data); the payload contains no per-user fields |

Staleness bound: an admin catalog/market edit becomes visible to
non-admin callers within at most 300 s. Tests in
`tests/test_public_cache.py` prove the underlying taxonomy search /
career-extras work runs **once** across repeated identical requests,
that distinct parameters stay distinct, and that results are unchanged.

**Catalog loaded once per process:** `career_guidance.taxonomy.
load_taxonomy` is `functools.lru_cache`-memoised (maxsize 2) and the
matcher is built once at startup (`backend.main._warm`); a test asserts
`load_taxonomy.cache_info().misses` does not grow across repeated
search requests.

## /recommend latency

Measured 2026-11-06 on the development sandbox VM with
`scripts/bench_recommend.py` (direct uvicorn, scratch port + scratch
database, anonymous requests, fixed representative payload, 1 warm-up
excluded, 25 measured requests — the route's own 30/min rate limit
caps a single run):

| Run | min | median | **p95** | max |
|---|---|---|---|---|
| 1 | 746.6 ms | 841.6 ms | **943.4 ms** | 954.3 ms |
| 2 | 761.2 ms | 867.3 ms | **953.6 ms** | 955.7 ms |

**Baseline caveat (honest):** the "~292 ms" Phase 1 figure was the
*eval harness's in-process matcher latency* (`eval/run.py`,
`p95_latency_ms` over the golden cases — no HTTP, no persistence, no
middleware), not an end-to-end HTTP number, and it was measured on a
different machine. The bench above is end-to-end HTTP on a shared
sandbox VM (request middleware, matching, reality enrichment, run
persistence, gamification hooks). The two numbers are therefore **not
directly comparable**; the eval-harness p95 from the Phase 10 gate run
is recorded in `docs/UPGRADE_PLAN.md` §5 Phase 10 status alongside this
table so future comparisons use like-for-like series:
`scripts/bench_recommend.py` for HTTP, `eval/run.py` for in-process.

**Like-for-like eval series (in-process, golden set):** the Phase 10
gate run of `python -m eval.run` measured **p95 = 238.4 ms** (skills,
50 cases; interests p95 91.2 ms) — against the Phase 1 baseline of
~292 ms on the same harness, the matcher path has not regressed; it
improved by ~54 ms on this machine.

## Database index review (migration v10)

Every store's queries were reviewed. Already indexed (verified, not
duplicated): users by e-mail (UNIQUE) and handle (v5 partial UNIQUE),
skill_progress by user (PK prefix), share_tokens by hash (v8),
run_reviews by run (v6), consent_records by user + token hash (v7),
quiz_attempts by (user, skill, created) (v5), users by institute (v6),
coupon_redemptions (v9), subscriptions by user (v9).

Added in v10 for the hot per-user lookups that were full scans:
`idx_runs_user` (recommendation_runs user_id, id),
`idx_assessment_runs_user`, `idx_plans_user`,
`idx_interview_sessions_user`, `idx_payments_user`.

`EXPLAIN QUERY PLAN` on a scratch DB seeded with 5,000 runs / 2,000
assessment runs across 50 users (index dropped vs present, same data):

| Query | Before | After |
|---|---|---|
| `SELECT * FROM recommendation_runs WHERE user_id=? ORDER BY id DESC LIMIT 50` | `SCAN recommendation_runs` | `SEARCH recommendation_runs USING INDEX idx_runs_user (user_id=?)` |
| `SELECT * FROM assessment_runs WHERE user_id IS ? ORDER BY id DESC LIMIT 5` | `SCAN assessment_runs` | `SEARCH assessment_runs USING INDEX idx_assessment_runs_user (user_id=?)` |

## Frontend first-load JS

See the per-route table in `docs/UPGRADE_PLAN.md` §5 Phase 10 status:
the per-locale i18n split + lazy Firebase brought **every route to
≤245 kB** (worst route `/login` at 224 kB).
