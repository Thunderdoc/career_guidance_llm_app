# Upgrade Plan — Career Guidance AI: Master Build Prompt → Concrete Work

_Date: 2026-11-06 · Base: origin/main @ ad05b05 (production hardening, 2026-11-03)_
_Source prompt: "Career Guidance AI: Master Build Prompt for Muse" (owner-supplied, 2026-11-06)_
_Rule: extend / consolidate / polish the existing repo. No rewrite from scratch. No invented data._

---

## 0. Repo audit at start (verified 2026-11-06)

**Clean base:** Fresh worktree `career-guidance-live` at `origin/main` (`ad05b05`).
The older clone at `career-guidance/` has a dirty tree whose content matches
`origin/main` but whose local HEAD is stale (`f8e27ae`) because connector pushes
do not update the local clone. **All upgrade work happens in the fresh worktree
only.** Never integrate from the stale clone.

**What already exists and must be kept:**
- Frontend routes (24): `/, /admin, /billing, /careers, /classic, /compare,
  /dashboard, /discover, /history, /interview, /jobfit, /learn, /login,
  /onboarding, /plan, /pathway, /privacy, /recommend, /refund, /resume,
  /settings, /terms, /transitions` + `/careers/[id]`
- Backend: `backend/main.py` (recommend, resume/extract, skills/suggest,
  careers/search, careers/{id}, assessment, jobs/fit, history, analytics,
  export), `admin.py` (/me), `admin_console.py` (/admin/* incl. resources,
  synonyms, weights, settings, templates, feedback, audit, backup),
  `auth.py` (/auth/*), `billing.py` (/billing/*), `journey.py` (/profile,
  /onboarding, /discover, /plan, /learn, …)
- Core modules present: taxonomy, matching, matching2, market, market_seed,
  learning, providers, suggestions, suggestions2, resume, resume_score,
  riasec, skillgap, roadmap, pathway, transitions, journey, gamification,
  interview, explanations, engine, ladder, tasks, reports, keywords,
  synonyms, translations, content_store, settings_store, billing, storage,
  users, migrations, analytics, config, models, profile(s)
- Data present: `data/catalog/occupations.json` (974), `learning_resources.yaml`,
  `market_seed.yaml`, `skill_synonyms.yaml`, `assessment_items.yaml`,
  `bridge_paths.yaml`
- Billing: plans/trial/Razorpay/webhook/Pro-PDF-gate done, prices from env,
  unset = "Contact us" / 501 — already matches the prompt's placeholder rule.
- i18n: `frontend/lib/i18n.tsx` + `i18n-extra.ts`, EN/TA/HI in the signed-in app.

**What does NOT exist yet (prompt asks to create):**
- `career_guidance/india.py`, `career_guidance/reality.py`,
  `career_guidance/verify.py`
- `data/crosswalk_onet_nco.yaml`, `data/india_market.yaml`, `data/skill_quizzes/`
- `docs/SOURCES.md`, `docs/COMPLIANCE.md`, `docs/ROUTES.md`, this file
- Routes: `/start`, `/report/[runId]`, `/explore`, `/account`, `/p/[handle]`,
  `/methodology`
- Institute roles (`institute_admin`, `counsellor`), cohort dashboard,
  ConsentProvider / NotificationProvider abstractions, Postgres option

---

## 1. Conflicts & risks found (prompt § "How to work", point 3)

| # | Conflict / risk | Resolution (existing behaviour wins, noted) |
|---|---|---|
| C1 | **Guest-first vs private app.** README + code: app is private — `/` wrapped in `<RequireAuth>`, content APIs 401 without session, `PUBLIC_APP=false` default (admin flag can override). Prompt Phase 1.2 wants anonymous first result. | This is an intentional owner-directed *change*, not an accident: implement anonymous, rate-limited `/recommend` with a short-lived anonymous session; keep all saved-data routes (`/me`, `/history`, `/plan`, exports, `/admin`) authenticated. Update README to "public-first with gated depth" in the same commit so docs and code stop contradicting. Flagged here as the prompt requires. |
| C2 | **Route consolidation vs working links.** Prompt wants 7 surfaces; repo has 24 working routes incl. `/dashboard`, `/resume`, `/interview`, `/login` which the prompt's list omits. | Keep every old route: new surfaces are added, old routes become redirects (Next.js `redirects()` / stub pages) — never deletions. `/login` and `/dashboard` stay as real routes (auth + signed-in home) even though not in the 7-surface nav; nav ≠ route table. Documented in `docs/ROUTES.md`. |
| C3 | **Hero statistic needs a source.** Prompt 1.3 requires a "sourced, real statistic" but no source is supplied and inventing one is banned (Rule 1). | Landing ships with the hook slot wired to `docs/SOURCES.md` entry #1; until a verified source is added, the hero uses a non-numeric promise line ("Top-5 careers from 974 real occupations — O*NET") which is verifiable from the catalog itself. No placeholder statistic is displayed. |
| C4 | **India market data has no licensed source yet.** Phase 2 needs fresher salary / demand per career; only `market_seed.yaml` (labelled estimates + Adzuna-when-keyed) exists. Owner input #6 (data licences/feeds) is open. | Phase 2 ships the schema, crosswalk, Reality Score engine and admin editing UI with **seed data explicitly labelled `kind: estimate`** + `as_of`. No figure is ever presented as official. Score components with no data are excluded with "insufficient data" per prompt 2.2. |
| C5 | **Fonts + Tamil/Hindi glyphs.** Prompt wants one typeface pair with TA/HI support, subset, ≤245 kB first-load JS. Current stack uses system/next defaults. | Choose a single variable sans with Devanagari + Tamil coverage (e.g. Inter + Noto Sans Tamil/Devanagari subsets via `next/font`), verify glyph rendering with screenshots before committing to it; if bundle budget breaks, keep system stack and document why. |
| C6 | **DPDP / parental consent is legal-sensitive.** Prompt Phase 5 says implement engineering side only, not legal advice. | Build ConsentProvider with manual/email flow + audit record, `docs/COMPLIANCE.md` checklist marked "owner to review with a lawyer". No compliance claim is shown to users beyond the plain-language notice itself. |
| C7 | **SQLite on Render free tier is ephemeral** (known from SELLING.md: free tier sleeps, DB risk). Prompt Phase 6 wants persistent disk or Postgres. Owner input #5 is open. | Phase 6 implements the Postgres option behind the existing Database class + migration docs; the *hosting switch itself* stays an owner decision (free-only rule: no paid Render plan without owner say-so). |
| C8 | **First-load JS budget (≤245 kB) vs new surfaces.** Report image export, cohort charts, quiz UI can blow the budget. | Every new route code-split; heavy libs (image/PDF/chart) dynamically imported; budget checked in each phase summary, not only at the end. |
| C9 | **Local clone staleness** (see §0). | Fresh-worktree-only rule for all upgrade work; verify `git log origin/main -1` before every push; push is batched and needs the owner's GitHub approval tap. |

---

## 2. Phase → files map

### Phase 1 — Consolidate UI & first impression
| Task | Files (new = ✦, change = Δ) |
|---|---|
| 1.1 Route map + redirects | ✦ `docs/ROUTES.md`; Δ `frontend/next.config.ts` (redirects); ✦ `frontend/app/start/`, `app/report/[runId]/`, `app/explore/`, `app/account/` (thin shells reusing existing views); Δ nav in `frontend/components/app-shell.tsx` + `shell.tsx` (7 surfaces, `/classic` removed from nav) |
| 1.2 Guest-first | Δ `backend/main.py` (`_public_app` → anonymous session for `/recommend` only, rate-limited, short-lived cookie); Δ `frontend/components/require-auth.tsx` (gate save/export/plan/verify, not first result); Δ `README.md` (public-first wording); ✦ tests `tests/test_guest_access.py` |
| 1.3 Landing | Δ `frontend/components/landing-view.tsx` + `frontend/app/page.tsx` (hero, try-it box, sample report, 3 differentiators, trust strip, 4 steps, pricing w/ Institutions tab + demo form → `POST /api/v1/billing/demo-request` ✦ in `backend/billing.py`, FAQ, footer); ✦ `docs/SOURCES.md` (seed: O*NET only) |
| 1.4 Design system | ✦ `frontend/styles/tokens.css` (CSS vars, light/dark, WCAG AA checked); ✦ `frontend/components/ui/` (Button, Card, Badge, Tabs, Stepper, ProgressRing, ScoreMeter, Skeleton, EmptyState, Toast, Modal, Tooltip, DataTable, SourceLabel); Δ `frontend/app/globals.css`, `layout.tsx` (fonts) |
| 1.5 Wizard `/start` | ✦ `frontend/components/start-wizard.tsx` (4 steps, draft in localStorage + server run); Δ `career_guidance/profile.py` + `backend/main.py` (optional `constraints` object on recommend: persona, relocate, hours/week, budget, language, goal — additive, backward compatible); ✦ i18n keys EN/TA/HI in `frontend/lib/i18n*.ts*`; tests for constraints plumbing |
| Gates | `make ci`, `make blackbox`; Lighthouse mobile landing+report; screenshots 360px + 1280px (landing, wizard, report) |

### Phase 2 — India Reality Score & Career Report
| Task | Files |
|---|---|
| 2.1 India data layer | ✦ `career_guidance/india.py`, `data/crosswalk_onet_nco.yaml` (confidence + method per mapping, empty where none), `data/india_market.yaml` (source, source_url, as_of, kind per field); ✦ admin editor in `backend/admin_console.py` + `frontend/components/admin-view.tsx` (audit-logged); Δ `docs/SOURCES.md` (every source + licence, O*NET attribution) |
| 2.2 Reality Score | ✦ `career_guidance/reality.py` (5 components, missing-data exclusion + confidence); ✦ `tests/test_reality.py` (scoring, missing data, monotonicity); Δ matcher response in `career_guidance/suggestions.py` (+ optional `reality` field) |
| 2.3 Report page | ✦ `frontend/app/report/[runId]/` + `components/report-view.tsx` (match, Reality breakdown + SourceLabel, have/missing/priority skills, why-not, alternatives/stepping-stones, salary ladder, cities/sectors, PNG/PDF export, parent-version toggle); Δ API response (+ `why_not`, `alternatives`, `constraints_used`, provenance sources); Δ `career_guidance/transitions.py` (alternatives), explanations for why-not |
| Gates | Crosswalk loader + reality + report API tests; golden eval Hit@5 must not drop |

### Phase 3 — Proof of skill & 90-day plan
| Task | Files |
|---|---|
| 3.1 Verification | ✦ `career_guidance/verify.py`, `data/skill_quizzes/` (seed: Python, SQL, HTML/CSS, Excel, Communication — only where correctness is checkable); ✦ `backend/` router `/api/v1/skills/verify/*`; state machine unverified → quiz_passed / project_submitted → verified; rate limit + randomisation + retake cooldown; tests |
| 3.2 Public profile | ✦ `frontend/app/p/[handle]/`; opt-in controls in account; under-18 disabled by default; never expose email/age/school |
| 3.3 90-day plan | Δ `career_guidance/roadmap.py` (week-by-week from constraints: hours, budget; 1–3 tasks/week + verification check); ✦ `career_guidance/notifications.py` (NotificationProvider abstraction, SMTP impl, WhatsApp stub documented — no integration without owner creds); Δ dashboard "this week" card; ICS/MD export extended |
| Gates | Quiz grading, state-machine, plan-with-constraints tests; manual report→plan→verify walkthrough |

### Phase 4 — Institute portal
| Task | Files |
|---|---|
| Roles + onboarding | Δ `career_guidance/users.py` + migrations (roles `institute_admin`, `counsellor`, `student`; institute, seats); ✦ CSV invite import (validate, size-cap, row-error report) in `backend/` + tests incl. malformed files |
| Cohort dashboard | ✦ institute views in frontend (aggregate-by-default: missing-skills vs demand, readiness by dept/year, top careers, attention list); individual views role-gated; privacy test (aggregate-only) |
| Reports + branding | Cohort PDF/CSV export; logo + accent on reports; counsellor review notes + "Reviewed by counsellor" label; demo-request leads from Phase 1 land here |
| Gates | Role/permission tests, CSV tests, e2e institute demo with seeded data labelled DEMO |

### Phase 5 — Privacy, compliance & trust (parallel from Phase 1)
| Task | Files |
|---|---|
| Age gate + consent | ✦ `career_guidance/consent.py` (ConsentProvider, manual/email flow, timestamped + versioned record); under-18: no behavioural tracking/analytics, no public profile, no streak nudges |
| Notices + methodology | Δ legal pages (plain-language, EN/TA/HI); ✦ `frontend/app/methodology/` + `docs/COMPLIANCE.md` (DPDP checklist + breach runbook, "not legal advice") |
| Eval evidence | Δ `eval/` (counsellor-validation script + docs; no unsupported accuracy claims) |

### Phase 6 — Production readiness
| Task | Files |
|---|---|
| DB | Postgres option through Database class + migrations + docs; backup/restore script; structured logging; error-tracking hook; `/health` + readiness |
| SEO | Metadata, OG images, sitemap, robots, indexable `/careers/[id]`, TA/HI landing |
| Security | Dependency audit, rate limits on new routes, upload limits, CSRF review for cookie sessions, secure headers — fix findings |
| Docs | Δ `README.md`, `SELLING.md`, `docs/MASTER_PLAN.md`, `CHANGELOG.md`; LICENSE placeholder; O*NET attribution in footer + methodology |

---

## 3. Owner inputs — placeholders in force (do not guess)

1. Pro / Institute prices (env `BILLING_PRO_PRICE_INR`, `BILLING_INSTITUTE_PRICE_INR`; UI shows "Contact us" until set) — **open**
2. Razorpay test keys → live keys + webhook — **open**
3. Legal business name + contact email (env; TODO banner in non-production only) — **open**
4. SMTP or disable magic links — **open**
5. Render paid plan vs Postgres decision — **open** (free-only rule applies until owner decides)
6. India data licences / paid feeds for Phase 2 — **open** (seed estimates, labelled, until then)
7. Pilot college + permission for anonymised results — **open**

## 4. Working order

Phase 1 → 2 → 3 → 4 → 6, with Phase 5 items pulled forward alongside
(consent groundwork lands with Phase 3's public profiles at the latest —
profiles must not ship before the under-18 rule exists).
Each phase: implement → `make ci` + `make blackbox` green → preview verified
(rendered, screenshots where UI changed) → short summary (changed / files /
tests / verify / owner decisions) → batched push only on owner approval tap.

---

## 5. Phases 7–10 (owner extension, 2026-11-06)

- **Phase 7 — Intelligence v2:** optional embedding similarity behind a config flag (TF-IDF fallback; flag OFF by default unless eval ≥ baseline), scoped career chat `/api/v1/chat` grounded in report + taxonomy with off-topic refusal and graceful no-key degradation, multi-provider LLM factory (OpenAI/Gemini/Ollama, env-selected, timeout/retry, schema-validated), eval expansion (faithfulness + chat grounding).
  **Status (2026-11-06, local `upgrade/final`): SHIPPED.** Semantic layer `career_guidance/semantic.py` (TF-IDF scorer + fail-soft embedding scorer, blend seam in `MatcherV2.rank` only). Golden eval with blend ON (w=0.25): Hit@5 1.0 → 1.0, MRR 0.827 → 0.888, interests 1.0 → 1.0 (stable ×3 runs) — golden rule met, BUT a default-ON trial broke `test_core_v2`'s skills-only sanity gate (top pick 49.2%), so `SEMANTIC_MATCHING_ENABLED` ships OFF by default (opt-in). Provider factory in `providers.py` (OpenAI/Gemini/Ollama; shared timeout + one transient retry; same `_parse_*` validation; faithfulness extracted to `career_guidance/faithfulness.py` and reused by grounded merge + chat + eval). Scoped chat `career_guidance/chat.py` + `POST /api/v1/chat` (JSON, no SSE — no streaming pattern exists in the stack; deterministic scope check, offline answerer, other users' runs 404) + code-split chat panel on `/report` with EN/TA/HI strings. Eval: `eval/run_chat_eval.py` (faithfulness 4/4, chat grounding 8/8) wired into `make eval`; golden numbers unchanged. Version 1.3.0.
- **Phase 8 — Reach & mobile:** full PWA (static-only SW caching, never authenticated API), TA/HI landing at EN depth, signed expiring revocable share links for reports (privacy-tested), low-bandwidth mode (Save-Data + manual toggle).
  **Status (2026-11-06, local `upgrade/final`): SHIPPED.** Share links: `career_guidance/sharing.py` + migration v8 (`share_tokens`, SHA-256 hash at rest, raw token shown once), owner-only create/list/revoke (guest session for anonymous runs; sign-in does not adopt them), public rate-limited read built from the `report_v1` allowlist (privacy-scanned in tests: no owner identity, constraints, profile text, institute/counsellor data), expiry 7 d default / 30 d max as code constants, 410 expired/revoked, 404 unknown. Frontend: code-split share panel on `/report`, public `/shared/[token]` read-only view (217 kB first load — within budget). PWA: manifest completed (start_url `/`, icons verified on disk), hand-written `sw.js` v4 (shell precache, static cache-first, navigations network-first, `/api` never cached, SKIP_WAITING only via the new update-available toast), `/offline` page + dependency-free SW fallback at `public/sw-offline.html` (the export overwrites `out/offline.html` with the route — verified in build output). TA/HI landing: dictionaries were already at full parity (657/657 keys); fixed the real gaps — guest language switcher added to the landing footer, three hardcoded English strings localised. Low-bandwidth mode: `lib/bandwidth.ts` precedence (manual > Save-Data > off), `data-low-bandwidth` CSS + Motion gates, deferred chat/share panels, toggles in Settings + landing/report headers, account-prefs sync via existing `/me/prefs`. No frontend test runner exists in the repo — bandwidth logic verified via tsc + 18 node assertions on the compiled module. Version 1.4.0.
- **Phase 9 — Revenue v2:** Razorpay subscriptions as an additional option (501 while keys unset, signed-fixture webhook tests), coupons + referrals (owner-created in admin, redemption tests), institute analytics v2 (term-over-term, export scheduling metadata, counsellor work queue).
  **Status (2026-11-06, local `upgrade/final`): SHIPPED.** Migration v9 (subscriptions + webhook_events ledger, coupons/redemptions, referral codes/attributions/valueless pending rewards, payments discount columns, institute report_schedule). Subscriptions: `career_guidance/billing.py::create_subscription` (MockTransport-injectable; 501 keys unset / 409 plan-id unset — plan ids env-only `RAZORPAY_PRO_PLAN_ID`/`RAZORPAY_INSTITUTE_PLAN_ID`, never invented; 12 cycles), `POST /billing/subscribe`, `subscriptions_enabled` on the plans payload gates the UI Subscribe option, subscription status on `/billing/me`; webhook extended over the same HMAC path — charged extends to Razorpay's absolute current_end + activates, cancelled/halted/paused mark status only (plan stays until period end), replays idempotent via the ledger (asserted in tests), tampered signatures 401, unknown events/subscriptions ignored. Coupons (`career_guidance/coupons.py`): admin-only create/list/deactivate (audit-logged), percent/flat, max + per-user caps, expiry — every rejection tested; preview endpoint changes no state; checkout prices server-side and writes payment + redemption + referral attribution in ONE transaction (rollback asserted). Referrals v1 = attribution + counts only (`GET /me/referral`); rewards are pending valueless records — value comes only from an owner-created coupon. Institute analytics v2: term = calendar quarter, `cohort?period=current|previous` with both-quarter aggregates + deltas (empty period = honest zeros; no-e-mail privacy scans pass), review-queue v2 (unreviewed only, oldest first, limit/offset; Phase 4 review marks items off — linkage tested), `report_schedule` preference with nominal next_run (NO scheduler — documented honestly in README/SELLING). Frontend: coupon/referral fields, gated Subscribe button, referral card, p9_* EN/TA/HI. Gates: 502 pytest passed (468 + 34 new), coverage 91.80% (coupons 93%, backend/billing 85%, billing core 95%, institutes core 95%, backend/institutes 96% — all new modules ≥80%), eval unchanged (Hit@5 1.0 / MRR 0.827 / faithfulness 4/4 / chat 8/8), ruff/tsc/eslint clean, both builds green (/billing 263 kB, /account 270 kB first load — +1 kB vs Phase 8 baseline; already over the 245 kB budget pre-Phase-9). Version 1.5.0. (Coverage figures re-verified in two clean full runs after the first gate run's coverage save hit a sandbox /tmp-remount disk I/O error and printed a table from partially-flushed data; test count and all conclusions unchanged.)
- **Phase 10 — Scale, trust & launch finish:** public-endpoint caching, /recommend p95 documented vs ~292 ms eval baseline, DB index review, accessibility audit pass + checklist doc, institute public API (API-key auth, aggregates only), status/health wiring, final docs + consolidated owner-only go-live checklist.
  **Status (2026-11-06, local `upgrade/final`): SHIPPED — this closes the Phase 1–10 build.** **JS budget root cause fixed:** the ~103 kB shared chunk was the full EN+TA+HI dictionaries (plus Firebase via auth-context). Dictionaries are now split per locale (`lib/i18n-dict-{en,ta,hi}.ts` + `i18n-extra-{en,ta,hi}.ts`): EN is the bundled base, TA/HI load via dynamic `import()` and the provider awaits the chunk before switching (persisted locale honoured, no wrong-language flash, `Dict`/`Key` type safety and every `t()` call site unchanged); `auth-context` dynamic-imports Firebase only for sign-out. **Every route is now ≤245 kB first load** (full tables below). **Caching:** `career_guidance/cache.py` (TTL 300 s, bounded LRU) on `/meta`, `/skills/suggest`, `/careers/search`, `/careers/{id}` (normalised keys; career detail bypassed for platform admins); tests prove the underlying work runs once across repeats and `load_taxonomy` (lru_cache) loads the catalog once per process. **/recommend p95:** eval-harness in-process series (like-for-like vs the ~292 ms Phase 1 baseline) = **238.4 ms** in the Phase 10 gate run; end-to-end HTTP bench on this sandbox VM (`scripts/bench_recommend.py`, 25 reqs ×2) = 943/954 ms — different method + machine, documented honestly in `docs/PERFORMANCE.md`. **DB:** migration v10 adds per-user indexes (runs, assessment_runs, plans, interview_sessions, payments) after a full query review; EXPLAIN QUERY PLAN before/after (SCAN → SEARCH USING INDEX) in `docs/PERFORMANCE.md`; v9→v10 upgrade + idempotency tested. **Accessibility:** `docs/ACCESSIBILITY.md` — modal focus traps (both dialogs; the UI-kit modal had none), WAI-ARIA tab keyboard pattern in both Tabs, `aria-current` stepper, chat `role=log`, icon-button labels, and the one failing contrast token fixed (`#909090` 3.56:1 on bg-4 → `#a8a8a8` 4.78:1; full measured table in the doc; screen-reader verification honestly listed as a remaining gap). **Institute public API:** migration v10 `institute_api_keys` (SHA-256 at rest, raw `cgk_…` shown once), session-gated key management (institute_admin of that institute or platform admin, audited), public `GET /api/v1/public/institutes/{slug}/cohort` + `/top-careers` authenticated by `X-API-Key` ONLY (session alone = 401; valid key + wrong slug = 404; revoked = 401; 30/min per key), aggregates only (needs-attention reduced to a count; privacy-scanned payloads), `last_used_at` stamped — 7 tests. **Launch finish:** `/status` page (live `/health` + `/ready` from the browser, EN/TA/HI); docs sweep (README/ROUTES/SECURITY/MASTER_PLAN/CHANGELOG); SELLING go-live checklist consolidated to owner inputs ONLY (prices; Razorpay keys + plan ids + webhook; business name/email; SMTP-or-disable; Render/Postgres decision; data licences; pilot college); `.env.example` re-audited against the code — complete, no gaps; versions aligned at **1.5.0** (pyproject + package.json/lock root fields; `__version__` already 1.5.0). **CI parity:** every CI job's commands run locally and pass (ruff, pytest, coverage gate ≥85%, eval, tsc, eslint, export build) EXCEPT the Docker job — no Docker in this sandbox; `Dockerfile` and `ci.yml` are untouched by Phase 10. Gates: **514 pytest passed (502 + 12 new), coverage 91.93% overall (cache.py 98%, api_keys.py 100%, backend/public_api 97%, backend/main 84%), eval Hit@5 1.0 / MRR 0.827 / faithfulness 4/4 / chat 8/8, ruff check + format clean (143 files), tsc clean, eslint 0 errors (3 pre-existing warnings), both builds green.**

  **First-load JS — before (Phase 9 head) vs after (Phase 10, export build):**

  | Route | Before | After | | Route | Before | After |
  |---|---|---|---|---|---|---|
  | / | 258 kB | 187 kB | | /login | 258 kB | 224 kB |
  | /account | 270 kB | 200 kB | | /methodology | 211 kB | 178 kB |
  | /admin | 211 kB | 174 kB | | /offline | 156 kB | 122 kB |
  | /billing | 263 kB | 193 kB | | /onboarding | 264 kB | 194 kB |
  | /careers | 263 kB | 192 kB | | /p/[handle] | 216 kB | 183 kB |
  | /careers/[id] | 263 kB | 193 kB | | /pathway | 265 kB | 195 kB |
  | /classic | 276 kB | 206 kB | | /plan | 264 kB | 194 kB |
  | /compare | 264 kB | 193 kB | | /privacy | 153 kB | 119 kB |
  | /dashboard | 265 kB | 195 kB | | /recommend | 271 kB | 200 kB |
  | /discover | 263 kB | 192 kB | | /report/[runId] | 260 kB | 190 kB |
  | /explore | 263 kB | 192 kB | | /resume | 263 kB | 192 kB |
  | /history | 264 kB | 194 kB | | /settings | 263 kB | 193 kB |
  | /institute | 264 kB | 193 kB | | /shared/[token] | 220 kB | 186 kB |
  | /interview | 264 kB | 193 kB | | /start | 221 kB | 187 kB |
  | /jobfit | 262 kB | 192 kB | | /status | — (new) | 123 kB |
  | /learn | 263 kB | 192 kB | | /transitions | 263 kB | 192 kB |

  (Static routes /refund, /robots.txt, /sitemap.xml, /terms unchanged at 103 kB; /_not-found 104 kB. Server build produces the identical table.)

## 6. Industry-Ready Checklist (owner directive, 2026-11-06 — verify each with evidence in the final report)

1. Robustness: Pydantic validation + consistent error shapes on every new route; graceful degradation for LLM/Adzuna/SMTP/DB failures; failure-path tests, not only happy paths.
2. Security: server-side authz re-checked on every new route (401/403 tests), rate limits on public/expensive routes, upload limits, secure cookie flags in prod, security headers, no secrets/PII in logs, pip-audit + npm audit run (high/critical fixed or justified).
3. Data safety: migrations idempotent + backward-safe, proven by upgrading a Phase-1-era DB copy through all new migrations; transactions on multi-write; no data-loss paths in delete/export.
4. Observability: structured logs with request ids on new routes; health (live) vs readiness (DB reachable) distinguished; error-tracking hook documented.
5. Performance: /recommend p95 documented vs baseline; public catalog endpoints cached; per-route first-load JS ≤245 kB; catalog loaded once, reused (no N+1 loads).
6. Code quality: ruff + eslint + tsc 0 errors; coverage ≥85% overall and no new core module <80%; no dead code/TODOs in shipped paths except centralised owner-input markers.
7. Docs: README run/deploy/rollback, .env.example complete for every new env var, API changes in README table + ROUTES.md, CHANGELOG per phase, rollback runbook in docs/DEPLOY.md.
8. Release hygiene: CI workflow green on final tree, version bump + final changelog entry, small per-phase commits.
9. Polish: consistent empty/error/loading states via the Phase 1 UI kit on every new screen, keyboard accessibility on interactive widgets, EN/TA/HI complete for new strings.

Status per phase is recorded honestly in §2/§5 as work lands; anything partial is named, not hidden.
