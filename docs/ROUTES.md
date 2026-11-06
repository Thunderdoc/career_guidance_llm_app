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
| Account | `/account` | Everything about the signed-in user, tabs: `?tab=history|billing|settings|verify|institute|privacy` (history & progress, plan/billing, settings incl. export/delete-my-data, Phase 3 skill verification + public-profile controls, Phase 4 institute portal, Phase 5 privacy: age declaration + parental consent — code-split tabs). Sign-in required. |
| Institute | `/institute` | Phase 4: the same institute portal as the account tab, as its own route — create/claim an institute, invite members (e-mail list or CSV with per-row errors), seat usage, aggregate cohort dashboard, needs-attention list, counsellor review queue; students see their institute + counsellor review status. Sign-in required. |
| Admin | `/admin` | Admin console. Admin role verified server-side on every API call. |
| Public profile | `/p/[handle]` | Phase 3: a user's opt-in public profile — display name, verified skills, projects, 90-day plan progress only. 404 when not opted in; always 404 for under-18 accounts. |

## Legal & trust routes

| Route | Status |
| --- | --- |
| `/terms` | live |
| `/privacy` | live |
| `/refund` | live |
| `/methodology` | live (Phase 5): how matching + the Reality Score work, sources, known limits — guidance, not a guarantee of employment. Linked from the landing footer and the privacy notice. |

## Supporting routes (real pages, not in the 7-surface nav)

| Route | Why it stays |
| --- | --- |
| `/login` | Sign-in (Firebase Google / e-mail). Auth is a route, not a surface. |
| `/dashboard` | Signed-in home; the landing redirects signed-in visitors here. |
| `/careers/[id]` | Public, indexable career detail pages (974). Only the `/careers` index redirects. |
| `/resume` | Résumé tools (scoring) for signed-in users. |
| `/interview` | Interview-prep kit for signed-in users. |
| `/classic` | The legacy tabbed shell. Reachable by URL for support/comparison, **removed from navigation**. |
| `/shared/[token]` | Phase 8: public read-only view of a shared report (static-export placeholder pattern, token resolved client-side). Renders ONLY the share-safe allowlist payload — never owner identity, constraints or profile text. `noindex`. |
| `/offline` | Phase 8: localised offline page (EN/TA/HI). The service worker's offline fallback is the separate dependency-free `frontend/public/sw-offline.html` (see README → PWA). |
| `/status` | Phase 10: live service status — checks `/api/v1/health` + `/api/v1/ready` from the visitor's browser at view time (checking/ok/down states, nothing cached), localised EN/TA/HI, `noindex`. |

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
| Public | `GET /api/v1/health` (liveness), `GET /api/v1/ready` (readiness: DB + catalog, 503 with component breakdown when not ready — Phase 6), `GET /api/v1/meta`, `GET /api/v1/skills/suggest`, `GET /api/v1/careers/search`, `GET /api/v1/billing/plans`, `POST /api/v1/billing/demo-request`, `GET /api/v1/p/{handle}` (opt-in public profiles only; 404 otherwise, always for minors) |
| Public, rate-limited, anonymous | `POST /api/v1/recommend` — anonymous runs are stored with `user_id = NULL`, flagged `anonymous`, and are never visible in any user's history or exports |
| Run-scoped (Phase 7) | `POST /api/v1/chat` — rate-limited 20/min; signed-in callers may chat over their own runs or an anonymous run, guests only over anonymous runs; any other user's run answers 404. Answers are grounded only in that run's stored report + named taxonomy entries, with deterministic off-topic refusal |
| Signed-in only (401 anonymous) | `/history`, `/export/*`, `/analytics`, `/assessment*`, `/jobs/fit`, `/resume/*`, `/careers/{id}`, all `/me/*` (incl. Phase 5 `/me/consent`, `/me/consent/request`, `/me/consent/revoke`, `/me/age-declaration`), all journey routes (`/plan`, `/learn`, `/profile`, …), all `/skills/verify/*`, `/plan/90day*`, `POST /api/v1/institutes`, `/institutes/mine`, `/institutes/invites/claim`, `/institutes/reviews/mine` |
| Public, token-secured (no session) | `GET /api/v1/consent/confirm/{token}` — guardian decision link (grant/deny/revoke); token hashed at rest, 72 h expiry; 404 unknown, 410 expired, 409 already decided; rate-limited |
| Owner only (signed-in owner, or guest session for an anonymous run) | `POST /api/v1/runs/{run_id}/share` (create, expiry_days 1–30, default 7 — a code constant, not env), `GET /api/v1/runs/{run_id}/shares` (metadata list), `DELETE /api/v1/runs/{run_id}/share/{token_id}` (revoke; idempotent). Non-owners answer 403, unknown runs 404; a signed-in caller cannot manage an anonymous run's links |
| Public, token-secured, rate-limited (Phase 8) | `GET /api/v1/shared/{token}` — the share-safe report view, built from a field allowlist (`report_v1` scope in `career_guidance/sharing.py`): career titles, match %, matching/missing skills, Reality Score + labelled-estimate salary ladder, learning path. NEVER owner name/e-mail/handle, constraints (city/budget), raw profile text, institute or counsellor data. 404 unknown/deleted run, 410 expired or revoked |
| Institute staff only (401 anonymous / 403 student, outsider, other institute, or non-member platform admin) | `/institutes/{id}/cohort`, `/students…`, `/review-queue`, `/runs/{run_id}/review`, cohort `report.csv`/`report.pdf`, member list — institute_admin/counsellor of that institute; invites, member removal and branding are institute_admin of that institute only. Phase 9: `cohort?period=current\|previous` adds calendar-quarter term-over-term comparison; `review-queue` is unreviewed-only, oldest first, `limit`/`offset` paginated; `report_schedule` is set via the branding PATCH (institute_admin) |
| Admin only (401 anonymous / 403 non-admin) | all `/admin/*`, `GET /api/v1/billing/demo-requests`, `POST /api/v1/skills/verify/admin/review` (platform admin, or institute staff for their own students), Phase 9 coupon admin: `GET/POST /api/v1/billing/admin/coupons`, `POST /api/v1/billing/admin/coupons/{code}/deactivate` (audit-logged) |
| Signed-in only, Phase 9 billing | `POST /api/v1/billing/subscribe` (501 while Razorpay keys unset, 409 while the plan's plan-id env is unset), `POST /api/v1/billing/coupon/validate` (preview only, no state change), `GET /api/v1/me/referral` (own code + attribution counts) |
| Institute API keys (Phase 10) | Key management `POST/GET/DELETE /api/v1/institutes/{id}/api-keys` — institute_admin of that institute or a platform admin (401 anonymous, 403 other roles; audit-logged; raw key shown once at creation, SHA-256 hash at rest). Public reads `GET /api/v1/public/institutes/{slug}/cohort` + `…/top-careers` — `X-API-Key` header ONLY (session cookies do not authenticate), key bound to the slug's institute (mismatch → 404), 401 missing/wrong/revoked, 30/min per-key rate limit, aggregates only (needs-attention reduced to a count; no e-mails/names/user ids) |
| Public webhook (HMAC-verified, no session) | `POST /api/v1/billing/webhook` — Razorpay; signature verified before any row is touched (401 on mismatch, 501 while keys unset). Handles `payment.captured` and `subscription.*` (idempotent via the `webhook_events` ledger) |
