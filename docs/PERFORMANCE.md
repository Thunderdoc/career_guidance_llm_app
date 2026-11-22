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

## Kaam-Vaani load test (Step 9.5, 21 Nov 2026)

Script: `eval/kv_load.py` (httpx async; k6/Locust were not needed —
the script starts a real uvicorn server and drives it). Report:
`eval/kv_load_report.json`. Setup, chosen to match the deployment
shape honestly rather than to flatter the numbers:

- **One uvicorn worker** — the Render free-tier shape (one process,
  512 MB). No multi-worker scaling is claimed.
- **20 virtual users × 5 rounds = 500 requests** through the five
  anonymous AI endpoints (`/rag/ask`, `/rag/search`, `/rights/ask`,
  `/voice/extract`, `/matches`).
- **Distinct questions per request** (cycled from the 115 golden
  retrieval cases), so the Step 8.6 caches do NOT dominate — this
  measures the uncached path under concurrency.
- **Distinct X-Forwarded-For per virtual user**, so the Step 9.4
  rate limiters see distinct users; no limiter was disabled.
  Per-user counts stayed under the limits (rag 10, rights 5,
  voice 5, matching 5 per user).
- One warm-up request per endpoint first, so the timed run does
  not pay the ~4.3 s first retriever build.

Results (500 requests, **0 errors**, 27.08 s wall, 18.46 req/s):

| Endpoint | n | p50 | p95 | p99 | mean | max |
|---|---|---|---|---|---|---|
| /rag/ask | 100 | 579.7 ms | 1830.2 ms | 2509.2 ms | 781.9 ms | 2509.2 ms |
| /rag/search | 100 | 503.0 ms | 1506.7 ms | 2417.6 ms | 562.6 ms | 2417.6 ms |
| /rights/ask | 100 | 549.6 ms | 1267.9 ms | 1876.3 ms | 620.6 ms | 1876.3 ms |
| /voice/extract | 100 | 423.0 ms | 1140.8 ms | 1170.4 ms | 553.8 ms | 1170.4 ms |
| /matches | 100 | 2505.4 ms | 4204.9 ms | 4415.7 ms | 2521.2 ms | 4415.7 ms |

Memory (server process RSS): 266 MB before, 285 MB after, **293 MB
peak sampled** — fits the 512 MB free instance with headroom. (This
is the sandbox measurement, not Render; the shape is the same
single-worker process.)

Honest reading — these numbers are **much slower than the
single-user latencies**, and the reason is structural, not a bug:
every endpoint here is CPU-bound pure-Python work (BM25 + TF-IDF
over 1,048 chunks; the MatcherV2 pass over the full taxonomy),
and one worker serialises all 20 concurrent users behind the
GIL. `/matches` degrades most: p50 2.51 s under load vs ~380 ms
single-user (COMPLEXITY.md §17). The pilot will not see 20
simultaneous `/matches` calls (a human-paced voice flow), but
`/matches` is the first endpoint to degrade under concurrency.
The fix direction is caching base scores per profile signature
or more workers — the latter is a paid-tier decision, out of
scope for the free-only pilot. No 429s appeared: the rate
limiters never tripped at this (realistic) per-user volume.
