# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.5.0] - 2026-11-06

Final release of the Master Build upgrade (Phases 1–10, local
`upgrade/final` branch). Phase 10 — Scale, trust & launch finish:

### Added

- **JS budget fixed at the root (Phase 10)** — the i18n dictionaries
  are split per locale (EN bundled base; TA/HI in lazily imported
  chunks, loaded on demand by the provider with no wrong-language
  flash; type safety and call sites unchanged) and the Firebase SDK
  leaves the shared bundle (dynamic import for sign-out only).
  **Every route is now ≤245 kB first load** (worst /login 224 kB;
  most routes ~192 kB; before: up to 276 kB). Full before/after table
  in `docs/UPGRADE_PLAN.md` §5.
- **Public catalog cache** — `career_guidance/cache.py` (300 s TTL,
  bounded LRU) for `/meta`, `/skills/suggest`, `/careers/search`,
  `/careers/{id}` (admins bypass career detail); catalog loads once
  per process (tested). `/recommend` p95: 238.4 ms on the eval
  harness (like-for-like vs the ~292 ms Phase 1 baseline);
  end-to-end HTTP bench + method in `docs/PERFORMANCE.md` and
  `scripts/bench_recommend.py`.
- **Migration v10** — per-user indexes for the hot lookups (runs,
  assessment runs, plans, interview sessions, payments) with
  EXPLAIN-verified plans, plus the `institute_api_keys` table.
- **Institute public API** — API keys (SHA-256 at rest, raw shown
  once, revocable, `last_used_at`) managed by the institute's admin
  or a platform admin; read-only aggregate-only endpoints
  `/api/v1/public/institutes/{slug}/cohort` and `…/top-careers`
  authenticated by `X-API-Key` only (401 missing/wrong/revoked,
  404 on slug mismatch, 30/min per key, no personal fields).
- **Accessibility pass** — modal focus traps, WAI-ARIA tab keyboard
  pattern, stepper `aria-current`, chat live log, icon-button labels,
  and the failing muted-text token brightened to AA; measured
  contrast table + checklist + gaps in `docs/ACCESSIBILITY.md`.
- **Status page** — `/status` renders live `/health` + `/ready`
  checks from the visitor's browser (EN/TA/HI).
- **Launch finish** — SELLING.md go-live checklist consolidated to
  owner inputs only; `.env.example` re-audited (complete); versions
  aligned at 1.5.0. Gate run: **514 pytest passed · coverage 91.93 %
  (new modules 97–100 %) · eval Hit@5 1.0 / MRR 0.827 · ruff/tsc/
  eslint clean · both builds green**.

### Added (earlier phases in this release)

- Phase 9 — Revenue v2 (local `upgrade/final` branch): Razorpay
  **subscriptions** as an additional option beside one-time checkout
  (manual flow unchanged) — migration v9 (`subscriptions`,
  `webhook_events` idempotency ledger, `coupons`,
  `coupon_redemptions`, `referral_codes`, `referral_attributions`,
  `referral_rewards`, payments discount/code columns, institute
  `report_schedule`), `POST /api/v1/billing/subscribe` (501 while keys
  unset, 409 while the plan's env plan id is unset — plan ids are
  env-only, never invented; 12 billing cycles), webhook extended over
  the SAME HMAC path for `subscription.*` (charged → period extended
  to Razorpay's absolute `current_end` + plan on; cancelled/halted →
  status only, plan stays until period end; replays idempotent via the
  ledger), `subscriptions_enabled` flag on the plans payload (the UI
  shows Subscribe only when it is true), subscription status on
  `/billing/me`. **Coupons**: platform-admin create/list/deactivate
  (audit-logged), percent/flat with total + per-user caps and expiry,
  user preview endpoint (no state change), redemption inside checkout
  priced server-side and written in the SAME transaction as the
  payment row; no discount exists until an admin creates a coupon.
  **Referrals v1 = attribution only**: `GET /api/v1/me/referral` (code
  + counts), checkout records attribution + a pending, valueless
  reward record; value comes only from a coupon the referred user
  redeems. **Institute analytics v2**: a term is a calendar quarter —
  `cohort?period=current|previous` adds current-vs-previous-quarter
  aggregates + deltas (honest zeros for an empty period, aggregates
  only, no e-mails), review queue v2 (unreviewed only, oldest first,
  `limit`/`offset`; the Phase 4 review endpoint marks items off),
  `report_schedule` preference (`none|weekly|monthly`, nominal
  `next_run` — a preference record only; no scheduler sends reports
  yet). Frontend: coupon + referral fields on the billing view,
  Subscribe button gated on `subscriptions_enabled`, referral card in
  account, `p9_*` strings EN/TA/HI. Gate run: **502 pytest passed
  (468 baseline + 34 new) · coverage 91.80 % overall (coupons.py
  93 %, backend/billing 85 %, billing core 95 %, institutes core
  95 %, backend/institutes 96 %) · eval unchanged
  (Hit@5 1.0, MRR 0.827, faithfulness 4/4, chat grounding 8/8) ·
  ruff/tsc/eslint clean · both builds green (export: /billing
  263 kB and /account 270 kB first load — +1 kB each over the Phase 8
  baseline of 262/269 kB; both routes were already above the 245 kB
  budget before Phase 9, a pre-existing condition, while /shared
  stays at 220 kB within budget)**. Version bumped to 1.5.0.

