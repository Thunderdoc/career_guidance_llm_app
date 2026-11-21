# RUNBOOK — Career Guidance AI + Kaam-Vaani

Operations notes: incidents, rollbacks, key rotation. Started in
Kaam-Vaani Stage 1; extended at every stage that adds something
operational. Honest scope: this documents the procedures that exist
today — anything not yet built is listed as such, not implied.

## 1. Service map

| Piece | Where | Notes |
|---|---|---|
| Frontend | Vercel (Root Directory `frontend`, static export) | `NEXT_PUBLIC_*` vars are baked in at build time |
| Backend | Render Docker service | Serves `frontend/out` for direct Render-URL visits |
| Database | SQLite at `data/career_guidance.db` (Render disk `/app/data`) or Postgres via `DATABASE_URL` | Migrations v1–v13 run on startup (`career_guidance/migrations.py`) |
| Auth | Firebase Auth (ID tokens) + Google OAuth + magic link | Session cookie `cg_session`, 30-day TTL |
| LLM | Provider factory (`career_guidance/providers.py`) | Offline fallback when no key is configured |

Health: `GET /api/v1/health` (liveness). Readiness: `GET /api/v1/ready`
(DB + catalog, 503 when not ready). Every response carries
`X-Request-ID` — quote it in incident notes.

## 2. Kaam-Vaani feature flags (Stage 1)

Backend flags (`KV_VOICE`, `KV_RAG`, `KV_EMPLOYERS`, `KV_CONSENT`,
`KV_VIDEO_CHECK`, `KV_PILOT`) default ON unless `APP_ENV=production`;
explicit env always wins. Frontend mirrors (`NEXT_PUBLIC_KV_*`,
`frontend/lib/flags.ts`) share the defaults but are baked into the
static export at build time.

**Rolling a Kaam-Vaani feature back:** set the backend flag to `false`
in the Render env vars and restart the service — the route starts
404ing as JSON immediately. Then set the matching `NEXT_PUBLIC_KV_*`
flag to `false` in Vercel and redeploy so the UI stops offering the
feature. Backend-first matters: a hidden UI with a live route is a
smaller hole than a live UI over a dead route (the voice page degrades
to a notice when its flag is off, but other surfaces may not).

**Checking flag state live:** `GET /api/v1/kv/voice/status` answers
200 with the voice providers when `KV_VOICE` is on, 404 when off.
Since Stage 3 it also reports the STT/TTS gateway (configured vs
effective provider — a hosted provider without its key shows as
fallen back to `browser`, never as live) and the extraction mode
(`llm` only when a provider is configured, else `deterministic`).
The voice router's other endpoints are `POST /extract` (transcript
or per-question answers → structured profile; the `method` field
says honestly which path produced it) and `POST /confirm`
(validates the confirmation transition; illegal transitions 400).
There is no admin UI for flags yet (Stage 1) — env vars only.

The employer router (`/api/v1/kv/employers/*`, Stage 5) offers
`GET /employers/status` (flag state, phone-OTP availability, LLM
risk-score config, pay-plausibility status), employer
registration/profile, `POST /employers/mine/verify-phone`
(Firebase ID-token exchange — 503 until phone sign-in is enabled
in the Firebase console, owner step), listing CRUD with the
scam check on every create/edit, `GET /listings` (public,
verified-only), `POST /listings/{id}/report` (worker reports;
3 open reports auto-flag), and the admin queue under
`/api/v1/kv/admin/*` (review-queue, review employers/listings,
endorse, review reports — all audited). Sample data:
`scripts/seed_kv_listings.py` (idempotent; `--force` re-seeds;
exits 2 if a fake listing scores below the flag threshold).

The consent router (`/api/v1/kv/consent/*`,
`/api/v1/kv/worker-profile`, `/api/v1/kv/employers/matching/*`,
`/api/v1/kv/hire-outcomes/*`, Stage 6, behind `KV_CONSENT`)
offers `GET /consent/status` (public: the shareable fields with
their plain-language explanations, durations, outcomes),
worker-profile save/get, grant/revoke/mine/audit, ranked
consented candidates (verified employers and verified listings
only), shortlist, contact requests, and hire outcomes with
day-30/90 follow-ups. Sample data:
`scripts/seed_kv_workers.py` (idempotent; `--force` re-seeds
via `delete_sample_data` — audit rows are never deleted;
exits 2 if the listings seed has not run yet). Live
end-to-end check: `scripts/verify_kv_stage6.py --base-url
http://127.0.0.1:8102` against a running backend on a scratch
DB (22 checks incl. all negative cases; exit 0 only when
every check passes). **Consent incidents:** a worker's
consents and audit trail are visible to the worker on
`/sharing`; there is no admin consent view yet (L48) — a
consent dispute today needs a database read of `kv_consents`
+ `kv_consent_audit`. Revocation is immediate and final; a
revoked consent cannot be un-revoked (the worker grants a
fresh one instead).

