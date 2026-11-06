# Selling this product — status and go-live checklist

## What "sell-standard" means here

A buyer must be able to: see what the product is **without signing in**,
try it, pay for Pro, and get Pro. Everything else is polish.

## Built (backend, local — needs a server restart to go live)

- **Plans API** — `GET /api/v1/billing/plans` (public): Free / Pro /
  Institute with feature lists. Prices come from env
  (`BILLING_PRO_PRICE_INR`, `BILLING_INSTITUTE_PRICE_INR`); an unset
  price renders as "Contact us", never an invented number.
- **Trial** — `POST /api/v1/billing/trial/start` (one-time Pro window,
  `BILLING_TRIAL_DAYS`, default 7). `GET /api/v1/billing/me` reports
  assigned plan, effective plan, trial state.
- **Razorpay checkout** — `POST /api/v1/billing/checkout` creates a real
  Razorpay order (UPI + cards) and records it in the `payments` table.
  Without `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` it answers 501.
- **Razorpay webhook** — `POST /api/v1/billing/webhook` verifies the
  HMAC-SHA256 signature and only `payment.captured` activates the plan.
- **Razorpay subscriptions (Phase 9)** — `POST /api/v1/billing/subscribe`
  is an ADDITIONAL auto-renew option beside the one-time checkout (the
  manual flow is unchanged). It needs Razorpay **plan ids** from env
  (`RAZORPAY_PRO_PLAN_ID`, `RAZORPAY_INSTITUTE_PLAN_ID` — created by the
  owner in the Razorpay dashboard). While keys are unset it answers
  501; while a plan id is unset it answers 409 "subscriptions not
  configured" — never a fake success, never an invented plan id. The
  webhook also handles `subscription.*` events (charged extends the
  period to Razorpay's absolute period end and activates the plan;
  cancelled/halted mark the status but the plan stays until the period
  end), idempotently via a webhook-events ledger. Subscriptions are
  created for 12 billing cycles (`SUBSCRIPTION_TOTAL_COUNT` in
  `career_guidance/billing.py`), after which the customer re-subscribes.
  **Not live until the owner sets keys + plan ids and registers the
  subscription webhook events in the Razorpay dashboard.**
- **Coupons (Phase 9)** — platform-admin only (`POST/GET
  /api/v1/billing/admin/coupons`, deactivate; audit-logged). Percent or
  flat-₹ codes with optional total cap, per-user cap (default 1) and
  expiry. Users preview via `POST /api/v1/billing/coupon/validate`
  (no state change); redemption happens inside checkout, priced
  server-side and recorded in the same transaction as the payment row.
  **No discount exists until the owner creates a coupon — there are no
  seeded codes or campaigns.**
- **Referrals (Phase 9)** — `GET /api/v1/me/referral` gives each user a
  code + counts. Checkout accepts a `referral_code` and records an
  attribution plus a *pending, valueless* reward record. **Referrals
  are attribution only in v1**: any actual discount for a referred user
  comes only from a coupon code that user redeems (a coupon the owner
  created). No reward amount is promised anywhere.
- **Institute analytics v2 (Phase 9)** — cohort endpoint gains
  term-over-term comparison (a term is a calendar quarter; current vs
  previous quarter aggregates + deltas over real stored runs only),
  the counsellor review queue returns unreviewed runs oldest-first
  with pagination, and institutes can record a `report_schedule`
  preference (`none|weekly|monthly`, with a nominal next-run date).
  **The schedule is a preference record only — no scheduler sends
  reports yet.**
- **Pro gate** — the roadmap PDF export (`/plan/{id}.pdf`) requires Pro
  while `BILLING_ENFORCE_PRO` is true (default). Markdown/JSON/ICS
  exports stay free. Set `BILLING_ENFORCE_PRO=false` to restore open
  access for every signed-in user.
- **Migration 3** — `users.plan`, `users.trial_ends_at`, `payments` table.
  Applies automatically on the next server start.

## Built (frontend, local — needs a rebuild to go live)

- **Public landing page** — the root route is now a server-rendered
  landing (hero, features, how it works, pricing from the plans API,
  FAQ, footer). Signed-in visitors are redirected to /dashboard by a
  small client island; the old tabbed shell still lives at /classic.
- **Pricing section** — reads live plan data; an unset price shows
  "Contact us".
