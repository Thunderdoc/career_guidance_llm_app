# REPO_MAP.md — Career Guidance AI + Kaam-Vaani (branch `kaam-vaani`)

Orientation map written 20 Nov 2026 from the actual tree at commit
`c10b693` (Stage 5 done, Stage 6 starting). Every line below was seen
with `ls` / `find` / `grep` in this session — nothing inferred.

## Top level

- `backend/` — FastAPI app. `backend/main.py` builds the app and mounts
  every router; `backend/auth.py` holds the auth dependencies
  (`current_user`, `admin_user`, `employer_user`, `coordinator_user`).
- `career_guidance/` — domain package (stores, matching, taxonomy,
  providers, migrations). No HTTP code here.
- `frontend/` — Next.js 15 app (App Router, static export with
  `NEXT_EXPORT=1`). `frontend/app/` routes, `frontend/components/`
  views, `frontend/lib/` API client + flags + speech.
- `tests/` — pytest suite (49 files, incl. `test_kv_stage1.py` …
  `test_kv_stage5.py`).
- `eval/` — eval harnesses and gold sets (see below).
- `data/` — catalog, KB snapshot, seed data, YAML vocabularies.
- `scripts/` — seed/ingest/smoke/bench scripts.
- `docs/` — plan, runbook, compliance, security, routes, sources.
- Root docs: `ARCHITECTURE.md`, `ASSUMPTIONS.md`, `LIMITATIONS.md`,
  `EVAL_REPORT.md`, `COMPLEXITY.md` (Step 8.10: Big-O + measured
  numbers for the whole system), `README.md`, `CHANGELOG.md`,
  `SELLING.md`.
- CI: `.github/workflows/ci.yml` (python job: ruff, pytest, coverage
  ≥85%, golden eval, KV eval; web job: tsc, eslint, `NEXT_EXPORT=1`
  build; docker job). `Makefile` mirrors the same commands
  (`test`, `cov`, `lint`, `eval`, `build`, `ci`).

## Backend routers (`backend/*.py`)

| File | Mount | Purpose |
| --- | --- | --- |
| `main.py` | — | App factory; mounts routers; SPA catch-all serves `frontend/out/` when present and 404s unknown `/api/*` as JSON |
| `auth.py` | — | Auth deps; role checks are EXACT (an admin does NOT pass `employer_user`) |
| `kv_voice.py` | `/api/v1/kv/voice/*` | Stage 3 voice gateway + extraction + confirm (behind `KV_VOICE`) |
| `kv_rag.py` | `/api/v1/kv/rag/*` | Stage 2 RAG Q&A (behind `KV_RAG`) |
| `kv_rights.py` | `/api/v1/kv/rights/*` | Step 9.1 rights/scam assistant — topic-restricted RAG + verified-helpline escalation (behind `KV_RAG`) |
| `kv_pilot.py` | `/api/v1/kv/pilot/*` | Step 9.2 pilot console — bulk onboarding, coordinator review, metrics + CSV (behind `KV_PILOT`, coordinators + admins only) |
| `kv_video.py` | `/api/v1/kv/video/*` | Step 9.3 video skill check, EXPERIMENTAL — clip validity only, never stored (behind `KV_VIDEO_CHECK`, signed-in users, 5/hour) |
| `kv_ratelimit.py` | — (shared plumbing) | Step 9.4: `client_key` (per-IP key) + `kv_limiter` factory (registers every KV limiter) + `reset_all_kv_limiters` (test resets). Rate limits are per-process in-memory (A65/L67). |
| `kv_matching.py` | `/api/v1/kv/*` | Stage 4 `/matches`, `/gap-learning` (behind `KV_VOICE`) |
| `kv_employers.py` | `/api/v1/kv/employers/*`, `/kv/listings*`, `/kv/admin/*` | Stage 5 employer portal + public listings + admin queue (behind `KV_EMPLOYERS`) |
| `kv_consent.py` | `/api/v1/kv/consent/*`, `/kv/worker-profile`, `/kv/employers/matching/*`, `/kv/hire-outcomes/*`, `DELETE /kv/me/data` | Stage 6 consent + matching + hire outcomes (behind `KV_CONSENT`); Step 9.4 adds the KV data-deletion endpoint |
| `consent.py`, `journey.py`, `sharing.py`, `verify.py`, `institutes.py`, `billing.py`, `chat.py`, `assessment.py`, `admin.py`, `admin_console.py`, `public_api.py` | various `/api/v1/*` | Pre-existing app routers (guest recommendation, institutes, billing, parental consent v7 — a DIFFERENT consent domain from Kaam-Vaani employer consent) |

