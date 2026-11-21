# LIMITATIONS — Kaam-Vaani build

Honest list of what is prototype-only, not built, or not yet proven.
Updated at every stage. Anything here must also be labelled in the UI
or pitch where a user or judge could mistake it for a finished feature.

## Stage 0 (20 Nov 2026) — known from the start

- L1. **No LLM/STT/TTS keys.** All intelligence runs on the offline
  matcher, deterministic rules, TF-IDF retrieval and the browser's
  Web Speech API. No LLM-quality claim (extraction accuracy,
  faithfulness, answer quality) can be made until a keyed eval run.
- L2. **Browser speech recognition is not on-device.** Chrome's
  SpeechRecognition transcribes via Google's servers. The UI says so
  (privacy note on `/voice`); the app never claims "nothing leaves
  the device" and stores no audio.
- L3. **No employer verification humans.** The prototype provides
  the verification queue, rule checks and admin review UI. Real
  verification of real employers needs people and a process that do
  not exist yet.
- L4. **RAG sources may be thin.** Several planned sources (NSQF
  qualification packs, DGT syllabi, TNSDC course data) sit behind
  portals or PDFs that may not be legally/technically fetchable.
  Stage 2 documents per-source fetchability; the knowledge base
  ships with what is actually ingestible, nothing invented.
- L5. **Tamil/Hindi UI strings are unreviewed translations**
  (see ASSUMPTIONS.md A7). Flagged for native-speaker review before
  any pilot.
- L6. **Video skill-check is experimental by design** (Stage 9).
  It will be labelled "indicative, not a certificate" with honest
  accuracy testing; the reliable path is a coordinator-led practical
  check.
- L7. **Free-tier hosting limits.** Render free tier sleeps after
  idle and (if live is free-tier) wipes SQLite on deploy; Vercel
  Hobby and Firebase Spark have their own caps. Pilot scale needs
  the Postgres decision (Stage 1) and a cost note (Stage 10).
- L8. **OTP login depends on the owner** enabling phone sign-in in
  the Firebase console. Until then, employer verification is email
  + admin review.
- L9. **Demo/seed data is sample data.** All seeded listings,
  workers, employers and coordinators are labelled as such in the
  UI and are not real jobs or people.

## Stage 1 (20 Nov 2026)

- L10. **The CI Kaam-Vaani eval gate is a no-op until Stage 2.**
  The CI step and the Makefile `eval` target run `eval/run_kv.py`
  only once the script exists; until then they print that the gate
  is pending. This is deliberate — a stub that always passed would
  fake the gate green.
- L11. **Phone-first login does not exist yet.** The login endpoint
  still requires an e-mail address; a Firebase Phone Auth user with
  no e-mail cannot sign in until Stage 5 wires phone-first login.
- L12. **No admin UI for feature flags.** Flags are env vars only
  (Render/Vercel dashboards); there is no in-app toggle, and the
  frontend flags need a rebuild to change.

## Stage 2 (20 Nov 2026)

- L13. **Dense-embedding comparison — MEASURED in Step 7A (21 Nov
  2026), NOT adopted.** `intfloat/multilingual-e5-small` fused by
  RRF (k=60) scores WORSE than glossary-alone on the 173-case gold
  set: faithfulness 0.728 vs 0.942, refusal 0.600 vs 0.933,
  recall@5 0.961 vs 1.000 (see EVAL_REPORT.md for the full table
  and the two mechanisms — sibling confusion at rank 1, dense
  cosines breaking the refusal gates). Dense stays opt-in
  (`KV_DENSE_MODEL`) as a measured component; it is not the
  default and must not be enabled in production without the
  Step 8 calibration (L52).
- L14. **Several planned sources are unfetchable.** PMKVY, TNSDC,
  Naan Mudhalvan, CLC, ESIC, the cybercrime portal, I4C, NCVET and
  Infosec Awareness close the connection or time out; Apprenticeship
  India, EPFO, India Code and PIB return HTTP 403; Skill India
  Digital, e-Shram, the myScheme scheme pages, RBI and CERT-In are
  JS shells with no usable text. Wikipedia fallbacks cover some of
  the gap (see `docs/SOURCES.md` §5); apprenticeship-registration
  and TNSDC questions are refusal cases in v1.
