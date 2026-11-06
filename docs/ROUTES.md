# Route Map — Career Guidance AI (Phase 1 consolidation)

_Date: 2026-11-06 · Phase 1 of docs/UPGRADE_PLAN.md_

The product presents **7 surfaces**. Navigation shows only these; every
pre-Phase-1 route keeps working — old paths redirect to the surface that
replaced them (see the table below), so no bookmark, shared link, e-mail
link or exported reference breaks.

## The 7 surfaces

| Surface | Route | What it is |
| --- | --- | --- |
| Landing | `/` | Public landing: hero, live try-it, sample report, differentiators, trust strip, how it works, pricing + institute demo form, FAQ, footer. |
| Start | `/start` | 4-step wizard (persona → skills/interests → constraints → goal). Guest-first: no sign-in needed for the first result. Draft autosaves to localStorage. |
| Career Report | `/report/[runId]` | The report for one recommendation run: matches, match scores, priority skills, source labels. Guests see the run they just made (kept in sessionStorage); signed-in users can also open saved runs. Save/export/plan actions ask for sign-in. |
| Plan | `/plan` | Learning roadmap / plan surface (existing journey plan, learn and pathway views live here via tabs). Sign-in required. |
| Explore | `/explore` | Browse and compare careers, job-fit check, interest discovery and career transitions — one surface, tabs: `?tab=careers|compare|jobfit|discover|transitions`. Sign-in required (career search itself is also public from the landing/start flow). |
| Account | `/account` | Everything about the signed-in user, tabs: `?tab=history|billing|settings` (history & progress, plan/billing, settings incl. export/delete-my-data). Sign-in required. |
| Admin | `/admin` | Admin console. Admin role verified server-side on every API call. |

## Legal & trust routes

| Route | Status |
| --- | --- |
| `/terms` | live |
| `/privacy` | live |
| `/refund` | live |
| `/methodology` | **future (Phase 5)** — listed here so the slot is reserved; not yet built, and nothing links to it yet |

## Supporting routes (real pages, not in the 7-surface nav)

| Route | Why it stays |
| --- | --- |
| `/login` | Sign-in (Firebase Google / e-mail). Auth is a route, not a surface. |
| `/dashboard` | Signed-in home; the landing redirects signed-in visitors here. |
| `/careers/[id]` | Public, indexable career detail pages (974). Only the `/careers` index redirects. |
| `/resume` | Résumé tools (scoring) for signed-in users. |
| `/interview` | Interview-prep kit for signed-in users. |
| `/classic` | The legacy tabbed shell. Reachable by URL for support/comparison, **removed from navigation**. |

## Old route → new surface redirects

Implemented in `frontend/next.config.ts` (`redirects()`, non-permanent so
the map can still evolve). In the static-export production build
(`NEXT_EXPORT=1`) Next.js cannot emit server redirects; there the old
pages still exist, so links keep working, and the new surfaces are the
canonical navigation targets.

| Old route | Redirects to |
| --- | --- |
| `/recommend` | `/start` |
| `/onboarding` | `/start` |
| `/discover` | `/explore?tab=discover` |
| `/careers` | `/explore?tab=careers` |
| `/compare` | `/explore?tab=compare` |
| `/jobfit` | `/explore?tab=jobfit` |
| `/transitions` | `/explore?tab=transitions` |
| `/history` | `/account?tab=history` |
| `/billing` | `/account?tab=billing` |
| `/settings` | `/account?tab=settings` |
| `/learn` | `/plan` |
| `/pathway` | `/plan` |

## API access model (Phase 1 guest-first)

| Access | Routes |
| --- | --- |
| Public | `GET /api/v1/health`, `GET /api/v1/meta`, `GET /api/v1/skills/suggest`, `GET /api/v1/careers/search`, `GET /api/v1/billing/plans`, `POST /api/v1/billing/demo-request` |
| Public, rate-limited, anonymous | `POST /api/v1/recommend` — anonymous runs are stored with `user_id = NULL`, flagged `anonymous`, and are never visible in any user's history or exports |
| Signed-in only (401 anonymous) | `/history`, `/export/*`, `/analytics`, `/assessment*`, `/jobs/fit`, `/resume/*`, `/careers/{id}`, all `/me/*`, all journey routes (`/plan`, `/learn`, `/profile`, …) |
| Admin only (401 anonymous / 403 non-admin) | all `/admin/*`, `GET /api/v1/billing/demo-requests` |
