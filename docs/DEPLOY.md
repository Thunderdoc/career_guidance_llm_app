# Deployment guide — Career Guidance AI

Two managed services plus Firebase Authentication:

| Piece | Platform | URL | Root |
| --- | --- | --- | --- |
| API (FastAPI + SQLite) | **Render** (Docker) | `https://career-guidance-llm-app.onrender.com` | repo root |
| Web (Next.js 15) | **Vercel** | `https://career-guidance-web-sigma.vercel.app` | `frontend` |
| Auth | **Firebase** project `career-ai-ecba3` | — | — |

The browser only ever talks to the Vercel origin: `frontend/next.config.ts`
rewrites `/api/:path*` to `API_URL`, so session cookies stay first-party and no
CORS configuration is needed in production.

---

## 1. Render (backend)

### 1.1 Blueprint or manual service

`render.yaml` at the repo root describes the service. Either press
**New → Blueprint** and pick this repo, or create the service manually with:

* **Type**: Web Service · **Runtime**: Docker · **Dockerfile path**: `./Dockerfile`
* **Health check path**: `/api/v1/health`
* **Instance type**: Starter (see the disk note below)
* **Disk**: name `career-data`, mount path `/app/data`, 1 GB

> **Free-tier caveat.** Render rejects a Blueprint that attaches a persistent
> disk to a `plan: free` instance, and free containers also sleep after ~15 idle
> minutes. Two supported setups:
> * **Starter** – keep the disk; SQLite (`/app/data/career_guidance.db`) survives
>   redeploys. Recommended once real users have accounts.
> * **Free** – delete the `disk:` block. The filesystem is ephemeral, so the
>   database resets whenever the container is replaced. The schema migrates
>   itself on every boot (`career_guidance/migrations.py`), so the app always
>   comes up in a working (empty) state.
>
> The front end already handles the 30–60 s cold start with a
> “Waking up the server… (up to 60 s)” banner and automatic retries
> (`frontend/lib/api.ts`).

### 1.2 Environment variables (Render)

| Variable | Required | Value / purpose |
| --- | --- | --- |
| `APP_ENV` | ✅ | `production` (disables dev-only helpers, logs a loud warning if the session secret is missing) |
| `SESSION_SECRET` | ✅ | 32+ random chars, signs session cookies. `generateValue: true` in the Blueprint. **Rotating it signs everybody out.** |
| `PUBLIC_URL` | ✅ | `https://career-guidance-web-sigma.vercel.app` — used for redirects and magic links |
| `ADMIN_EMAILS` | ✅ | `ankitraj2163@gmail.com` (comma-separated; anyone listed becomes admin on first sign-in) |
| `FIREBASE_PROJECT_ID` | ✅ | `career-ai-ecba3` — enables `/api/v1/auth/firebase` (ID-token verification needs no service account) |
| `DATABASE_PATH` | ✅ | `/app/data/career_guidance.db` |
| `PUBLIC_APP` | ⬜ | `false` (default): the product is private, every content route returns **401** without a session. `true` re-opens anonymous access (guest mode). |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `SMTP_FROM` | ⬜ | Only for the e-mail magic-link fallback. Gmail: host `smtp.gmail.com`, port `587`, user = your address, password = a 16-character **App password** (Account → Security → 2-Step Verification → App passwords). Never the account password. |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | ⬜ | Optional live salary/postings data; curated seeds are used when empty |
| `OPENAI_API_KEY` | ⬜ | Not required. With no key the app runs in offline mode (`ai_mode: false`) and uses the template explanation engine. |

Rotating `SESSION_SECRET`:

```bash
# Render Dashboard → the service → Environment → edit SESSION_SECRET → Save
# (or `generateValue: true` in render.yaml and re-sync the Blueprint)
# Effect: every existing cg_session cookie stops verifying → users sign in again
#         via Firebase. No database change, nothing else to do.
```

### 1.3 Verify after a deploy

```bash
curl -s https://career-guidance-llm-app.onrender.com/api/v1/health
# {"status":"ok","version":"2.0.0","ai_mode":false,"occupations":974,...}

curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://career-guidance-llm-app.onrender.com/api/v1/recommend \
  -H 'content-type: application/json' -d '{"skills":"python"}'    # → 401 (private app)
```

---

## 2. Vercel (frontend)

* **Root Directory**: `frontend` · Framework: Next.js · Node 22
* Auto-deploys from `main` (`NEXT_EXPORT` is **not** set on Vercel, so dynamic
  routes and the `/api` rewrite work; the Docker build uses the static export).

