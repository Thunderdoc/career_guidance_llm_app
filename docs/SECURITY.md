# Security posture — Career Guidance AI (Phase 6 review, 2026-11-06)

What was checked, what was fixed, and what is knowingly left as a
documented follow-up. Nothing in this file is aspirational: every claim
maps to code or a test named below.

## Fixed in Phase 6

| Item | Where | Evidence |
| --- | --- | --- |
| Security headers on every API response (incl. errors): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()` | `backend/main.py` request middleware | `tests/test_security.py::test_security_headers_*` |
| Session cookie `Secure` flag is now forced when `APP_ENV=production` (previously it depended only on the public base URL starting with `https://`, so a misconfigured `PUBLIC_URL` silently dropped it). `HttpOnly` + `SameSite=Lax` were already set; the logout `delete_cookie` now mirrors the same flags | `backend/auth.py` `Auth.issue/clear` | `tests/test_security.py::test_session_cookie_*` |
| Uniform 500 shape `{detail, request_id}`; exception text never reaches the client | `backend/main.py` middleware | `tests/test_observability.py` |

## Verified, already in place (no change needed)

- **Upload limits** — résumé extract capped at 5 MB → 413
  (`backend/main.py`); institute CSV invites capped at 5 MB / row-count
  capped in `career_guidance/institutes.py` (`MAX_CSV_BYTES`,
  `MAX_CSV_ROWS`), whole-file problems → structured 422, never 500.
  Regression tests: `tests/test_error_shapes.py`.
- **Rate limits** — `/recommend` 30/min per client; quiz start/submit,
  consent request/confirm, magic links all have dedicated limiters.
- **Authz** — every Phase 2–5 route re-checks the session/role
  server-side; anonymous calls to saved-data routes answer 401
  (`tests/test_error_shapes.py::test_new_routes_reject_anonymous_with_detail`
  plus the per-phase API suites).
- **Secrets/PII in logs** — access logs carry method, redacted path,
  status, duration and request id only; token-like path segments are
  scrubbed (`career_guidance/logging_setup.redact_path`); bodies,
  e-mails and profile text are never logged (tested with a marker
  string in `tests/test_observability.py`).
- **Session secret** — production refuses to boot without
  `SESSION_SECRET` (`backend/auth.py`).

## Share tokens (Phase 8)

Report share links (`career_guidance/sharing.py`, migration v8,
`backend/sharing.py`) follow the same token discipline as the consent
links, tightened for a *public read* surface:

- **Hash at rest, always.** The token is 32 bytes of
  `secrets.token_urlsafe`; the database stores only its SHA-256 hex
  (`share_tokens.token_hash`, UNIQUE). The raw token is returned
  exactly once, in the create response — it cannot be recovered later,
  only revoked and re-created. A test inspects the DB row and asserts
  the raw token appears nowhere in it.
- **Expiry is a code constant, not configuration:** default 7 days,
  maximum 30 (`expiry_days` validated 1–30 → 422 outside). Expired and
  revoked links answer **410 Gone**; unknown tokens **404**.
- **Minimal by construction.** The public payload is *built* from the
  `report_v1` allowlist in `career_guidance/sharing.py` (career titles,
  match %, matching/missing skills, Reality Score with its labelled
  sources, salary ladder labelled an estimate, learning path) — never
  filtered down from a full report. The builder never reads the stored
  profile, so owner name/e-mail/handle, constraints (city, budget),
  raw profile text, institute and counsellor data cannot leak; a
  privacy test scans the serialised payload for seeded markers of each.
- **Ownership.** Only the run's owner can create/list/revoke: the
  signed-in owner, or — for an anonymous run — a guest (no-session)
  caller. Sign-in does **not** adopt anonymous runs (same rule as
  history/exports), so a signed-in non-owner gets 403, never access.
- **Abuse controls.** Creation is rate-limited per caller (10/hour);
  the public read is rate-limited per client IP (60/min). Tokens in
  URLs are scrubbed from access logs by the existing
  `redact_path` (≥24-char token-like segments). Delete-my-data removes
  the user's `share_tokens` rows, killing their links with the account.
- **Service worker / CSP.** The PWA worker is same-origin (`/sw.js`),
  already covered by the report-only CSP's `script-src 'self'` — no
  policy change was needed or made. The backend's SPA fallback serves
  `sw.js` with `Cache-Control: no-cache` so worker updates are picked
  up promptly, and the worker never caches `/api/*` responses.

## Institute API keys (Phase 10)

Public institute API (`career_guidance/api_keys.py`, migration v10,
`backend/public_api.py`) — the same hash-at-rest discipline as share
tokens, for machine callers:

- **Hash at rest, raw shown once.** Keys are `cgk_` + 32 bytes of
  `secrets.token_urlsafe`; the DB stores only the SHA-256 hex
  (`institute_api_keys.key_hash`, UNIQUE). A test inspects the stored
  row and asserts it equals the hash and never contains the raw key.
- **Header-only auth.** Public reads accept `X-API-Key` and nothing
  else: a valid session cookie without the header answers 401 (tested).
  Missing, malformed, unknown and revoked keys all answer 401.
