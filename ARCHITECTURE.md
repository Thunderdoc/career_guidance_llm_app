# ARCHITECTURE — Career Guidance AI + Kaam-Vaani

Kaam-Vaani is a voice-first, RAG-powered career + job-matching layer for
rural school-leavers, built ON the live Career Guidance AI app (v1.5.0) for
the GAVS Tech4Bharat prototype (team Hackastra, filed 20 Nov 2026).
It is an additive layer: new modules behind feature flags, reusing the
existing matcher, taxonomy, auth, consent, verification and institute
machinery. Nothing that works today is rewritten.

This document is the Stage 0 output of the Kaam-Vaani build. Everything in
§2 was verified against the repo on 20 Nov 2026; decisions in §3–§9 record
*why*, including where the master prompt was adapted to the repo.

Related docs: `docs/KAAM_VAANI_PLAN.md` (staged build plan + risks),
`ASSUMPTIONS.md`, `LIMITATIONS.md`, `docs/SOURCES.md`,
`docs/COMPLIANCE.md`, `docs/SECURITY.md`, `docs/DEPLOY.md`.

## 1. System overview

```
  Rural school-leaver (low-end Android, patchy network, EN/HI/TA)
        │  voice (Web Speech API) or tap/typing
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Next.js 15 frontend (Vercel, Root Directory: frontend)   │
  │  /voice onboarding · spoken matches · /employer portal   │
  │  PWA shell + service worker · i18n EN/HI/TA (+1 file     │
  │  per language) · feature flags (NEXT_PUBLIC_KV_*)         │
  └──────────────────────┬───────────────────────────────────┘
                         │ HTTPS /api/v1/* (+ /api/v1/kv/*)
                         ▼
  ┌──────────────────────────────────────────────────────────┐
  │ FastAPI backend (Render, Docker, Python 3.11)            │
  │  Routers: existing (auth/me/journey/admin/billing/       │
  │  verify/institutes/consent/chat/sharing/public_api)      │
  │  + Kaam-Vaani (kv_voice, kv_rag, kv_listings,            │
  │  kv_employers, kv_consent, kv_admin)                     │
  │  JSON logging + request ids · rate limiting (30/min)     │
  │  CORS via CORS_ALLOW_ORIGINS · signed session cookie     │
  └──────┬───────────────────────────────┬───────────────────┘
         │                               │
         ▼                               ▼
  ┌─────────────────────┐     ┌─────────────────────────────┐
  │ SQLite (default) /  │     │ LLM providers (optional,    │
  │ Postgres via        │     │ env keys; offline fallback) │
  │ DATABASE_URL        │     │ OpenAI · Gemini · Ollama    │
  │ migrations v1–v10   │     │ + TaxonomyProvider (offline)│
  │ (+ v11+ Kaam-Vaani) │     │ + TF-IDF semantic layer     │
  └─────────────────────┘     └─────────────────────────────┘
  Firebase Auth (ID-token verify, no Admin SDK) · Google OAuth · magic link
```

## 2. Verified current state (Stage 0 inspection, 20 Nov 2026)

### 2.1 Repo and branches

- Remote: `github.com/Thunderdoc/career_guidance_llm_app`.
  Local working clone: `career-guidance-live`, branch `upgrade/final`,
  HEAD `c7cc847` (v1.5.0). Content diff vs `origin/main` (`f838656`)
  is only 2 lines of `.github/workflows/ci.yml` — the Phase 1–10 dev
  commits were squashed into main. Kaam-Vaani work happens on feature
  branch `kaam-vaani` from this HEAD. The sibling clone
  `career-guidance` is stale (pre-upgrade) — do not touch.
- Local git push is impossible from this VM (no HTTPS credentials);
  GitHub writes go through the connector with the owner's approval tap.
  No push/deploy without the owner's explicit approval (standing rule).

### 2.2 Stack

- Frontend: Next.js 15 (App Router), static export (`NEXT_EXPORT=1`),
  34 routes, Tailwind, Firebase client SDK. PWA already exists:
  `manifest.webmanifest`, `sw.js`, `sw-offline.html`, icons.
  i18n: typed per-locale dicts, EN bundled, TA/HI lazy-loaded chunks;
  every key added to `i18n-extra-en.ts` must exist in `-hi`/`-ta`
  (TS enforces it). Bundle: every route ≤245 kB first load (Phase 10).
  `bandwidth.ts` / `bandwidth-context.tsx` already adapt to slow
  networks. **No feature-flag system exists yet** (Stage 1).
- Backend: FastAPI + `career_guidance` package (UI-agnostic domain
  code) + `backend/` router layer (factory functions returning
  `APIRouter`). Python 3.11 in Docker; 3.12 locally. Structured JSON
  logging with request ids (`logging_setup.py`), per-IP rate limiter,
  CORS from env (default `*` — dev only; production must set
  `CORS_ALLOW_ORIGINS`).
- Tests: 464 test functions in 46 files (`tests/`); CI runs
  ruff + pytest + **coverage gate ≥85%** + golden eval
  (`python -m eval.run --min-hit 0.75`) + tsc/eslint/next build +
  Docker build. Baseline on 20 Nov 2026: pytest green (see Stage 0
  report); the suite must stay green at every stage.
- Eval harness exists: `eval/` (`golden.json`, `golden_interests.json`,
  `run.py`, `run_chat_eval.py`, `report.json`, counsellor validation).
  Stage 2 extends it with a Kaam-Vaani gold set — it does not start
  from zero.

### 2.3 Database — CONFIRMED: SQLite default, Postgres optional

