# Test report — Career Guidance AI

**Scope of this report:** everything that was *executed* for phases S1–S5 of
`docs/MASTER_PLAN.md`, plus an explicit list of what the sandbox **cannot** test
and the exact manual steps to close each item.

Everything in the "Executed" columns is reproducible from the repository:

| Command | What it runs |
| --- | --- |
| `make ci` | ruff (`check` + `format --check`) → pytest → coverage gate ≥ 85 % → `eval.run --min-hit 0.75` |
| `make lint` | ruff, then `eslint .` and `tsc --noEmit` in `frontend/` |
| `make test` | `pytest -q -p no:warnings` |
| `make cov` | coverage over `career_guidance` + `backend`, fails under 85 % |
| `make eval` | golden Hit@5 gate (skills + interests) |
| `make build` | `NEXT_EXPORT=1 next build` (993 static routes) |
| `make blackbox` | `scripts/smoke_api.py` against `http://127.0.0.1:8000` |
| `make blackbox-prod` | the same black-box round against the Render API **and** the Vercel origin |

---

## 1. Executed in this sandbox — automated

### 1.1 White-box (pytest, 186 tests)

| Suite | Result |
| --- | --- |
| `tests/` (whole suite) | **190 passed** in ~49 s, 0 failures, 0 errors |
| Coverage (`--cov=career_guidance --cov=backend`) | **91 %** (5616 statements, 514 missed) — gate is 85 % |
| `tests/test_pathway.py` | 14 passed (ladder + pathway + gate evidence + phase maths) |
| `tests/test_admin_console.py` | 13 passed (401 / 403 / 200 / 404 / 422 per endpoint, audit trail) |
| `tests/test_journey_api.py` | 16 passed |
| `tests/test_core_v2.py` | 31 passed (incl. hash-seed determinism regression) |
| `tests/test_eval_golden.py` | Hit@5 gates for both golden suites |

Worked examples asserted by tests (real values, not smoke):

* Ladder maths: `HOURS_PER_SKILL = 14`, `MIN_COVERAGE = 0.18`, zone delta clamped −1…+2,
  entry rungs restricted to the same market family.
* Pathway verdicts: `eligible` / `reachable` / `blocked`, hard blockers only for
  preparation gaps and regulated-profession gates.
* Admin console: career overrides round-trip to the public career page, hidden
  careers 404, blank override maps → 422, unknown feedback/announcement id → 404,
  unknown setting key → 422, `audit_log` row for every write.

### 1.2 Evaluation harness (offline, no API keys)

| Suite | Hit@5 | MRR | p95 | Cases |
| --- | --- | --- | --- | --- |
| `eval/golden.json` (skills) | **1.0** | 0.827 | ~100 ms | 50 |
| `eval/golden_interests.json` | **1.0** | — | ~42 ms | 7 |

Verified **identical for `PYTHONHASHSEED` 0…5** (regression: matcher v2 used to
depend on set iteration order, which moved a golden case in and out of the top 5).

### 1.3 Lint / types / build

* `ruff check .` → *All checks passed* ; `ruff format --check .` → 79 files formatted.
* `npx tsc --noEmit` → clean (0 errors) with 371 extra + 97 core i18n keys × 3 locales type-checked.
* `npx eslint .` → 0 errors, 1 warning (`@next/next/no-page-custom-font` on the
  Google-Fonts `<link>` in `app/layout.tsx` — expected for the App Router).
* `NEXT_EXPORT=1 next build` → **995 static pages** (`/careers/[id]` × 974 + 20 routes),
  first-load JS ≤ 245 kB.

### 1.4 Black-box round (HTTP only, 43 checks)

`python scripts/smoke_api.py` against a live uvicorn — **43 passed, 0 failed**:

* public: `/health`, `/meta`, `/skills/suggest`, `/careers/search`, `/auth/*`;
* private by design → **401** for `POST /recommend`, `/assessment`, `/jobs/fit`,
  `/resume/extract`, `GET /history`, `GET /careers`, `GET /careers/{id}`;