## Kaam-Vaani domain modules (`career_guidance/kaamvaani/`)

- `flags.py` — flag helpers.
- `voice.py` — voice session state machine (Stage 3).
- `extract.py` — deterministic transcript → `VoiceProfile` extractor
  (Stage 2/3); `VoiceProfile` = skills, interests, education, city,
  income_text, income_monthly, goal_type, raw_text.
- `rag.py` — hybrid BM25 (inverted index) + TF-IDF retriever, snapshot
  loader, citation + refusal gates (Stage 2). Step 8.1: `Hit`
  carries `title_bonus`; the title-evidence rescue
  (`TITLE_RESCUE_THRESHOLD` 0.20) waives the cosine floor + weak-match
  rule for a strongly title-matched top hit (L53).
- `matching.py` — `KVScorer` (IDF skill overlap 0.30 + stemmed phrase
  title 0.40 + MatcherV2 0.10 + zone 0.10 + income 0.10), `KV_MAP`
  (19 canonicals → O*NET competencies), `expand_competencies`,
  `title_purity`, `income_fit`, gap/learning helpers (Stage 4).
  Step 8.1: weights + zone rules moved to
  `data/kv_ranker_weights.yaml`; combination + ordering delegate to
  `ranker.py` (score-identical refactor, pinned by
  `tests/test_kv_step8_1.py`).
- `ranker.py` — `RankerConfig` (validated YAML weights + zone rules),
  `MultiCriteriaRanker` (weighted combine + ordering with an
  injectable comparator), `ScoredItem` (Step 8.1).
- `skillgraph.py` — `SkillGraph` (Kahn's toposort + cycle
  detection, Dijkstra over lexicographic `(paid, count)` costs),
  `build_gap_graph` / `skill_plan_for` (production graph from
  gap skills + catalogue courses; `LearningPlan` with ordered
  steps, totals, covered-by-held, uncovered) (Step 8.2).
- `geo.py` — geohash encode/decode + haversine + `GeohashIndex`
  (sorted-hash prefix-range radius search; city coordinates
  from `data/kv_city_coords.yaml`, 6 seed cities) (Step 8.3).
- `dedup.py` — `DuplicateIndex` (SHA-256 fingerprints + Bloom
  pre-filter + word 3-shingle Jaccard, threshold 0.5 tuned on a
  369-pair labelled set: precision 1.000, recall 0.907)
  (Step 8.4).
- `citations.py` — citation verifier: per-sentence token-overlap
  support (≥ 0.8) against the cited chunk, truncation handling,
  drop-unsupported repair; wired into `answer_question`
  (Step 8.5).
- `wages.py` — central-sphere minimum-wage tables reader:
  employment matching (longest keyword phrase, word boundaries)
  + monthly bands (daily totals x 26) for the pay-plausibility
  check; piece-rate employments excluded (L39, Step 8A).
- `cache.py` — `LruCache` (bounded, thread-safe, optional TTL,
  hit/miss/eviction stats) + the four Step 8.6 caches:
  `translation_cache`, `profile_cache`, `llm_cache`, and
  `CachingCompleter` (LLM-result cache wrapper; failures never
  cached). The answer/search cache is an `LruCache` owned by the
  RAG router, keyed by snapshot versions (Step 8.6).
- `providers.py` (top-level `career_guidance/`) — the LLM factory
  gains `LlamaCppCompleter` (in-process GGUF via llama-cpp-python,
  lazy import + lazy model load) and `LlamaCppProvider`, selected
  with `LLM_PROVIDER=llamacpp` + `LLAMACPP_MODEL_PATH` (Step 8.7);
  setup guide `docs/LOCAL_LLM_SETUP.md`; live test gated on
  `KV_TEST_LLAMACPP_MODEL` (tests/test_kv_step8_7.py).
