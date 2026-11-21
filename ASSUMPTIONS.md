# ASSUMPTIONS — Kaam-Vaani build

Recorded per the master prompt §0: assume, record, continue. Each entry
names the stage that made it and what would change it. Challenged
assumptions are struck through, never deleted.

## Stage 0 (20 Nov 2026)

- A1. The `career-guidance-live` clone (branch `upgrade/final`, HEAD
  `c7cc847`) is the current base; the content diff vs `origin/main`
  is only 2 lines of CI config. If a later fetch shows main has moved
  materially, the `kaam-vaani` branch rebases before any push.
- A2. No new API keys will be available during this build (standing
  rule). Every feature is therefore designed offline-first with a
  provider interface for later keyed use. If a key becomes available,
  the LLM/STT/TTS paths get a keyed eval run before any quality claim.
- A3. The existing migration runner (`career_guidance/migrations.py`,
  v1–v10) is used instead of Alembic: it is tested, Postgres-aware,
  and already owns the live schema. Alembic would be a second source
  of truth and a data risk.
- A4. RAG retrieval starts with BM25 + TF-IDF over chunks stored in
  the relational DB (zero new dependencies, works on SQLite and
  Postgres). Dense embeddings (multilingual-e5 class, local) and
  pgvector are optional second retrievers, adopted only if the Stage
  2 eval shows they beat TF-IDF on the gold set.
- A5. Employer phone verification uses Firebase Phone Auth if the
  owner enables phone sign-in in the Firebase console (Spark plan:
  10 verifications/day free). Until then, verification is email +
  admin review. No SMS provider is purchased.
- A6. The live Render service is understood to have autoDeploy OFF
  (manual deploys) and may be on the free tier (ephemeral SQLite),
  contradicting `render.yaml` (`autoDeploy: true`, starter + disk).
  The live state is confirmed before Stage 11; `render.yaml` is not
  edited without owner approval.
- A7. The Tamil/Hindi translations in the voice UI (Stage 3
  groundwork, `i18n-extra-{hi,ta}.ts`) are straightforward
  translations by the build agent, not reviewed by a native speaker.
  They are flagged for review by a Tamil/Hindi speaker before the
  pilot; the UI never claims certified translations.
- A8. The voice-only v1 code committed as Stage 3 groundwork
  (`/voice`, `lib/speech.ts`, `lib/voice-profile.ts`,
  `lib/voice-vocabulary.ts`) is the browser-native fallback the
  master prompt §4.2 requires. Stage 3 reworks it into the guided
  4–6 question flow; the typed fallback and vocabulary stay.
- A9. "Minimum wage" answers come only from sourced RAG chunks
  (official pages). Where no sourced figure exists for a
  state/role, the assistant says it does not know and points to the
  coordinator — it never quotes the static `_INDIA_BANDS` estimates
  in `market.py` as wages.
- A10. One role per account for the prototype: a user is a worker,
  employer, coordinator, or admin. (The institute pattern already
  allows a separate `institute_role`; Kaam-Vaani roles extend
  `users.role`.) Real users who are both worker and employer would
  need two accounts until a later multi-role design.

## Stage 1 (20 Nov 2026)

- A11. Feature-flag defaults are ON in dev and OFF in production,
  on both sides (backend `KV_*` env vars, frontend `NEXT_PUBLIC_KV_*`
  baked at build time). Explicit env always wins. The production
  default means a fresh production deploy ships Kaam-Vaani dark until
  each feature is staged deliberately.
- A12. OTP scaffolding is storage + documentation only: migration v11
  adds `phone_e164` / `phone_verified_at` to `users` and
  `UserStore.set_phone_verified()` records a number Firebase has
  already verified. Firebase does the OTP check; the backend never
  sends or checks codes. The `/api/v1/auth/firebase` login endpoint
  still requires an e-mail address — phone-first login (a phone-only
  account with no e-mail) is a Stage 5 design decision, not Stage 1.
- A13. Role deps match their role exactly: `employer_user` accepts
  only role `employer`, `coordinator_user` only role `coordinator` —
  admins do NOT pass them (one role per account, A10). Admins reach
  employer/coordinator data through admin routes.