- **Institute binding.** A key authenticates only for its own
  institute: presented against another institute's slug (or an unknown
  slug) it answers 404, so key validity cannot be probed across
  institutes.
- **Aggregates only.** Payloads reuse the Phase 4 cohort builder with
  the individual needs-attention list reduced to a count before
  serialisation; a privacy test scans responses for e-mail markers,
  user ids and field names (`email`, `user_id`, `student_id`).
- **Lifecycle.** Creation/listing/revocation require a session as the
  institute's `institute_admin` or a platform admin (403 otherwise,
  audit-logged); revocation is immediate and one-way; every successful
  authentication stamps `last_used_at` so stale keys are visible.
- **Abuse controls.** 30 requests/minute per key (stricter than the
  session cohort routes). Keys never appear in URLs, so access-log
  redaction is unaffected; key values are never logged.

## Dependency audits (2026-11-06)

- **pip-audit** (against `requirements.txt`, pip-audit 2.10.1):
  **"No known vulnerabilities found."**
- **npm audit** — **could not be run from the build sandbox**: the
  registry audit endpoint is rejected by the sandbox egress policy
  (`403 policy_denied` on `POST /-/npm/v1/security/audits/quick`).
  This is an environment limit, not a clean result. Mitigation: CI now
  runs `npm audit --audit-level=high` as a non-blocking step
  (`.github/workflows/ci.yml`) so findings surface on every push;
  run it locally before a release with `cd frontend && npm audit`.
  No high/critical finding is being "accepted" here — none could be
  observed from this environment at all.

## CSRF posture (current design, stated honestly)

There is no separate CSRF token. The design relies on:

1. The session cookie is `SameSite=Lax`, so cross-site POSTs do not
   carry it in modern browsers — a forged cross-site form/fetch cannot
   ride a signed-in session.
2. All state-changing API routes consume JSON (`Content-Type:
   application/json`), which a cross-site HTML form cannot send without
   a CORS preflight; CORS origins are configurable via
   `CORS_ALLOW_ORIGINS` and should be locked to the production
   front-end origin in deployments (the default `*` exists for dev
   previews — with credentials-less requests this does not expose the
   cookie, but lock it down anyway).
3. Two state-changing GETs exist by design and are **token-secured, not
   session-secured**: the e-mail magic link and the guardian consent
   confirm link. Both use single-purpose, expiring, hashed tokens —
   the standard pattern for e-mailed links.

Residual risk accepted: a same-site subdomain attacker would not be
stopped by SameSite=Lax. If the app is ever served alongside untrusted
subdomains, add a custom-header check (`X-Requested-With`) or an
Origin allowlist middleware on mutating routes.

## CSP follow-up (exact next step)

CSP currently ships as `Content-Security-Policy-Report-Only` with a
conservative policy (see `backend/main.py`) because the Next.js static
export emits inline scripts and Firebase Auth needs Google endpoints;
enforcing the report-only policy verbatim would break sign-in.
Graduation path:

1. Collect report-only violations in production for one release.
2. Move the remaining inline scripts behind nonces/hashes in the
   server (non-export) build, or self-host them.
3. Flip the header name to `Content-Security-Policy` with:
   `default-src 'self'; script-src 'self' https://apis.google.com https://www.gstatic.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://www.googleapis.com; frame-src https://accounts.google.com https://*.firebaseapp.com; object-src 'none'; base-uri 'self'`
   (i.e. today's report-only value minus `'unsafe-inline'` for scripts
   once step 2 lands).

## Kaam-Vaani hardening (Step 9.4, 2026-11-21)

### Rate limits (new)

Before Step 9.4, only the video check had a rate limit. Every
other Kaam-Vaani POST was unmetered. All limits are enforced by
the shared `backend/kv_ratelimit.py` (one `RateLimiter` per
router, registered so the test suite can reset them between
tests — `tests/conftest.py` autouse fixture). A 429 carries the
same message everywhere: "Too many requests — please wait a
minute."

| Endpoints | Budget | Key |
|---|---|---|
| `POST /api/v1/kv/rag/search`, `/kv/rag/ask` | 30/min | IP |
| `POST /api/v1/kv/rights/ask` | 30/min | IP |
| `POST /api/v1/kv/voice/extract`, `/kv/voice/confirm` | 30/min | IP |
| `POST /api/v1/kv/matches`, `/kv/gap-learning` | 30/min | IP |
| `POST /api/v1/kv/listings/{id}/report` | 10/min | IP |
| `POST /api/v1/kv/consent/*`, `/kv/employers/matching/*`, `/kv/hire-outcomes*`, `DELETE /api/v1/kv/me/data` | 60/min | user |
| `POST /api/v1/kv/employers/register`, `/kv/employers/listings`, `/kv/employers/listings/check` | 60/min | user |
| `POST /api/v1/kv/employers/mine/verify-phone` (OTP) | 5/hour | user |
| `POST /api/v1/kv/video/check` | 5/hour | user |