- `lora_data.py` — LoRA dataset builder (Step 8.8): gold profile
  cases -> validated TRL messages-format JSONL (49 train / 6 val),
  deterministic split, PII safety net; CLI
  `scripts/build_lora_data.py`; config `training/lora_config.yaml`;
  notebook `training/train_lora_colab.ipynb` (not executed);
  runbook `docs/LORA_RUNBOOK.md`.
- `trace.py` — agent trace log (Step 8.9): `Trace` (per-request,
  spans with PII-validated detail) + `TraceSink` (bounded ring +
  size-rotated JSONL file), process-wide singleton via `get_sink`;
  admin read API `backend/kv_traces.py` (GET /traces, GET
  /traces/{id}); wired into /ask, /search, /extract, /matches.
- `rights.py` — rights/scam assistant (Step 9.1):
  `answer_rights_question` (Stage 2 `answer_question` restricted
  to `RIGHTS_TOPICS` = rights/scam/wages/employment, 56 chunks),
  `scam_intent` (English keywords on the translated query),
  `load_helplines` (verified numbers from
  `data/kv_helplines.json` — 1930 cybercrime + 1514 NCS — the
  ONLY source the escalation block may quote), `escalation_for`
  (scam-tagged helplines, on scam-intent or a scam-topic top
  chunk, including on refusals).
- `pilot.py` — pilot-console helpers (Step 9.2):
  `normalise_phone` (coordinator-typed phone → E.164 for the
  users-table lookup; unrecognised shapes pass through and miss,
  never guessed) and `bulk_onboard` (up to 100 rows, each resolved
  by `user_id` or `phone` against existing accounts — no account
  is ever created — per-row created/updated/failed with reasons;
  a bad row never fails the batch). Metrics live on the stores:
  `ConsentStore.pilot_metrics` (profiles, consents, shortlists,
  contact requests, outcomes, retention) +
  `EmployerStore.pilot_metrics` (employers, listings, scam
  reports, review-queue counts); `outcome_counts` /
  `retention_summary` accept `employer_id=None` for the global
  view. `UserStore.get_by_phone` is the phone lookup.
- `video.py` — video skill check, EXPERIMENTAL (Step 9.3):
  `check_clip` (ffprobe duration + video stream, 6 evenly spaced
  ffmpeg frames, PIL brightness/blank/motion; verdict is clip
  VALIDITY only — "Indicative only — not a certificate",
  confidence low by design; thresholds chosen not tuned).
  Clips are never stored, results never persisted; the router
  streams the upload to a temp file and deletes it in a
  `finally` (5 checks/hour/user, 50 MB cap).
- `employers.py` — `EmployerStore` (employers, listings, reports;
  status machines; audited review queue; `public_dict()`) (Stage 5);
  `delete_employer_data` (Step 9.4 erasure — employer + listings,
  reports kept as safety records).
- `scam.py` — deterministic scam checker: 10 weighted rules, FLAG 70 /
  WARN 40, `max(rules, llm)` (Stage 5).
- `consent.py` — `ConsentStore` (worker profiles, consents,
  append-only audit, shortlists, contact requests, hire outcomes
  + follow-ups), `score_candidate` (weights 0.35/0.30/0.20/0.15),
  `filter_profile` allow-list, `consent_explanation` template
  (Stage 6); `delete_worker_data` + `delete_employer_consents` +
  module-level `delete_all_kv_data` (Step 9.4 erasure — outcomes
  anonymised via a one-way tombstone, audit trail never touched).

## Database and migrations

- `career_guidance/db.py` — `connect(target)` / `translate_ddl`
  (SQLite local; Postgres optional via `DATABASE_URL`).
- `career_guidance/migrations.py` — versioned runner; `LATEST_VERSION`
  is `max(...)` over the `MIGRATIONS` list; currently **14**.
  Kaam-Vaani migrations: v11 (roles/phone, Stage 1), v12 (kv_chunks,
  Stage 2), v13 (`kv_employers`, `kv_listings`, `kv_listing_reports`,
  Stage 5), v14 (`kv_worker_profiles`, `kv_consents`,
  `kv_consent_audit`, `kv_shortlists`, `kv_contact_requests`,
  `kv_hire_outcomes`, Stage 6). No FK constraints in KV tables; stores enforce ownership,
  routers enforce roles. Inserts use `RETURNING id` on Postgres /
  `lastrowid` on SQLite.