## 3. Database

**Migrations are forward-only.** There is no down-migration: a bad
migration is fixed by a new forward migration, or by restoring the
database from backup (see below). The runner (`migrate()`) applies
pending versions in one transaction each and records them in
`schema_migrations`; re-running is a no-op. Never hand-edit the live
schema — add a migration.

**Backups (SQLite):** copy `data/career_guidance.db` while the app is
stopped, or use SQLite's `.backup` command against the running file.
On Render free tier the filesystem is ephemeral — the DB file does
NOT survive a deploy there (see ARCHITECTURE.md §2.3). Before any
real pilot, move to Postgres (`DATABASE_URL`, Supabase/Neon free
tier); the migration runner and the core store already support it,
but the per-feature-store boundary in `docs/DEPLOY.md` §6 still
applies — confirm before switching production.

**Checking the applied version:** `SELECT version, name, applied_at
FROM schema_migrations ORDER BY version;` — latest is v14 (Kaam-Vaani
Stage 6: `kv_worker_profiles`, `kv_consents`, `kv_consent_audit`,
`kv_shortlists`, `kv_contact_requests`, `kv_hire_outcomes` tables).

### 3.1 Postgres cutover (Step 7C, verified 21 Nov 2026)

**What is proven:** migrations 1..14 apply on a real Postgres 16.2
in one call (re-run is a no-op), and the migration runner, the core
store and all Kaam-Vaani stores round-trip on Postgres (RAG chunks,
employers/listings, consents + audit). The check is committed:
`KV_TEST_POSTGRES_URL=<scratch-url> pytest tests/test_kv_step7c.py -q`
(needs `psycopg` — `pip install -r requirements-postgres.txt`).
Run it against a SCRATCH database before any cutover — the live
test expects an empty DB and writes test rows into it.

**What is NOT proven (the boundary):** the legacy per-feature
stores (users, profiles, journey, billing, verification,
institutes, legacy consent, content, coupons, gamification,
RIASEC, roadmap, settings, sharing, synonyms, api_keys, admin
console) open the SQLite file directly. With `DATABASE_URL` set,
they keep using `DATABASE_PATH` — the app runs split-brain (core +
Kaam-Vaani on Postgres, the rest on SQLite). Do not cut production
over until those stores are ported behind the dialect layer,
store by store. See `docs/DEPLOY.md` §6.

**Cutover steps (staging first, no production data):**

1. Provision the Postgres instance (Supabase/Neon free tier, or
   the Render add-on — free-only rule: confirm the tier has no
   expiry that breaks the pilot); copy its connection URL.
2. Install the driver in the image:
   `pip install -r requirements-postgres.txt`.
3. Set `DATABASE_URL=<redacted>
   (keep `DATABASE_PATH` set for the remaining SQLite stores).
4. Boot the app; the migration runner applies 1..14 on Postgres
   automatically. Verify:
   `SELECT version FROM schema_migrations ORDER BY 1;`
   (expect 1..14) and `GET /api/v1/ready` →
   `checks.database == "ok"`.
5. Smoke: one anonymous `POST /api/v1/recommend`, one
   `POST /api/v1/kv/rag/ask`, one employer registration +
   listing create; confirm rows in `recommendation_runs`,
   `kv_rag_chunks`, `kv_employers` on Postgres.
6. Roll back by unsetting `DATABASE_URL` and redeploying; the
   SQLite file was never modified by the Postgres path.

**Local Postgres for testing (this sandbox runs as root, and
Postgres refuses to run as root):** install `pgserver` + psycopg
into a scratch venv, open the bundled libs for the `nobody` user
(`chmod -R o+rX <venv>/lib/python3.12/site-packages/pgserver.libs
<venv>/.../pgserver/pginstall`), then init + start as `nobody`:

```bash
PG=<venv>/lib/python3.12/site-packages/pgserver/pginstall/bin
mkdir -p /tmp/kv-pgdata /tmp/kv-pgrun && chown nobody:nogroup /tmp/kv-pgdata /tmp/kv-pgrun
runuser -u nobody -- $PG/initdb -D /tmp/kv-pgdata --auth=trust -U postgres
runuser -u nobody -- $PG/pg_ctl -D /tmp/kv-pgdata \
  -o "-k /tmp/kv-pgrun -p 54333 -c listen_addresses=127.0.0.1" \
  -l /tmp/kv-pg.log start