| Variable | Required | Value |
| --- | --- | --- |
| `API_URL` | ✅ | `https://career-guidance-llm-app.onrender.com` (server-side rewrite target, no trailing slash) |
| `NEXT_PUBLIC_FIREBASE_API_KEY` | ✅ | Firebase web config |
| `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` | ✅ | `career-ai-ecba3.firebaseapp.com` |
| `NEXT_PUBLIC_FIREBASE_PROJECT_ID` | ✅ | `career-ai-ecba3` |
| `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET` | ✅ | `<project>.appspot.com` |
| `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID` | ✅ | Firebase web config |
| `NEXT_PUBLIC_FIREBASE_APP_ID` | ✅ | Firebase web config |

Add the same `NEXT_PUBLIC_FIREBASE_*` values (and `API_URL`) as **Preview**
environment variables if you want PR previews to work; preview URLs look like
`career-guidance-web-<hash>-<team>.vercel.app`.

> The Docker image in this repo also builds the front end; if you self-host it,
> pass the `NEXT_PUBLIC_FIREBASE_*` values as **build args** (`docker compose`
> reads them from `.env`).

---

## 3. Firebase console checklist

1. **Authentication → Sign-in method**
   * enable **Google**;
   * enable **Email/Password** (verification e-mails are enforced by the API:
     any password-provider ID token with `email_verified != true` is rejected).
2. **Authentication → Settings → Authorised domains → Add domain**
   * `career-guidance-web-sigma.vercel.app` (production)
   * `localhost` (local dev, already there by default)
   * each Vercel **preview** domain you want to test
     (`career-guidance-web-*.vercel.app` — wildcards are not supported, add the
     exact host or a custom preview domain)
   * the Render host if you open the bundled front end from there