- Phase 8 — Reach & mobile (local `upgrade/final` branch): shareable
  report links — `career_guidance/sharing.py` + migration v8
  (`share_tokens`: SHA-256 hash at rest only, raw URL-safe token
  returned once at creation), owner-only `POST/GET/DELETE
  /api/v1/runs/{run_id}/share(s)` (signed-in owner, or guest session
  for an anonymous run; sign-in does not adopt anonymous runs),
  public rate-limited `GET /api/v1/shared/{token}` whose payload is
  BUILT from the documented `report_v1` allowlist (career titles,
  match %, matching/missing skills, Reality Score, salary ladder
  labelled estimates, learning path — never owner identity,
  constraints, profile text, institute/counsellor data; privacy-
  scanned in tests), expiry default 7 d / max 30 d as code constants,
  expired/revoked → 410, unknown → 404. Frontend: code-split share
  panel on `/report` (create, copy link, expiry, revoke) and a public
  read-only `/shared/[token]` page (218 kB first load, within
  budget), EN/TA/HI. Full PWA: completed manifest (`start_url: /`,
  on-disk-verified icons), hand-written `sw.js` v4 (shell precache,
  static cache-first, navigations network-first, `/api/*` never
  cached, update only via the new update-available toast), `/offline`
  page + dependency-free SW fallback at `public/sw-offline.html`
  (export overwrites `out/offline.html` with the route — verified),
  `sw.js` served `Cache-Control: no-cache` by the backend; same-origin
  worker already covered by the report-only CSP. TA/HI landing:
  dictionaries verified at full parity (657/657 keys ×3; only
  untranslatables identical); gaps fixed — guest language switcher
  added to the landing footer, three hardcoded English strings
  localised. Low-bandwidth mode: `lib/bandwidth.ts` precedence
  (manual > Save-Data > off), `data-low-bandwidth` CSS kill-switch +
  Motion gates via an import-light signal (a direct context import
  measurably bloated `/shared` to 256 kB; decoupled back to 218 kB),
  deferred chat/share panels, toggles in Settings + landing/report
  headers, account-prefs sync via existing `PUT /me/prefs`; no
  frontend test runner exists in the repo, so the pure logic was
  verified by 18 node assertions on the tsc-compiled module.
  Gate run: **468 pytest passed (449 baseline + 19 new) · coverage
  91.23 % (new modules 96 %/97 %) · eval unchanged (Hit@5 1.0,
  MRR 0.827, faithfulness 4/4, chat grounding 8/8) · ruff/tsc/eslint
  clean · both builds green**. Version bumped to 1.4.0.