* signed-in journey: profile → onboarding → target → readiness → ratings → plan →
  exports (`md`, `ics`, `json`, `pdf` validated by content, not just status);
* flagship: `POST /pathway` payload shape, `/pathway/signals`, `/ladder`,
  422 on an unknown experience level;
* documents: `/api/v1/me/report.pdf` and the legacy `/api/v1/reports/career.pdf`
  both start with `%PDF`;
* admin surfaces 403 for a non-admin session.

### 1.5 Accessibility & contrast (static analysis)

Contrast was computed, not eyeballed, from the design tokens
(`frontend/app/globals.css`) over every surface (`bg`, `bg-2`, `bg-3`, panel):

| Token | Before | After | Worst surface ratio |
| --- | --- | --- | --- |
| `--color-text-tertiary` (`text-fg-3`) | `#666666` (2.50:1) | `#909090` | **4.50:1** (bg-3) |
| `--color-destructive` (`text-danger`) | `#e05050` (3.71:1) | `#e86868` | **4.52:1** (bg-3) |
| `text-fg-2`, `text-fg`, `text-accent`, `text-gold`, `text-ok` | — | unchanged | ≥ 5.10:1 |

Also verified statically: `prefers-reduced-motion` zeroes animation/transition
durations app-wide; the skip-to-content link, `aria-label`s on icon-only
buttons, `aria-current="page"` in the sidebar, `aria-expanded` on disclosures,
`role="status"`/`role="alert"` on the cold-start banners, and `lang` switching
with the locale.

### 1.6 PWA assets

* `public/manifest.webmanifest` — name, standalone display, maskable + any icons,
  three shortcuts, `/dashboard` start URL.
* `public/sw.js` — cache-first for `/_next/static/**`, icons and fonts;
  network-first for navigations with `/offline.html` fallback; **`/api/**` is never
  cached or replayed** (per-account data).
* `scripts/make_icons.py` regenerates `icon-192.png`, `icon-512.png`,
  `icon-maskable-512.png`, `apple-touch-icon.png`.
* All four assets are present in the exported bundle (`frontend/out/`).

### 1.7 Bugs found and fixed by this round

| Symptom | Root cause | Fix |
| --- | --- | --- |
| `GET /admin/overview` → 500 once any recommendation run existed | `AnalyticsSummary` had no `top_skills`; requested skills were never aggregated | `summarize()` now counts tokens from `run.profile["skills"]` into `top_requested_skills` |
| A B.Sc Nursing graduate was told the *nursing* gate was unmet | the regulated-profession gate only looked at the degree field, not the résumé | `pathway.credential_evidence()` — phrases such as “nursing”, “GNM”, “MBBS”, “LLB” clear the gate and are shown as the evidence |
| Pathway plan claimed “24 weeks” for 168 study hours at 6 h/week | phase weeks were the chunk size (4), not the hours | phases now follow the running study-hour total, so `weeks == ceil(total_hours / hours_per_week)` |
| `/dashboard` “Download report” and `/reports/career.pdf` returned the SPA HTML shell | path never mapped | both point at `/api/v1/me/report.pdf` (legacy path aliased server-side) |
| Matcher ranking varied between processes (Hit@5 1.0 ⇄ 0.98) | set iteration order (hash seed) chose which skill “claimed” a competency hint | sorted iteration in `matching.py` (`implied`, tech hits, cosine) and `matching2.py` |

---

## 2. **Not testable in this sandbox — manual verification required**

The sandbox has **no browser, no Firebase/Google reachability, no external HTTP**
(`curl https://…` fails at the TLS handshake with `SSL_ERROR_SYSCALL`, and
`example.com` is equally unreachable). Nothing below has been executed; treat the
table as a to-do list, not as evidence.

### 2.1 Browser-only behaviour (no headless browser available)

