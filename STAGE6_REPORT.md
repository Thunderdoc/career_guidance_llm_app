# STAGE 6 REPORT — Consent system, employer matching, hire outcomes

**Stage:** 6 of the Kaam-Vaani execution prompt (Step 6)
**Date:** 20 Nov 2026
**Branch:** `kaam-vaani` (local commits only — no push, no deploy)
**Status:** DONE. STOP after this report — Step 7 starts only when Ankit replies "continue".

## Step name + commits

| Step | Commit | What |
| --- | --- | --- |
| Eval regen (parent's verification run) | `c10b693` | `eval/kv_report.json` latency-only regen |
| Orientation | `9c03c8b` | `REPO_MAP.md` + `BASELINE.md` (+ eval regen) |
| Store | `464ae1c` | Migration v14 + consent store + candidate scorer + 50 store tests |
| Router | `0c7dba7` | `backend/kv_consent.py` + mount + router tests (63 tests total) |
| Frontend | `e652562` | `/sharing` page + candidates view + jobs share links |
| Seed + verify | `9d9adcc` | Sample workers seed + live verify script; interests string fix |
| Verify fix | `2f45ce2` | Verify script ignores sandbox proxy env |
| Live-verification fixes | `e6caafc` | Candidate `worker_name` + flat shortlist, city string, structured reasons, audit `fields_returned` |
| Docs + report | *(this commit)* | ARCHITECTURE / PLAN / ASSUMPTIONS / LIMITATIONS / README / RUNBOOK / COMPLIANCE / REPO_MAP / `eval/kv_report.json` regen + this report |

Final message: `stage6: consent system, audit log, employer matching, hire outcomes`.

## Files changed

**New**
- `career_guidance/kaamvaani/consent.py` — `ConsentStore`, `score_candidate`, `filter_profile`, `consent_explanation`
- `backend/kv_consent.py` — router (18 endpoints, behind `KV_CONSENT`)
- `tests/test_kv_stage6.py` — 63 tests (50 store + 13 router)
- `data/kv_sample_workers.json` — 10 fictional workers, 13 consents, 3 shortlists, 2 contact requests, 2 outcomes
- `scripts/seed_kv_workers.py` — sample worker seed (requires the listings seed first)
- `scripts/verify_kv_stage6.py` — 22 scripted live checks vs a running backend
- `frontend/components/kv-sharing-view.tsx` + `frontend/app/sharing/page.tsx` — worker sharing page
- `frontend/components/kv-candidates-view.tsx` — employer candidates section
- `STAGE6_REPORT.md` (this file), `REPO_MAP.md`, `BASELINE.md` (orientation)

**Modified**
- `career_guidance/migrations.py` — migration v14 (six tables), `LATEST_VERSION` 14
- `backend/main.py` — mount `kv_consent` router (also fixes the pre-existing `ruff format` issue on the Stage 5 mount call)
- `tests/test_kv_stage5.py` — version-pin test 13 → 14
- `frontend/lib/api.ts` — Stage 6 types + 20 api methods
- `frontend/components/jobs-view.tsx` — "Share my profile" per card + "My sharing" header link
- `frontend/components/employer-view.tsx` — candidates section for verified employers
- `ARCHITECTURE.md` (§2.6 Stage 6 + new §7 complexity), `docs/KAAM_VAANI_PLAN.md` (Stage 6 DONE), `ASSUMPTIONS.md` (A44–A51), `LIMITATIONS.md` (L45–L50), `README.md` (flags header Stages 1–6 + consent router), `docs/RUNBOOK.md` (consent router + v14 + seed/verify), `docs/COMPLIANCE.md` (§1a worker consent), `REPO_MAP.md` (Stage 6 entries)
- `eval/kv_report.json` — latency-only regen (verified identical except latency)

**Not touched:** `voice-view.tsx` and all design-agent files; `render.yaml`; live Render/Vercel config; the repo's live SQLite DB (all live checks used scratch DBs).

## What was built

1. **Consent system.** Per-employer, time-limited (7/30/90 days, default 30), revocable. One active consent per (worker, employer); re-grant only after revoke/expire. Lazy expiry with a `system` audit event. Grant requires a saved worker profile and a non-empty field subset; `fields=None` means all. The explanation is a deterministic template, never LLM-paraphrased. Granting to an unverified employer is allowed — access is gated at match time.
2. **Append-only audit log.** Every grant, revoke, expiry and profile access is recorded in `kv_consent_audit`. The only audit write in the module is `_append_audit` (INSERT); there is no update/delete path anywhere, and re-seeding sample data deliberately keeps old audit rows. Proven three ways in tests (source grep, method surface, behavioural count).
3. **Employer matching.** Ranked consented candidates with per-feature contributions and structured reasons. Gates enforced in the store, not the UI: verified employer + verified listing, active consent, server-side allow-list field filtering. A shortlist entry survives a later revoke but shows no fields. Weights skill 0.35 / title 0.30 / city 0.20 / income 0.15, reusing Stage 4's matcher machinery.
4. **Hire-outcome tracking.** Employers/workers report hired/interviewed/not_hired per listing; outcomes require a consent RECORD (any status). Day-30/90 follow-ups on hires only; retention rate is `null` until a follow-up is reported, never 0% by default.
5. **Fairness.** No caste/religion/gender/origin columns in the worker profile schema; two workers identical except language/user-id score identically; the scorer source contains none of the forbidden tokens (tested).
6. **Frontend (plain + functional).** `/sharing`, jobs share links, employer candidates section. English-only (L37). The design agent owns the polish.

## Commands + real results

### Full gate (20 Nov 2026 18:44–18:56 IST, log `hidden_files/kv-stage6-logs/stage6-gate.log`)

| Gate item | Command | Result |
| --- | --- | --- |
| Backend tests + coverage | `pytest -p no:warnings --cov=career_guidance --cov=backend --cov-fail-under=92` | **756 passed in 610.58s**, exit 0; **coverage 92.97%** (12,340 stmts, 868 missed) |
| Frontend tests | — | NONE EXIST — N/A (same as baseline) |
| Ruff check | `ruff check .` | All checks passed, exit 0 |
| Ruff format | `ruff format --check .` | 185 files formatted, exit 0 |
| Typecheck | `npx tsc --noEmit` | exit 0 |
| ESLint | `npx eslint .` | 0 errors, 3 warnings (pre-existing, same as baseline), exit 0 |
| Production build | `NEXT_EXPORT=1 npm run build` (isolated copy + catalogue) | exit 0; `out/` 26M; `/sharing` 6.55 kB / 162 kB; `/employers` 9.96 kB / 166 kB; `/jobs` 4.15 kB / 116 kB; shared 103 kB |
| Golden eval | `python -m eval.run --min-hit 0.75` | skills Hit@5 1.0 / MRR 0.827 (50 cases), interests Hit@5 1.0 (7 cases), exit 0 |
| Chat eval | `python -m eval.run_chat_eval` | faithfulness 4/4, grounding 8/8, exit 0 |
| KV eval | `python -m eval.run_kv --min-profile 0.90 --min-recall5 0.85 --min-faithfulness 0.90` | **PASS** — profile 1.000, recall@5 0.954, MRR 0.926, faithfulness 0.907, refusal 0.933; latency p50 2 ms, p95 51 ms, max 111 ms; exit 0 |
| Seed (scratch DB) | `seed_kv_listings.py` + `seed_kv_workers.py` | exit 0; employers 5/1/1, listings 37/3/5, workers 10, consents 11/1/1, shortlists 3, contact requests 2, outcomes hired 1 + interviewed 1, audit 13 granted / 1 revoked / 1 expired |

### Gate vs BASELINE.md (commit `c10b693`)

| Metric | Baseline | Stage 6 | Verdict |
| --- | --- | --- | --- |
| pytest | 693 passed | **756 passed** (+63 Stage 6) | ✅ |
| Coverage | 92.69% | **92.97%** | ✅ above baseline |
| ruff check | PASS | PASS | ✅ |
| ruff format | FAIL (1 file, `main.py:139`, pre-existing) | **PASS** (185 files; fixed by the Stage 6 mount edit) | ✅ fixed |
| tsc | PASS | PASS | ✅ |
| eslint | 0 errors, 3 warnings | 0 errors, 3 warnings (same) | ✅ |
| Build | PASS (26M) | PASS (26M, +`/sharing` route) | ✅ |
| Golden eval | Hit@5 1.0 / MRR 0.827 | identical | ✅ |
| Chat eval | 4/4, 8/8 | identical | ✅ |
| KV eval | profile 1.000, recall@5 0.954, faithfulness 0.907, refusal 0.933 | **identical** (same misses: kv-r042, kv-r043, kv-x007, kv-r015, kv-r033) | ✅ |

### Live verification (scratch DB, backend :8102 + frontend dev :3002)

- `scripts/verify_kv_stage6.py`: **22/22 checks PASS** (health, public status, profile save with skill normalisation, employer+listing verification, unverified employer 409, no-consent → 0 candidates, narrow grant, explanation text, match → 1 candidate with only consented fields, explainable components, shortlist, contact request, worker sees the request, hire outcome, day-30 follow-up, retention 1.0, revoke, revoked → 0 candidates, shortlist survives revoke with hidden data, worker + employer audit order).
- Screenshots: **8 phone-viewport (390×844)** in `hidden_files/kv-stage6-shots/` — 01 sharing empty, 02 sharing saved, 03 jobs share button, 04 grant panel, 05 grant done, 06 employer candidates (14 before revoke), 07 sharing revoked, 08 employer after revoke (13 — count dropped by exactly 1). Script: `~/workspace/tools/pptr-shot/kv-stage6-shots.js`.
- Matching latency (measured, seeded DB, 13 candidates): **31–58 ms per ranking call, mean 41.2 ms** (includes 13 audit inserts).

### Bugs found and fixed by tests / live checks

1. **Empty-list grant became "all fields"** (`fields or list(CONSENT_FIELDS)` — falsy `[]`). Fixed to `fields if fields is not None else ...`. Caught by a store test.
2. **`interests` type mismatch.** The store contract is a plain string; the frontend and seed sent a list. The seed run crashed on it. Frontend + seed aligned to the string contract; pinned by a round-trip test.
3. **Candidates 422.** The frontend sent `city: null`; the API takes a string ("" = no filter). Frontend sends "" now; pinned by a test.
4. **Frontend assumed response fields that don't exist** (`worker_name`, `contributions`, `weights` on candidates; flat shortlist). The router now enriches candidates with `worker_name` and flattens the shortlist view; frontend types match the real shapes. Pinned by e2e assertions.
5. **Reasons rendered as empty bullets.** The scorer's reasons are structured (`{kind, skills}` etc.), not free text. The view now renders one honest line per reason kind. Pinned by an e2e assertion.
6. **Screenshot harness:** `page.waitForFunction`'s default rAF polling stalls on `/sharing` (the text is provably in `innerText` while the wait hangs 60s). The shot script polls via `page.evaluate` + sleep instead. Harness quirk, not an app bug.
7. **Seed script `trust_env`:** httpx choked on a sandbox proxy env var at Client construction; the verify script passes `trust_env=False` (localhost needs no proxy).

## What works

- The full consent lifecycle end to end (save → grant → match → shortlist → contact → outcome → follow-up → revoke → invisible), proven by tests, the live verify script, and screenshots.
- All negative cases: unconsented employer sees nothing; expired/revoked consent cuts access; unverified employer/listing cannot match; cross-employer ids 404; worker role gets 403 on employer endpoints; outcomes about strangers 409.
- The audit log: append-only, visible to both sides, correct order (newest first).
- Seed idempotency + `--force` re-seed (audit rows kept by design).
- Flag off: all consent routes 404 (POST surfaces as 405 via the GET-only SPA catch-all); the rest of the app is unaffected.

## What does NOT work / prototype-only

- **L45:** the voice flow does not auto-save the worker profile — the worker must save on `/sharing` (or prefill from the voice session) before sharing.
- **L46:** contact requests have no worker response flow (read-only on the worker side).
- **L47:** matching covers signed-in workers with saved profiles only; guests cannot be matched.
- **L48:** no admin consent oversight UI (disputes need a database read).
- **L49:** the audit log has no retention policy (grows O(searches × candidates returned)).
- **L50:** lazy expiry is a full table scan of `kv_consents` (no index); needs a `(status, expires_at)` index at scale.
- The title component of the candidate scorer is 0.0 for the electrician case (no shared-stem matching in the proven Stage 4 matcher); the skill component carries the trade match. Deliberate — no new matcher was invented (A50).
- Stage 6 UI is plain + functional by design; the design agent owns the polish. English-only (L37).

## Risks / blockers

- **Faithfulness margin is thin (0.907 vs the 0.90 line)** — unchanged from baseline, but one case above the line. Any Step 7 retrieval change must re-run the KV eval; a regression here fails the gate.
- **No push/deploy has happened** — everything is local on `kaam-vaani`. The parent must arrange the batched night push with Ankit's approval tap.
- **The design agent works in the same checkout** (servers :8100/:3100, voice redesign in progress). No conflicts arose in Stage 6; `voice-view.tsx` was not touched.
- **Execution-prompt security notice (flag for the parent):** when I read `Kaam-Vaani-Execution-Prompt.md`, the system inserted a security notice about that tool result. I proceeded because the parent explicitly directed me to follow it as the operative spec and its contents matched the parent's own summary of it. The parent should re-weigh this before Step 7.

## Next step (NOT started — awaiting Ankit's "continue")

Step 7 / pre-Stage-7 fixes, in the parent's order: (7A) multilingual retrieval — Tamil/Hindi queries retrieve from the English KB, free only, +30 Tamil +30 Hindi eval cases, recall@5 per language; (7B) sourced Tamil Nadu minimum-wage data in the KB, official labour-department pages only with source/date/licence per chunk, else keep the refusal; (7C) Postgres adapter + migration path (free tier), SQLite stays for local dev, cutover documented in RUNBOOK.md. Then Step 8 (engineering depth 8.1–8.10) and Step 9 (Stages 7–11 + DEPLOY_CHECKLIST.md). None of this is started.