# then: KV_TEST_POSTGRES_URL=postgres://postgres@127.0.0.1:54333/<db>
# stop with: runuser -u nobody -- $PG/pg_ctl -D /tmp/kv-pgdata stop
```

## 4. Key rotation

| Secret | Rotation procedure |
|---|---|
| `SESSION_SECRET` | Set the new value in Render env vars and restart. **All sessions invalidate** — every signed-in user must sign in again. Rotate only with a user-facing notice, or accept the sign-outs. There is no dual-secret grace period yet. |
| `GOOGLE_CLIENT_SECRET` | Rotate in Google Cloud console, update Render env vars, restart. No user impact (per-login flow). |
| `RAZORPAY_KEY_SECRET` | Rotate in the Razorpay dashboard, update env vars, restart. In-flight checkouts fail and must be retried by the user. |
| Firebase | No server secret is held (ID tokens verify against Google's published certs, fetched and cached). Nothing to rotate server-side. |
| LLM provider keys (`OPENAI_API_KEY`, `GEMINI_API_KEY`) | Rotate at the provider, update env vars, restart. The app falls back to offline matching while a key is invalid — never a hard outage. |

Secrets live in env vars only — never in the repo, never in logs
(PII redaction: `career_guidance/logging_setup.py`).

## 5. Incidents

**App won't start in production:** the most common cause is a missing
`SESSION_SECRET` (the app refuses to start without it when
`APP_ENV=production` — see `backend/auth.py`). Check the Render logs
for the exact message before anything else.

**500s on every request:** check `GET /api/v1/ready` — it names the
failing component (database or catalog). If the database check fails,
confirm the disk mount (`/app/data`) and that migrations ran
(startup logs show `Database migrated to v…`).

**Eval gate red in CI:** the golden eval (`python -m eval.run
--min-hit 0.75`) gates every push. A Hit@5 drop means the matcher
changed — do not lower the threshold to pass; find the regression.
The Kaam-Vaani eval gate (`eval/run_kv.py`, Stage 2+) is a no-op
until the script exists — if it starts failing after Stage 2, the
thresholds are in `ARCHITECTURE.md` §3.7 and the actuals belong in
`EVAL_REPORT.md`.

**A Kaam-Vaani route 404s unexpectedly:** check the flag first
(`KV_*` in Render env vars; remember the production default is OFF),
then the deploy log (did the new code actually deploy — Render
autoDeploy state is unconfirmed, see ARCHITECTURE.md §2.3).

## 6. Agent trace log (Step 8.9)

Every `/ask`, `/search`, `/extract` and `/matches` call is traced
(translation / retrieval / ranking / verification stages with
latencies). Traces hold NO PII by construction — the question is
identified by a hash, span details carry counts and scores only.
The response carries its `trace_id` for correlation.

- **Read (admin only):** `GET /api/v1/kv/traces?limit=50`
  (newest first) and `GET /api/v1/kv/traces/{trace_id}` (404 when
  unknown or aged out). The router mounts when KV_RAG or KV_VOICE
  is on; without an admin session both endpoints 403.
- **Storage:** an in-memory ring (default 200 traces,
  `KV_TRACE_MAX_TRACES`) plus an optional JSONL file sink
  (`KV_TRACE_FILE`; off by default). The file rotates at 10 MB,
  keeping 3 files (~30 MB max). A restart starts empty in memory;
  the file is the only durable copy.
- **Retention:** size-bounded, NOT time-based. Recommended ops
  retention is 7 days — enforce it with a logrotate/pruning cron
  on the JSONL file; no time-based pruning is built in (L62).
- **Correlating a user report:** hash the reported question with
  SHA-256 and take the first 16 hex chars — that is the trace's
  `query_hash`. (Only works when the report quotes the question
  exactly; the trace never stores the text itself.)

## 7. What does not exist yet (Stage 1)

- No error-tracking dashboard (the `ERROR_WEBHOOK_URL` hook posts a
  minimal JSON payload on unhandled 500s; nothing consumes it yet).
- No uptime check / alerting — manual `GET /api/v1/health` only.
- No admin UI for feature flags (env vars only).
- No automated backups — manual copies (see §3).
- No dual-secret session rotation (see §4).
