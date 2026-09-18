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