| # | Item | Exact steps | Expected |
| --- | --- | --- | --- |
| B1 | Private app redirect | Open `https://career-guidance-web-sigma.vercel.app/` in a private window | Redirect to `/login?next=/`, no app content rendered |
| B2 | Google popup sign-in | On `/login` click **Continue with Google** | Popup completes, lands on `/dashboard`; the session cookie is `cg_session` |
| B3 | Redirect fallback (S1 2.3) | Block the popup (or use a domain that is not authorised), click the Google button again | A “Continue with Google (redirect)”-style fallback appears; the redirect flow completes and `getRedirectResult` on `/login` finishes the sign-in |
| B4 | Browser mismatch messages (S1 2.2) | Visit `/login` from a host that is **not** in Firebase → Authorised domains | The error text names the current `window.location.hostname` and the console path *Firebase → Authentication → Settings → Authorised domains → Add domain*; an unknown code renders `Sign-in failed (auth/xxx)` |
| B5 | Magic-link e-mail delivery | Request a magic link with a real address | Mail arrives (requires the SMTP env vars below); the link signs in and returns to `next` |
| B6 | Cold start banner (S1 2.4) | Open the Vercel URL after Render has slept (> 15 min idle) | “Waking up the server… (up to 60 s)” with automatic retry, not an error |
| B7 | Motion | Browse with *prefers-reduced-motion: reduce* set in the OS | Animations collapse to near-zero duration; layout unchanged |
| B8 | Lighthouse ≥ 90 (S5) | Chrome DevTools → Lighthouse → Mobile, on `/login`, `/dashboard`, `/recommend` (signed in) | Performance / Accessibility / Best-Practices / SEO ≥ 90 |
| B9 | WCAG AA spot check | axe DevTools browser extension on `/login`, `/dashboard`, `/recommend`, `/pathway` | 0 violations (contrast tokens already pass by computation) |
| B10 | Keyboard walk | `Tab` from the top of `/dashboard` | Skip-to-content appears first, focus ring visible on every control, sidebar uses `aria-current` |
| B11 | PWA install | Chrome → **Install app** on the Vercel URL; then take the network offline and reload | App installs with the sparkle icon; offline shows `offline.html`; `/api/*` is never served from cache |
| B12 | i18n rendering | Switch the locale switcher to தமிழ் / हिन्दी in the top bar | Every string on the S3 screens changes (Mozilla-independent check: no English leftovers on `/dashboard`, `/plan`, `/learn`, `/resume`, `/onboarding`) |
| B13 | PDF download | `/settings` → **Download the PDF report**, and `/dashboard` → **Download the PDF report** | A real PDF opens (server-rendered via reportlab) |
| B14 | Compare deep link | Open `/compare?ids=15-1199.08,13-2011.01` | Two careers compared side by side with the shared/unique skill split |

### 2.2 Firebase console (needs owner access to project `career-ai-ecba3`)

| # | Item | Steps |
| --- | --- | --- |
| F1 | Authorised domains | Firebase → Authentication → Settings → Authorised domains: add `career-guidance-web-sigma.vercel.app`, `localhost`, `127.0.0.1` and each Vercel preview domain (`career-guidance-web-*.vercel.app`; wildcards are not supported) |
| F2 | Providers | Authentication → Sign-in method: enable **Google** and **Email/Password** |
| F3 | Email templates / continue URLs | Authentication → Templates: confirm the action URL points at the app origin, otherwise `auth/unauthorized-continue-uri` appears (the code retries without the continue URL, which is the fallback, not the goal) |
| F4 | API key restrictions | Google Cloud console → APIs & Services → Credentials: the browser key must allow the Vercel origin (otherwise `auth/invalid-api-key` / `auth/configuration-not-found`) |

### 2.3 Third-party deployments and e-mail (needs the dashboards)