- Live DB (DO NOT TOUCH for tests): `data/career_guidance.db`.
  Tests and live checks use tmp/scratch DBs via `DATABASE_PATH`.
- Key pre-existing tables: `users` (role user/admin/employer/
  coordinator; `phone_e164`, `phone_verified_at`), `profiles` (one
  row per user: persona, education, skills_json, goals, interests),
  `audit_log` (written via `UserStore.audit()`), `consent_records`
  (v7 PARENTAL consent — do not reuse for employer consent).

## Feature flags

- Backend: `career_guidance/config.py` (`kv_voice`, `kv_rag`,
  `kv_employers`, `kv_consent`, `kv_video_check`, `kv_pilot` —
  default ON unless `APP_ENV=production`; env `KV_*`). `.env.example`
  lines 130–135 list them (`KV_CONSENT` already present).
- Frontend mirror: `frontend/lib/flags.ts` (`kvFlags`,
  `NEXT_PUBLIC_KV_*`, baked into the static export at build time).
- Flag off = the route 404s as JSON (POST surfaces as 405 via the
  GET-only SPA catch-all).

## Frontend

- Routes: `frontend/app/voice/`, `frontend/app/employers/`,
  `frontend/app/jobs/`, `frontend/app/sharing/`, `frontend/app/rights/`,
  `frontend/app/pilot/`, `frontend/app/video-check/` (Kaam-Vaani);
  `app/admin/` hosts the Kaam-Vaani admin tab. Pages are thin wrappers importing a `*-view.tsx`.
- Views: `frontend/components/voice-view.tsx` (being redesigned by
  the design agent — DO NOT TOUCH), `employer-view.tsx`,
  `jobs-view.tsx`, `kv-admin-view.tsx`, `kv-voice-ui.tsx`,
  `kv-sharing-view.tsx`, `kv-candidates-view.tsx` (Stage 6, plain
  and functional — the design agent owns the polish),
  `kv-rights-view.tsx` (Step 9.1, plain and functional — the
  design agent owns the polish; renders escalation numbers ONLY
  from the API response, never hardcoded),
  `kv-pilot-view.tsx` (Step 9.2, plain and functional — the design
  agent owns the polish; no landing link by design — an ops
  console is reached directly),
  `kv-video-view.tsx` (Step 9.3, plain and functional — the design
  agent owns the polish; experimental, no landing link).
- API client: `frontend/lib/api.ts` (`api` object; `kv*` methods;
  `ApiError`; `request()` helper). `frontend/lib/speech.ts`
  exports `speak(text, locale, callbacks)` (browser speechSynthesis).
- Auth state: `frontend/lib/auth-context.tsx` (`useAuth()`).
- **No frontend tests exist** (no test script in `package.json`, no
  `*.test.*` files, no vitest/jest dependency) — gate item
  "frontend tests" is N/A until one is added.

## Tests

- `tests/conftest.py` — `app_module` fixture (freshly imported
  backend, isolated tmp SQLite DB via `DATABASE_PATH`), `client`
  fixture, `login(client, email)` via magic-link `dev_link` (local
  only). `tests/test_kv_stage5.py` (43 tests) is the pattern for
  Stage 6 tests (store + router + flag-off).
