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