- A14. Role values are enforced server-side only
  (`users.VALID_ROLES` + `validate_role()`). SQLite cannot add a
  CHECK constraint via ALTER TABLE, and a users-table rebuild was
  judged not worth the data risk for a value the code validates at
  every write path (admin endpoint pattern + `set_role`).
- A15. The SPA catch-all 404s as JSON for unmatched `api/*` paths
  (Stage 1 fix). Previously it served 200 HTML for any unmatched
  path, which would have masked a flag-off kv route as "up" wherever
  `frontend/out` exists (local builds, Docker, Render).

## Stage 2 (20 Nov 2026)

- A16. The backend deterministic extractor
  (`career_guidance/kaamvaani/extract.py`) is a server-side mirror
  of `frontend/lib/voice-profile.ts`, NOT a byte-identical copy.
  Known parity gaps: word boundaries are Unicode-mark-aware on the
  backend (the frontend check is letters/numbers only, so the
  Devanagari alias "कर" could false-positive inside "नौकरी" there);
  education and income parsing have native-script (Devanagari/Tamil)
  extensions the frontend lacks; city matching accepts Hindi/Tamil
  postpositions ("Chennai mein", "Salem la"). The two paths share
  ONE vocabulary — `data/voice_aliases.yaml` (spoken-form skill
  aliases) and `data/kv_cities.yaml` (155 cities, pinned to the
  frontend CITIES list by a test) — so they agree on what a skill
  or city is even where the matching rules differ.
  (Stage 3: these gaps are closed — see A26. The verb-form gap
  in L20 remains.)
- A17. The RAG answer is extractive, not generative: the top
  retrieved chunk is quoted verbatim (truncated to 600 chars), or
  the question is refused. With no LLM in the loop, the answer
  cannot add words the knowledge base never said — which is why the
  faithfulness check is a citation check, not an LLM-as-judge score
  (the master prompt §5.6 mentions both; Stage 2 implements the
  citation check only).
- A18. Retrieval tuning constants are measured on the 113-case gold
  set and documented in `EVAL_REPORT.md` (title-bonus blend
  coverage 0.75 / purity 0.25 at weight 0.5, subordinate penalty
  0.3, topic-split cosine floors 0.10 occupation / 0.07 web-wiki,
  `WEAK_COSINE` 0.10 + two-term rule, stopword list). They are
  fitted to this gold set — a bigger or different gold set may move
  them, and the eval gate exists to catch that.
- A19. O*NET occupation documents say "Preparation level: N", not
  the O*NET label "Job Zone: N". The label injected the word "job"
  into all 974 chunks (df 95%), where it matched every job-related
  query equally and drowned the real signal (measured).
- A20. Wikipedia is a FALLBACK source only, used where the official
  source is unfetchable (HTTP 403, connection refused, or a JS
  shell). It is openly licensed (CC BY-SA 4.0) and every chunk
  carries its source + fetch date, so a stale or wrong figure is
  traceable. Statutory figures from Wikipedia (EPF/ESI ceilings)
  are ingested as-is; minimum-wage figures are never taken from
  Wikipedia — no fetchable source carries them, so specific wage
  questions are refusal cases.
- A21. Migration numbering: the RAG chunks table is v12; the
  employers table planned for Stage 5 moves to v13
  (`docs/KAAM_VAANI_PLAN.md`, Stage 2 note). Migration tests use
  `LATEST_VERSION`-based assertions (converted in Stage 2) so the
  next migration does not churn four test files.

## Stage 3 (20 Nov 2026)

- A22. Model routing (master prompt §5.5b): the single configured
  completer IS the cheap/fast tier — there is no second, larger
  model to route to, so no two-model router is built. Building one
  with the same provider on both sides would fake a routing
  decision. If a second provider is configured later, the router
  decision is revisited.