- Default store is **SQLite** at `data/career_guidance.db`
  (`DATABASE_PATH`). A dialect layer (`career_guidance/db.py`, Phase 6)
  selects Postgres when `DATABASE_URL` is `postgres://…` (psycopg,
  `requirements-postgres.txt`, lazy import) and translates placeholders
  + DDL. Honest boundary (from the module docstring): the dialect layer
  backs the core `storage.Database` and the migration runner; the
  remaining per-feature stores still open the SQLite file directly and
  are migrated store-by-store. **Step 7C verified the Postgres path
  live (21 Nov 2026, Postgres 16.2): migrations 1..14 apply in one
  call and all Kaam-Vaani stores round-trip; the one failure found
  (v2's unquoted `current_role` — a Postgres reserved word) is
  fixed and guard-tested. Full cutover still needs the legacy
  stores ported (L54); see `docs/RUNBOOK.md` §3.1.**
- Migrations: versioned runner in `career_guidance/migrations.py`
  (v1–v14, recorded in `schema_migrations`, one transaction per
  version, Postgres DDL translation). **No Alembic** — the master
  prompt's Alembic ask is adapted: the existing runner already does
  the job and is tested; introducing a second migration system would
  risk the live data. Kaam-Vaani tables land as v11+.
- Tables already present (relevant): `users`, `recommendation_runs`,
  `profiles`, `audit_log`, `feedback`, `consent_records` (v7, parental
  consent), `skill_verifications` / `quiz_attempts` / `skill_projects`
  (v5), institutes + membership + invites + run reviews (v6),
  `institute_api_keys` (v10), share links (v8, hashed tokens).
  The `jobs` table is a **background-jobs queue**, not job listings —
  no listings/employer tables exist yet (Stage 5).
- Render: `render.yaml` declares `plan: starter` + 1 GB disk at
  `/app/data` (SQLite survives redeploys) and `autoDeploy: true`.
  ⚠️ **Discrepancy to confirm in Stage 11:** the live service is
  understood to run with autoDeploy OFF (manual deploys) and may be
  on the free tier (ephemeral filesystem → SQLite resets on deploy).
  Do not change `render.yaml` without owner approval. If live is
  free-tier, pilot data MUST move to Postgres (Supabase/Neon free
  tier) before any real pilot — see `docs/KAAM_VAANI_PLAN.md` risks.

### 2.4 Auth — CONFIRMED: Firebase + Google OAuth + magic link

- Firebase Auth: ID tokens verified server-side with Google's
  published x509 certs (`backend/firebase.py`, no Admin SDK, only
  `FIREBASE_PROJECT_ID` needed). Email/password sign-in requires
  Firebase `email_verified`; federated IdPs are trusted.
- Fallbacks: Google OAuth 2.0 authorization-code flow (no client
  library) and email magic link via SMTP (dev: link logged/returned
  when SMTP is unset, never in production).
- Session: HttpOnly signed cookie `cg_session` (itsdangerous,
  30-day TTL, `Secure` on HTTPS/production). Production refuses to
  start without `SESSION_SECRET`.
- Roles: `users.role` (`user` / `admin` via `ADMIN_EMAILS` or
  promotion) + `users.institute_role`
  (`institute_admin` / `counsellor` / `student`, at most one institute
  per user). Server-side role checks on every institute route.
  **No employer/coordinator roles yet** (Stage 1/5).
  Guest/anonymous use works everywhere except `/me/*` and `/admin/*`.
- No OTP/phone login yet. Free option for Stage 5: Firebase Phone
  Auth (Spark plan: 10 verifications/day free) — needs the owner to
  enable phone sign-in in the Firebase console; until then, employer
  verification is email + admin review.

### 2.5 Matching, LLM and grounding — what already exists

- Matcher: `recommend_v2` / `MatcherV2` — offline O*NET matcher over
  974 occupations (`data/catalog/occupations.json`), TF-IDF hybrid,
  Hit@5 0.98 on the golden eval. `POST /api/v1/recommend` is public,
  rate-limited, guest-first. Verified live 20 Nov 2026 (real Top-5,
  `provider: matcher-v2`, `is_demo: false`).
- LLM: provider-agnostic factory (`career_guidance/providers.py`):
  OpenAI (`gpt-4o-mini`), Gemini (`gemini-2.0-flash`), Ollama
  (`llama3.1`), selected by `LLM_PROVIDER` or key presence, with
  `TaxonomyProvider` (offline) as the no-key default. **No API keys
  are available for this build** — every Kaam-Vaani feature must work
  with the offline path and degrade gracefully when no provider is
  configured (the app already does this: `used_fallback`).
- Semantic layer (`semantic.py`, Phase 7): TF-IDF scorer (zero new
  deps) + optional `sentence-transformers` embeddings behind
  `SEMANTIC_EMBEDDING_MODEL` (lazy import, fails soft to TF-IDF).
  Flag `SEMANTIC_MATCHING_ENABLED` ships OFF by default (a measured
  regression on a sanity gate). Stage 2 reuses this pattern.
- Grounded chat (`chat.py`, Phase 7): answers ONLY from the caller's
  stored report + taxonomy entries the message names; deterministic
  scope check with hard refusals (no LLM needed); faithfulness checks
  (`faithfulness.py`) reused by eval and chat. Stage 7 extends this
  pattern to the RAG rights/scam assistant.
- Consent (parental, Phase 5): versioned `consent_records`, hashed
  unguessable guardian tokens (72 h), grant/deny/revoke, least-data
  age declaration (band + optional birth year only, never a full DOB).
  Stage 6 builds **per-employer data-sharing consent** as a new
  consent type reusing these mechanics — it is a different domain
  (sharing profile fields with an employer), not the parental flow.
- Verification (Phase 3): skill state machine
  (unverified → quiz_passed → verified; project evidence with human
  review; self-reported until approved). Stage 5 reuses the
  state-machine + review-queue pattern for employer/listing
  verification.
- Institutes (Phase 4): aggregate-by-default cohort data, role-gated
  per-student detail, invites, public API keys (v10). Stage 8's
  pilot/coordinator console builds on this.
- Market data (`market.py`): Adzuna adapter (free tier, needs keys)
  + static India salary-band fallback, labelled as estimates in the
  UI. Kaam-Vaani must never present these bands as sourced wages.
- Learning resources: `data/learning_resources.yaml` (curated, free
  courses) + admin-editable `resources` table (`content_store.py`).

### 2.6 What does NOT exist yet (Kaam-Vaani scope)

Video skill-check · offline action queue · SMS/WhatsApp share ·
answer-language translation (L16 stays open for answers — Step 7A
fixed Tamil/Hindi RETRIEVAL via glossary translation and measured
the dense-embedding comparison, closing L13; see EVAL_REPORT.md).

Step 9.1 delivered (21 Nov 2026): the rights/scam assistant — a
topic-restricted view of the Stage 2 RAG (`answer_question` with
a new `topics` parameter on `HybridRetriever.search`, backward
compatible: None searches everything as before). Retrieval covers
rights/scam/wages/employment only (56 chunks); an occupation
question refuses here even though the open path answers it
(pinned by test). Escalation is the one place the assistant
speaks words the KB never said, so it is tightly bounded: the
escalation block lists ONLY helpline numbers from
`data/kv_helplines.json` (1930 National Cyber Crime Helpline,
sourced from the PIB release of 6 Apr 2022; 1514 NCS helpline,
sourced from the KB's own ncs.gov.in chunk) — a number not in
that file can never reach a worker. Escalation appears on
scam-intent questions (English keywords on the translated query)
or a scam-topic top chunk, including on refusals. Router
`backend/kv_rights.py` (status/ask, own answer cache + trace,
behind `KV_RAG` — it shares the RAG flag); plain functional
`/rights` page + landing link (design agent owns the polish).

Step 9.2 delivered (21 Nov 2026): the pilot/institute console —
pilot OPERATIONS, never a recruiter portal. Router
`backend/kv_pilot.py` (behind `KV_PILOT`, coordinators + admins
only via a `pilot_user` dep): bulk worker onboarding (up to 100
rows/request, each row resolved by `user_id` or `phone` against
existing accounts — `UserStore.get_by_phone` on the E.164 column,
`normalise_phone` in `career_guidance/kaamvaani/pilot.py` — no
account is ever created here; per-row created/updated/failed
results, a bad row never fails the batch), metrics from stored
rows only (`ConsentStore.pilot_metrics` + `EmployerStore.pilot_
metrics`: profiles, consents by status, shortlists, contact
requests, outcomes, 30/90-day retention with the rate None until
a follow-up is reported, employers/listings/reports by status,
review-queue counts) with CSV export (metrics + full roster),
the review queue for coordinators (approve/reject employers and
listings, uphold/dismiss reports, endorsement — the same store
methods and audit actions as the admin console, which stays
unchanged), and the worker roster (names enriched from the
accounts table). `outcome_counts` / `retention_summary` now
accept `employer_id=None` for the global view (backward
compatible). Plain functional `/pilot` page (metrics, bulk
JSON textarea, queue actions, roster; design agent owns the
polish) — deliberately NO landing link: an ops console is
reached directly, not advertised to workers. Voice-flow match
views are not persisted, so they are not in the metrics (L65).

Step 9.3 delivered (21 Nov 2026): the video skill check —
EXPERIMENTAL. `career_guidance/kaamvaani/video.py` (ffprobe
duration + video stream, ffmpeg frame sampling — 6 evenly
spaced frames, PIL brightness/blank/motion analysis) + router
`backend/kv_video.py` (behind `KV_VIDEO_CHECK`, signed-in users,
5 checks/hour per user, 50 MB cap streamed to a temp file and
deleted in a `finally`). The verdict is CLIP VALIDITY only
(30–60 s, visible, moving) — it never assesses skill, and every
response carries "Indicative only — not a certificate" with the
limits text; confidence is LOW by design. Thresholds are
CHOSEN, not tuned (no labelled data exists): dark < 20 mean
brightness, blank < 5 stddev, static < 2.0 frame-to-frame
difference, majority-of-frames rule. No clip is stored and no
result is persisted. Tested honestly on SYNTHETIC ffmpeg clips
only (testsrc moving / black / static red / short / long / text
file) — no real task recordings exist in the repo and none is
faked. Plain functional `/video-check` page (design agent owns
the polish) — no landing link: experimental, reached directly.

Step 9.4 delivered (21 Nov 2026): hardening. Rate limits on
every Kaam-Vaani POST (`backend/kv_ratelimit.py`: anonymous
AI endpoints 30/min/IP, reports 10/min/IP, signed-in
mutations 60/min/user, OTP + video check 5/hour/user;
admin/coordinator endpoints deliberately unmetered; per-process
in-memory — A65/L67). Data deletion: `DELETE /api/v1/kv/me/data`
plus `delete_all_kv_data` wired into account self-delete and
the admin user delete (before this, self-delete left every KV
row behind); outcomes anonymised via a one-way tombstone,
reports kept as safety records, the audit trail never touched.
Dependency audit: pip-audit 9 vulns → 4 (pypdf/dnspython/
opentelemetry-api bumped; diskcache has no fix and no exposure;
pytest's fix is a deferred major bump). OWASP Top 10 review in
docs/SECURITY.md. Two real findings fixed/closed: the Phase 6
`Permissions-Policy: microphone=()` blocked the voice flow's
mic on the Render-served origin (now `microphone=(self)`,
camera/geolocation stay blocked), and L50 was already closed
by v14's `(status, expires_at)` index (verified by an EXPLAIN
QUERY PLAN test). L49 stays open: the 365-day audit retention
policy is recorded (COMPLIANCE.md §4a) but no automated prune
exists by design.

Step 9.5 delivered (21 Nov 2026): load test. `eval/kv_load.py`
drives a real single-worker uvicorn server (the Render free-tier
shape) with 20 virtual users × 5 rounds = 500 requests, distinct
questions per request (uncached path) and distinct X-Forwarded-For
per user (no limiter disabled). Result: 0 errors, 18.46 req/s,
RSS peak 293 MB. `/matches` is the slowest under load (p50
2.51 s vs ~380 ms single-user) — CPU-bound scoring serialised
on one worker; see docs/PERFORMANCE.md for the full table and
the honest reading.

Step 9.6 delivered (21 Nov 2026): docs. New: DESIGN_DOC.md
(problem, architecture, six design decisions, measured-and-
rejected list), TESTING.md (how to run every gate, incl. the
--basetemp lesson), MODEL_CARD.md (no fine-tuned model in
production — deterministic + retrieval; the LLM artefacts are
measured, not default), DATA_CARD.md (all seven datasets, no
real user data anywhere), TECHNICAL_SUMMARY.md (one page),
PROMPTS.md (both system prompts, versioned, local-LLM path
only). Extended: EVAL_REPORT.md with the ablation table (hybrid
0.948 beats BM25-only 0.887 and TF-IDF-only 0.870; rescue adds
2 cases; verifier changes nothing on the extractive path;
dense-only not measured), docs/ROUTES.md (all 7 KV pages + the
full KV API table), docs/SOURCES.md (the two verified helplines).

Step 9.7 delivered (21 Nov 2026): pitch assets, all in
`docs/pitch/` — 3-minute demo script (+ 90-second backup),
12-slide deck outline with speaker notes, 30 judge Q&As with
honest answers, real-vs-prototype table, one-page impact
measurement plan. Every number is measured; every demo line is
a real flow; the gaps (English answers, no real-user evaluation
yet, no business model) are stated in the assets themselves,
not hidden from judges.

Step 9 ends with DEPLOY_CHECKLIST.md (21 Nov 2026): the deploy
decision checklist for Ankit — 5 owner decisions (Render
free-vs-Starter, live service state, Postgres-before-pilot,
branch push, audit-log prune), 10 pre-deploy verifications
(incl. CORS lockdown, ffmpeg, the 2-worker vs 1-worker
difference, HSTS from the platform, Firebase phone enablement),
staging→production sequence with live smoke tests, 48-hour
watch, rollback. Nothing deploys itself.

Stage 6 delivered (20 Nov 2026): the consent system, employer
matching and hire-outcome tracking — migration v14 (six tables,
no FK constraints: `kv_worker_profiles`, `kv_consents`,
`kv_consent_audit`, `kv_shortlists`, `kv_contact_requests`,
`kv_hire_outcomes` + index on worker city), the consent store
(`career_guidance/kaamvaani/consent.py` — per-employer,
time-limited 7/30/90-day revocable consent, one active consent
per (worker, employer), lazy expiry with a `system` audit event,
allow-list field filtering `filter_profile`, the append-only
audit log — the only audit write in the module is `_append_audit`
(INSERT); `delete_sample_data` deliberately never deletes audit
rows), the candidate scorer (`score_candidate` in the same module
— reuses Stage 4's matcher machinery, weights skill 0.35 / title
0.30 / city 0.20 / income 0.15, per-feature contributions and
structured reasons; the title component is 0.0 for the
electrician case because the proven Stage 4 matcher has no
shared-stem matching — the skill component carries the trade
match, and no new matcher was invented), the router
(`backend/kv_consent.py` — worker profile save/get, grant/revoke/
mine/audit, ranked consented candidates, shortlist, contact
requests, hire outcomes + day-30/90 follow-ups and retention
summary, behind `KV_CONSENT`), matching gates enforced in the
store (verified employer + verified listing, active consent,
server-side field filtering; a shortlist entry survives a later
revoke but shows no fields), hire outcomes requiring a consent
RECORD (any status — outcomes may be reported after a consent
ends, never about a stranger), the seed
(`data/kv_sample_workers.json` + `scripts/seed_kv_workers.py` —
10 fictional workers, 13 consents across all three states, 3
shortlists, 2 contact requests, 2 outcomes incl. a day-30
follow-up; requires the Stage 5 listings seed first), the live
verification script (`scripts/verify_kv_stage6.py` — 22 scripted
checks against a running backend incl. all negative cases), and
the plain functional frontend: `/sharing` (worker profile form
with "Use my voice profile" prefill from sessionStorage, grant
panel driven by `?listing=ID`, consents + revoke, contact
requests, outcomes, audit log, spoken explanation via the Listen
button), "Share my profile" on every `/jobs` card, and the
candidates section in the employer portal (verified employers
only: listing picker, ranked candidates with fit reasons/gaps,
shortlist / contact / report outcome, shortlist + outcomes with
retention). Stage 6 UI is English-only (L37). The confirmed voice
profile is still NOT stored server-side — the worker profile is a
separate, explicit save (L45); contact requests have no worker
response flow yet (L46); matching covers signed-in workers with
saved profiles only (L47).

Stage 5 delivered (20 Nov 2026): the employer portal — migration
v13 (`kv_employers`, `kv_listings`, `kv_listing_reports` + 8
indexes), the employer store
(`career_guidance/kaamvaani/employers.py` — status machines
pending → verified/rejected/flagged, verify blocked unless the
employer is verified, verified → pending on edit, duplicate
detection, 3-open-reports auto-flag, endorsement badge, audited
review queue), the deterministic scam checker
(`career_guidance/kaamvaani/scam.py` — 10 weighted rules,
FLAG_THRESHOLD 70 / WARN_THRESHOLD 40, LLM advisory score via
`prompts/scam-risk.md` v1.0.0 with `max(rules, llm)`, pay
plausibility framework-only until a sourced minimum wage exists,
L18/L39), the router (`backend/kv_employers.py` — register/mine/
verify-phone/listings CRUD/check, public verified-only listings,
worker report flow, admin review + endorse + report-review,
behind `KV_EMPLOYERS`), phone verification via Firebase ID-token
exchange (e-mail match + `email_verified` + `phone_number`
claim; phone sign-in is an owner console step, L38), the seed
(`data/kv_sample_listings.json` + `scripts/seed_kv_listings.py`
— 7 employers, 40 legit + 5 fake listings, all labelled sample
data; the seed fails loudly if a fake scores below 70), and the
frontend: `/employers` portal (register, dashboard, listing CRUD
with scam-check preview, 2-step phone linking), `/jobs` public
verified listings with city/category filters and a worker report
flow, and the Kaam-Vaani tab in the admin console (review queue,
endorse, report uphold/dismiss). Stage 5 UI is English-only
(L37); the client phone flow is built but not live-verified
(L44).

Stage 4 delivered (20 Nov 2026): the Kaam-Vaani scorer
(`career_guidance/kaamvaani/matching.py` — IDF-weighted skill
overlap + stemmed phrase title signal + base MatcherV2 score +
zone and income fits, weights 0.30/0.40/0.10/0.10/0.10, zone
filter slack 1.0; `KV_MAP` of 19 canonicals → O*NET
competencies, tight on purpose), the matching router
(`backend/kv_matching.py` — `/kv/matches` and `/kv/gap-learning`,
sharing the `KV_VOICE` flag; gap via `skillgap.evaluate`,
learning path via `learning.resources_for_gaps`, RAG citations
from courses/skilling topics, best-effort), and the Stage 4
`/voice` results step (top-5 KV cards with structured why-it-
fits, Class 6–8 "Simpler" re-explanation, per-match and summary
spoken readout with next/hear more/save, gap detail with free
learning path + dated source citations, sessionStorage-saved
matches; falls back to guest `/recommend` only on status
0/404/405).

Stage 3 delivered (20 Nov 2026): the STT/TTS gateway
(`career_guidance/kaamvaani/voice.py` — browser Web Speech as the
free default, OpenAI Whisper/TTS via env key, graceful fallback),
LLM profile extraction with repair prompt + deterministic fallback
(`career_guidance/kaamvaani/profile.py`), the conversation state
machine (`VoiceSession`, pure `transition`), the prompt library
(`/prompts/profile-extractor.md` v1.0.0), the guided 5-question
`/voice` flow with confirmation (voice or tap) and sessionStorage
resume, and the `backend/kv_voice.py` router (status/extract/
confirm, behind `KV_VOICE`).

Stage 2 delivered (20 Nov 2026): RAG ingestion/retrieval (BM25 +
TF-IDF hybrid over snapshot v1, 1,040 chunks, `kv_rag_chunks` table
v12, `backend/kv_rag.py` router), the deterministic backend profile
extractor, the eval harness (`eval/kv_golden.json`, 113 cases;
`eval/run_kv.py`; `EVAL_REPORT.md`). Feature flags and
employer/coordinator roles landed in Stage 1. Step 7B (21 Nov
2026) grew the snapshot to v2 (1,048 chunks, +8 central-sphere
minimum-wage chunks) and extended the title bonus to wage chunks.

### 2.7 Stage 3 groundwork already in the tree (from the superseded v1 brief)

The voice-only v1 brief was replaced by the master prompt, but its
frontend code is the browser-native fallback the master prompt §4.2
requires, so it is kept and committed as Stage 3 groundwork:
`frontend/app/voice/page.tsx`, `frontend/components/voice-view.tsx`,
`frontend/lib/speech.ts` (Web Speech wrapper, EN/HI/TA),
`frontend/lib/voice-profile.ts` (deterministic profile extraction —
the offline fallback for Stage 3's LLM extraction),
`frontend/lib/voice-vocabulary.ts` (generated from
`data/skill_synonyms.yaml` by `scripts/gen_voice_vocab.py`), 46
`voice_*` i18n keys (EN/HI/TA), landing hero "Try voice" CTA.
Stage 3 reworked it into the guided 5-question flow with backend
extraction + confirmation (79 `voice_*` i18n keys; the vocabulary
generator now also emits `CITY_ALIASES` from
`data/kv_cities.yaml`); the typed fallback and the vocabulary stay.

## 3. Target architecture decisions

### 3.1 Layout: one new subpackage, one router prefix

- Domain logic: `career_guidance/kaamvaani/` — one module per master
  prompt §4.2 area: `voice.py` (STT/TTS gateway interfaces),
  `profile.py` (extraction + confirmation state machine),
  `rag.py` (ingest/retrieve/answer), `listings.py`,
  `employers.py`, `verification.py`, `consent.py`,
  `matching.py` (Kaam-Vaani filters over `MatcherV2`),
  `safety.py`, `analytics.py`, `video_check.py` (Stage 9).
- Routers: `backend/kv_*.py`, mounted under `/api/v1/kv/*`,
  each behind its feature flag (flag off → 404, same as if the
  route never existed).
- Frontend: routes stay top-level (`/voice` exists;
  `/employer`, `/coordinator` to come); Kaam-Vaani components under
  `frontend/components/kv/`; flags in `frontend/lib/flags.ts`.
- Prompts: `/prompts/*.md` (versioned, testable system prompts),
  loaded by the RAG/LLM layer, never inline in code.

### 3.2 Data: SQLite dev, Postgres production, no Alembic

- New tables arrive as migrations v11+ in the existing runner
  (SQLite DDL, Postgres-translated automatically). Kaam-Vaani stores
  go through `career_guidance.db.connect()` so the Postgres path
  works from day one — no new direct-`sqlite3` stores. (Verified
  live on Postgres 16.2 in Step 7C, 21 Nov 2026 — see §2.3.)
- RAG store decision: **chunks in the relational DB + BM25/TF-IDF
  retrieval first** (zero new deps, works on SQLite and Postgres,
  no downloads). Dense embeddings are an optional second retriever
  behind `SEMANTIC_EMBEDDING_MODEL` (multilingual-e5 class, local
  `sentence-transformers`, free, CPU) — the Stage 2 eval measures
  whether embeddings beat TF-IDF on the gold set before they ship.
  pgvector is the production option when `DATABASE_URL` is Postgres
  (Stage 2 designs the interface so the vector store is swappable;
  it is NOT required for the prototype to work).
- Object storage for optional video clips (Stage 9): local disk in
  dev, short TTL auto-delete; no new paid bucket.

### 3.3 Providers: interfaces first, free fallbacks always working

| Capability | Interface | Free default (no key) | Hosted (env key, later) |
|---|---|---|---|
| LLM | `SuggestionProvider` (exists) | `TaxonomyProvider` + deterministic rules | OpenAI / Gemini / Ollama |
| Embeddings | `semantic.py` scorer protocol | TF-IDF | `sentence-transformers` local |
| STT | `kaamvaani/voice.py` `STTProvider` | Browser Web Speech API | Whisper API etc. (env) |
| TTS | `kaamvaani/voice.py` `TTSProvider` | Browser speechSynthesis | Hosted TTS (env) |
| SMS/WhatsApp | share provider (Stage 8) | Share links / copy text | Provider via env var |

Rule: if a stage genuinely needs a key that does not exist, build
the interface with the free fallback working and FLAG it — never
stall, never invent a key.

### 3.4 Auth & roles (Stage 1/5)

- Extend `users.role` with `employer` and `coordinator` values
  (migration + server-side validation; `is_admin` unchanged).
  Employer profile data lives in a new `employers` table (one row
  per employer user); coordinator membership reuses the institute
  pattern (coordinators belong to an institute/pilot org).
- OTP phone verification: Firebase Phone Auth when the owner
  enables it (10/day free on Spark); until then, email + admin
  review. No SMS provider is bought.

### 3.5 Feature flags (Stage 1)

Backend: env vars on `Settings` (`KV_VOICE`, `KV_RAG`,
`KV_EMPLOYERS`, `KV_CONSENT`, `KV_VIDEO_CHECK`, `KV_PILOT`),
default ON in dev, OFF in production until staged.
Frontend: `NEXT_PUBLIC_KV_*` read once in `lib/flags.ts`.
Flagged-off routes return 404; flagged-off UI is not rendered.

### 3.6 Grounding and honesty (non-negotiable)

- Every factual claim shown to a user comes from the RAG knowledge
  base with a source (title + link) or is omitted. The LLM answers
  from retrieved context only; insufficient context → "I don't
  know / please ask your coordinator".
- Structured outputs (profile extraction, match explanations,
  skill gaps, learning paths) validate with Pydantic; invalid →
  repair prompt once, then deterministic fallback.
- Matches are labelled suggestions, never job guarantees.
- Demo/seed data is labelled "sample data" everywhere it appears.
- No invented wages, scheme details or listings — ever.
- Prompt-injection defence: employer listing text and uploaded
  content are untrusted data, never instructions.
- PII redaction in logs; no raw audio stored by default; DPDP
  principles (notice, consent, purpose limitation, minimisation,
  correction, erasure) — see `docs/COMPLIANCE.md`, extended in
  Stage 6/10.

### 3.7 Evaluation (Stage 2, before tuning)

Extend `eval/` with `eval/kv_golden.json` (≥100 realistic
voice-style queries, EN/HI/TA, incl. noisy/code-mixed/vague) and
`eval/run_kv.py`. Metrics: profile-extraction field accuracy,
retrieval recall@k + MRR, answer faithfulness (LLM-as-judge +
citation check), refusal correctness, latency p50/p95, cost per
session. Thresholds (master prompt §11): profile ≥90%,
recall@5 ≥85%, faithfulness ≥90% — actuals reported honestly in
`EVAL_REPORT.md` even if lower. The eval gate runs in CI; the build
fails below threshold.

**Stage 2 (20 Nov 2026):** the harness is built and the gate is
live — `eval/kv_golden.json` (113 cases), `eval/run_kv.py`,
`eval/kv_report.json` (committed + CI artifact). Final eval PASS:
profile 1.000, recall@5 0.954, MRR 0.926, faithfulness 0.907,
refusal 0.933, latency p50 3 ms / p95 49 ms. Faithfulness is
measured by citation check only in Stage 2 (the answer is a
verbatim quote, so a correct citation means grounding); LLM-as-judge
needs a configured provider and is not implemented. Cost per
session is not measured — the Stage 2 answer path uses no LLM and
no paid API.

## 4. Key flows (target)

1. **Voice onboarding (F1):** greet → language → 4–6 spoken
   questions (skills / location / income need / availability) →
   transcript shown → profile extracted (LLM structured output
   when configured, deterministic fallback otherwise) → confirmed
   by voice or tap → stored (guest session or account).
2. **Matching (F2):** confirmed profile → `MatcherV2` + Kaam-Vaani
   filters (radius, minimum income, shift, language) → Top-5 with
   plain-language "why it fits", skill gap, free learning path with
   sources → spoken readout (per-match + summary), next/hear more.
3. **Listings (F3):** employer registers → OTP/email verify →
   creates listing → duplicate detection + scam-pattern rules +
   pay-plausibility vs sourced minimum wages → admin review queue →
   verified / rejected / flagged. Workers see verified only.
4. **Consent (F4/F5):** worker hears a plain-language spoken
   explanation of exactly which fields go to which employer →
   grants per-employer, time-limited, revocable consent →
   immutable audit log → employer sees only consented fields →
   shortlist / contact request / hire-outcome reporting.
5. **Rights/scam assistant (F6):** voice question → RAG retrieve
   (hybrid + rerank) → grounded answer with citations → escalation
   routes (sourced helplines) on exploitation/unpaid-wages/distress.

## 5. Deployment (current; Stage 11 changes nothing without approval)

- Frontend: Vercel (Root Directory `frontend`, static export).
- Backend: Render Docker service (multi-stage Dockerfile: Node
  build → Python API serving `frontend/out` for direct Render-URL
  visits). `docker-compose.yml` runs the same image locally with a
  named volume for SQLite.
- One-command local start: `make api` + `make web` (or compose).
  Stage 1 adds the Kaam-Vaani env template (`.env.example`
  additions) and documents the flag defaults.
- Stage 11 (deploy + smoke tests + demo rehearsal) needs the
  owner's explicit approval and happens at night in one batched
  sitting, per standing rules.

## 6. Risks (summary — full register in docs/KAAM_VAANI_PLAN.md)

1. Free-tier Render may wipe SQLite on deploy → pilot data needs
   Postgres before any real pilot.
2. No LLM/STT/TTS keys → all intelligence must work offline-first;
   LLM quality claims must wait for a keyed eval run.
3. RAG sources (NSQF QPs, DGT syllabi, TNSDC) may not be fetchable
   — Stage 2 documents per-source fetchability in `SOURCES.md`.
4. Browser STT accuracy in Tamil dialects/code-mixed speech is
   unmeasured until the eval gold set runs.
5. Employer verification at scale is a human process — the
   prototype provides the queue + checks, not the humans.
6. `render.yaml` says `autoDeploy: true` / starter plan; live
   service state may differ — confirm before Stage 11.

## 7. Complexity (time/space) — measured where stated

Numbers below are measured on this VM (shared 1.5 CPU) unless
marked as analysis. "n" is the size of the working set in each
case; the pilot scale is hundreds of workers/listings, not
millions, so linear scans are acceptable and are called out
where they would not scale.

The consolidated measured reference is `COMPLEXITY.md`
(Step 8.10): Big-O plus measured numbers for the whole system
— retrieval, ranking, matching, skill graph, geohash, dedup,
verifier, caches, local LLM, LoRA builder, trace log — with an
end-to-end latency table, a space summary, and a "what breaks
first at scale" list. This §7 is the per-component prose
version, kept in sync with the code; `COMPLEXITY.md` is the
single place to look a number up.

### 7.1 Employer matching (Stage 6)

`rank_candidates_for_listing(listing_id)`: one query for the
employer's granted consents, one bulk profile fetch, then
`score_candidate` per consented worker and a sort.

- Scoring one candidate: O(R + W + P) where R = required
  competencies for the listing, W = the worker's competencies,
  P = phrase-variant sets built from the worker's skills. All
  three are small (single-digit to low-teens) for real profiles.
- Ranking: O(C log C) for C consented candidates, plus O(C)
  audit INSERTs (one `accessed` event per returned candidate,
  in a single transaction).
- Measured (seeded DB, listing 1, 13 consented candidates):
  31–58 ms per ranking call, mean 41.2 ms over 5 runs (includes
  the 13 audit inserts; the spread is SQLite fsync variance).
  The 20-candidate default cap (`limit`, max 100) bounds the
  per-call work.
- Space: matching is computed on the fly — no ranking cache, no
  materialised table. Persistent state is one row per worker
  profile, one row per consent, and one audit row per candidate
  returned per search, so the audit log grows O(searches ×
  candidates returned). At pilot scale that is thousands of rows;
  no archival/rotation exists yet (a Stage 9+ concern).
- Grant/revoke/profile-save are O(1) row operations plus one
  audit INSERT. Lazy expiry runs a full scan of `kv_consents`
  (`status='granted' AND expires_at <= now`, no index) on every
  read path — fine at pilot scale, but it needs a
  `(status, expires_at)` index once the consents table grows
  past tens of thousands of rows.

### 7.2 RAG retrieval (Stage 2; multilingual + dense in Step 7A; wages in Step 7B)

BM25 + TF-IDF hybrid over snapshot v2 (1,048 chunks), held in
memory per process. Retrieval is O(chunks) per query with small
constants (sparse vector dot products over the query's terms).
Measured by the KV eval (189 cases, 21 Nov 2026): p50 39 ms, p95
56 ms, max 148 ms (glossary path; latency varies with machine load
— an earlier same-day run showed p50 63 ms). Index memory is
O(chunks × avg terms) — a few MB at snapshot scale.

Step 7A adds two retrieval paths, both measured in EVAL_REPORT.md:

- **Glossary translation** (the shipped default): O(n × w) token
  lookups for an n-token query with max phrase width w=3, plus one
  YAML load cached for the process lifetime. Space: one ~8 KB
  glossary file. Zero model, zero network, zero extra latency
  worth measuring (translation is dict lookups).
- **Dense retrieval** (opt-in, `KV_DENSE_MODEL`): construction
  embeds all C chunks once, O(C) forward passes (batched); per
  query one embedding forward pass + O(C × d) dot products
  (d = 384). Space: O(C × d) floats for the index (~1.6 MB at
  snapshot scale) + O(P) for the model (P ≈ 118M parameters,
  ~470 MB fp32 weights + the torch runtime — measured memory and
  latency in EVAL_REPORT.md). RRF fusion over the full hybrid +
  dense rankings is O(C log C) for the sort.
- The shared tokenizer's Indic limitation (L51): it splits on
  `[^\\w]+`, which shreds Tamil/Hindi words at combining marks.
  The translator uses its own whole-word tokenizer; the shared
  one is untouched, so the English path is byte-identical.

### 7.3 Ingestion (Stage 2)

Batch-only (`eval`/ingest scripts): O(documents × chunks per
document), run once per snapshot, not on the request path.
Snapshot v2 = 1,048 chunks from the curated sources in
`SOURCES.md` (v1's 1,040 + 8 wage chunks from Step 7B).
Re-ingestion replaces the snapshot table; no incremental update
exists yet.

### 7.4 Voice profile extraction (Stage 3)

Deterministic fallback extraction is O(answers × vocabulary);
LLM extraction cost is the provider's (no key is configured in
this build, so the fallback is the live path). The confirmed
voice profile is held client-side in sessionStorage only — zero
server-side storage, zero server-side retention.

### 7.5 Occupation ranker (Stage 4; separate component in Step 8.1)

`KVScorer.rank` scores every occupation the zone filter keeps
(~800 of 974 for a 12th-pass profile) and orders them through
`MultiCriteriaRanker` (`career_guidance/kaamvaani/ranker.py`).

- Scoring one occupation: O(core + phrases × title words) — the
  IDF-weighted skill overlap over the occupation's core
  competencies (≤ 10) plus the title-purity check over the
  profile's phrase-variant sets. All inputs are small.
- Combination (`ranker.combine`): O(F) in the number of features
  (F = 5 live). Ordering (`ranker.rank`): O(n log n) comparisons
  via the injected comparator, each O(1). The ranker adds no
  asymptotic cost over the old inline sort it replaced.
- The dominant cost is the base matcher: `_base_scores` runs
  MatcherV2 over the full taxonomy once per `rank` call (its own
  O(n) pass), and the IDF table is built once per scorer
  construction, O(n × core).
- Space: O(n × core) for the per-occupation core-competency
  cache + O(competencies) for the IDF table, both built once per
  scorer (the router holds one scorer for the process lifetime).
- The title-evidence rescue (Step 8.1, L53) is one float
  comparison per answer — no measurable latency (KV eval after
  the change: p50 103 ms, p95 204 ms over 189 cases).

### 7.6 Skill-gap path engine (Step 8.2)

`skillgraph.build_gap_graph` builds the production graph (gap
skills + catalogue courses, one node per course URL) and runs
Dijkstra per gap skill from a START node, then orders the chosen
courses by topological order with gap-importance priority.

- Dijkstra: O((V + E) log V) per gap skill (``heapq`` over
  lexicographic ``(paid, count)`` tuple costs); G gaps cost
  O(G x (V + E) log V). Topological order (Kahn's): O(V + E).
  The builder is O(G x R) resource lookups (R <= 2 candidates
  per skill) plus a DOMAIN_HINTS scan for covered-gap
  compression.
- Measured (five probe profiles, 20 runs each): mean **0.36 ms**
  per plan (min 0.28, max 0.43 ms). Production graphs are tiny
  (9–14 nodes, 9–14 edges) — the engine is nowhere near a
  bottleneck at any plausible scale; a catalogue 100x larger
  would still plan in milliseconds.
- Space: O(V + E) for the graph, built per request and
  discarded; no cache (the catalogue is small and the build is
  sub-millisecond).
- Coverage, measured on the five probe profiles' top matches
  (flat path vs engine): demo 5/8 → 6/8, electrician 5/7 → 5/7,
  tailor 5/6 → 6/6, driver 3/9 → 4/9, btech 5/8 → 7/8 — **23/38
  → 28/38**. All engine courses free (0 paid) on these profiles;
  paid-minimisation is proven on hand-made graphs, not exercised
  by the probe set. The 10 still-uncovered gaps have no curated
  resource at all (L32/L56) and are listed as uncovered, not
  silently dropped.

### 7.7 Geohash location index (Step 8.3)

`geo.GeohashIndex` encodes every verified listing once (precision
6, ~1.2 km x 0.61 km cells) and keeps the ``(hash, item_id)``
pairs sorted. A radius query picks a query precision from the
radius (cells small relative to the radius — p6 to 5 km, p5 to
60 km, p4 to 150 km, p3 beyond), enumerates the geohash cells
intersecting the query disc's bounding box (padded one cell per
side — without the padding, cells touching the box in a sliver
fall between grid points; the property test caught 13 misses in
60 trials before the fix), pulls each cell's entries with a
binary-search prefix range, and filters the candidates with an
exact haversine distance. The geohash only prunes; the haversine
decides.

- Build: O(n log n) for the sort, O(n) space. Query: O(cells x
  log n + candidates) haversines, where cells is the number of
  bounding-box cells (<= ~40 for the precision table) — versus
  O(n) haversines for a linear scan. The index is cached on the
  store instance and invalidated by every listing write; without
  the cache the build (~1 s at 100k) would dwarf the per-query
  saving.
- Measured (50 random queries each, radii 10/25/50 km, synthetic
  points in a Tamil Nadu bounding box — labelled synthetic, the
  seed has only 45 real listings): 1k listings — index 2.28 ms
  vs scan 0.67 ms (**0.3x**: the ~2 ms cell-enumeration overhead
  dominates below ~5k listings); 10k — 2.09 ms vs 7.18 ms
  (**3.4x**); 100k — 7.13 ms vs 70.70 ms (**9.9x**). Build:
  8.6 ms / 86 ms / 1005 ms. The first precision table (coarse
  cells, p3 for 50 km) pulled ~56% of a 100k table into the
  filter and measured only 1.8x — the retune to fine cells is
  what the numbers above reflect.
- Correctness: the property test pins exact agreement with a
  linear scan on seeded random data (300 trials, two seeds, two
  regions, radii 1–500 km, 0 mismatches).
- The radius is city-centre to city-centre (A57): listings carry
  a city name only. Only the 6 seed cities have coordinates
  (L57).

### 7.8 Duplicate detection (Step 8.4)

`dedup.DuplicateIndex` answers "is this submission a repost?"
in three layers: an exact SHA-256 fingerprint over normalised
title + city + description; a Bloom filter over the fingerprints
as the pre-filter (a "definitely not present" skips the dict
lookup; a "possibly present" is confirmed by the dict, so a
Bloom false positive can never flag a listing); and word
3-shingle Jaccard (adaptive shingle size for short texts)
against the same employer's listings in the same city, at or
above the tuned threshold of 0.5. Exact matches win over near
ones; among near matches the highest similarity wins, most
recent on a tie. The index is cached on the store and
invalidated by every listing write.

- Build: O(L x W) for L listings of W words (shingle sets).
  Exact lookup: O(k) Bloom hashes + O(1) dict. Near lookup:
  O(E x S) Jaccard comparisons against the employer's E
  listings in the city with S shingles each. Space: O(L x S)
  shingle sets + 95,851 bits (~12 KB) for the Bloom filter.
- Measured (labelled set, 369 pairs: 279 positive from
  mechanical variants of the 45 seed listings — exact copy,
  title reworded, description sentence dropped/shuffled,
  combined edits; 90 negative — different jobs, including the
  hard case of the same title with a different job's
  description): precision **1.000**, recall **0.907** at
  threshold 0.5 (F1 0.951). The full sweep: 0.3 → P 1.000 /
  R 0.982; 0.4 → 1.000 / 0.953; 0.5 → 1.000 / 0.907; 0.6 →
  1.000 / 0.832; 0.8 → 1.000 / 0.405. 0.5 was chosen over 0.3
  for its 0.389 margin above the highest negative (0.111).
  Bloom FP rate: 0/10,000 probes at pilot scale (45 items);
  at the 10k design point, measured 0.0095 vs theoretical
  0.0100. Zero false negatives on real fingerprints (by
  construction — a Bloom filter never misses a member).
- The same description with a different title is deliberately
  excluded from the labelled set (a retitle is genuinely
  ambiguous); the detector flags it (~0.85 Jaccard) as intended
  behaviour — an identical body is the same job. Cross-employer
  duplication is out of scope (L42).

### 7.9 Citation verifier (Step 8.5)

`citations.verify_answer` checks every answer sentence against
its cited chunk with token overlap (the repo's ``tokenize`` —
stopwords dropped, light stemming): a sentence is supported
when >= 0.8 of its content tokens appear in the chunk.
``answer_question`` verifies before returning — unsupported
sentences are dropped, and if nothing grounded remains the
answer refuses with reason ``"unverified"``. A trailing "…"
marks the final sentence truncated (the 600-character cap cuts
it mid-sentence): reported, but excluded from the verdict.
Every answer carries a ``verification`` summary (verified,
sentences, supported, truncated, dropped).

- Complexity: O(S x T) for S sentences and T chunk tokens
  (set intersections); negligible next to retrieval.
- Measured on the 115 gold retrieval cases: **115/115 answers
  verified, 591/591 sentences supported** (support rate 1.000;
  complete sentences 476/476), 0 dropped, 0 unverified
  refusals, 0 answers changed — the verifier proves the
  extractive guarantee rather than changing behaviour. All 115
  answers hit the 600-char cap, so the truncation path is the
  common path, not an edge case. The 6 unfaithful cases are all
  verified (faithful=False, verified=True): grounding is not
  relevance (L58), and faithfulness stays 0.948.

### 7.10 Caches (Step 8.6)

Four caches, one eviction policy (LRU, bounded, thread-safe —
`career_guidance/kaamvaani/cache.py`), one invalidation rule each.
The rule for every cache is the same principle: **an entry is keyed
by everything that determines its value, so a stale entry is
unreachable, not merely unlikely.**

| Cache | Key | Invalidation |
| --- | --- | --- |
| Translation | raw query string | none needed in-process: the glossary is loaded once per process, so translation is a pure function of the query |
| Answer / search (RAG router) | (snapshot versions, kind, query, top_k, filters) | the snapshot version is IN the key — a re-ingest can never serve a pre-ingest answer |
| Profile (voice router `/extract`) | (payload, prompt version) | a prompt edit naturally misses; the deterministic path keys on `""` (it never reads the prompt) |
| LLM result (`CachingCompleter`) | SHA-256(system prompt, user content) | 1-hour TTL (bounds staleness if the model behind a URL is re-pulled); failures are never cached |

- Complexity: O(1) get/put (hash + OrderedDict); O(n) memory for n
  entries. Bounds: translation 512, answer 256, profile 256, LLM
  256 entries — an answer dict is ~1–2 KB, so the answer cache is
  well under 1 MB at full capacity.
- Measured (21 Nov 2026, `~/workspace/tmp/kv86_bench.py`, snapshot
  v2, 1,048 chunks, 20 gold questions): raw `answer_question` p50
  21.8 ms / p95 33.6 ms; router `/ask` cold p50 27.4 ms, **warm p50
  3.6 ms (~7.6x faster on a repeated question)**; 2 passes over the
  same 20 questions give 20 hits / 20 misses (hit rate 0.50, as
  expected — first pass all miss, second all hit). The cold p95
  (734 ms) is the first request, which builds the retriever: the
  first `HybridRetriever` build in a fresh process costs ~4.3 s
  (sklearn/numpy warm-up on the first TF-IDF fit), ~0.7 s warm
  (measured 3 builds: 4262 / 762 / 693 ms) — a pre-existing cost of
  the lazy retriever build, not of the cache.
- Honest limits: the translation cache is a negligible win in
  absolute terms (glossary lookup is 0.019 ms/question cold; the
  cache saves ~1.2 ms over 69 questions) — it is kept because it is
  free and correct, not because it saves real time. The LLM cache
  is the big win when a provider IS configured: 10 identical
  completions make 1 provider call (measured with a 50 ms mock).
  All caches are per-process, in-memory (L59): nothing is shared
  across workers or restarts.

### 7.11 Local LLM provider (Step 8.7)

Two local, no-key providers behind the shared `ChatCompleter`
interface (`career_guidance/providers.py`): `OllamaCompleter`
(pre-existing, HTTP to a local Ollama server) and
`LlamaCppCompleter` (new in 8.7 — loads a GGUF file in-process
via `llama-cpp-python`). Selected with `LLM_PROVIDER=ollama` /
`llamacpp`; `llamacpp` additionally requires
`LLAMACPP_MODEL_PATH`. Both have a `SuggestionProvider` wrapper
(`OllamaProvider` / `LlamaCppProvider`) sharing the strict JSON
schema validation. The binding is an OPTIONAL dependency (lazy
import); the model loads lazily on first completion, not at
startup. Full setup: `docs/LOCAL_LLM_SETUP.md`.

**Measured here (21 Nov 2026):** `llama-cpp-python 0.3.37`
(compiled from source — no prebuilt wheel for this platform,
~11 min); Qwen2.5-0.5B-Instruct Q4_K_M (469 MB); load 0.4 s;
peak RSS 670 MB at n_ctx 2048; generation 10.1 tokens/s on
4 CPU threads; full extraction with the production prompt
35.9 s (prompt processing dominates). The production prompt
needs ~1440 tokens, so the default context is 2048 (512
failed on the real prompt). **Ollama was NOT executed in this
sandbox** — its interface exists and is factory-wired, but the
server, install and model pull were not run here.

**Quality (honest):** the 0.5B model follows the JSON schema
reliably and gets concrete fields right (skills, education,
city, income on unseen input) but makes semantic field errors
(`interests` = "job_6_months", `goal_type` = "explore" for a
person who explicitly wants a job) that Pydantic validation
does NOT catch. The deterministic fallback and the voice
flow's confirm step stay mandatory (L60).

### 7.12 LoRA pipeline (Step 8.8)

A fine-tuning pipeline for profile extraction — the one place an
LLM generates structured output in the main flow. The dataset
builder (`career_guidance/kaamvaani/lora_data.py`, CLI
`scripts/build_lora_data.py`) turns the 55 gold profile cases
into TRL messages-format JSONL (49 train / 6 val, seed 42,
deterministic): the target is the deterministic extractor's
full 7-field output, validated against the gold `expected`
(skills as a set, like the KV eval) — a case the extractor
disagrees with is skipped and reported, never built on a lie
(0 skipped today). Every example is validated before it is
written (3-turn shape, 7-key JSON assistant reply, PII safety
net over phone/email patterns) and carries its provenance
(`source`, `gold_case_id`, `language`, `prompt_version`); the
build report records the gold file's SHA-256.

Deliberate exclusions: retrieval cases stay eval-only (training
on them would teach ungrounded answering, against the design);
refusal cases are the wrong task shape; seed workers have no
transcripts (9/10 Tamil — templating unverified Tamil would be
invented data). Config `training/lora_config.yaml` (Qwen2.5-0.5B
base, r=8/alpha=16, completion-only loss) and notebook
`training/train_lora_colab.ipynb` (free Colab T4, adapter-vs-base
val eval) are the prepared training path. **Training was NOT run
here (no GPU) and the notebook was NOT executed** — see
`docs/LORA_RUNBOOK.md`. 55 examples is a seed set, not a
production fine-tune (L61).

### 7.13 Agent trace log (Step 8.9)

Per-request structured JSON traces of what the agent did:
`career_guidance/kaamvaani/trace.py` (`Trace` + `TraceSink`,
process-wide singleton shared by the RAG, voice and matching
routers). A trace records the endpoint, a query hash (first 16
hex of the SHA-256 of the question/transcript — correlation
without storing text), cache-hit flag, total latency, outcome
("answered" / "refused:<reason>" / "cache_hit" / "error"), and
one span per stage with its own latency + safe detail:
`/ask` → translate / retrieve / verify; `/search` → retrieve;
`/extract` → extract (method + skill count); `/matches` →
match (returned count + top score). Every response carries its
`trace_id`. Admin-only read API: `GET /api/v1/kv/traces` (newest
first, limit 1..200) and `GET /api/v1/kv/traces/{id}`
(`backend/kv_traces.py`, mounted when KV_RAG or KV_VOICE is on).

PII safety is by construction: span details are validated on
write — forbidden keys (names, phones, raw text, profile
fields) and string values over 500 chars are rejected (the span
is recorded as an error with a rejection note, never the unsafe
content), and tracing never breaks a request. Storage: an
in-memory ring (default 200 traces) plus an optional JSONL file
sink (`KV_TRACE_FILE`; 10 MB/file, 3 files, size rotation).
Retention is size-bounded, not time-based (L62); the file is
the only durable copy — a restart starts empty.

### 7.14 Rights/scam assistant (Step 9.1)

Same cost as `/ask` (7.2): the rights path IS `answer_question`
with a topic filter, so retrieval is O(chunks) for the BM25 +
TF-IDF scoring over the 1,048-chunk snapshot, then the refusal
gates and the citation verifier (7.9). The topic filter restricts
the candidate set (56 of 1,048 chunks) for normalisation and hit
construction — the scorers still score all chunks, so the filter
saves hit-construction work, not scoring work. The scam-intent
check is O(query tokens) against a fixed keyword set; helpline
loading is a one-time 1.5 KB JSON read, cached per process.
Space: one more per-process `HybridRetriever` (~33 MB peak-RSS
rise at build — COMPLEXITY.md §2, transient sklearn fit
allocations included) + one more answer cache (256 entries,
same bounds as 7.10).

### 7.15 Pilot console (Step 9.2)

Metrics are COUNT/GROUP BY queries over the KV tables — O(rows
scanned) per table, no joins, all on the pilot-scale tables
(hundreds of rows); the outcome/retention half loads at most
1000 outcome rows into Python for the latest-per-(listing,
worker) dedup, so it caps silently past 1000 reports (documented
in the method docstrings — pilot scale is far below it). The
roster is O(limit) profile rows + one user lookup per row (the
same N+1 pattern the consent router already uses for candidate
names); the CSV export pages through the roster in 500s so
memory stays bounded. Bulk onboarding is O(rows) with one
profile-existence lookup + one upsert per row, capped at 100
rows per request. No new indexes: the roster orders by
`created_at` on a small table; a worker base in the tens of
thousands would want a `(created_at)` index and a bulk user
lookup.

### 7.16 Video skill check (Step 9.3, experimental)

One check runs ffprobe (one pass over the file headers) + 6
ffmpeg frame extractions (each decodes up to its timestamp —
O(duration) decode work per frame in the worst case, bounded by
the 60 s clip cap) + PIL statistics on 6 downscaled 160 px-wide
frames (O(pixels), trivial). Measured end-to-end on a 30 s
320×240 synthetic clip: 1.08–1.24 s over 3 runs (ffmpeg
dominates; the PIL analysis is milliseconds). Space: the
uploaded clip sits on /tmp up to the 50 MB cap until the
`finally` deletes it — the 5/hour/user rate limit bounds
concurrent /tmp use. No result is stored, so there is no
storage growth at all.

### 7.17 Hardening (Step 9.4)

Rate limiting is O(1) amortised per call (sliding-window deque
per key, expired entries popped lazily; memory O(keys × calls
in window) — bounded by the window, and the per-IP key space
is the caller population). Deletion is one DELETE per table
(all indexed on the key columns: `user_id` is the profile PK,
`worker_user_id`/`employer_id` are indexed on consents,
shortlists, contact requests and outcomes) + one UPDATE on
outcomes — O(rows owned by the user), not O(table). The L50
expiry query is O(log consents + expired) via
`idx_kv_consents_expiry` (verified by test). The audit log
remains the one unbounded grower (L49): one row per returned
candidate per employer search, no automated prune by design.

### 7.18 Load test (Step 9.5)

The load test is O(users × rounds) requests against a live
server; per-request cost is the endpoint's own cost (retrieval
O(chunks) per query, matching O(taxonomy) per call) — there is
no per-request overhead added by the harness. Under 20-user
concurrency the single worker serialises CPU-bound work, so
latency grows roughly linearly with concurrency until the
worker saturates; `/matches` (p50 2.51 s at 20 users, vs
~380 ms single-user) is the first endpoint to degrade. Memory
is flat: RSS 266 → 285 MB, peak 293 MB, inside the 512 MB free
instance. Full numbers in docs/PERFORMANCE.md.

### 7.19 What is NOT built (honest gaps)

- No cached/approximate ranking: every employer search re-scores
  all consented workers. Fine at pilot scale; a worker base in
  the tens of thousands would need pre-filtering (city index
  exists on `kv_worker_profiles.city`; skill pre-filtering does
  not — skills live in a JSON column).
- No embedding model, no local LLM inference in the DEFAULT request
  path: dense retrieval exists as an opt-in (`KV_DENSE_MODEL`,
  Step 7A — measured, not the default) and a local LLM exists as
  an opt-in provider (`LLM_PROVIDER=llamacpp`, Step 8.7 —
  measured with a 0.5B model, see 7.11) — nothing in this build
  claims LLM-powered matching or ranking by default, and the
  Ollama server path was not executed here.
- Audit log has no retention policy (see 7.1).