- Phase 7 — Intelligence v2 (local `upgrade/final` branch): semantic
  layer (`career_guidance/semantic.py` — `TfidfSemanticScorer` reusing
  the existing TF-IDF machinery; `EmbeddingSemanticScorer` lazily
  importing sentence-transformers only when `SEMANTIC_EMBEDDING_MODEL`
  is set, failing soft to TF-IDF on any error) blended at ONE seam in
  `MatcherV2.rank` (`final = (1-w)·hybrid + w·semantic`, w =
  `SEMANTIC_BLEND_WEIGHT` = 0.25, flag `SEMANTIC_MATCHING_ENABLED`).
  Golden-eval comparison (TF-IDF blend, three runs, stable): OFF —
  Hit@5 1.0, MRR 0.827, interests 1.0; ON — Hit@5 1.0, MRR 0.888,
  interests 1.0. The golden rule (default ON only on strict MRR
  improvement with no Hit@5 drop) was met, but a default-ON trial broke
  the existing `test_core_v2` skills-only sanity gate (top pick fell to
  49.2% match), so the flag ships **OFF by default** (opt-in per
  deployment); embeddings were not installed or measured — no quality
  claim. Multi-provider LLM factory (`ProviderFactory` in
  `providers.py`): `LLM_PROVIDER=openai|gemini|ollama` (default keeps
  the OpenAI-key behaviour, then Gemini-key), Gemini via plain HTTPS
  (key in header, never URL), Ollama via its local API; shared timeout
  + exactly one retry on transient errors; every provider reuses the
  same `_parse_*` strict schema validation, and the faithfulness filter
  was extracted to `career_guidance/faithfulness.py` (grounded merge,
  chat and eval all call it — no forks); identical offline fallback on
  any provider failure. Scoped career chat (`career_guidance/chat.py`,
  `POST /api/v1/chat`, JSON — no SSE, the stack has no streaming
  pattern): context only from the caller's stored run (recommendations,
  Reality recomputed for those careers, linked 90-day plan) + taxonomy
  entries named in the message; deterministic no-LLM scope check with
  i18n-keyed refusal (`p7_chat_refusal`); LLM answers must pass the
  faithfulness check or fall back to the deterministic offline answerer
  (salary ladder / priority skills / gaps / plan extraction, honest
  offline prefix otherwise); signed-in = own or anonymous run, guest =
  anonymous only, other users' runs 404; rate-limited 20/min.
  Code-split chat panel on `/report` (next/dynamic; panel logic in its
  own lazy chunk, `/report` first-load JS 256 kB — inside the
  pre-existing 253–266 kB range), EN/TA/HI `p7_chat_*` strings,
  empty/error states via the UI kit. Eval expansion
  (`eval/run_chat_eval.py`, wired into `make eval`): faithfulness 4/4
  (planted ungrounded skills against the checker directly), chat
  grounding 8/8; golden eval numbers unchanged. Gate run: **449 pytest
  passed (405 baseline + 44 new) · total coverage 91% (new core
  modules: semantic 94%, chat 89%, faithfulness 100%, backend/chat
  88%) · ruff/eslint/tsc clean**. Version bumped to 1.3.0.

- Phase 6 — Production readiness (local `upgrade/final` branch):
  Postgres option through a central dialect layer
  (`career_guidance/db.py` — `DATABASE_URL` selection, placeholder/DDL
  translation, password never logged) wired into the core
  `storage.Database` and the migration runner; SQLite stays the default
  and `psycopg` is an optional extra (`requirements-postgres.txt`);
  per-feature stores remain on the SQLite file (boundary + smoke
  procedure documented in `docs/DEPLOY.md` §6); backup/restore scripts
  (`scripts/backup_db.py`, `scripts/restore_db.py` — integrity-checked,
  timestamped, retention, pre-restore safety copy); structured JSON
  logging with request-id propagation (`career_guidance/logging_setup.py`,
  `X-Request-ID`, token-redacted paths, no bodies/PII in logs);
  `GET /api/v1/ready` readiness distinct from `/health` liveness;
  uniform `{detail, request_id}` 500s + `ERROR_WEBHOOK_URL` error hook
  (no-op by default); security headers + report-only CSP on every API
  response; session-cookie `Secure` forced in production; SEO
  (metadata/OG defaults, `sitemap.ts`, `robots.ts`, per-career
  `generateMetadata` + indexable career pages, JSON-LD); landing fully
  localised EN/TA/HI via `p6_*` keys; `docs/SECURITY.md` (audit results:
  pip-audit clean; npm audit blocked by the sandbox registry policy and
  moved to a non-blocking CI step); error-shape audit of the Phase 2–5
  routes (all expected failures already `{detail}` 4xx — regression
  tests added). Version bumped to 1.2.0.