Unmetered by design: admin/coordinator-only endpoints
(`kv_pilot`, `kv_traces`, admin review) — authenticated,
attributable, low volume. Honest limits (A65/L67): the
limiters are per-process in-memory (a multi-worker deploy has
one budget per worker, not one global budget) and the per-IP
key trusts the first `X-Forwarded-For` entry, which a client
can spoof to rotate keys. This is friction against casual
abuse, not a hard abuse boundary — true protection belongs at
the platform edge.

### OWASP Top 10 review — Kaam-Vaani surface (2026-11-21)

| # | Risk | Kaam-Vaani posture |
|---|---|---|
| A01 | Broken access control | Role-scoped deps on every signed-in route (`current_user` / `employer_user` / `admin_user` / `coordinator_user` / `pilot_user`); consent-gated matching enforced in the query layer, not the UI; a worker's own data only (ownership checked per call). Verified by the Stage 6 + 9.2 tests. |
| A02 | Cryptographic failures | No secrets in the KV layer (no API keys by design); session cookie `SameSite=Lax`, signed; share tokens hashed; no PII in URLs. |
| A03 | Injection | All SQL values are bound parameters. 12 f-string SQL sites exist in `consent.py` (4) / `employers.py` (8), each marked `# noqa: S608` — every one interpolates only fixed clause fragments (`"status = 'verified'"`, `"role_category = ?"`) or dict keys from the method's own fixed field set; no request data is ever interpolated. Verified by reading all 12 sites on 2026-11-21. No shell injection: ffmpeg/ffprobe are invoked with an argv list, never a shell string. |
| A04 | Insecure design | Consent is per-employer, time-boxed, revocable, one active per pair; the audit trail is append-only; the video check cannot certify skill (labelled indicative). |
| A05 | Security misconfiguration | Security headers middleware ships (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP-Report-Only — see `backend/main.py`; no HSTS header is set by the app — the platform must provide it); Step 9.4 fixed `Permissions-Policy` from `microphone=()` to `microphone=(self)` because the Phase 6 value blocked the Kaam-Vaani voice flow's mic on the Render-served origin (camera and geolocation stay blocked). CORS default is `*` with credentials off — lock `CORS_ALLOW_ORIGINS` to the production front-end origin at deploy (deploy-checklist item); every KV router sits behind an env feature flag, default ON except in production. |
| A06 | Vulnerable components | See the dependency audit below (2026-11-21). |
| A07 | Auth failures | Firebase ID tokens + magic links + signed sessions (base app); OTP is Firebase's, not ours — the backend only stores a Firebase-verified number, and the endpoint is rate-limited 5/hour/user. |
| A08 | Data integrity failures | No deserialisation of untrusted data (no pickle anywhere in the KV path); uploads are size-capped and type-checked by probe, not extension. |
| A09 | Logging failures | The timing middleware logs method / redacted path / status / duration only — never bodies, e-mails, tokens or profile text. The agent trace log stores questions/transcripts as 16-hex SHA-256 hashes only (Step 8.9). |
| A10 | SSRF | The KV backend makes no outbound requests on behalf of user input (no URL fetch from a user-supplied URL anywhere in the KV surface). |

### Upload limits (Kaam-Vaani)

- Video check: 50 MB cap enforced DURING streaming (413 past
  the cap), empty file → 422, duration probed by ffprobe
  (30–60 s), temp file deleted in a `finally`, never stored.
- Resume upload (base app): 5 MB cap, 413 past it.
- No other KV endpoint accepts file uploads.

### Dependency audit (2026-11-21, pip-audit 2.10.1)

97 packages audited. Before: **9 known vulnerabilities in 5
packages**. Fixed by version bumps (verified by re-audit +
`pip check` clean):

| Package | Was | Now | CVEs fixed |
|---|---|---|---|
| pypdf | 6.21.3 | 6.21.4 | CVE-2026-119203, -119204, -119205 (crafted-PDF infinite loop / memory exhaustion — REAL exposure: `resume.py` parses user-uploaded PDFs) |
| dnspython | 2.9.0 | 2.9.2 | CVE-2026-128089 (zone-file DoS; transitive, app never parses zone files) |
| opentelemetry-api | 1.45.1 | 1.45.2 | CVE-2026-126360 (traceparent ReDoS; transitive, app does not use OTel) |

After: **4 known vulnerabilities in 2 packages**, both
accepted with reasons (not ignored):

- **diskcache 5.6.3** — PYSEC-2026-2447 (×2): pickle RCE if an
  attacker has write access to the cache directory. NO fix
  version exists. The app never imports diskcache and creates
  no cache directory — no exposure.
- **pytest 8.4.2** — PYSEC-2026-1845 (×2): `/tmp/pytest-of-*`
  local DoS/privilege issue. Dev-only dependency; the fix
  (9.0.3) is a major-version bump, deliberately NOT taken
  mid-project (risk to the 1100-test suite). Single-user VM,
  negligible exposure; revisit after the hackathon.

**npm audit** — still cannot run from this sandbox (see the
2026-11-06 note above); CI runs it as a non-blocking step.