- A23. Guided extraction uses question context: the per-question
  answers are extracted with the question they answer (a bare
  "Madurai" to the city question counts, education/income are
  parsed from their own answers, skills are unioned, the goal
  answer wins over a goal word elsewhere). Implemented in both the
  backend (`extract_profile_guided`) and the frontend offline
  fallback (`extractProfileFromAnswers`), kept in parity.
- A24. The client holds the session (sessionStorage) and round-trips
  it through POST /confirm; the server stores no session and no
  transcript. The client mirrors the `extracted` transition locally
  after /extract (state "confirm") and mirrors `confirm`/`decline`
  locally when the server is unreachable. The server re-validates
  every transition it receives, so a client that jumps the flow
  gets a 400 — the local mirror is a UX convenience, not a trust
  boundary.
- A25. Language is chosen once on the greet screen and kept for the
  whole flow (the state machine's `set_language` is a one-time
  transition). Changing language mid-flow is not supported in
  Stage 3 — a user who picks the wrong language restarts from the
  greet screen ("Start fresh").
- A26. A16's parity gaps are CLOSED in Stage 3, except the verb-form
  gap (L20). The frontend extractor now matches the backend on
  mark-aware word boundaries (the Devanagari alias "कर" no longer
  false-positives inside "नौकरी"), Devanagari/Tamil education and
  income parsing, and Hindi/Tamil city postpositions plus
  native-script substring matching (`CITY_ALIASES`, generated from
  `data/kv_cities.yaml` by `scripts/gen_voice_vocab.py`).
  Digit normalisation before education matching was added to BOTH
  extractors (a Devanagari-digit class number like "१२वीं" now
  matches). The KV eval was re-run after the change — all metrics
  unchanged (profile 1.000, recall@5 0.954, faithfulness 0.907).

## Stage 4 (20 Nov 2026)

- A27. Scorer weights are measured on 5 probe profiles, not a
  tuned model: skill 0.30, title 0.40, base 0.10, zone 0.10,
  income 0.10. The probes are the Stage 3 demo profile
  (farming/computer, 12th pass, Madurai, ₹15,000/mo), an
  electrician, a tailor, a driver and a high-income B.Tech
  profile. Zone filter slack is 1.0 job zone; zone-gap penalty
  0.15/zone, capped at 0.5. The weights are a starting point —
  a larger probe set may retune them, but any change re-runs the
  Stage 4 scorer tests (demo top-1, electrician top-1, tailor
  top-1, zone-filter counts).