- Phase 5 — Privacy, compliance & trust (local `upgrade/final` branch):
  least-data age declaration (`age_band` + optional birth year only,
  never a full date of birth; migration v7 `users.age_band`/`birth_year`
  + `consent_records`); `career_guidance/consent.py` (ConsentProvider ABC,
  ManualEmailConsentProvider over the notifications abstraction with
  log fallback, hashed 72-hour guardian tokens, versioned notice —
  bumping `NOTICE_VERSION` computes old grants as `needs_reconsent`);
  consent API (`PUT /me/age-declaration`, `POST /me/consent/request`,
  `GET /me/consent`, `POST /me/consent/revoke`, public token-secured
  `GET /consent/confirm/{token}`); minor rules for unconsented under-18
  accounts (no behavioural analytics events, no XP/streak nudges,
  excluded from institute needs-attention individual lists while cohort
  aggregates still count them, public profiles stay off, core guidance
  keeps working); comprehensive account deletion (pre-Phase-5 delete
  orphaned verifications, projects, 90-day plans, payments, tool events,
  consent records and reviews — now one root-cause path; feedback/audit
  anonymised) and a complete export (verifications, attempts, projects,
  90-day plans, payments, consent records added); `/methodology` page
  (matcher + Reality Score weights, sources, known limits, EN/TA/HI);
  plain-language privacy notice (EN/TA/HI summary); account Privacy tab
  + onboarding age step; `docs/COMPLIANCE.md` DPDP-oriented engineering
  checklist (not legal advice) with breach-response runbook;
  counsellor-validation eval protocol + agreement-stats script
  (`eval/counsellor_validation.py`, sample CSV is fake data, no results
  claimed).


### Added

- Phase 4 — Institute portal (local `upgrade/final` branch): migration v6
  (`institutes`, `users.institute_id`/`institute_role`, `institute_invites`,
  `run_reviews`); `career_guidance/institutes.py` (one institute per user,
  seat-limited invites — pending invites reserve a seat, default seat limit
  is a documented constant until the owner sets Institute plan config);
  `/api/v1/institutes/*` (self-serve create, e-mail + CSV invites with
  per-row error reports and structured 422s, member management, aggregate
  cohort with no e-mails, per-student detail for institute staff only,
  cohort CSV/PDF exports with institute branding, counsellor review queue);
  run reviews surface on the student's history/report payload labelled
  exactly "Reviewed by counsellor"; counsellors can now also verify
  projects of students in their own institute; `/institute` route +
  code-split Institute tab in `/account`; demo-request lead count in the
  admin overview; EN/TA/HI strings.

### Added

- Phase 3 — Proof of skill & 90-day plan (local `upgrade/final` branch):
  skill verification with 5 bundled quizzes (Python, SQL, HTML/CSS, Excel,
  Communication — 8 questions each, answer keys server-side only, sealed
  attempt tokens, 70% pass mark, 24-hour retake cooldown after a failed
  attempt) via `GET/POST /api/v1/skills/verify/*`; state machine
  unverified → quiz-verified (auto) or project_submitted (self-reported) →
  verified only after an admin review (`POST /api/v1/skills/verify/admin/review`);
  public profiles at `/p/[handle]` (`GET /api/v1/p/{handle}`, opt-in only,
  minors force-disabled, no email/age/school ever exposed); 90-day plans
  (`POST/GET /api/v1/plan/90day`, 13 weeks from the run's priority skills and
  hours-per-week constraint, tasks only from the curated learning catalogue,
  Markdown + ICS export); dashboard "This week" card; `NotificationProvider`
  abstraction (log default, SMTP via the existing mail env, WhatsApp stub
  pending owner credentials); migration v5 (verification tables, 90-day
  plans, `users.handle`/`public_profile`/`is_minor`).

### Added

- Phase 2 — India Reality Score & career report (local `upgrade/final`
  branch; entry backfilled in Phase 6 from the shipped code):
  `career_guidance/india.py` + `data/india_market.yaml` +
  `data/crosswalk_onet_nco.yaml` (every figure labelled with source,
  `as_of` and `kind: estimate` where it is an estimate — no figure is
  presented as official); `career_guidance/reality.py` Reality Score
  (5 components, missing-data exclusion with "insufficient data",
  confidence) enriching matcher responses with `why_not`,
  `alternatives` and provenance sources; `/report/[runId]` report page
  (Reality breakdown, have/missing/priority skills, salary ladder,
  cities/sectors, PNG/PDF export, parent-version toggle); admin
  India-market override editor (`GET/PUT /api/v1/admin/india-market`,
  audit-logged); sources recorded in `docs/SOURCES.md`.

