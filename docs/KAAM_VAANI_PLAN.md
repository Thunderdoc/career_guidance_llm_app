# Kaam-Vaani build plan (GAVS Tech4Bharat prototype)

Stage-by-stage plan for the Kaam-Vaani layer on Career Guidance AI v1.5.0.
Companion to `ARCHITECTURE.md` (design decisions) and `ASSUMPTIONS.md` /
`LIMITATIONS.md` (what was assumed / what is honestly not done).

**Standing rules (override the master prompt wherever they conflict):**
no push to GitHub and no deploy without the owner's explicit approval
(local commits on feature branch `kaam-vaani` are fine; pushes happen
at night in one batched sitting with his approval tap); free tiers only,
no new API keys (build provider-agnostic interfaces with free fallbacks
working, flag anything that genuinely needs a key); no invented data —
demo data labelled "sample data"; secrets in env only, never in the repo.

**Process (per stage):** build → run the app → run all tests and evals
→ fix failures → update docs → commit locally on `kaam-vaani` with a
clear message → report to the parent agent (what was built, test/eval
results, screenshots where UI changed, blockers). Never move on with
red tests. Priority: Stages 0–6 first, then STOP for a check before
Stages 7–11.

**Timeline context:** GAVS idea submitted 20 Nov 2026 (Submission ID
`6b00439b828825ceb6f45fce`, team Hackastra); shortlist 23 Nov 2026;
prototype window 23 Nov–15 Dec 2026; finale 27 Dec 2026, Bengaluru.

## Stage 0 — Inspect, ARCHITECTURE.md, build plan ✅ DONE 20 Nov 2026

- Inspected the repo; confirmed real DB (SQLite default, Postgres
  optional via `DATABASE_URL`) and auth (Firebase ID tokens + Google
  OAuth + magic link + signed session cookie).
- Wrote `ARCHITECTURE.md`, this plan, `ASSUMPTIONS.md`, `LIMITATIONS.md`.
- Baseline: backend health OK (v1.5.0, 974 occupations, offline mode);
  pytest baseline green (see Stage 0 report); `tsc --noEmit` green.
- Committed on branch `kaam-vaani`.

## Stage 1 — Infra, CI, env, DB, auth/roles, feature flags ✅ DONE 20 Nov 2026

- Feature-flag system: backend env flags on `Settings`
  (`KV_VOICE`, `KV_RAG`, `KV_EMPLOYERS`, `KV_CONSENT`,
  `KV_VIDEO_CHECK`, `KV_PILOT`; ON in dev, OFF in production) +
  `frontend/lib/flags.ts` (`NEXT_PUBLIC_KV_*`).
- `.env.example`: Kaam-Vaani vars (flags, RAG/embedding model,
  STT/TTS provider placeholders, share provider placeholder).
- Roles: extend `users.role` with `employer` + `coordinator`
  (migration v11, server-side validation, new `employer`/`coordinator`
  deps); document the OTP decision (Firebase Phone Auth needs the
  owner to enable phone sign-in; until then email + admin review).
- CI: add the Kaam-Vaani eval gate (Stage 2 script wired in once it
  exists); keep the ≥85% coverage gate green.
- Docs: README setup section for Kaam-Vaani flags; `RUNBOOK.md`
  started (incidents, rollbacks, key rotation).
- **Acceptance:** flags toggle routes/UI on and off; new roles
  enforced server-side (403s tested); all existing tests green.

Done 20 Nov 2026 (commit on `kaam-vaani`; see the Stage 1 report):
`career_guidance/kaamvaani/flags.py`, `backend/kv_voice.py` (status
endpoint — the first `/api/v1/kv/*` route), migration v11 (phone
columns + role index), `employer`/`coordinator` roles with deps +
admin endpoint, `frontend/lib/flags.ts` + gated landing CTA and
`/voice` page, guarded CI + Makefile kv eval gate (no-op until
`eval/run_kv.py` exists in Stage 2), `docs/RUNBOOK.md`. Root-cause
fix found while testing: the SPA catch-all used to serve 200 HTML
for unmatched `/api/*` paths (masking flag-off routes as "up") —
it now 404s as JSON for `api/*` paths, pinned by a regression test.
All gates green (see the Stage 1 report for numbers).

## Stage 2 — RAG ingestion, retrieval, evaluation harness (eval BEFORE tuning) ✅ DONE 20 Nov 2026

- `scripts/ingest/*`: fetch → clean → chunk (semantic, 300–500
  tokens, overlap) → embed → upsert → versioned snapshot. Chunks in
  the relational DB with source URL/title/date/licence/language.
- Sources (official/openly licensed only; per-source fetchability
  documented in `docs/SOURCES.md`): O*NET (already in-app) enriched
  with tasks/skills/tools; NCVET/NSQF QPs, DGT ITI trades, PMKVY /
  Skill India Digital, NSDC catalogues, TNSDC / Naan Mudhalvan,
  SWAYAM/NPTEL free courses, apprenticeship info; Code on Wages /
  minimum wages, wage-payment rules, e-Shram, NCS, grievance
  channels + helplines, PF/ESI basics; scam patterns from official
  advisories; district-level local trades (cited only).
- Retrieval: BM25 + TF-IDF hybrid first (zero new deps, reuses
  `semantic.py`); metadata filters (language, state/district,
  topic); optional dense embeddings behind `SEMANTIC_EMBEDDING_MODEL`
  (multilingual-e5 class, local, free); rerank interface.
  pgvector interface designed for the Postgres path (not required
  for the prototype).
- **Eval FIRST:** `eval/kv_golden.json` (≥100 voice-style queries,
  EN/HI/TA, incl. noisy/code-mixed/vague; expected profile fields,
  expected sources, expected refusals) + `eval/run_kv.py` (profile
  accuracy, recall@k, MRR, faithfulness, refusal correctness,
  latency p50/p95, cost/session). Thresholds: profile ≥90%,
  recall@5 ≥85%, faithfulness ≥90%. Tune retrieval only after the
  harness runs; publish `EVAL_REPORT.md` (honest actuals).
- **Acceptance:** ingestion runs end-to-end on at least the
  fetchable sources; retrieval returns cited chunks; eval harness
  runs in CI and reports metrics; no source without a stored
  citation appears in any answer.

**Delivered (20 Nov 2026):** eval harness first
(`eval/kv_golden.json`: 113 cases — 55 profile, 43 retrieval, 15
refusal; `eval/run_kv.py` with the CI/Makefile CLI); ingestion
pipeline `scripts/ingest/*` (O*NET + 9 official web sources + 8
Wikipedia fallbacks → snapshot v1, 1,040 chunks); BM25 + TF-IDF
hybrid retriever with title bonus, subordinate penalty, metadata
filters and query rewriting (`career_guidance/kaamvaani/rag.py`);
deterministic profile extractor (`career_guidance/kaamvaani/extract.py`,
server-side mirror of the frontend voice flow, Stage 3's offline
fallback); migration **v12** (`kv_rag_chunks` table + indexes);
`backend/kv_rag.py` router (status/search/ask, mounted behind
`settings.kv_rag`); `eval/kv_report.json` added to the CI artifact
upload; `EVAL_REPORT.md` (honest actuals) + `docs/SOURCES.md` §5
(per-source fetchability). **Final eval (run 4): PASS** — profile
1.000, recall@5 0.954, MRR 0.926, faithfulness 0.907, refusal
0.933, latency p50 3 ms / p95 49 ms. Known misses kept in the gold
set: kv-r042/r043 (non-English questions), kv-r015 (farm),
kv-r033 (fraud), kv-x007 (e-Shram "card" homonym). Dense-embedding
comparison NOT measured (`sentence-transformers` not installed —
see `EVAL_REPORT.md`).

**Migration-numbering decision:** the RAG chunks table takes v12;
the employers table planned for Stage 5 moves to **v13**. The
hardcoded migration-version lists in `test_consent.py` /
`test_institutes.py` / `test_verify.py` / `test_public_api.py` were
converted to `LATEST_VERSION`-based assertions to stop the +1
churn (as `test_db_postgres.py` already does).

## Stage 3 — Voice pipeline + profile extraction + confirmation ✅ DONE 20 Nov 2026