- L15. **e-Shram has zero coverage in v1.** The official portal is
  a JS shell, no Wikipedia article exists, and the one article that
  mentions it does so in a single poorly-written sentence with a
  wrong date (so it was not used). e-Shram questions are refusal
  cases — and the retriever currently answers one wrongly via the
  "card" homonym (kv-x007, see L17).
- L16. **The knowledge base is English-only — retrieval now works
  cross-lingually, answers stay English.** Step 7A (21 Nov 2026):
  Tamil/Hindi questions are translated to English by a static
  glossary (`data/kv_glossary.yaml`) before retrieval, and
  Tamil/Hindi recall@5 went from ~0.10 to 1.000 (EVAL_REPORT.md).
  The answers are still quoted verbatim from the English KB, so a
  Tamil question gets a correct, cited answer in English.
  Translating answers (or ingesting Tamil/Hindi chunks) is open
  work. A Tamil/Hindi word outside the glossary is dropped, not
  guessed — an untranslated question retrieves what its Latin
  tokens match, or refuses honestly.
- L17. **Keyword retrieval cannot resolve homonyms.** "Card" in
  "e-Shram card" matches playing cards (Gaming Dealers, cosine
  0.1624 — higher than several legitimate matches); "fraud" in "how
  to report job fraud" matches the Fraud Examiners occupation
  instead of the reporting guidance (kv-r033). These are
  retrieval-model limits, not data gaps.
- L18. **No Tamil Nadu STATE minimum-wage figures (Step 7B
  update).** Central-sphere rates for 7 scheduled employments ARE
  in snapshot v2 from the Labour Bureau VDA order (File No.
  6/1/2026-VDA, rates from 1 Oct 2026) — but TN state rates are
  not: the TN Labour Department's minimum-wage G.O. PDFs all
  return 404 (probed 21 Nov 2026) and the Commissioner's VDA
  statement is not on the official site. TN-specific wage
  questions (a tailor in Madurai, TN shop workers) are refusal
  cases (kv-x016/x017). Third-party aggregator figures conflict
  (₹8,500/mo vs ₹13,823/mo for the same category) and are never
  ingested.
- L19. **The EPFO article contradicts itself.** It carries two
  different EPF wage-ceiling figures (₹15,000 historical, ₹25,000
  current per the article); whether ₹25,000 is in force or proposed
  could not be verified from a fetchable official source. Both are
  kept with source + fetch date cited — see `docs/SOURCES.md` §5.4.