- Stage test files: `test_kv_stage1.py` … `test_kv_stage6.py`
  (Stage 6: 63 tests — store + router + flag-off).
  After Stage 6: **756 passed** (see `STAGE6_REPORT.md`).
  Step test files: `test_kv_step7c.py` (Step 7C), `test_kv_step8_1.py`
  (Step 8.1: ranker config/comparator + refactor regression +
  fairness + title-rescue gate + per-feature contributions, 36 tests),
  `test_kv_step8_2.py` (Step 8.2: hand-made graph engine tests +
  fake-catalogue builder + real-catalogue plan + router skill_plan,
  20 tests), `test_kv_step8_3.py` (Step 8.3: geohash/haversine +
  index-vs-scan property + store radius search + cache
  invalidation + router radius, 20 tests),
  `test_kv_step8_4.py` (Step 8.4: fingerprint/shingles/Jaccard
  + Bloom FP rates + index scope + labelled-set P/R gate +
  store + router duplicate flag, 16 tests),
  `test_kv_step8_5.py` (Step 8.5: splitting/overlap/truncation
  + drop-unsupported + answer-dict verification + integration +
  gold-set measurement pinned, 14 tests),
  `test_kv_step8_l39.py` (L39: wage bands + employment matching
  + four verdicts + advisory-only contract + router, 11 tests),
  `test_kv_step9_1.py` (Step 9.1: topics param + rights module +
  helpline provenance + kv_rights router, 32 tests),
  `test_kv_step9_2.py` (Step 9.2: phone lookup + bulk onboarding
  + pilot metrics vs seeded data + kv_pilot router, 28 tests),
  `test_kv_step9_3.py` (Step 9.3: video check on synthetic ffmpeg
  clips + kv_video router incl. rate limit + temp-file deletion,
  16 tests),
  `test_kv_step9_4.py` (Step 9.4: rate limits on all KV POSTs +
  data deletion (worker/employer/both sides, endpoint, self-delete
  integration) + Permissions-Policy mic fix + L50 index proof,
  20 tests).

## Eval

- `eval/run_kv.py` — Kaam-Vaani eval (profile extraction, recall@5,
  MRR, faithfulness, refusal); gold set `eval/kv_golden.json`;
  report `eval/kv_report.json`.
- `eval/run.py` — golden eval (`eval/golden.json`,
  `eval/golden_interests.json`); report `eval/report.json`.
- `eval/run_chat_eval.py` — chat faithfulness/grounding eval.
- `eval/run_kv.py` thresholds (CI): profile ≥0.90, recall@5 ≥0.85,
  faithfulness ≥0.90.

## Knowledge base and seed data

- KB snapshot v2: `data/kv_rag_snapshot_v2.jsonl` (1,048 chunks) +
  `data/kv_rag_snapshot_v2.meta.json`. Ingestion: `scripts/ingest/`.
  (v1, 1,040 chunks, kept for reference.)
- Sample listings: `data/kv_sample_listings.json` +
  `scripts/seed_kv_listings.py` (7 employers — 5 verified, 1 pending,
  1 flagged; 40 legit + 5 fake listings; seed exits 2 if a fake
  scores <70). All labelled sample data.
- Sample workers: `data/kv_sample_workers.json` +
  `scripts/seed_kv_workers.py` (10 workers, 13 consents across all
  three states, 3 shortlists, 2 contact requests, 2 outcomes;
  requires the listings seed first; `--force` re-seeds, audit
  rows are kept). Live end-to-end check:
  `scripts/verify_kv_stage6.py` (22 checks vs a running backend).
- Vocabularies: `data/voice_aliases.yaml`, `data/kv_cities.yaml`,
  `data/skill_synonyms.yaml`.
- Ranker config: `data/kv_ranker_weights.yaml` (Step 8.1 — the five
  live weights + the three aspirational features at 0 + zone rules).

## Where Stage 6 went (built, 20 Nov 2026 — see STAGE6_REPORT.md)

- Migration v14 in `career_guidance/migrations.py`.
- `career_guidance/kaamvaani/consent.py` (store + candidate
  scorer + field filtering).
- `backend/kv_consent.py` (router, mounted in `backend/main.py`
  behind `settings.kv_consent`).
- `tests/test_kv_stage6.py` (63 tests).
- Frontend: `frontend/lib/api.ts` additions, new
  `frontend/components/kv-sharing-view.tsx` + `frontend/app/sharing/`,
  share button in `jobs-view.tsx`, candidates section in
  `employer-view.tsx` (via a new `kv-candidates-view.tsx`).
- Seed: `data/kv_sample_workers.json` + `scripts/seed_kv_workers.py`.
- Verification script: `scripts/verify_kv_stage6.py`.