3. **Authentication → Templates → (any action URL field)**
   Add the Vercel origin so verification/reset e-mails can return to the app.
   Without it Firebase answers `auth/unauthorized-continue-uri` — the client
   retries the send **without** the continue URL, so the user still gets a
   working link (it just lands on Firebase's default page).
4. **Project settings → Your apps → Web app** — the six `NEXT_PUBLIC_*` values.
5. Optional: *Authentication → Users* to reset a password or delete an account
   when someone asks by e-mail.

---

## 4. First-run acceptance (10 minutes)

```bash
# 1. API up, private
curl -s https://career-guidance-llm-app.onrender.com/api/v1/health

# 2. Front end builds and is protected (also: `make blackbox-prod`)
curl -sI https://career-guidance-web-sigma.vercel.app/ | head -1     # 200 (HTML shell)
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://career-guidance-web-sigma.vercel.app/api/v1/recommend \
  -H 'content-type: application/json' -d '{"skills":"python"}'       # 401 via the Vercel proxy
```

Then in a browser:

1. `/` → redirected to `/login?next=/` (no content leaks).
2. Sign in with Google → onboarding wizard appears once → `/dashboard`.
3. `/discover` → 36 items → result page with Holland code + radar.
4. `/recommend` → cards show match %, readiness %, ₹ salary band, demand badge.
5. `/plan` → rate skills → readiness → roadmap → export MD/JSON/ICS/PDF.
6. `/admin` (only for `ADMIN_EMAILS`) → 12 modules, all backed by real data.
7. Sign out → `/` redirects to `/login` again.
8. `/pathway` → pick a target, paste a résumé → verdict + bridges + phased plan.
9. Install the PWA (Chrome → Install app), then go offline → the offline page
   appears and `/api/*` is never served from cache.

The full executed/not-executed ledger, including the browser-only steps above
and the Firebase console checklist, lives in
[`docs/TEST_REPORT.md`](TEST_REPORT.md).

## 5. Backups & restore

* Admin console → **System → Download SQLite backup** (or `GET /api/v1/admin/backup.db`).
* Restore from the same page (uploads replace the file, then migrations re-run).
* On Starter, the disk already survives redeploys; a monthly download is still
  the cheapest insurance policy.

### 5.1 Command-line scripts (Phase 6)

For scheduled/off-box backups, use the scripts (SQLite deployments):

```bash
# Timestamped, integrity-checked copy into ./backups (keeps the newest 14)
python scripts/backup_db.py --db /app/data/career_guidance.db --out-dir backups --keep 14

# Restore: validates the backup FIRST, copies the current DB aside as
# <db>.pre-restore-<timestamp>, then swaps and re-checks. Stop the app first.
python scripts/restore_db.py backups/career_guidance-20261106T120000Z.db --db /app/data/career_guidance.db
```

Both scripts exit non-zero without touching anything when a file fails
SQLite's `PRAGMA integrity_check`. Postgres deployments: use `pg_dump` /
`pg_restore` instead — the scripts refuse nothing, they simply only speak
SQLite files.

---

## 6. Choosing Postgres on Render (Phase 6 option)

SQLite stays the default. `DATABASE_URL` switches the **core storage
layer** (`career_guidance.storage.Database`) and the **migration runner**
to Postgres through the central dialect layer
(`career_guidance/db.py`); dialect differences (placeholder style, row
factory, DDL translation) live only there.

| | SQLite on persistent disk | Postgres |
| --- | --- | --- |
| Render cost | Starter instance + 1 GB disk | Free/paid Postgres add-on (check current Render pricing; the free tier has an expiry — owner decision, free-only rule) |
| Survives redeploys | Yes (disk) | Yes |
| Backups | File copy / scripts in §5.1 | `pg_dump` (managed snapshots on paid tiers) |
| Concurrency | One writer at a time — fine for this app's load | Full concurrent writes |
| Ops burden | None | Connection string rotation, add-on lifecycle |

**Current boundary (honest):** the per-feature stores (users, journey,
billing, verification, institutes, consent, …) still open the SQLite
file directly. Running with `DATABASE_URL=postgres://…` today migrates
and serves the recommendation-runs `Database` on Postgres while the
remaining stores keep using `DATABASE_PATH`. A full cutover is a
store-by-store migration behind the same dialect layer — do not point
production at Postgres until that lands. The option exists now so the
schema, migrations and core store are proven portable ahead of it.

To enable (staging first):

1. Provision the Postgres instance; copy its **internal** connection URL.
2. `pip install -r requirements-postgres.txt` must be part of the image
   (add it to the Docker build) — psycopg is an optional extra so
   SQLite-only installs stay lean.
3. Set `DATABASE_URL=postgres://…` (Render env). Leave `DATABASE_PATH`
   set for the remaining stores.
4. Smoke procedure (no production data): boot the app, then verify
   `GET /api/v1/ready` → `checks.database == "ok"`, run one anonymous
   `POST /api/v1/recommend`, and confirm a row landed:
   `psql "$DATABASE_URL" -c "SELECT count(*) FROM recommendation_runs;"`
   and `psql "$DATABASE_URL" -c "SELECT version FROM schema_migrations ORDER BY 1;"`
   (expect versions 1..7).
5. Roll back by unsetting `DATABASE_URL` and redeploying; the SQLite
   file was never modified by the Postgres path.

---

## 7. Readiness, health & observability (Phase 6)

| Endpoint | Meaning | Use |
| --- | --- | --- |
| `GET /api/v1/health` | Liveness: process up, catalog size, version | Render `healthCheckPath` |
| `GET /api/v1/ready` | Readiness: DB `SELECT 1` + catalog loaded; `503` with a per-component `checks` breakdown when not ready | Load-balancer / deploy verification |

Logs are JSON lines (one object per record: `ts`, `level`, `logger`,
`msg`, `request_id`, and for access lines `method`, redacted `path`,
`status`, `duration_ms`). Incoming `X-Request-ID` headers are propagated
and echoed on the response. Bodies, e-mails, tokens and profile text are
never logged. Set `ERROR_WEBHOOK_URL` to receive a minimal JSON POST
(`event`, `error_type`, truncated `message`, `request_id`) on unhandled
500s; unset (default) disables it, and webhook failures are swallowed.

---

## 8. Rollback runbook

Migrations are **additive only** (new tables/columns, never drops), so
rolling back code never requires rolling back the database.

1. **Backend (Render)** — Dashboard → the service → *Deploys* → pick the
   last known-good deploy → **Redeploy** (or push the previous commit).
   The schema on disk stays at the newer version; older code ignores
   columns/tables it does not know.
2. **Frontend (Vercel)** — Dashboard → the project → *Deployments* →
   pick the last known-good deployment → **Promote to Production**.
3. **Database (only if data itself is bad)** — stop the service, restore
   the newest good backup with `scripts/restore_db.py` (§5.1; it keeps a
   `.pre-restore-*` copy of whatever it replaces), start the service,
   verify `GET /api/v1/ready`.
4. **Config-only regression** — revert the env change in the dashboard
   and redeploy/restart; no code or DB action needed. Rotating
   `SESSION_SECRET` signs everyone out (see §1.2).