| # | Item | Steps | Expected |
| --- | --- | --- | --- |
| D1 | Render env vars | Render → the web service → Environment: set `SESSION_SECRET` (rotate it), `PUBLIC_URL`, `ADMIN_EMAILS`, `FIREBASE_*`, `GOOGLE_CLIENT_ID/SECRET` (if used) exactly as listed in `docs/DEPLOY.md` | Redeploy succeeds; `/api/v1/health` reports `{"status": "ok"}` |
| D2 | Vercel env vars | Vercel → project → Settings → Environment Variables: `NEXT_PUBLIC_API_BASE` (leave empty to use the rewrite) and `API_URL` (Render origin) | `/api/v1/health` through the Vercel origin returns 200 JSON, not HTML |
| D3 | SMTP (optional) | Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (Gmail app password) | Magic-link e-mails are delivered; `GET /api/v1/admin/system` reports `smtp: true` |
| D4 | Disk persistence | Render → Disk: 1 GB mounted at `/app/data` | SQLite survives a redeploy (log in, redeploy, session still valid) |
| D5 | Production smoke | `make blackbox-prod` **from a machine with internet** | 43 checks pass against both Render and Vercel |
| D6 | Cold-start timing | `time curl -s -o /dev/null -w '%{time_total}\n' https://career-guidance-llm-app.onrender.com/api/v1/health` after sleep | First call warms it (up to ~60 s), second call < 2 s |

### 2.4 Manual database / deployment steps

| # | Item | Steps |
| --- | --- | --- |
| M1 | In-place SQLite upgrade | Deploy; watch the Render logs for the migration lines | `migrate()` runs versioned, idempotent migrations **to v2**; re-running is a no-op; existing rows survive (verify with `GET /api/v1/history` after the deploy) |
| M2 | Backup / restore round-trip | `/admin` → System → **Download backup**, keep it; then restore via `POST /api/v1/admin/restore` | Data returns; `GET /api/v1/admin/audit` shows the `system:restore` entry |
| M3 | CSV catalogue import | `/admin` → Careers → import a small CSV | Rows appear in `/careers` and are audit-logged |
| M4 | Unmatched-skill mapping | `/admin` → Skills → map an unmatched skill from a real run | The skill resolves to a canonical on the next `/recommend` |
| M5 | Feature flags | `/admin` → Settings: flip `flags.module.discover` off | `/discover` returns 503 for signed-in users; the UI shows the disabled state; flip back |

### 2.5 Live data sources (deliberately not tested)

| # | Item | Note |
| --- | --- | --- |
| L1 | `market_seed.build_adapter(live=True)` | The live branch needs free API keys (Adzuna/USAJobs); production runs `ai_mode=false` and always uses the curated seed (`data/market_seed.yaml`, “Source: curated, updated 2026-09”). The curated path is covered by tests; **the live branch is not exercised anywhere yet** |
| L2 | LLM-enhanced provider | No API key exists and none will be added; `/recommend` runs matcher v2 with the offline fallback, and `is_demo`/`provider` in the response say so |
| L3 | `sendEmailVerification` / `sendPasswordResetEmail` retry-on-`auth/unauthorized-continue-uri` | Needs a real Firebase project; code path is unit-reviewed only |

---

## 3. Known limitations (not defects, but stated plainly)

1. **`pytest` coverage is 91 %, not 100 %** — the uncovered lines are network/live
   branches (L1, L2), Firebase REST calls, and defensive `except` blocks.
2. **The static export contains 995 HTML shells**; `/careers/[id]` pages are
   prerendered for the 974 catalogue ids, so a catalogue change needs a rebuild
   (the Vercel build is dynamic and unaffected).
3. **Service worker caching is shell-only** — a first-visit user who goes offline
   sees `offline.html`, never stale recommendations.
4. **Tamil/Hindi quality**: the 371 extra keys are translated, but sentences that
   embed O*NET labels (“zone 4”, “Bachelor's degree”) keep the English label inside
   the localised sentence, because the label is a data value, not UI copy.
5. **`/reports/career.pdf` is an alias** kept for continuity; the canonical path is
   `/api/v1/me/report.pdf`.