- Backend gateway: `career_guidance/kaamvaani/voice.py` — provider
  interfaces `STTProvider` / `TTSProvider`; browser Web Speech as
  the free default (frontend `lib/speech.ts`, already built);
  hosted providers via env only.
- Profile extraction: structured-output extraction (Pydantic schema,
  repair prompt on invalid output) when an LLM is configured;
  deterministic fallback = the existing `lib/voice-profile.ts`
  extractor (vocabulary from `data/skill_synonyms.yaml`) when no
  LLM is available. Server-side extraction endpoint mirrors the
  frontend fallback so both paths agree.
- Guided flow: rework `/voice` into greet → language → 4–6 spoken
  questions → live transcript → profile shown for confirmation
  (voice or tap) → stored (guest session or account). Recovers from
  silence, noise, wrong language, mic denied (tap UI). Typed
  fallback always visible.
- Conversation state machine (resume if interrupted); multi-turn
  memory limited to the session unless the user opts in.
- **Acceptance (F1):** a Tamil-only speaker completes onboarding in
  under 3 minutes with no typing (tested with the typed fallback +
  scripted transcript in headless; mic path verified in a real
  browser by the owner); extraction field accuracy measured by the
  Stage 2 eval; all tests green.

**Delivered (20 Nov 2026):** STT/TTS gateway
(`career_guidance/kaamvaani/voice.py`: `STTProvider`/`TTSProvider`
ABCs; browser client-side providers + OpenAI Whisper/TTS via
`OPENAI_API_KEY`, selected by `KV_STT_PROVIDER`/`KV_TTS_PROVIDER`,
default `browser`, graceful fallback with a warning log when a
hosted provider is configured without its key); LLM structured
extraction (`career_guidance/kaamvaani/profile.py`:
`extract_profile_llm` with one repair attempt, Pydantic
validation, `normalise_llm_profile` through the shared vocabulary;
`extract_profile_smart` = LLM first, deterministic fallback;
`extract_profile_guided` = per-question extraction with question
context) + the prompt library (`prompts/profile-extractor.md`
v1.0.0, version-header validated, 5 examples EN/HI/TA); the
conversation state machine (`VoiceSession`, pure `transition`,
states greet → language → questions → confirm → matches →
gap_learning → consent → next_steps → done; `remember` recorded,
not acted on); the `backend/kv_voice.py` router (status reports
configured vs effective gateway + extraction mode; extract takes
`text` or per-question `answers`; confirm validates the transition
and the user's edited profile wins; illegal transitions 400);
the guided 5-question `/voice` flow (auto-spoken questions,
"listen again" on every spoken output, live transcript, mic +
always-visible typed fallback per question, skip, silence/
no-speech/mic-denied/network recovery to the tap UI, voice or tap
confirmation with yes/no interpretation, sessionStorage resume,
honest offline fallback with an on-screen note when the server is
unreachable); frontend extractor parity with the backend
(mark-aware boundaries, Devanagari/Tamil education + income,
Hindi/Tamil city postpositions, `CITY_ALIASES` from
`data/kv_cities.yaml` — A16 gaps closed, see A26); 79 `voice_*`
i18n keys (EN/HI/TA, unreviewed — L5). **Gates:** pytest 624
passed (585 baseline + 39 new Stage 3 tests), coverage 92.43%
(gate 85%; `kv_voice.py` 100%, `voice.py` 99%, `profile.py` 94%,
`extract.py` 96%), ruff check + format clean, `tsc --noEmit`
clean, eslint 0 errors, `NEXT_EXPORT=1` build passes (`/voice`
24.7 kB). **Evals:** KV eval PASS — profile 1.000, recall@5 0.954,
MRR 0.926, faithfulness 0.907, refusal 0.933 (all metrics
unchanged after the `extract.py` digit-normalisation change);
golden eval skills Hit@5 1.0 / MRR 0.827, interests Hit@5 1.0;
chat eval faithfulness 4/4, grounding 8/8. **Live (scratch DB,
backend :8100 + frontend dev :3000):** status/extract/confirm all
200; EN/HI/TA extracts fully accurate; decline returns to
questions; confirm-from-matches 400s; guest recommend 200 with 5
recs; typed flow driven end to end in headless Chromium with 8
screenshots (EN greet → questions → confirm → matches, TA greet +
confirm). Mic path NOT verified headless (L25) — needs a real
browser check by the owner. L16 unchanged (retrieval stays
English-only); LLM extraction quality unmeasured (L23).

## Stage 4 — Matching upgrades + spoken results + gap/learning path ✅ DONE 20 Nov 2026

- Kaam-Vaani filters over `MatcherV2`: location radius, minimum
  income, shift/availability, language.
- Results: Top-5 with plain-language "why it fits", skill gap
  (reuses `skillgap.py`), free learning path with sources (reuses
  `learning.py` + RAG courses), spoken readout per match + summary
  ("listen again" on every spoken output), next/hear more/save.
- "Simpler" re-explanation button (reading level Class 6–8).
- **Acceptance (F2):** filters change results measurably (tested);
  every learning-path item carries a source; spoken output works in
  EN/HI/TA where the device has a voice; matches labelled as
  suggestions, never guarantees.

**Delivered (20 Nov 2026):** the Kaam-Vaani scorer
(`career_guidance/kaamvaani/matching.py` — IDF-weighted skill
overlap + stemmed phrase title signal + base MatcherV2 score +
zone and income fits, weights 0.30/0.40/0.10/0.10/0.10, zone
filter slack 1.0, zone-gap penalty 0.15/zone capped at 0.5;
`KV_MAP` of 19 canonicals → O*NET competencies, tight on
purpose — the full YAML `expands` list measured WORSE in probes,
A28) and the matching router (`backend/kv_matching.py` —
`POST /kv/matches` and `POST /kv/gap-learning`, sharing the
`KV_VOICE` flag; gap via `skillgap.evaluate`, learning path via
`learning.resources_for_gaps`, RAG citations from courses/skilling
topics, best-effort). **Before/after on the Stage 3 demo profile**
(farming/computer, 12th pass, Madurai, ₹15,000/mo): before — top
15 all 5.8–7.9%, 0 matching skills, teachers crowned by the zone
tiebreak; after — Data Entry Keyers #1 (50.9%), Computer Operators
#2 (46.8%), Agricultural Technicians #3 (45.4%), Agricultural
Inspectors #4 (42.7%), Computer Programmers #5 (39.3%), no
teachers in the top 5. Electrician probe: Electricians #1 (76.5%);
tailor: Fashion Designers #1 (61.1%). Location radius / shift /
language filters have NO per-occupation data — city is recorded +
shown, session language drives UI/TTS; documented, not faked
(L30). The `/voice` results step: top-5 KV cards with structured
why-it-fits, Class 6–8 "Simpler" re-explanation, per-match and
summary spoken readout with next/hear more/save, gap detail with
free learning path + dated source citations (snippets NOT shown —
homepage boilerplate, L33), sessionStorage-saved matches; falls
back to guest `/recommend` only on status 0/404/405 (A33). **Gates:**
pytest 650 passed (624 baseline + 26 new Stage 4 tests), coverage
92.51% (gate 85%; `matching.py` 96%, `kv_matching.py` 91%),
ruff check + format clean, `tsc --noEmit` clean, eslint 0 errors,
`NEXT_EXPORT=1` build passes (`/voice` 26.4 kB). **Evals:** KV eval
PASS — profile 1.000, recall@5 0.954, MRR 0.926, faithfulness
0.907, refusal 0.933 (all metrics unchanged; extraction untouched);
golden eval skills Hit@5 1.0 / MRR 0.827, interests Hit@5 1.0;
chat eval faithfulness 4/4, grounding 8/8. **Live (scratch DB,
backend :8100 + frontend dev :3000):** `/kv/matches` 200 in 0.42s
(Data Entry Keyers #1 50.9%); `/kv/gap-learning` 200, gap strong
1/missing 8, 5 learning items, 3 citations; wrong-state 400s and
unknown-occupation 404 verified; typed flow driven end to end in
headless Chromium with screenshots (matches + gap + Simpler).
**"N" badge:** the Next.js dev-mode indicator, confirmed absent
from the production export (screenshot 04) — no app fix needed
(L34). Interests-field raw sentence noted, NOT retuned (L36).
Auto-speak now waits for the TTS capability check before speaking,
so voiceless devices no longer show a stuck "Speaking…" indicator.

## Stage 5 — Employer portal, listings, verification, scam checker ✅ DONE 20 Nov 2026

- Employer registration + profile (`employers` table, migration
  v13); listing CRUD (`listings` table) with verification states
  (pending / verified / rejected / flagged).
- Checks: OTP-confirmed phone (Firebase Phone Auth when enabled,
  else email + admin review), duplicate detection, scam-pattern
  rules + LLM risk score (rules work offline; LLM score only when
  configured), pay plausibility vs sourced minimum wages (RAG),
  ITI/skilling-centre/panchayat endorsement badge, worker "report
  listing". Workers see verified listings only.
- Admin review queue (reuses the Phase 3 verify review pattern).
- Seed: ~40 sample verified listings (TN rural roles) + 5
  deliberately fake listings to demo scam detection — all labelled
  "sample data".
- **Acceptance (F3):** full lifecycle tested (register → list →
  review → verified → worker-visible); fake listings flagged by
  rules; unverified listings never visible to workers.

**Delivered (20 Nov 2026):** migration v13 (`kv_employers`,
`kv_listings`, `kv_listing_reports` + 8 indexes); the employer
store (`career_guidance/kaamvaani/employers.py` — status machines,
verify blocked unless the employer is verified, verified →
pending on edit (A39), duplicate detection, 3-open-reports
auto-flag (A38), endorsement badge, audited review queue); the
scam checker (`career_guidance/kaamvaani/scam.py` — 10 weighted
rules, FLAG 70 / WARN 40, `max(rules, llm)` (A41), LLM advisory
score via `prompts/scam-risk.md` v1.0.0, pay plausibility
framework-only (A37)); the router (`backend/kv_employers.py` —
register/mine/verify-phone, listings CRUD + check preview, public
verified-only listings, worker reports, admin review + endorse +
report review, behind `KV_EMPLOYERS`); phone verification via
Firebase ID-token exchange (e-mail match + `email_verified` +
`phone_number` claim — the `email_verified` requirement was added
during Stage 5, closing the claim-match gap); the seed
(`data/kv_sample_listings.json` + `scripts/seed_kv_listings.py` —
7 employers, 40 legit + 5 fake listings, all labelled sample
data; the seed fails loudly if a fake scores below 70); and the
frontend — `/employers` portal (register, dashboard, listing CRUD
with scam-check preview, 2-step phone linking), `/jobs` public
verified listings with city/category filters and a worker report
flow, the Kaam-Vaani tab in the admin console, landing CTAs, and
`kvEmployers` API client + Firebase phone-linking helpers. Stage 5
UI is English-only (L37) and plain/functional by design — a
dedicated design agent owns Kaam-Vaani UI/UX polish from here on
(see the coordination note in MEMORY.md, 20 Nov 2026). **Live bug
found and fixed by the Stage 5 live check:** the read endpoints
(`GET /employers/mine`, `GET /employers/listings[/id]`) required
the employer role, so a fresh user got 403 and never saw the
register form — onboarding was broken. The reads now take any
signed-in user (404 = no profile yet, the UI shows the register
form); actions stay employer-gated (403). Pinned by
`test_fresh_user_reads_404_but_actions_stay_role_gated`, and an
existing test that had encoded the 403 was corrected. **Seed
verified live:** 7 employers (5 verified, 1 pending, 1 flagged),
45 listings (37 verified, 3 pending, 5 flagged), all 5 fakes
flagged at 70–100. **Minimum wages:** a web search found only
conflicting third-party aggregators and no fetchable official
source, so pay plausibility stays framework-only (L18/L39) and
the KB snapshot is untouched. **Gates:** pytest 693 passed (650
baseline + 43 Stage 5), coverage 93% total (gate 85%;
`kv_employers.py` 92%, `employers.py` 95%, `scam.py` 97%),
ruff check + format clean, `tsc --noEmit` clean, eslint 0 errors,
`NEXT_EXPORT=1` build exit 0 (`/employers` 7.34 kB, `/jobs`
4.08 kB, `/voice` 26.1 kB). **Evals:** KV eval PASS — profile
1.000, recall@5 0.954, MRR 0.926, faithfulness 0.907, refusal
0.933 (all metrics identical; extraction/retrieval untouched);
golden eval skills Hit@5 1.0 / MRR 0.827, interests Hit@5 1.0.
**Live (scratch DB, backend :8101 + frontend dev :3001 — :8100
and :3000 were the design agent's servers):** 16/16 API checks
pass (public feed 37 verified, Madurai filter 15, fake 404s,
register → pending, scam check 90 on fake-style text, legit
listing pending → admin approve → public, endorse, 3 reports →
auto-flag → leaves feed, report upheld, verify-phone 503 while
Firebase is unconfigured); 7 phone-viewport screenshots
(jobs guest + report, employer register + dashboard + scam check
+ flagged listing, admin queue). **Environment notes:** the
first three export builds failed flakily — root cause was
`/tmp` (512M tmpfs) at 100% from pytest temp dirs; freed, and
the build then passed from an isolated copy (the design agent's
dev server shares the repo `.next`). A service restart mid-run
wiped `/tmp` (scratch DB + scripts) — re-seeded from the repo.
`frontend/out` is gitignored build output, but the backend's SPA
catch-all (and its JSON "Not found." for unknown /api paths)
registers only when `out/` exists — deleting it before a build
broke two flag-off tests until it was restored from the
successful isolated build; future builds should use an isolated
copy or back `out/` up first. The design agent committed a
voice-flow redesign (`cd3f3a5`) mid-stage on the same branch;
repo-wide `tsc` passes on the merged tree.

## Stage 6 — Consent system, audit logs, employer matching ✅ DONE 20 Nov 2026

- Per-employer data-sharing consent: plain-language + spoken
  explanation of exactly which fields are shared; per-employer,
  time-limited, revocable; immutable consent audit log (extends
  the `audit_log` + Phase 5 consent mechanics, new consent type).
- Employer matching: ranked, verified, consented candidates with
  fit reasons and gaps; shortlist, contact request; employer sees
  ONLY consented fields (server-side field filtering, tested).
- Hire-outcome reporting (feeds the 3-month retention metric).
- **Acceptance (F4/F5):** consent grant/revoke/expiry tested;
  unconsented fields never leak (negative tests); audit log is
  append-only; hire outcomes recordable.
- **STOP after Stage 6 — report back for a check before Stages 7–11.**

**Delivered (20 Nov 2026):** migration v14 (six tables, no FK
constraints: `kv_worker_profiles`, `kv_consents`,
`kv_consent_audit`, `kv_shortlists`, `kv_contact_requests`,
`kv_hire_outcomes` + index on worker city); the consent store
(`career_guidance/kaamvaani/consent.py` — per-employer 7/30/90-
day revocable consent, one active consent per (worker,
employer), lazy expiry with a `system` audit event, allow-list
`filter_profile`, append-only audit log — the only audit write
is `_append_audit` (INSERT), and `delete_sample_data`
deliberately never deletes audit rows); the candidate scorer
(`score_candidate` in the same module — reuses Stage 4's matcher
machinery, weights skill 0.35 / title 0.30 / city 0.20 / income
0.15, per-feature contributions + structured reasons; the title
component is 0.0 for the electrician case because the proven
Stage 4 matcher has no shared-stem matching — the skill
component carries the trade match, no new matcher invented
(A50)); the router (`backend/kv_consent.py` — worker profile
save/get, grant/revoke/mine/audit, ranked consented candidates,
shortlist, contact requests, hire outcomes + day-30/90
follow-ups and retention summary, behind `KV_CONSENT`);
matching gates enforced in the store (verified employer +
verified listing, active consent, server-side field filtering;
a shortlist entry survives a later revoke but shows no fields
(A47)); hire outcomes requiring a consent RECORD, any status
(A48); retention rate `null` until a follow-up is reported,
never 0% by default (A49); the seed
(`data/kv_sample_workers.json` +
`scripts/seed_kv_workers.py` — 10 fictional workers, 13
consents (11 granted, 1 revoked, 1 expired), 3 shortlists, 2
contact requests, 2 outcomes incl. a day-30 follow-up;
requires the listings seed first); the live verification
script (`scripts/verify_kv_stage6.py` — 22 scripted checks);
and the plain functional frontend — `/sharing` (worker profile
form with "Use my voice profile" prefill from sessionStorage,
grant panel driven by `?listing=ID`, consents + revoke,
contact requests, outcomes, audit log, spoken explanation),
"Share my profile" on every `/jobs` card, and the candidates
section in the employer portal (verified employers only).
Stage 6 UI is English-only (L37) and plain/functional by
design — the dedicated design agent owns Kaam-Vaani UI/UX
polish. **Live bugs found and fixed by the Stage 6 live
check:** (1) `interests` is a plain string in the store
contract, but the frontend and seed sent a list — the seed
run crashed on it; frontend + seed aligned to the string
contract, pinned by a round-trip test. (2) The candidates
endpoint 422'd — the frontend sent `city: null` but the API
takes a string ("" = no filter); frontend sends "" now,
pinned by a test. (3) The frontend assumed `worker_name`,
`contributions` and `weights` on candidates and a flat
shortlist — the store returns neither names nor
contributions/weights, and the shortlist view is nested; the
router now enriches candidates with `worker_name` and flattens
the shortlist view, and the frontend types match the real
shapes, pinned by e2e assertions. (4) Candidate reasons are
structured (`{kind, skills}` etc.), not free text — the view
rendered empty bullets; it now renders one honest line per
reason kind, pinned by an e2e assertion. **Seed verified
live:** 10 workers, 13 consents (11/1/1), 3 shortlists, 2
contact requests, 2 outcomes (hired + interviewed, day-30
still_employed on the hire). **Matching latency (measured,
seeded DB, 13 candidates):** 31–58 ms per ranking call, mean
41.2 ms. **Gates:** pytest 756 passed (693 baseline + 63
Stage 6) in 610.58s, coverage 92.97% total (floor 92;
baseline 92.69%), ruff check + format clean (185 files; the
Stage 5 `main.py` format issue is fixed by the Stage 6 mount
edit), `tsc --noEmit` clean, eslint 0 errors (3 pre-existing
warnings), `NEXT_EXPORT=1` build exit 0 (`/sharing` 6.55 kB,
`/employers` 9.96 kB, `/jobs` 4.15 kB, shared 103 kB).
**Evals:** KV eval PASS — profile 1.000, recall@5 0.954, MRR
0.926, faithfulness 0.907, refusal 0.933 (all metrics
identical to baseline, same misses; extraction/retrieval
untouched); golden eval skills Hit@5 1.0 / MRR 0.827,
interests Hit@5 1.0; chat eval faithfulness 4/4, grounding
8/8. **Live (scratch DB, backend :8102 + frontend dev :3002
— :8100/:3100 were the design agent's servers):**
`verify_kv_stage6.py` 22/22 checks pass (grant/revoke/expiry,
matching with/without consent, shortlist, contact, outcomes,
day-30 follow-up, retention 1.0, audit order, all negative
cases); 8 phone-viewport screenshots (sharing empty + saved,
jobs share button, grant panel + done, employer candidates
14 → 13 across a live revoke, sharing revoked). **Complexity**
is documented in ARCHITECTURE.md §7 (matching, retrieval,
ingestion, embeddings — no dense embeddings ship, L13).
**Environment notes:** the isolated frontend copy must exclude
`node_modules` (a full `cp -r` filled the 512M /tmp tmpfs);
`page.waitForFunction`'s default rAF polling stalls on
`/sharing` in the screenshot harness — the shot script polls
via `page.evaluate` + sleep instead (harness quirk, not an
app bug — the DOM dump proved the text present).

## Step 7 — Pre-Stage-7 fixes: multilingual retrieval, TN minimum-wage data, Postgres path (execution prompt Steps 7A–7C)

**Not the same as plan Stage 7 below** (Rights/scam assistant).
The owner lifted the Stage 6 stop on 21 Nov 2026 ("don't stop,
continue day and night 24 by 7") and the build runs Step 7 →
Step 8 → Step 9 without further stops. No push/deploy without
his approval. Product direction (his ruling 21 Nov 2026):
Kaam-Vaani is NOT a job portal / LinkedIn clone /
employer-recruiter portal — the product is the AI (voice-first
generative-AI/LLM/RAG career companion for rural school-leavers
17–24); the Stages 5–6 employer side stays as built, no further
portal expansion. Role split (reaffirmed 21 Nov 2026): the
builder owns the inside (logic, flow, content, internals); the
design agent owns ALL UI/UX; design runs IN PARALLEL with the
build (21 Nov 2026) — screens are handed to the design agent
the moment they exist, while the builder moves to the next
part. Step 7 produces no screens (retrieval logic, KB data,
database path), so there is nothing to hand over for it.

### 7A Multilingual retrieval ✅ DONE 21 Nov 2026

- Measured first: +30 Tamil (kv-r044–r073) + 30 Hindi
  (kv-r074–r103) retrieval cases in the gold set (same topics
  and expected English KB source IDs as the English cases;
  every expected source verified present in snapshot v1), and
  per-language recall@5 / MRR / faithfulness in the harness.
  Before: Tamil recall@5 0.129, Hindi 0.097, aggregate 0.466
  (only PMKVY/NSDC/Roman code-mixed cases passed, via Latin
  tokens); English unchanged at 1.000.
- Glossary query translation (the shipped default):
  `career_guidance/kaamvaani/translate.py` +
  `data/kv_glossary.yaml` (~130 Tamil/Hindi/Roman occupation,
  skill and trade terms), longest phrase first, Latin tokens
  pass through, unmatched non-Latin tokens dropped. Two real
  bugs found by measuring: the shared `[^\\w]+` tokenizer
  shreds Indic words at combining marks (L51 — the translator
  uses its own whole-word tokenizer), and Tamil plural datives
  lose the "கள்" pulli (the stripper retries with it restored).
  English queries are a no-op, so the English path is
  byte-identical.
- Dense embeddings + RRF (opt-in, measured): `DenseRetriever`
  (`career_guidance/kaamvaani/dense.py`,
  intfloat/multilingual-e5-small, E5 query/passage prefixes),
  fused with the hybrid by reciprocal rank fusion (k=60, full
  rankings) in `HybridRetriever.search`; enabled with
  `KV_DENSE_MODEL` / the eval's `--dense-model` flag. Needs the
  sentence-transformers + torch packages (not in the build env);
  without them the router stays hybrid-only with a warning.
  Comparison numbers in EVAL_REPORT.md (L13 closed).
- After (21 Nov 2026, 173 cases) — **KV eval PASS**: recall@5
  1.000 (103/103), MRR 0.966, faithfulness 0.942 (97/103),
  profile 1.000, refusal 0.933. Per language: English 1.000 /
  0.972 / 0.951, Hindi 1.000 / 0.962 / 0.935, Tamil 1.000 /
  0.962 / 0.935. Remaining unfaithful are rank 2–3 near-misses
  between sibling occupations (mechanic ×2, farm ×2 mirroring
  the known English kv-r015) plus the known English kv-r015 /
  kv-r033. Answers stay English (verbatim KB quotes) — L16
  stays open for answer language.

### 7B Sourced Tamil Nadu minimum-wage data — DONE (21 Nov 2026)

- Central-sphere rates ingested from the Labour Bureau VDA order
  (File No. 6/1/2026-VDA, 30 Sep 2026, rates from 1 Oct 2026):
  snapshot v2 (1,048 chunks) adds 8 wage chunks — 7 scheduled
  employments + 1 scope/areas chunk. Numbers read by OCR from the
  scanned official PDF, verified two ways (52 sums re-added, 0
  mismatches; cross-checked against three independent readings).
  Data file `data/kv_wage_tables_2026-10.json`, ingester
  `scripts/ingest/wages.py` (fails loudly on bad arithmetic), OCR
  evidence utility `scripts/ingest/ocr_vda_order.py`.
- TN STATE rates are NOT in the KB: the TN Labour Department's
  G.O. PDFs all return 404 (5 tested). TN-specific wage questions
  refuse honestly (kv-x016/x017). Aggregator figures never
  ingested. L18/L39 updated.
- Three real bugs fixed by measuring: the currency-figure pattern
  matched "Sewers," (kv-x016); Tamil/Hindi figure patterns refused
  law questions (kv-r068/r098 — law exclusion added); short wage
  chunks outranked the right chunk (title bonus extended to wage
  chunks, redundant header dropped, Tamil stem added).
- Gold set 173 → 189 cases (+12 wage retrieval, +4 refusal).
  KV eval PASS: profile 1.000, recall@5 1.000, MRR 0.970,
  faithfulness 0.930, refusal 0.947. New known misses kv-r013 /
  kv-r039 (IDF shift below the 0.10 cosine floor — L53, Step 8.1).

### 7C Postgres adapter + migration path — DONE (21 Nov 2026)

- No new adapter was needed: the Phase 6 dialect layer
  (`career_guidance/db.py` + `_migrate_postgres`) already routes
  `DATABASE_URL` to Postgres. Step 7C VERIFIED it live against a
  real local Postgres 16.2 (pgserver binaries run as user
  `nobody` — Postgres refuses to run as root): migrations 1..14
  apply in one call, re-run is a no-op, SQLite agrees; all 10 KV
  tables present; RagStore / EmployerStore / ConsentStore
  round-trip (incl. `RETURNING id` and the audit trail).
- One real bug found + fixed: v2's profiles DDL used unquoted
  `current_role` — a Postgres reserved word (SQLite accepts it
  silently). Quoted in the DDL and the profiles upsert SQL
  (quoted identifiers work identically in SQLite;
  already-migrated DBs unaffected). A guard test scans all
  migration DDL for unquoted reserved words.
- Boundary confirmed + documented (DEPLOY.md §6, RUNBOOK.md
  §3.1): 16 legacy per-feature stores still open SQLite
  directly — a `DATABASE_URL` deployment today runs split-brain
  (core + Kaam-Vaani on Postgres, the rest on SQLite). Full
  cutover needs a store-by-store port; do not point production
  at Postgres until that lands.
- Cutover steps written in RUNBOOK.md §3.1 (provision → driver →
  `DATABASE_URL` → migrate → verify → smoke → rollback); the
  live check is committed as `tests/test_kv_step7c.py` (runs
  when `KV_TEST_POSTGRES_URL` is set). DEPLOY.md §6's stale
  "versions 1..7" fixed to 1..14.

## Step 8A — Engineering depth, first half (execution prompt 8.1–8.5)

**Not the same as plan Stage 8 below** (pilot console / PWA).
Step 8A is the execution prompt's engineering-depth half: ranker,
skill-graph engine, location index, duplicate detection, citation
verifier. 8.6–8.10 follow as Step 8B after 8A is verified.

### 8.1 Ranker — DONE (21 Nov 2026)

- Separate component: `career_guidance/kaamvaani/ranker.py`
  (`RankerConfig` + `MultiCriteriaRanker` + `ScoredItem`) with an
  injectable comparator; weights + zone rules in
  `data/kv_ranker_weights.yaml` (validated: sum 1.0, ≥ 0, no
  unknown features). Aspirational features (distance,
  availability, language) at weight 0 — no per-occupation data
  (L30). `KVScorer` delegates combination + ordering; the
  zone-gap penalty stays in the scorer (domain rule).
  Per-feature contributions (weight x value) reach the API as
  `KVMatch.contributions` (sum = pre-penalty score) with the
  matching frontend type in `lib/api.ts`.
- **Score-identical refactor, proven:** pre-refactor top-5 for
  the five Stage 4 probe profiles captured before the refactor
  and pinned in `tests/test_kv_step8_1.py` (36 tests) — all five
  reproduced exactly. Fairness tests: determinism,
  order-independence (shuffled taxonomy), input isolation (city),
  feature set exactly the five live features, no
  protected-attribute name in ranker/matching source. Finding:
  free-text `income_text` leaks into the base matcher via the
  goals field (~1e-4 score shift — L55, documented, not fixed in
  the refactor).
- **Title-evidence rescue (L53 FIXED):** a top hit with title
  bonus ≥ 0.20 is grounded by its title and waives the cosine
  floor + weak-match rule (`Hit.title_bonus`,
  `TITLE_RESCUE_THRESHOLD`). Faithfulness 0.930 → **0.948**
  (109/115); [en] 0.915 → 0.957; refusal unchanged 0.947.
  Rescues exactly kv-r013 (0.312) + kv-r039 (0.250); nearest
  refusal kv-x009 (0.167) stays refused.
- Measured + REJECTED (EVAL_REPORT.md): margin/ratio gates
  (catastrophic), hybrid-score gates, floor lowering,
  TITLE_BOOST_WEIGHT 0.7/0.8 (faithfulness → 0.887),
  synonym-aware titles (→ 0.922), IDF-weighted titles (no
  change). kv-r056/r086 (car mechanic) resists all three title
  approaches — needs an intent signal or a dense tiebreak.
- Dense calibration (L52): measured in Step 8.1 — see
  EVAL_REPORT.md "Dense embeddings" section.

### 8.2 DAG/Dijkstra skill-gap engine — DONE (21 Nov 2026)

- General engine: `career_guidance/kaamvaani/skillgraph.py`
  (`SkillGraph`: Kahn's topological order with deterministic
  priority + cycle detection, Dijkstra over lexicographic
  `(paid, count)` costs via `heapq`). Proven on hand-made
  graphs where the right answer is known (linear chain, diamond
  with a cheaper branch, free-two-course-path beats paid
  shortcut, cycle detection).
- Production graph from real data only: gap skills + catalogue
  courses (up to 2 candidates per skill, so Dijkstra has a
  free/paid choice); one node per course URL; edges course →
  skill with the course's real cost. Gap skills implied by a
  held skill through DOMAIN_HINTS are dropped as already held.
  **No prerequisite edges** — none exist in the repo (L56);
  plan order is gap-importance order until real data (NSQF)
  lands. Time = course count (A56 — no durations in the
  catalogue). The plan is the union of per-skill cheapest paths,
  not a set-cover optimum (documented).
- Integration: the gap-learning endpoint returns an additive
  `skill_plan` (ordered steps, totals, covered-by-held,
  uncovered with reasons) alongside the unchanged flat
  `learning_path`; frontend type in `lib/api.ts`.
- Measured on the five probe profiles' top matches: coverage
  23/38 (flat) → **28/38** (engine) — demo 5/8→6/8, electrician
  5/7→5/7, tailor 5/6→6/6, driver 3/9→4/9, btech 5/8→7/8; all
  courses free (0 paid); shared courses counted once (btech: 7
  skills via 5 courses). The 10 still-uncovered gaps have no
  curated resource (L32/L56) and are listed, not dropped.
  Engine time 0.36 ms mean per plan. Tests:
  `tests/test_kv_step8_2.py` (20 tests).

### 8.3 — DONE (21 Nov 2026)

- Geohash location index (`career_guidance/kaamvaani/geo.py`):
  base32 encode/decode (verified against the Wikipedia
  reference vector `u4pruydqqvj`), haversine distance,
  `GeohashIndex` (sorted `(hash, item_id)` pairs; radius query
  = bounding-box cell enumeration + binary-search prefix ranges
  + exact haversine filter). City-centre coordinates for the 6
  seed cities in `data/kv_city_coords.yaml` (geocoded 21 Nov
  2026, CITY-level, relevance 100; sanity-checked by distance).
- Integration: `GET /kv/listings?near_city=…&radius_km=…`
  (default 25 km, max 500; unmapped centre city → 400 naming
  the mapped cities; `city` + `near_city` together → 400);
  newest-first order preserved, limit applied after the radius
  filter; frontend `kvPublicListings` params + response echo.
  The index is cached on the store instance, invalidated by
  every listing write (create/update/status/delete/sample
  purge); listings in unmapped cities are excluded from radius
  results but keep the plain city filter (L57).
- Two real bugs found and fixed by measurement: (1) bbox cell
  enumeration missed sliver cells — 13 of 60 random trials
  missed points before the one-cell padding fix (property test
  now 300/300 across two seeds/regions, radii 1–500 km);
  (2) the first precision table (coarse cells, p3 for 50 km)
  pulled ~56% of a 100k table into the filter (1.8x) — retuned
  to cells small relative to the radius.
- Benchmark (50 random queries each, radii 10/25/50 km,
  SYNTHETIC points in a TN bounding box — the seed has only 45
  real listings): 1k — index 2.28 ms vs scan 0.67 ms (0.3x,
  enumeration overhead dominates below ~5k); 10k — 2.09 ms vs
  7.18 ms (3.4x); 100k — 7.13 ms vs 70.70 ms (9.9x). Build:
  8.6 / 86 / 1005 ms. Tests: `tests/test_kv_step8_3.py`
  (20 tests).

### 8.4 — DONE (21 Nov 2026)

- Near-duplicate detection (`career_guidance/kaamvaani/dedup.py`):
  SHA-256 fingerprints over normalised title + city +
  description; a Bloom filter pre-filter (sized for 10k items
  at 1% design FP: 95,851 bits, 7 hashes — a false positive
  costs one dict lookup, never a flag); word 3-shingle Jaccard
  (adaptive size for short texts) at threshold 0.5, tuned on a
  labelled set. `DuplicateIndex` cached on the store,
  invalidated by every listing write; `find_duplicate` now
  takes the description (the router passes it) and returns the
  matched listing. The scam check's duplicate flag message now
  covers near-duplicates; the 25-point weight is unchanged.
- Deliberate behaviour change from Stage 5: the same title with
  a DIFFERENT description is a new opening reusing a title, not
  a duplicate — the old title-only check wrongly flagged it.
  Scope stays same-employer + same-city (L42); cross-employer
  duplication stays an admin judgement.
- Measured on the labelled set (369 pairs: 279 positive from
  mechanical variants of the 45 seed listings, 90 negative
  including same-title/different-description hard negatives;
  no-op variants excluded so recall is measured on changed
  text only): precision **1.000**, recall **0.907** at threshold
  0.5 (F1 0.951). Sweep: 0.3 → R 0.982; 0.4 → R 0.953; 0.6 →
  R 0.832; 0.8 → R 0.405 — precision 1.000 throughout
  (highest negative: 0.111). The 26 misses at 0.5 are heavily
  edited variants (title AND description changed, sim
  0.125–0.5). Bloom FP: 0/10,000 at pilot scale; 0.0095
  measured vs 0.0100 theoretical at the 10k design point.
  Tests: `tests/test_kv_step8_4.py` (16 tests); Stage 5's
  `test_duplicate_detection` updated to the new behaviour.

### 8.5 — DONE (21 Nov 2026)

- Citation verifier (`career_guidance/kaamvaani/citations.py`):
  every answer sentence is checked against its cited chunk by
  token overlap (≥ 0.8 supported; the repo's `tokenize`, so
  plurals match). `answer_question` verifies before returning —
  unsupported sentences are dropped, and if nothing grounded
  remains the answer refuses with reason `"unverified"`. A
  trailing "…" marks the final sentence truncated (reported,
  excluded from the verdict). Every answer carries a
  `verification` summary; refused answers carry None.
- Measured on the 115 gold retrieval cases: **115/115 answers
  verified, 591/591 sentences supported** (support rate 1.000;
  complete sentences 476/476), 0 dropped, 0 unverified
  refusals, 0 answers changed. All 115 answers hit the 600-char
  cap — truncation is the common path, not an edge case. The 6
  unfaithful cases (kv-r015, kv-r033, kv-r056, kv-r059, kv-r086,
  kv-r089) are all verified but not faithful: their answers are
  verbatim from the cited chunk while the chunk is the wrong one
  for the question — grounding is not relevance (L58), and the
  verifier is deliberately NOT a faithfulness fix. Faithfulness
  stays 0.948. Tests: `tests/test_kv_step8_5.py` (14 tests,
  including the gold-set measurement pinned in the suite).

### L39 wage-tables → scam-check wiring — DONE (21 Nov 2026)

- The inherited small item from Step 7: the central-sphere wage
  tables (`data/kv_wage_tables_2026-10.json`) are wired into the
  scam check's pay-plausibility framework (`wages.py` +
  `scam.check_pay_plausibility`). Employment matched by keyword
  phrase (longest wins, word boundaries — "mines" does not match
  "determines"); pay compared against the wide monthly band
  (lowest daily total x 26 to highest daily total x 26).
  Verdicts: below_minimum (best offered pay below every
  central-sphere rate), above_range (informational — lowest
  offered pay above every central-sphere rate),
  within_central_range, or unknown (no employment match, no pay
  figures, or a piece-rate employment, which cannot convert to a
  monthly figure). Advisory only: the verdict never flags a
  listing and never changes the scam score (pinned by test).
  Central-sphere only (L18: TN state rates are absent) —
  "below_minimum" means below the central-sphere band, never
  "below the legal minimum wage for this job". Bands pinned by
  test (construction ₹14,690–₹28,886/mo). The employer status
  endpoint reports the wage scope as `central_sphere`. Tests:
  `tests/test_kv_step8_l39.py` (11 tests).

## Step 8B — Engineering depth, second half (execution prompt 8.6–8.10)

**Not the same as plan Stages 8–10 below.** Step 8B is the
execution prompt's second engineering-depth half: caches, local
LLM provider check, LoRA pipeline, agent trace log, COMPLEXITY.md.

### 8.6 Caches — DONE (21 Nov 2026)

- One LRU core (`career_guidance/kaamvaani/cache.py`: bounded,
  thread-safe, optional TTL, hit/miss/eviction stats) + four
  caches, each keyed by everything that determines its value, so
  a stale entry is unreachable, not merely unlikely:
  translation (raw query; the glossary is process-lifetime, so
  no invalidation is possible), answer/search (RAG router;
  snapshot versions IN the key, so a re-ingest can never serve
  a pre-ingest answer), profile (voice router `/extract`;
  payload + prompt version), LLM result (`CachingCompleter`,
  SHA-256 of system prompt + user content, 1-hour TTL; failures
  never cached). Answer values are deep-copied on write and
  read, so a caller mutating a returned dict cannot poison the
  cache. Cache stats surface on the RAG + voice `/status`
  endpoints.
- Measured (21 Nov 2026, `~/workspace/tmp/kv86_bench.py`,
  snapshot v2, 1,048 chunks, 20 gold questions): raw
  `answer_question` p50 21.8 ms; router `/ask` cold p50 27.4 ms,
  **warm p50 3.6 ms (~7.6x faster on a repeated question)**;
  2 passes over the same 20 questions give 20 hits / 20 misses.
  The cold p95 (734 ms) is the first request building the
  retriever (first build in a fresh process ~4.3 s — sklearn
  warm-up; ~0.7 s warm). LLM cache: 10 identical completions
  make 1 provider call. Honest limit: the translation cache is
  a negligible win in absolute terms (0.019 ms/question cold)
  and is kept because it is free and correct, not because it
  saves real time. All caches are per-process, in-memory (L59).
- Bug found by the tests and fixed in the same step: the
  `CachingCompleter` constructor used `cache or llm_cache`, and
  an empty `LruCache` is falsy (`__len__`), so a fresh cache
  passed in was silently replaced by the shared one — now an
  explicit `is None` check, with the trap documented in the
  code. Tests: `tests/test_kv_step8_6.py` (31 tests, incl.
  LRU eviction order, TTL with an injected clock, thread-safety
  smoke, snapshot-version invalidation, failure non-caching).

### 8.7 Local LLM provider check — DONE (21 Nov 2026)

- **Executed, not just interfaced.** `llama-cpp-python 0.3.37`
  installed (no prebuilt wheel for this platform — compiled from
  source, ~11 min; the first attempt failed because pip unpacks
  in `/tmp`, a 512 MB tmpfs — `TMPDIR` to a workspace dir fixed
  it) and Qwen2.5-0.5B-Instruct Q4_K_M (469 MB) loaded and run:
  load 0.4 s, peak RSS 670 MB at n_ctx 2048, generation
  10.1 tokens/s on 4 CPU threads, full extraction with the
  production prompt 35.9 s (prompt processing dominates).
- New `LlamaCppCompleter` + `LlamaCppProvider` in
  `career_guidance/providers.py`, behind the shared
  `ChatCompleter` interface: lazy import of the optional
  binding, lazy model load on first completion, temperature
  0.0, `ProviderError` on missing package / unset path /
  missing file / empty reply. Factory: `LLM_PROVIDER=llamacpp`
  + `LLAMACPP_MODEL_PATH`; settings `LLAMACPP_N_CTX` (default
  2048 — the production prompt needs ~1440 tokens, so 512
  failed on the real prompt), `LLAMACPP_N_THREADS`,
  `LLAMACPP_MAX_TOKENS`. Setup guide `docs/LOCAL_LLM_SETUP.md`.
- **Honest quality (L60):** with the real prompt the 0.5B model
  follows the JSON schema and gets concrete fields right on
  unseen input (tailor/Salem/10th/₹20k: skills, education,
  city, income all correct) but makes semantic errors
  (`interests` = "job_6_months", `goal_type` = "explore") that
  Pydantic validation does NOT catch. The deterministic
  fallback and the confirm step stay mandatory. **Ollama was
  NOT executed here** — its interface exists and is wired,
  but the server/install/pull were not run in this sandbox.
- Tests: `tests/test_kv_step8_7.py` (19 tests: factory
  selection, stub-module behaviour incl. lazy load + error
  paths, env parsing, and a live test gated on
  `KV_TEST_LLAMACPP_MODEL` that runs the real model with the
  real prompt on a non-example transcript).

### 8.8 LoRA pipeline — DONE (21 Nov 2026)

- **The pipeline, not a trained model.** No GPU exists in this
  sandbox, so no training ran and the notebook was not executed
  — that is stated in the code, the runbook and the notebook
  itself, and no accuracy gain is claimed anywhere.
- Dataset builder (`career_guidance/kaamvaani/lora_data.py` +
  `scripts/build_lora_data.py`): the 55 gold profile cases ->
  TRL messages-format JSONL, **49 train / 6 val** (seed 42,
  deterministic — byte-identical hashes on re-run). Target =
  the deterministic extractor's full 7-field output, validated
  against the gold `expected` (skills as a set, like the KV
  eval); a drifted case is skipped with a reason — 0 skipped.
  Every example is validated before writing (3-turn shape,
  7-key JSON reply, PII safety net) and carries provenance
  (`source`, `gold_case_id`, `language`, `prompt_version`).
  Committed: `training/data/kv_lora_train.jsonl` +
  `kv_lora_val.jsonl` (a test pins them byte-identical to the
  builder's output from the current gold set).
- Deliberate exclusions, documented: retrieval cases stay
  eval-only (training on them would teach ungrounded
  answering); refusal cases are the wrong task shape; seed
  workers have no transcripts (9/10 Tamil — templating
  unverified Tamil would be invented data). The runbook
  (`docs/LORA_RUNBOOK.md`) explains how to grow the dataset
  honestly (more gold cases, human-reviewed 8.9 traces).
- Config `training/lora_config.yaml` (Qwen2.5-0.5B-Instruct
  base — the measured model, r=8/alpha=16, completion-only
  loss, max_length 2048 covering the ~1200-token prompt) +
  notebook `training/train_lora_colab.ipynb` (11 cells, valid
  nbformat 4, all code cells parse; free Colab T4; GPU fail-fast;
  adapter-vs-base val eval with per-field accuracy).
- Bug found by running the builder and fixed in the same step:
  4 cases were first skipped because the builder compared
  skills as an ordered list — the KV eval compares them as a
  set, so the builder now does the same (regression-pinned by
  a test that reorders skills without skipping and changes a
  skill with skipping). Tests: `tests/test_kv_step8_8.py`
  (14 tests; `lora_data.py` at 100% coverage).

### 8.9 Agent trace log — DONE (21 Nov 2026)

- Per-request structured JSON traces
  (`career_guidance/kaamvaani/trace.py`): endpoint, query hash
  (first 16 hex of the SHA-256 — correlation without storing
  text), cache-hit flag, total latency, outcome, and one span
  per stage with its latency + safe detail. Wired into
  `/ask` (translate / retrieve / verify), `/search`
  (retrieve), `/extract` (extract: method + skill count),
  `/matches` (match: returned + top score). Every response
  carries its `trace_id`. Cache hits trace with no spans;
  pipeline errors trace with status "error" and the exception
  still propagates. Gap-learning is untraced by design (a
  deterministic lookup) and 400 client errors are not traced.
- **PII safety by construction:** span details are validated on
  write — forbidden keys (names, phones, raw text, profile
  fields) and values over 500 chars are rejected (the span is
  recorded as an error with a rejection note, never the unsafe
  content). Tests grep recorded traces for the raw question,
  a phone number, the transcript, the profile city/skills and
  the answer text — none of it appears.
- Storage: process-wide `TraceSink` (in-memory ring, default
  200 traces) + optional JSONL file sink (`KV_TRACE_FILE`;
  10 MB/file, 3 files, size rotation). Retention is
  size-bounded, not time-based (L62); the file is the only
  durable copy. Admin-only read API `backend/kv_traces.py`
  (GET /api/v1/kv/traces newest-first, GET /traces/{id} or
  404), mounted when KV_RAG or KV_VOICE is on.
- Bug found by the tests and fixed in the same step: the
  translate span stored `translated.applied` as a boolean —
  it is actually the TUPLE of glossary terms used, so the
  validator rejected it; the span now records
  `applied: bool(...)` + `terms: len(...)`, and the validator
  also accepts tuples of scalars. Tests:
  `tests/test_kv_step8_9.py` (33 tests: deterministic-clock
  spans, PII rejection incl. case-insensitivity, ring
  eviction, file rotation, thread-safety smoke, router wiring
  incl. the 403/404 admin paths).

### 8.10 COMPLEXITY.md — DONE (21 Nov 2026)

- `COMPLEXITY.md` (repo root): Big-O + MEASURED numbers for the
  whole system — retrieval, translation, occupation ranker,
  employer matching, skill-graph engine, geohash index,
  duplicate detection, citation verifier, caches, voice
  extraction, local LLM, LoRA builder, trace log — plus an
  end-to-end latency table, a per-process space summary, a
  "what breaks first at scale" list, and a measurement log
  (every number traced to its benchmark/eval run and date).
  Nothing estimated: where two runs disagreed, both are shown
  and the spread is explained.
- New measurements in this step (`~/workspace/tmp/kv89_bench.py`):
  trace overhead is unmeasurable (−0.21 ms mean delta, inside
  run-to-run noise; 747-byte mean trace JSON; 0.0013 ms per
  sink store); `/extract` deterministic p50 6.79 ms;
  `/matches` p50 376.57 ms — the slowest endpoint (the base
  MatcherV2 pass over the full taxonomy runs once per call);
  retriever build 1,728 ms with ~33 MB peak-RSS rise
  (transient fit allocations included).
- `ARCHITECTURE.md` §7 now points at `COMPLEXITY.md` as the
  consolidated measured reference; `REPO_MAP.md` lists it.
  No code changed in this step (docs only).

### L55 fixed (Step 8B, after 8.10)

- The free-text `income_text` no longer leaks into matching
  scores: `_base_scores` passes `goal_type` only as the base
  matcher's goals string (income stays scored by the dedicated
  income-fit component). Pinned by
  `test_income_text_does_not_leak_into_base_scores` — it
  paraphrases the income wording with the same parsed number
  (changing only the digits never leaked: the semantic
  tokenizer drops numbers). The pin fails on the old code
  (max base-score diff 0.00114 on a paraphrase) and passes on
  the new code. The 8.1 golden top-5s were re-baselined with
  an explanatory comment: order identical in all five probe
  profiles, scores moved by <= 0.0004 except btech / Computer
  Programmers (−0.0058, a semantic-scorer renormalisation
  effect). KV eval re-run: PASS, metrics identical.

## Stage 7 — Rights/scam RAG assistant, safety guardrails, escalation ✅ DONE 21 Nov 2026 (execution prompt Step 9.1)

- Voice Q&A over the RAG base ("is this job real?", "minimum
  wage?", "my employer hasn't paid me") — grounded answers with
  citations, "I don't know" when context is insufficient.
- Safety: prompt-injection defence (listing text = untrusted data),
  PII redaction in logs, refusal/redirect rules (medical, legal
  beyond sourced info, unsafe), escalation to human coordinator /
  sourced helplines on exploitation, unpaid wages or distress.
- Bias/fairness check documented: never filter/rank by caste,
  religion, gender, region of origin.
- **Acceptance (F6):** gold-set refusal correctness + faithfulness
  measured; escalation paths tested; injection attempts fail.
- **Delivered (Step 9.1):** `career_guidance/kaamvaani/rights.py`
  (topic-restricted `answer_question` over rights/scam/wages/
  employment, 56 chunks; scam-intent detection; escalation ONLY
  from `data/kv_helplines.json` — 1930 cybercrime via PIB 6 Apr
  2022, 1514 NCS via the KB's ncs.gov.in chunk), router
  `backend/kv_rights.py` (status/ask, own answer cache + trace,
  behind `KV_RAG`), plain functional `/rights` page + landing
  link (design agent owns the polish). 31 tests
  (`tests/test_kv_step9_1.py`): topic restriction pinned (an
  occupation question answers on the open path, refuses here),
  escalation pinned (scam question → 1930; refused scam question
  still escalates; non-scam → none), no-invented-numbers pin
  (escalation numbers ⊆ file). Limits: L63 (English answers,
  English-only scam keywords, 2 helplines).

## Stage 8 — Pilot/institute console, PWA/offline, SMS/WhatsApp share

- Console (builds on the Phase 4 institute portal): bulk worker
  onboarding, employer verification, metrics (profiles, matches
  viewed, consents, interviews, hires, 30/90-day retention, scam
  reports) + CSV export.
- PWA: extend the existing service worker (caching strategy,
  offline action queue + sync); SMS/WhatsApp share of matches
  (provider via env var, feature-flagged; share links work without
  a provider).
- **Acceptance (F8/F9):** console metrics match stored data; offline
  queue syncs on reconnect; share works with no provider configured.
- **Console DONE (Step 9.2, 21 Nov 2026)** — `backend/kv_pilot.py`
  behind `KV_PILOT`, coordinators + admins only: bulk onboarding
  (100 rows max, `user_id` or `phone` resolution, no account
  creation — A63), coordinator review queue + endorse (same store
  methods + audit as the admin console), metrics from stored rows
  only + CSV export (metrics + roster), worker roster. Metrics
  asserted against seeded rows in `tests/test_kv_step9_2.py`
  (28 tests). One acceptance gap, documented as L65: "matches
  viewed" is NOT tracked — the voice flow never persisted views,
  so the console reports the stored funnel (shortlists + contact
  requests) instead. PWA/offline + SMS/WhatsApp share still open
  (WhatsApp flagged, L64 — needs the owner's phone pairing).

## Stage 9 — Video skill-check prototype (honest testing) ✅ DONE 21 Nov 2026 (execution prompt Step 9.3)

- 30–60 s task video → frame/audio analysis → indicative result
  with confidence and limits. Labelled "indicative, not a
  certificate". Coordinator-led practical check offered as the
  reliable alternative. Object storage only for clips, short-TTL
  auto-delete.
- **Acceptance (F7):** accuracy tested honestly and reported in
  `TESTING.md`; never claimed as solved.
- **Delivered (Step 9.3):** `career_guidance/kaamvaani/video.py`
  (`check_clip`: ffprobe + 6 ffmpeg frames + PIL brightness/blank/
  motion) + `backend/kv_video.py` (behind `KV_VIDEO_CHECK`,
  signed-in, 5/hour/user, 50 MB cap, temp file deleted in a
  `finally`). The verdict is CLIP VALIDITY only — no skill
  assessment exists, confidence is LOW by design, every response
  carries "Indicative only — not a certificate" + the limits text.
  Thresholds chosen, not tuned (A64/L66). NO clip storage and NO
  result persistence — stricter than the plan's short-TTL
  auto-delete, because there is no object storage on the free
  tier. Tested ONLY on synthetic ffmpeg clips (16 tests in
  `tests/test_kv_step9_3.py`); no real task recording has ever
  been run through it. Plain functional `/video-check` page
  (design agent owns the polish), no landing link.

## Stage 10 — Hardening: security, load, accessibility, docs, seed data

- OWASP Top 10 review, dependency audit, rate limits, upload limits
  + scanning, secure headers, CSRF/CORS review; load test (k6/Locust)
  at pilot scale; accessibility audit (axe, Lighthouse ≥90 mobile
  where achievable); performance pass (bundle, latency).
- Docs complete: README, ARCHITECTURE.md, API docs (OpenAPI),
  PROMPTS.md, SOURCES.md, EVAL_REPORT.md, TESTING.md, COMPLIANCE.md
  (DPDP items flagged for legal review), LIMITATIONS.md,
  ASSUMPTIONS.md, RUNBOOK.md.
- Seed data complete: 40 listings, 10 sample workers, 5 employers,
  3 coordinators, 5 fake listings (all "sample data").
- **Acceptance:** checklists in master prompt §7 complete or
  explicitly listed as limitations.
- **Delivered (Step 9.4, 21 Nov 2026 — security half):** rate limits
  on every KV POST (`backend/kv_ratelimit.py`); data deletion
  (`DELETE /api/v1/kv/me/data` + `delete_all_kv_data`, wired into
  self-delete and admin delete); dependency audit (pip-audit 9 → 4
  vulns, 2 accepted with reasons); OWASP Top 10 review in
  docs/SECURITY.md; `Permissions-Policy` mic fix (`microphone=(self)`,
  was blocking the voice flow); L50 closed (index verified by test);
  L49 retention policy recorded (365 days, no automated prune).
  **Still open in Stage 10:** load test (Step 9.5), docs set
  (Step 9.6), accessibility audit (no automated axe/Lighthouse run
  on KV screens — documented as a gap, L68).

## Stage 11 — Deploy, smoke tests, demo rehearsal, pitch assets

- **Needs the owner's explicit approval first.** Deploy to staging
  then production (Vercel + Render); smoke tests; demo rehearsal run.
- Pitch assets: 3-min demo script (+ 90-s backup), pitch deck
  outline (10–12 slides + speaker notes), 30 hard judge Q&As,
  "real vs prototype" table, one-page impact measurement plan
  (baselines/targets, no outcomes claimed as achieved).
- **Acceptance (§11 Definition of Done):** full voice journey works
  in Tamil/Hindi/English on the deployed URL on a low-end Android;
  F1–F10 pass automated tests; eval thresholds met and reported;
  no secrets in the repo; all docs + pitch assets exist.

## Risk register

| # | Risk | Impact | Mitigation / owner |
|---|---|---|---|
| R1 | Free-tier Render wipes SQLite on deploy (ephemeral FS) | Pilot data loss | Confirm live plan in Stage 1; Postgres (Supabase/Neon free tier) before any real pilot |
| R2 | No LLM/STT/TTS keys available | LLM quality unmeasurable; features must work offline-first | Provider interfaces + deterministic fallbacks; flag keyed eval as pending |
| R3 | RAG sources not fetchable (NSQF QPs, DGT syllabi, TNSDC portals, PDFs behind logins) | Thin knowledge base | Per-source fetchability in SOURCES.md; use only what is allowed; O*NET + public pages first |
| R4 | Browser STT accuracy in Tamil dialects / code-mixed speech unmeasured | F1 fails for real users | Gold set incl. noisy/code-mixed queries; typed fallback always available; measure, don't assume |
| R5 | Employer verification at scale needs humans | Fake employers slip through | Queue + rule checks + admin review; honest "prototype" labelling; no auto-verify |
| R6 | `render.yaml` (autoDeploy true, starter) vs live service state may differ | Wrong deploy assumptions | Confirm live state before Stage 11; never edit render.yaml without approval |
| R7 | Coverage gate ≥85% + eval gate in CI | New code must be tested or CI goes red | Tests written with every stage; no stage closes with red tests |
| R8 | Scope creep (11 stages, 10 features, finale 27 Dec) | Half-built breadth instead of working depth | Stages 0–6 first + checkpoint; honest LIMITATIONS.md for anything cut |
| R9 | LaundryAI deadline (~4 Dec) overlaps the prototype window | Owner bandwidth | Build stays autonomous; owner time needed only for approvals/taps |
| R10 | DPDP compliance is not legal advice | Compliance gaps | COMPLIANCE.md flags items for legal review; least-data design throughout |