- **Terms / Privacy / Refund pages** — honest templated content; the
  business name and contact email are marked placeholders the owner
  fills in before announcing paid plans.
- **In-app billing page** (`/billing`, linked in the sidebar) — current
  plan, trial button, per-plan actions, Razorpay Checkout.js payment
  flow (loaded on demand, only when keys are configured). Until keys
  are set, paid plans honestly show "Payments coming soon".
  Phase 9: a coupon code field (with a server-side discount preview)
  and an optional referral code field feed checkout; a "Subscribe
  (auto-renew)" option appears next to the one-time button ONLY when
  the plans API reports subscriptions enabled (keys + plan ids set);
  the account shows the user's own referral code and counts.

## Built (Phase 10 — scale, trust & launch finish)

- **First-load JS budget met on every route** — the i18n dictionaries
  are split per locale (EN bundled; TA/HI load on demand) and the
  Firebase SDK no longer ships in the shared bundle: every route in
  the static export is ≤245 kB first load (worst: /login 224 kB).
- **Public catalog caching** — `/meta`, `/skills/suggest`,
  `/careers/search`, `/careers/{id}` responses are cached in-process
  (300 s TTL; admins bypass career detail). See docs/PERFORMANCE.md.
- **Institute public API** — institutes can mint API keys (raw key
  shown once, SHA-256 at rest) for read-only, aggregate-only public
  endpoints (`/api/v1/public/institutes/{slug}/cohort`,
  `…/top-careers`). No personal data in payloads.
- **Status page** — `/status` shows live liveness/readiness from the
  visitor's browser.
- **Accessibility pass** — modal focus traps, tab keyboard pattern,
  AA-measured contrast (one failing token fixed). docs/ACCESSIBILITY.md.

## Still to build

- Institute seat management in the admin console (v1: admin assigns the
  Institute plan manually).

## GO-LIVE CHECKLIST — owner inputs ONLY

Everything not listed here is closed by the code. Each item is a value
or decision only the owner can supply; until it is supplied the
product degrades honestly (e.g. prices show "Contact us", payments
answer 501) rather than inventing anything.

1. **Prices** — Pro and Institute monthly prices in INR
   (`BILLING_PRO_PRICE_INR`, `BILLING_INSTITUTE_PRICE_INR`).
2. **Razorpay keys + plan ids + webhook** — test-mode keys first,
   verify a test payment end-to-end, then live keys
   (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`); create the Pro /
   Institute subscription plans in the Razorpay dashboard and set
   `RAZORPAY_PRO_PLAN_ID` / `RAZORPAY_INSTITUTE_PLAN_ID`; register the
   webhook URL (`{PUBLIC_URL}/api/v1/billing/webhook`) with the
   `payment.*` + `subscription.*` events enabled. (Coupons are
   optional and owner-created in the admin API — no coupon exists
   until you create one.)
3. **Business name + contact email** — the legal name and support
   e-mail shown on Terms / Privacy / Refund pages and invoices.
4. **SMTP or disable** — production SMTP credentials for magic links
   (`SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM`),
   or the decision to disable magic links and use Firebase/Google
   sign-in only.
5. **Render / Postgres decision** — stay on the free tier (sleeps;
   first hit waits ~1 minute), move to a paid Render plan, and/or set
   `DATABASE_URL` to a Postgres instance (the code option is built;
   the hosting spend is the owner's call). Vercel needs `API_URL` and
   `NEXT_PUBLIC_API_BASE` pointing at the backend either way.
6. **India data licences** — licensed salary/demand feeds to replace
   the labelled seed estimates in the Reality Score (until then every
   figure stays labelled `estimate` with its `as_of` date).
7. **Pilot college** — one institute to pilot with, plus its
   permission to use anonymised cohort results in marketing.

## Follow-ups (not blocking a sale)

- Institute seat management in the admin console.

## Deliberately NOT built

- No fake testimonials, no invented user counts, no placeholder prices.
- No Stripe (Razorpay covers UPI + cards for India; Stripe is a later
  addition if international buyers appear).
- ~~No auto-renewal/subscription billing in v1~~ — superseded by
  Phase 9: subscriptions are now built as an additional opt-in option,
  but they stay INACTIVE until the owner sets Razorpay keys + plan ids
  (checklist 2b). One-time checkout remains the default sale.