- Phase 1 consolidation (local `upgrade/phase1` branch): 7-surface route map
  in `docs/ROUTES.md` with redirects for every old route; guest-first access
  (anonymous, rate-limited `POST /recommend`, flagged `anonymous`, saved-data
  routes unchanged); `docs/SOURCES.md`; landing rework (live try-it box,
  sample report, differentiators with honest phase labels, trust strip,
  4 steps, Individuals/Institutions pricing tabs, institute demo-request
  form backed by `POST /api/v1/billing/demo-request` + migration 4
  `demo_requests` table, admin-only lead list); design tokens
  (`frontend/styles/tokens.css`) + lightweight `frontend/components/ui/*`
  primitives; `/start` 4-step wizard with localStorage draft and an
  additive, backward-compatible `constraints` object on recommend runs;
  `/report/[runId]`, `/explore` and `/account` surfaces reusing existing
  views; new wizard/landing strings in English, Tamil and Hindi.
- README Authentication section now describes the public-first model.

### Added

- Sell-standard billing: Free / Pro / Institute plans (`GET /billing/plans`,
  public), one-time Pro trial (`POST /billing/trial/start`), Razorpay
  checkout + HMAC-verified webhook (`POST /billing/checkout`, `/billing/webhook`),
  payments ledger and user plan/trial columns (migration 3). Checkout and the
  webhook answer 501 while Razorpay keys are unset; unset prices render as
  "Contact us".
- Roadmap PDF export is the Pro feature while `BILLING_ENFORCE_PRO` is on
  (default); Markdown/JSON/ICS exports stay free.
- Public landing page at `/` (server-rendered: hero, features, how it works,
  live pricing, FAQ), Terms / Privacy / Refund pages, in-app `/billing` page
  with sidebar link, and the classic tabbed shell preserved at `/classic`.
- `frontend/.env.example` (was missing although the root `.env.example`
  referenced it) and billing variables in `.env.example`.

### Fixed

- Journey PDF export test now covers the Pro gate (402 for Free, 200 after
  trial) instead of assuming open access.
- Production hardening: the app now refuses to start when `APP_ENV=production`
  and `SESSION_SECRET` is unset (previously it logged an error and kept
  running on a known dummy secret), and the CORS allow-list is env-driven
  via `CORS_ALLOW_ORIGINS` instead of a hardcoded wildcard.

## [1.1.0] - 2026-09-03

### Added

- Career profile: skills, interests, education, experience level, and goals.
- Resume upload with safe in-memory text extraction (.txt, .md, .pdf via pypdf),
  size limits, and clear failure handling.
- Structured recommendations: match reason, matching skills, missing skills,
  suitability level, ordered learning path, and practical next steps.
- SQLite persistence for recommendation history (`DATABASE_PATH`, default
  `data/career_guidance.db`), encapsulated in a swappable `Database` class.
- Analytics page computed only from real stored data: run totals, most
  recommended careers, most common skill gaps, runs per day.
- Recommendation card UI with skill-gap breakdown and roadmap expander.
- Schema validation for AI responses; unknown suitability values normalized.
- Tests for profiles, resume extraction, recommendations, storage, analytics.

### Changed

- History page now reads from the persistent database instead of the session.
- Demo provider now performs genuine keyword-based skill matching against a
  curated career catalog instead of returning fixed suggestions.

### Removed

- Session-only history module (replaced by database-backed history).

## [1.0.0] - 2026-09-03

### Added

- `career_guidance` package with UI-agnostic core logic, input validation, and logging.
- Pluggable suggestion providers: OpenAI-backed AI provider plus an offline demo provider,
  with automatic fallback when the AI service is unavailable.
- Multi-page Streamlit UI (Career Guidance, History, About) with loading, empty, error,
  and success states, demo-mode banner, and result download.
- Session history with Markdown/JSON export and clear function.
- Configuration via environment variables (`APP_ENV`, `LOG_LEVEL`, `MIN_INPUT_LENGTH`,
  `MAX_INPUT_LENGTH`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`)
  documented in `.env.example`.
- Unit test suite (pytest) covering validation, providers, fallback, history, and formatting.
- GitLab CI/CD pipeline with lint (ruff) and test stages.
- `Dockerfile` for container deployment with health check.
- `pyproject.toml` packaging with semantic versioning.
- `.gitignore`, `CHANGELOG.md`, and professional `README.md`.

### Changed

- `app.py` refactored into a thin Streamlit entry point with error handling.
- `requirements.txt` now pins dependency version ranges.