- A28. `KV_MAP` is tight on purpose: 19 canonicals map to a
  small set of O*NET competencies each. The full YAML `expands`
  list was measured WORSE in probes (generic expansions match
  hundreds of occupations; Plumbers ranked #1 for the demo
  profile). Title matching uses phrase-AND semantics with stemmed
  variant sets, and single-word phrases come from canonical names
  + the transcript ONLY — never from alias words (a "garment
  construction" alias would match Construction Carpenters, "auto
  technician" would match every "* Technicians" title).
- A29. Income fit is a coarse gate on the curated wage seed
  (p50/p75 vs the annualised monthly need → 1.0/0.7/0.4), never
  a wage promise. No occupation carries wage data beyond the seed
  bands; a match that "can pay what you need" means the seed band
  covers the need, not that any employer offers that wage.
- A30. The gap reuses the existing `skillgap.evaluate` engine
  with matched skills rated 5 and missing skills 0 — no invented
  ratings. The learning path reuses `learning.resources_for_gaps`;
  every item carries URL, source, provider and a free flag, and
  the UI shows the free badge from it. Citations come from RAG
  topics "courses" + "skilling", deduped by URL, top 3.
- A31. The matching router shares the `KV_VOICE` flag — no new
  flag for Stage 4. Flag off → the routes are unmounted; for POST
  that surfaces as HTTP 405, not 404, because the SPA catch-all
  in `main.py` is GET-only. The frontend treats 0/404/405 as
  "KV matching unavailable" (A33).
- A32. RAG citations are best-effort: the gap endpoint reads the
  RAG store directly, and a missing/unreadable store yields an
  empty citation list + a warning log, never a 500. The gap and
  learning path are computed even when citations are empty.
- A33. The frontend falls back to the guest `/recommend` endpoint
  ONLY on `ApiError` status 0/404/405 from `/kv/matches`. A 400
  (wrong state, bad profile) is shown to the user, never hidden
  behind the fallback — silently falling back would hide a real
  flow error.
- A34. "Why it fits" and "Simpler" are template-built from the
  structured match reasons, not LLM-generated — the same reasons
  the scorer returns, rendered as Class 6–8 sentences. Saved
  matches live in sessionStorage only (guest-first): the server
  never sees them, and they do not survive a tab close.

## Stage 5 (20 Nov 2026)

- A35. Registration sets the user's role to `employer`
  immediately; verification gates VISIBILITY, not the role. A
  pending employer can create listings (they sit pending) but
  nothing reaches workers until both the employer and the
  listing are admin-verified. This keeps the flow usable while
  review is pending, and the admin queue is the only gate that
  matters.
- A36. Phone verification is a Firebase ID-token exchange: the
  client links a phone via Firebase Phone Auth, then posts a
  fresh ID token to `/employers/mine/verify-phone`. The server
  accepts it only when the token's e-mail matches the signed-in
  session user, `email_verified` is true, and the token carries
  a `phone_number` claim.
  Phone sign-in must be enabled in the Firebase console first
  (owner step, L38) — until then the endpoint returns 503 and
  the UI says so.
- A37. Pay plausibility is framework-only: the scam check
  returns `pay: {status: "unknown", reason: ...}` because no
  fetchable official minimum-wage source exists (L18/L39).
  The interface (`check_pay_plausibility`) is ready to take
  sourced figures when one is found — no invented wages, ever.
- A38. Three open reports auto-flag a listing (the third
  report's response says so). Auto-flag is a review trigger,
  not a verdict: the listing leaves the public feed and waits
  in the admin queue; upholding a report flags the listing,
  dismissing all its reports restores it to pending.
- A39. Editing a verified listing returns it to pending
  (verified → pending on edit). The old verified text stays
  visible to workers only until the edit lands — after an edit
  the listing is invisible until re-reviewed, so an employer
  cannot bait-and-switch a verified job.
- A40. Seed employers/listings are labelled `is_sample` and
  reviewed_by "seed-script". The 5 fake listings are flagged by
  the same rules workers are protected by (scores 70–100); the
  seed script exits 2 if any fake scores below the flag
  threshold, so a rules regression fails the seed loudly.
- A41. The final scam score is `max(rules_score, llm_score)`.
  The LLM can only raise the score, never lower it — a
  confident LLM must not overrule a deterministic fee-demand
  signal, and a missing/failed LLM degrades to rules-only with
  `llm_status` recorded on the check.
- A42. The coarse pay sanity bounds (below ₹1,000/mo and above
  ₹1,50,000/mo) are heuristics, not wage judgements: they
  catch obvious typos and bait, not underpayment. Real wage
  plausibility waits on sourced minimum wages (A37).
- A43. Phone binding is token-validity only until account
  linking exists: the server trusts the Firebase token's
  `phone_number` claim (Firebase verified it by SMS), but the
  number is not yet linked to the app account as a second
  factor — it is a verification badge on the employer profile,
  not a login method.
- A44. Worker profile skills are normalised to taxonomy
  canonicals at save (`clean_worker_skills` — the same
  canonicalisation the listing side uses), so a voice-confirmed
  skill ("electrical technician") and a listing requirement
  ("electrical") meet on one name. Unknown terms are preserved
  verbatim. The voice session in sessionStorage keeps the
  original wording; the server-side shareable copy is the
  normalised one.
- A45. Consent is per-employer, not per-listing: granting for
  one listing shares the profile with that employer for every
  listing they match against while the consent is active. The
  listing id on a grant is "granted from" context only.
- A46. Granting consent to a not-yet-verified employer is
  allowed — access is gated at match time (verified employer +
  verified listing), so an early grant becomes usable the
  moment the employer verifies, without the worker re-granting.
- A47. A shortlist entry survives a later revoke but shows no
  fields: the employer keeps the bookmark (and the fact that
  they shortlisted this worker), the data disappears.
- A48. Hire outcomes may be reported after a consent ends
  (they require a consent RECORD, any status) but never about
  a stranger — an employer cannot report outcomes for a worker
  who never shared with them.
- A49. The retention rate is `null` until at least one day-30
  or day-90 follow-up is reported — never 0% by default. An
  unreported follow-up is missing data, not a lost job.
- A50. The candidate scorer reuses Stage 4's matcher machinery
  deliberately, including its limits: the title component is
  0.0 for the electrician case (no shared-stem matching in the
  proven matcher) and the skill component carries the trade
  match. No new matcher was invented for Stage 6.
- A51. `contact` shares the account e-mail plus the verified
  phone only — an unverified phone is never shared, and the
  e-mail shared is the sign-in e-mail (magic-link accounts
  have no separate contact e-mail).
- A52. Multilingual retrieval is glossary query translation
  (Step 7A): a Tamil/Hindi question's content words are mapped
  to English via a static bilingual glossary
  (`data/kv_glossary.yaml`), longest phrase first, Latin tokens
  passing through, unmatched non-Latin tokens dropped. English
  queries are returned unchanged, so the English retrieval path
  is byte-identical. Answers stay English (verbatim KB quotes).
- A53. Dense fusion uses reciprocal rank fusion with k=60 over
  the FULL hybrid and dense rankings (no top-N truncation before
  fusing — a chunk at rank 21 in both lists outranks a chunk at
  rank 1 in one). RRF sets the ORDER; each hit keeps its hybrid
  score (the refusal gates still read hybrid evidence) and gains
  its dense cosine; the cosine gate reads max(hybrid, dense).
- A54. Central-sphere minimum-wage figures come from the Labour
  Bureau VDA order (File No. 6/1/2026-VDA, 30 Sep 2026, rates
  from 1 Oct 2026), a scanned PDF read by OCR and verified two
  ways (all 52 printed basic+VDA=total sums re-added, 0
  mismatches; all totals cross-checked against three independent
  readings of the same order). Monthly figures are daily rate ×
  26 working days — a conversion shown as arithmetic in the
  chunk, not printed in the order. The ingester fails loudly on
  bad arithmetic. TN state rates are NOT covered (L18).
- A55. The Postgres path is verified against PostgreSQL 16.2
  (local pgserver, 21 Nov 2026): migrations 1..14, the core
  store and all Kaam-Vaani stores. SQLite stays the local-dev
  default; `DATABASE_URL` selects Postgres. The v2 profiles DDL
  quotes `"current_role"` (a Postgres reserved word) — quoted
  identifiers work identically in SQLite, so the shared DDL/SQL
  stays portable. Legacy stores are SQLite-only (L54).
- A56. (Step 8.2) One course = one unit of learning effort in
  the skill-gap path engine. The learning catalogue carries no
  durations or difficulty levels (verified: no duration /
  difficulty key on any of the 62 resources), so the spec's
  (time, cost) Dijkstra weights are (course count, paid count)
  — both measured from the catalogue (the free flag is real
  data: 58 free, 4 paid), neither invented. When durations land
  in the catalogue, the edge weights change and this assumption
  goes away; the engine itself is weight-agnostic.
- A57. (Step 8.3) A listing's location is its city's centre.
  Listings carry a city name only (no street address), so the
  radius filter measures city-centre to city-centre distance —
  approximate by design. A worker in Madurai searching 50 km
  sees Virudhunagar (41.7 km) but not Dindigul (51.5 km); the
  boundary is a city-centre boundary, not a door-to-door one.
  City coordinates come from the map geocoder (21 Nov 2026,
  CITY-level matches, relevance 100) and live in
  `data/kv_city_coords.yaml` — never from memory. When listings
  carry real addresses, the index takes them without a design
  change (it indexes points, not cities).
- A58. (Step 8.6) A cache entry is keyed by everything that
  determines its value. Translation is a pure function of the
  query within a process (glossary loaded once); the answer
  cache keys on the snapshot versions, so a re-ingest can never
  serve a pre-ingest answer; the profile cache keys on the
  request payload plus the extraction-prompt version (the router
  owns one fixed completer and the process vocabulary, where
  that key is complete); the LLM cache keys on (system prompt,
  user content) with a 1-hour TTL. Provider/model settings are
  fixed per process, so a cached completion cannot come from a
  different model than the live one — except a model swapped
  behind the same URL without a restart, which the TTL bounds
  to one hour.
- A59. (Step 8.7) A local LLM is an OPT-IN provider, never the
  default: the app ships offline-first and `LLM_PROVIDER=llamacpp`
  (with `LLAMACPP_MODEL_PATH`) or `=ollama` selects it. The
  measured model is Qwen2.5-0.5B-Instruct Q4_K_M (469 MB, ~670 MB
  peak RSS at n_ctx 2048); the default context is 2048 because
  the production profile-extractor prompt needs ~1440 tokens.
  Model files are never committed to the repo. Any provider
  failure falls back to the deterministic offline path exactly
  as the hosted providers do.
- A60. (Step 8.8) LoRA fine-tunes profile extraction ONLY. The
  retrieval cases are eval-only by design (training on them
  would teach ungrounded answering, against the grounded RAG
  design); the training target is the deterministic extractor's
  output, validated against gold — the fine-tune teaches the
  model to imitate the deterministic path, not to invent a new
  one. Model files and adapters are never committed to the repo.
- A61. (Step 8.9) A trace identifies a request by the hash of
  its question/transcript (first 16 hex of SHA-256), never by
  the text itself, and span details carry only counts, scores,
  IDs, flags and short labels. The trace sink is process-wide
  and shared by the RAG, voice and matching routers; the admin
  traces endpoint is the only read path, and it requires the
  admin dependency. Tracing is best-effort observability: a
  tracing bug degrades the trace, never the request.
- A62. (Step 9.1) The rights assistant answers from the rights
  topics only — rights, scam, wages, employment (56 chunks) — and
  shares the KV_RAG flag with the main RAG: it is a restricted
  view of the same knowledge base, not a second one. Escalation
  quotes ONLY numbers from data/kv_helplines.json, each verified
  against the official source it cites; the file is the single
  source of truth for helpline numbers, and a number not in it
  can never reach a worker. Escalation appears on scam-intent
  questions or a scam-topic top chunk — including on refusals,
  where the worker needs the helpline most.
- A63. (Step 9.2) Bulk onboarding assumes the worker already has
  an account: a row resolves by `user_id` or by `phone` (E.164
  lookup on the users table, normalised by `normalise_phone` —
  bare 10-digit Indian mobile or 91+10 digits become +91; anything
  else passes through and misses rather than being guessed). No
  account is created by onboarding, and a row with no resolvable
  account fails with a clear reason. The coordinator owns account
  creation (workers sign up on their own phones first).
- A64. (Step 9.3) The video check assumes the clip is a genuine
  recording of the worker doing the task — it can only verify the
  recording is watchable (right length, visible, moving), not
  whose hands are in it or whether the task was done well. The
  thresholds (dark < 20, blank < 5, static < 2.0, majority of 6
  frames) are CHOSEN, not tuned: no labelled task clips exist to
  tune against, so the numbers are documented as judgement calls
  and the verdict stays "indicative, not a certificate".
- A65. (Step 9.4) Rate limits are per-process in-memory friction,
  not a hard abuse boundary: a multi-worker deploy has one budget
  per worker, and the per-IP key trusts the first X-Forwarded-For
  entry (spoofable). True protection belongs at the platform edge.
  Admin/coordinator-only endpoints are deliberately unmetered
  (authenticated, attributable, low volume).
- A66. (Step 9.4) Deletion anonymises hire outcomes with a
  one-way tombstone (deleted-{sha256(user_id)[:12]}) rather than
  deleting the rows, so aggregate retention stats stay valid; the
  consent audit trail is never deleted (append-only consent
  evidence, 365-day retention policy recorded in COMPLIANCE.md
  §4a, no automated prune).
