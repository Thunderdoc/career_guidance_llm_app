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

## Still to build

- Institute seat management in the admin console (v1: admin assigns the
  Institute plan manually).
- Landing page in Tamil and Hindi (the signed-in app is trilingual;
  the landing is English-only for v1).

## Go-live checklist (owner decisions, in order)

1. **Prices** — Pro and Institute monthly prices in INR.
2. **Razorpay keys** — test-mode keys first, verify a test payment
   end-to-end, then live keys. Webhook secret goes in
   `RAZORPAY_KEY_SECRET`; register the webhook URL in the Razorpay
   dashboard (`{PUBLIC_URL}/api/v1/billing/webhook`).
3. **Business details** — legal name + contact email for Terms/Privacy/
   Refund pages.
4. **Sign-in delivery** — production magic links need real SMTP, or
   disable magic links and use Firebase/Google only.
5. **Hosting** — Render starter plan (the free tier sleeps; a buyer
   hitting a sleeping backend waits ~1 minute). Vercel needs `API_URL`
   and `NEXT_PUBLIC_API_BASE` pointing at the Render backend.
6. **Flip the switch** — confirm `BILLING_ENFORCE_PRO=true` (PDF paywall
   on) before announcing paid plans.

## Follow-ups (not blocking a sale)

- `SESSION_SECRET` fallback: production without a secret currently logs an
  error but keeps running; make it fail hard at startup in production.
- CORS is `allow_origins=["*"]` (no credentials); tighten to an env-driven
  list once the production frontend origin is fixed.
- Landing page in Tamil and Hindi (the signed-in app is trilingual).
- Institute seat management in the admin console.

## Deliberately NOT built

- No fake testimonials, no invented user counts, no placeholder prices.
- No Stripe (Razorpay covers UPI + cards for India; Stripe is a later
  addition if international buyers appear).
- No auto-renewal/subscription billing in v1: checkout sells a plan
  activation; renewals are manual until subscription demand is proven.
