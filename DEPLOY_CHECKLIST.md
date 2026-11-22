# DEPLOY CHECKLIST — Kaam-Vaani

_For Ankit's approval. NOTHING here deploys itself: every box
needs a human decision or a human tap. The step ends when this
checklist is approved — the deploy itself is a separate,
owner-approved action. Local branch `kaam-vaani`, HEAD `a8cfde5`
(21 Nov 2026). No push has happened; nothing below is live._

## 0. Decisions only Ankit can make (answer before any deploy)

- [ ] **D1 — Free vs Starter on Render.** `render.yaml` today says
  `plan: starter` ($7/month) with a 1 GB persistent disk, and
  `autoDeploy: true`. The free-only rule means the deploy must
  use the free tier UNLESS Ankit approves $7/month. Free =
  delete the `disk:` block, set `plan: free`, and accept that
  the SQLite file resets on every redeploy (schema migrations
  re-run on boot, so the app starts clean — but pilot data is
  lost). **Do not edit `render.yaml` without his approval (R6).**
- [ ] **D2 — Confirm the LIVE Render service state.** The file
  may not match reality: check the Render dashboard for the
  live plan, autoDeploy setting, env vars, and whether the
  service is the Blueprint one or a manual one. Record what is
  live before changing anything.
- [ ] **D3 — Postgres before real pilot data?** Render free
  wipes SQLite on deploy (R1). Before REAL users arrive, pilot
  data must live on Postgres (Supabase/Neon free tier). BUT:
  16 legacy stores still open SQLite directly (L54 split-brain
  boundary) — pointing production at Postgres today splits
  reads/writes across two databases. Decision: pilot on SQLite
  with the wipe risk accepted and documented, or do the
  store-by-store port first.
- [ ] **D4 — Push the `kaam-vaani` branch?** The branch is
  local-only. Pushing needs his approval tap (night batch,
  11:30 PM IST). Merging to `main` is a separate decision.
- [ ] **D5 — Audit-log prune (L49).** The log grows one row per
  returned candidate per employer search, with a 365-day
  retention POLICY recorded but no automated prune. Decide:
  accept growth for the pilot, or schedule the prune as a
  deliberate ops task. Do not automate it silently — the log
  is append-only by design.

## 1. Pre-deploy verifications (Muse runs, Ankit checks)

- [ ] **V1 — Full gate green on the deploy commit.** Backend
  1,132 passed + 3 skipped, coverage ≥85% (measured 93.52%);
  ruff clean; tsc + eslint clean; `NEXT_EXPORT=1` build exit 0
  (1,019 pages); KV eval PASS (faithfulness 0.948); golden +
  chat evals PASS. Re-run on the exact commit being deployed —
  do not trust an older gate.
- [ ] **V2 — No secrets in the repo.** Grep for keys/tokens/
  passwords in the diff being pushed. The repo must contain no
  API keys (none exist), no Firebase service-account JSON, no
  `.env` files. `git log` the branch for accidental commits.
- [ ] **V3 — F1–F10 acceptance.** The ten acceptance features in
  `docs/KAAM_VAANI_PLAN.md` (F1 voice onboarding → F10) pass
  their automated tests. The Stage 11 definition of done
  requires this explicitly.
- [ ] **V4 — Feature flags.** All six KV flags (`KV_VOICE`,
  `KV_RAG`, `KV_EMPLOYERS`, `KV_CONSENT`, `KV_VIDEO_CHECK`,
  `KV_PILOT`) default ON unless `APP_ENV=production`. Decide
  per flag what production gets — a flag-off router answers
  404, which is the safe way to ship dark.
- [ ] **V5 — CORS.** `CORS_ALLOW_ORIGINS` MUST be set to the
  production front-end origin. The default is `*` (credentials
  off) — fine for dev, not for production. Do not change the
  code default (it would break the live deployment); set the
  env var on Render.
- [x] **V6 — ffmpeg.** DONE 22 Nov 2026: `ffmpeg` added to the
  Dockerfile (Stage 2, one `apt-get` line, `--no-install-recommends`;
  Debian's `ffmpeg` package ships both ffmpeg and ffprobe, verified
  on packages.debian.org for bookworm). Takes effect on the next
  Render rebuild — until then the old image still 503s the video
  check, which is the designed behaviour, not a crash.