- L20. **Verb-form skill gaps in the deterministic extractor.**
  "I drive a bus" extracts no skill — bare "drive" would
  false-positive on "pen drive". The occupation phrasing ("bus
  driver") works. Stage 3's LLM extraction is expected to close
  this class of gap; the deterministic extractor stays as the
  offline fallback.
- L21. **Figure questions whose answer is "free" are refused.**
  The figure-grounding rule refuses any wage/fee question whose top
  chunk carries no currency figure — including a question whose
  correct answer is that something costs nothing. Acceptable in v1;
  a "free" answer needs an explicit free-service fact in the base.
- L22. **Faithfulness margin is thin: 0.907 against a 0.90
  threshold (39/43).** One retrieval regression fails the CI gate.
  Any change to retrieval, the snapshot, or the gold set must
  re-run `python -m eval.run_kv`.

## Stage 3 (20 Nov 2026)

- L23. **LLM extraction quality is unmeasured.** No LLM provider is
  configured in the build environment (A2), so
  `extract_profile_llm` is exercised only with mock completers in
  tests. No field-accuracy claim can be made for the LLM path until
  a keyed eval run; the deterministic path is what the Stage 2 gold
  set measures (profile 1.000).
- L24. **Hosted STT/TTS are mock-tested only.** The OpenAI
  Whisper/TTS providers are implemented against httpx
  MockTransport in tests; no live API call has been made (no key).
  The browser Web Speech path is the only live voice path.
- L25. **The mic path is headless-unverifiable.** Microphone input,
  live recognition and speech synthesis cannot be exercised in
  headless CI or the VM's headless Chromium (no mic, no voices).
  The guided flow is verified end-to-end with the typed fallback +
  scripted transcripts; the mic path needs a real-browser check by
  the owner (F1 acceptance).
- L26. **F1's "under 3 minutes" is not timed.** The flow is 5
  questions with one tap each; no timed user test has been run.
  The claim is structural (5 questions, no typing required), not
  measured.
- L27. **Language cannot be changed mid-flow** (see A25). A user
  who picks the wrong language restarts from the greet screen
  ("Start fresh"); the in-progress answers are discarded.
- L28. **The "remember me" opt-in is recorded, not acted on.**
  `VoiceSession.remember` is accepted and carried in the session,
  but no storage beyond the tab exists in Stage 3 — a remembered
  profile is a later stage. The UI offers no remember toggle yet,
  so the flag is always false in practice.
- L29. **L16 is unchanged by Stage 3.** The voice flow handles
  Tamil/Hindi transcripts through the deterministic extractor (the
  gold set covers it), but retrieval stays English-only — a
  Tamil/Hindi question still retrieves nothing (kv-r042/r043).
  Multilingual retrieval is a later-stage decision.

## Stage 4 (20 Nov 2026)

- L30. **Location radius, shift and language filters have no
  per-occupation data.** No occupation carries a location until
  Stage 5 employers exist; there is no shift data and no language
  requirement anywhere in the seed. The city is recorded and shown
  on the matches screen, and the session language drives the UI
  and TTS — but no match is filtered by distance, shift or
  language, and the UI does not claim otherwise.
- L31. **Driver profiles stay mechanic-biased.** Extraction maps
  "driving" to the repair-oriented "automotive" canonical, so a
  driver profile ranks mechanics above Heavy and Tractor-Trailer
  Truck Drivers (#5). Fixing it needs an extraction change, which
  must re-run the KV eval (faithfulness margin 0.907 vs 0.90) —
  out of Stage 4 scope.
- L32. **The learning-resources YAML is IT-heavy.** Non-IT gaps
  (e.g. agriculture) surface generic SWAYAM/NPTEL items, not
  domain-specific courses. The items are real and free, but the
  path is thinner outside IT/computer work.
- L33. **RAG course citations are thin.** Snapshot v1 carries 3
  course chunks + 13 skilling chunks, so citations are often the
  same SWAYAM/NPTEL/NQR items across occupations. Citation
  snippets are NOT shown in the UI — several are homepage
  boilerplate ("I was never a student of science…") — only the
  title, URL and date.
- L34. **The "N" badge in dev screenshots is the Next.js dev-mode
  indicator, not app UI.** It appears in every dev-mode shot at
  the same position (bottom-left of the first viewport) and is
  ABSENT from the production export (verified by screenshot of
  the static build, 20 Nov 2026). No app fix needed.
- L35. **HI/TA Stage 4 strings are unreviewed** (24 new `voice_*`
  keys, agent-written). Same caveat as L5 — flagged for
  native-speaker review before any pilot.
- L36. **The Interests field on the confirm screen holds the whole
  raw sentence** ("farming and basic computer work, and I can
  type. Madurai. I need a job"). Noted in Stage 4, NOT retuned —
  any extraction change must re-run the KV eval and the
  faithfulness margin is thin (0.907 vs 0.90).

## Stage 5 (20 Nov 2026)

- L37. **Stage 5 UI is English-only.** The employer portal, jobs
  page and admin queue have no HI/TA strings — the voice flow
  stays the trilingual surface, and Stage 5 screens are the
  employer/admin side. Same caveat as L5/L35: flagged for
  translation before any pilot that puts employers on it.
- L38. **Phone OTP is blocked on an owner-only Firebase step.**
  Phone sign-in must be enabled in the Firebase console, and
  the free plan allows a limited number of SMS verifications a
  day. Until enabled, verification is e-mail + admin review
  only, and the verify-phone endpoint returns 503 honestly.
- L39. **Pay plausibility is wired — central-sphere only (Step
  8A, DONE).** The scam check now compares a listing's pay
  against the matched scheduled employment's wide monthly band
  (lowest daily total x 26 to highest daily total x 26) from
  the Labour Bureau VDA order: below_minimum / above_range /
  within_central_range / unknown, advisory only (never flags,
  never scores). What stays limited: the band is wide because
  the check does not know the listing's area or skill category
  (the area lists are prose in the source notes — parsing area
  membership out of prose would be a transcription risk), so
  "within_central_range" cannot confirm the exact minimum wage;
  piece-rate employments (stone-mines-piece) cannot convert to
  monthly and stay unknown; and TN state rates are still missing
  (L18) — a private Tamil Nadu employer follows state rates, so
  "below_minimum" means below the central-sphere band, never
  "below the legal minimum wage for this job".
- L40. **The LLM risk score is unmeasured — no key exists.**
  The prompt (`prompts/scam-risk.md` v1.0.0) and the advisory
  path are built and mock-tested, but no real LLM has ever
  scored a listing. All protection in production today is the
  deterministic rules path; the LLM path must be measured
  against the 5 fake + 40 real seed listings before any claim
  about it is made.
- L41. **There is no auto-verification.** Every employer and
  every listing waits for a human admin. At pilot scale this is
  deliberate (trust first); at larger scale the queue becomes a
  bottleneck and needs a trusted-employer fast lane — a later
  decision, not a Stage 5 feature.
- L42. **Duplicate detection is same-employer, same-city only
  (Step 8.4).** The narrow Stage 5 title-only check is replaced:
  exact SHA-256 fingerprints + a Bloom pre-filter + word
  3-shingle Jaccard (threshold 0.5, tuned on a 369-pair labelled
  set: precision 1.000, recall 0.907). A reworded repost is now
  caught, and a reused title with a different description is
  correctly NOT a duplicate. What remains narrow is the scope:
  the same job from a second employer account is still not
  auto-caught — cross-employer duplication stays an admin
  judgement, not an automatic block. The 26 labelled-set misses
  at threshold 0.5 are heavily edited variants (title AND
  description both changed, similarity 0.125–0.5).
- L43. **Phone binding is token-validity only, not UID-linked.**
  The server requires the token's e-mail to match the session
  user AND `email_verified` to be true (Google sign-in sets
  it; email/password users verify via the sign-up e-mail) —
  but it does not yet record the Firebase UID against the app
  account at sign-in. A stricter link (UID recorded at
  sign-in, token UID must match) is a hardening item for
  Stage 10.
- L44. **The client phone-linking flow is built but NOT
  live-verified.** `startPhoneLink`/`confirmPhoneLink` in
  `lib/firebase.ts` and the 2-step UI in the employer view
  follow the Firebase v12 SDK, and the server endpoint is
  fully tested with stubbed Firebase — but no real SMS has
  ever flowed through it (needs L38's console step + a real
  phone). Verify on a real phone before the pilot.
- L45. **The voice flow does not auto-save the worker
  profile.** The confirmed voice profile lives only in
  sessionStorage; the worker must save a work profile on
  `/sharing` (or tap "Use my voice profile" to prefill it)
  before they can share with an employer. A one-tap
  "save my voice profile" step at the end of the voice flow
  is a documented follow-up, not built in Stage 6.
- L46. **Contact requests have no worker response flow.**
  An employer can send a message and the worker can read it
  on `/sharing`, but the worker cannot reply, accept or
  decline in the app — the follow-up happens outside it
  (phone/e-mail, if the worker shared contact details).
- L47. **Matching covers signed-in workers with saved
  profiles only.** Guests cannot be matched (there is no
  profile to share and no account to consent from), and a
  signed-in worker with no saved profile is invisible to
  employers until they save one.
- L48. **No admin consent oversight UI.** Admins can see
  employers, listings and reports in the review queue, but
  there is no admin view of consents or the consent audit
  log — a consent dispute today needs a database read.
- L49. **The audit log has no automated retention.** One row
  is appended per candidate returned per employer search, so
  it grows O(searches × candidates returned). Step 9.4 records
  the POLICY (365-day retention, COMPLIANCE.md §4) but builds
  NO automated prune: the log is append-only by design (Stage 6
  invariant, execution prompt 6.2) and pruning it is a
  deliberate future ops decision, not a code path. Fine at
  pilot scale; the prune decision is a deploy-checklist item.
- L50. **CLOSED (Step 9.4, verified by test).** Lazy expiry is
  NOT a full table scan: v14 already ships
  `idx_kv_consents_expiry` on `(status, expires_at)` and the
  expiry query matches it exactly. `test_expiry_query_uses_index`
  proves the planner uses the index (no `SCAN kv_consents`).
  The earlier text was written before the index was noticed.
- L67. **Rate limits are per-process and spoofable.** The
  limiters are in-memory per worker (a multi-worker deploy has
  one 30/min budget per worker, not one global budget) and the
  per-IP key trusts the first `X-Forwarded-For` entry, which a
  client can spoof to rotate keys. They are friction against
  casual abuse, not a hard abuse boundary; true protection
  belongs at the platform edge (Render rate limiting / a WAF).
  Recorded as A65.
- L68. **No automated accessibility audit on KV screens.** The
  base app's ACCESSIBILITY.md covers the base app by hand; no
  axe/Lighthouse run has been done on the Kaam-Vaani screens
  (/voice, /rights, /pilot, /video-check, /jobs, /sharing).
  The plain/functional builder screens are the design agent's
  to polish, and the audit belongs with that pass.

## Step 7A (21 Nov 2026)

- L51. **The shared tokenizer shreds Indic words.** It splits on
  `[^\\w]+`, and `\\w` does not cover Indic combining marks (Tamil
  vowel signs, the pulli, Devanagari matras), so a Tamil/Hindi word
  is split into fragments — and different words collapse onto the
  same fragments (measured: "மின் பணியாளர்" once translated to
  "security guard"). Harmless for retrieval scoring (Tamil/Hindi
  tokens never appear in the English KB, so they score 0 whole or
  shredded), but the query translator uses its own whole-word
  tokenizer (`translate.py`) and the shared one must never be used
  to match Indic text. A future Indic-aware shared tokenizer is
  Step 8+ work; it must keep the English path byte-identical.
- L52. **Dense retrieval is uncalibrated — do not enable it
  (Step 8.1 calibration ANSWERED: dense stays opt-in).** Two
  measured defects (21 Nov 2026): (1) RRF fusion promotes dense
  favourites above the hybrid's correct rank-1 (sibling
  occupations tie in dense space — Helpers--Electricians
  0.8307 vs Electricians 0.8279 for a Tamil query), dropping
  faithfulness to 0.728 (Step 7A, 173 cases) / 0.765 (Step 8.1
  reproduction, 189 cases); (2) dense cosines sit in a
  compressed high band (every chunk ≥0.75 for an electrician
  query, including unrelated ones), so the TF-IDF refusal
  floors never fire and refusal falls to 0.600 / 0.684. Step
  8.1 measured the alternatives and they all fail:
  dense-as-tiebreak (eps 0.03/0.05/0.10) drops faithfulness to
  0.878, breaks six previously faithful cases, does not fix
  kv-r056/r086, and drops recall@5 to 0.991 at eps ≥ 0.05; and
  NO dense floor exists — top-hit dense cosine for retrieval
  vs refusal cases overlaps almost completely (min 0.718 vs
  0.717, median 0.838 vs 0.802). A different model (e.g. a
  cross-encoder reranker) is the only remaining honest option
  and is unmeasured. Dense also costs ~900 MB RAM and ~270 ms
  p50 per query on CPU — it does not fit the 512 MB Render free
  tier as built.
- L53. **The cosine refusal floors are absolute while IDF is
  corpus-relative — adding chunks can push marginal cases below
  a floor (Step 7B; mechanism FIXED in Step 8.1, residual risk
  remains).** Adding 8 wage chunks to snapshot v2 shifted IDF
  enough that kv-r013 (mason, cosine 0.092) and kv-r039 (noisy
  electrician, 0.096) fell below the 0.10 occupation floor and
  refused, even though the correct chunk still ranked #1 with a
  strong hybrid score (1.25 / 1.04). Step 8.1 fixed both with
  the title-evidence rescue (a top hit with title bonus ≥ 0.20
  is grounded by its title and waives the floor — measured:
  rescues exactly those two, zero refusal regressions;
  faithfulness 0.930 → 0.948). The underlying fragility is NOT
  gone: a future corpus change can push a case below the floor
  whose title does NOT match strongly, and the rescue will not
  save it. Re-measure the floors (and the rescue threshold)
  whenever the corpus grows; do not lower a floor to fit cases
  without re-measuring the refusal set.
- L54. **Postgres cutover is blocked on the legacy stores (Step
  7C).** Migrations 1..14 and the Kaam-Vaani stores are verified
  on live Postgres 16.2, but 16 legacy per-feature stores (users,
  profiles, journey, billing, verification, institutes, legacy
  consent, content, coupons, gamification, RIASEC, roadmap,
  settings, sharing, synonyms, api_keys, admin console) open the
  SQLite file directly. With `DATABASE_URL` set the app runs
  split-brain (core + Kaam-Vaani on Postgres, the rest on
  SQLite). Full cutover needs a store-by-store port behind the
  dialect layer; until then, do not point production at
  Postgres. See `docs/DEPLOY.md` §6 and `docs/RUNBOOK.md` §3.1.
- L55. **FIXED in Step 8B — the free-text income string no longer
  leaks into matching through the base matcher.** (Was: a Step 8.1
  fairness finding — `KVScorer._base_scores` built the base
  matcher's goals field as `f"{goal_type}. Needs to earn
  {income_text}"`, so paraphrasing the income string shifted base
  scores by up to ~1e-3, final scores ~1e-4.) The goals field is
  now `goal_type` only; income is scored by the dedicated
  income-fit component. Pinned by
  `test_income_text_does_not_leak_into_base_scores` (fails on the
  old code, passes on the new). Re-baselining the 8.1 golden
  top-5s changed scores by up to 0.0058 (btech / Computer
  Programmers — a semantic-scorer renormalisation effect) and
  <= 0.0004 elsewhere; the ORDER is identical in all five probe
  profiles.
- L56. **No prerequisite data exists for the skill-gap engine
  (Step 8.2).** The DAG/Dijkstra engine fully supports
  prerequisite edges (proven on hand-made graphs), but the
  production graph has none: O*NET importance order is
  importance, not a prerequisite; `bridge_paths.yaml` is
  profession-change routes, not skill prerequisites; NSQF
  appears twice in the KB and is not a progression structure.
  Until real prerequisite data lands (NSQF levels would be the
  source), the plan order is gap-importance order. Related: the
  plan is the union of per-skill cheapest paths, not a global
  set-cover optimum — a single course covering several gaps at
  a lower total cost than the per-skill cheapest picks is not
  searched for. Also, the catalogue is IT-heavy (L32): 10 of
  the 38 probe-profile gaps have no curated resource at all
  (trade competencies like "operation and control",
  "equipment maintenance", "building and construction") — the
  engine lists them as uncovered instead of silently dropping
  them, but it cannot teach them.
- L57. **The radius filter knows 6 cities (Step 8.3).** Only
  Madurai, Tiruppur, Dindigul, Tirunelveli, Chennai and
  Virudhunagar have coordinates (`data/kv_city_coords.yaml`) —
  the cities the seed listings use. A radius search centred on
  any other city is a 400 naming the mapped cities, and a
  listing in an unmapped city never appears in radius results
  (it still appears in the plain city filter). Adding a city
  means geocoding it and appending one YAML entry. Related: the
  store still fetches verified rows from SQLite and filters in
  Python — the index prunes the haversine work, not the SQL
  fetch — so at very large scale the geohash prefix would need
  pushing into SQL (a stored `geohash` column + prefix query).
  The cached index is per store instance and invalidated by
  every listing write on that instance; a listing written
  concurrently on another thread may be missed by one in-flight
  radius query (the next query sees it).
- L58. **The citation verifier checks grounding, not relevance
  (Step 8.5).** It proves every answer sentence maps to its
  cited chunk (token overlap ≥ 0.8) — and all 6 still-unfaithful
  gold cases PASS verification, because their answers are
  verbatim from the cited chunk while the chunk is the wrong one
  for the question (rank 2–3 sibling near-misses). Catching those
  is the ranker's job, not the verifier's; faithfulness stays
  0.948 and the verifier must not be read as a faithfulness fix.
  Related: every gold answer hits the 600-character cap, so the
  last sentence of every answer is a truncated fragment — the
  verifier reports it as truncated rather than failing it.
- L59. **All caches are per-process, in-memory (Step 8.6).**
  Translation, answer/search, profile and LLM-result caches live
  in the server process only: nothing is shared across workers or
  restarts, and a restart starts cold (the first request after a
  restart also pays the ~4.3 s first `HybridRetriever` build —
  sklearn warm-up on the first TF-IDF fit; ~0.7 s warm). At pilot
  scale (one server process) this is fine; a multi-worker deploy
  would need a shared cache (Redis or equivalent) and is not
  built. The translation cache is a negligible win in absolute
  terms (glossary lookup is 0.019 ms/question) — it is kept
  because it is free and correct, not because it saves real time.
- L60. **The measured local LLM is a 0.5B model: schema-reliable,
  semantically fallible, and slow (Step 8.7).** Qwen2.5-0.5B-Instruct
  Q4_K_M follows the extraction JSON schema and gets concrete
  fields right (skills, education, city, income on unseen input),
  but on a tailor-in-Salem transcript it returned `interests` =
  "job_6_months" and `goal_type` = "explore" for a person who
  explicitly wants a job — and Pydantic validation does NOT catch
  these, because the types are all valid. A full extraction with
  the production prompt takes ~36 s on 4 shared CPU threads
  (prompt processing dominates; generation ~10 tokens/s), which
  is slow for an interactive voice flow. The deterministic
  extractor and the voice flow's confirm step stay mandatory;
  a larger model (1.5B/3B) was NOT measured here. The Ollama
  server path was not executed in this sandbox either — only
  its interface exists.
- L61. **The LoRA dataset is a 55-example seed set, and no
  training has run (Step 8.8).** 49 train / 6 val examples can
  smoke-test the pipeline and may fix the narrowest extraction
  errors, but a production fine-tune wants hundreds of reviewed
  examples, and a 6-example val set can only signal, not prove.
  The config values are chosen, not tuned; the notebook was not
  executed; no adapter exists and no accuracy gain is claimed.
  Growing the dataset honestly (more gold cases, human-reviewed
  traces) is documented in docs/LORA_RUNBOOK.md.
- L62. **Trace retention is size-bounded, not time-based, and
  traces are process-local (Step 8.9).** The in-memory ring
  holds the last 200 traces and a restart starts empty; the
  optional JSONL sink rotates by size (10 MB/file, 3 files),
  not by date. The recommended ops retention is 7 days, but
  strict time-based pruning is NOT built in — it needs a
  logrotate/pruning cron on the JSONL file. Gap-learning is
  untraced by design (a deterministic lookup, not an agent
  step), and 400 client errors are not traced either.
- L63. **The rights assistant answers in English and detects
  scam intent in English (Step 9.1).** Answers are verbatim
  English quotes even for Tamil/Hindi questions (L16, unchanged);
  scam-intent keywords run on the glossary-translated query,
  and the glossary covers occupation/skill/trade terms, not scam
  vocabulary — so a Tamil/Hindi scam question gets its escalation
  only when the top retrieved chunk is a scam chunk. Only two
  helplines are verified on file (1930 cybercrime, 1514 NCS):
  state cyber cells, women's/child helplines and bank fraud
  desks are NOT listed, because no number is quoted without an
  official source checked in-session.
- L64. **SMS/WhatsApp share is NOT built (Step 9, flagged).**
  Sharing a match or a rights answer over SMS/WhatsApp needs a
  WhatsApp Business account + phone pairing that only the owner
  can do (his phone, his QR scan) — no integration was attempted
  and none is faked. The voice flow and the /rights page work
  without it; share-by-SMS/WhatsApp stays a documented gap until
  the owner pairs an account.
- L65. **Voice-flow match views are not tracked (Step 9.2).** The
  pilot console's metrics come only from stored rows: the match
  funnel it reports is shortlists + contact requests (employer
  actions on consented candidates). How many matches a worker
  VIEWED in the voice flow is not persisted anywhere, so the
  console cannot report it — adding it would mean a write on every
  /matches call (a new table + migration), deliberately not done
  in Step 9. The outcome/retention metrics also load at most 1000
  outcome rows for their latest-per-(listing, worker) dedup and
  cap silently past that (pilot scale is far below it).
- L66. **The video skill check does not assess skill (Step 9.3).**
  It measures clip properties only (duration, brightness, blank
  frames, motion) and cannot tell a good weld from a bad one, or
  a worker's hands from anyone else's. Thresholds are chosen, not
  tuned — no labelled task clips exist. It was tested ONLY on
  synthetic ffmpeg clips (testsrc / solid colours); no real task
  recording has ever been run through it. Clips are never stored
  and results are never persisted, so a coordinator cannot review
  a past check. ffmpeg/ffprobe must be installed where the
  backend runs (present on this machine; Render's free tier would
  need them in the build — a deploy checklist item).