- [ ] **V7 — Two workers vs one.** The Dockerfile runs uvicorn
  with `--workers 2`; the load test measured ONE worker. Two
  workers means: rate-limit budgets are per-process (a caller
  gets 2× the budget across workers), and the in-memory caches
  don't share. Not a blocker — but the measured shape differs
  from the shipped shape, and the deploy should know it.
- [ ] **V8 — HSTS.** The app sets NO HSTS header (by design —
  the platform must provide it). Confirm Render/Vercel serve
  HSTS on the production origins; do not add it in app code
  without a review (a wrong HSTS header bricks the domain).
- [ ] **V9 — Firebase phone sign-in.** The employer phone OTP
  (`/employers/mine/verify-phone`) needs Firebase phone
  auth enabled in the Firebase console. Owner-only step (Stage
  5). Without it, verify-phone fails and employer verification
  falls back to the human review queue.
- [ ] **V10 — Seed data.** Confirm the 40 listings / 10 sample
  workers / 5 employers / 3 coordinators / 5 fake listings are
  wanted on the deployed instance (they are labelled "sample
  data"). For a real pilot, seed then delete the fakes via the
  admin console — or deploy clean and seed via the pilot bulk
  endpoint.

## 2. Deploy sequence (staging first, then production)

- [ ] **S1 — Push `kaam-vaani` to GitHub** (approval tap, night
  batch). Verify the push on github.com (branch + HEAD hash).
- [ ] **S2 — Deploy backend to Render** (Blueprint apply or
  manual deploy from the branch, per the D2 finding). Wait for
  the health check (`/api/v1/health`) to pass.
- [ ] **S3 — Deploy frontend to Vercel** (Root Directory:
  `frontend`, branch `kaam-vaani`). Verify the deploy URL.
- [ ] **S4 — Smoke tests on the LIVE URLs** (not localhost):
  - `/api/v1/health` 200, `/api/v1/ready` 200
  - `/voice` loads; typed Tamil profile extracts + confirms
  - `/api/v1/kv/rag/ask` returns a cited answer
  - `/rights` answers + shows 1930 escalation on a scam question
  - `/jobs` lists verified listings; a fake seed listing shows flagged
  - `/pilot` 403 for a non-coordinator, 200 for a coordinator
  - `/video-check` uploads a 30 s clip → usable/unusable verdict
    (a 503 here means the deploy did not pick up the ffmpeg image — see V6)
  - `DELETE /api/v1/kv/me/data` on a test account erases KV rows
- [ ] **S5 — Mic check on a REAL phone (L25).** The voice mic
  path is unverified headless. On a low-end Android, on the
  deployed URL: tap mic, speak Tamil, confirm the transcript
  arrives. Also confirm `Permissions-Policy: microphone=(self)`
  allows it on the Render-served origin (the 9.4 fix).
- [ ] **S6 — Demo rehearsal.** Run the 3-minute demo script
  (`docs/pitch/demo-script-3min.md`) end to end on the deployed
  URL, warm (first request after a cold start pays ~4.3 s for
  the retriever build). Note any line that fails and fix it
  before the round — do not rehearse around a failure.

## 3. Post-deploy (first 48 hours)

- [ ] **P1 — Watch the logs** for 500s, 429 spikes (a limiter
  mis-firing on real traffic), and the video-check 503 rate.
- [ ] **P2 — Confirm the first retriever build** happened (warm
  the URL after every deploy — a cold first user waits ~4 s).
- [ ] **P3 — Rollback plan.** If the deploy breaks the live
  Career Guidance app: Render → roll back to the previous
  deploy; Vercel → roll back to the previous deployment. Both
  are one-click; no data migration is involved (v1–14 apply
  cleanly, and the KV tables are additive — no legacy table was
  altered).
- [ ] **P4 — Tell the pilot institute** the URL, the coordinator
  login path, and the known gaps (English answers, TN state
  wages absent, video check experimental). Do not oversell.

## 4. What this checklist deliberately does NOT approve

- Any paid tier (Render Starter, or any paid service) — D1.
- Any new API key — none exists, none is needed.
- Pushing to `main` or merging — D4 covers the branch push only.
- Real-user data collection beyond the pilot plan
  (`docs/pitch/impact-measurement-plan.md`) — the week-0
  baseline comes first.
- Legal/DPDP compliance — flagged for legal review
  (COMPLIANCE.md §4a); this checklist does not claim it.
