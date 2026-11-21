# BASELINE.md — Kaam-Vaani Stage 6 baseline (pre-Stage-6 tree)

Measured 20 Nov 2026, 23:09–23:21 IST, on branch `kaam-vaani` at
commit `c10b693` ("Kaam-Vaani Stage 6: regenerate eval report
(latency-only)"; Stage 5 done, Stage 6 not started). Every number
below comes from the baseline gate run in this session
(log: `~/workspace/goals/gavs-tech4bharat-idea-submission/hidden_files/kv-stage6-logs/baseline-gate.log`).
Every later claim of "improved" must compare to this file.

Gate commands (discovered from `.github/workflows/ci.yml` and
`Makefile`, not assumed):

- backend tests: `pytest -q -p no:warnings`
- coverage: `pytest -q -p no:warnings --cov=career_guidance --cov=backend --cov-report=term-missing --cov-fail-under=85`
- lint: `ruff check . && ruff format --check .` + `cd frontend && npx eslint . && npx tsc --noEmit`
- production build: `cd frontend && NEXT_EXPORT=1 npm run build` (from
  an ISOLATED COPY — never in the repo; the copy must also contain
  `data/catalog/occupations.json` at `../data/catalog/`, see the build
  note below)
- golden eval: `python -m eval.run --min-hit 0.75` + `python -m eval.run_chat_eval`
- KV eval: `python -m eval.run_kv --min-profile 0.90 --min-recall5 0.85 --min-faithfulness 0.90`

## Results

| Gate item | Result |
| --- | --- |
| Backend tests | **693 passed, 0 failed** (exit 0). 50 test files; KV stage tests 27+44+39+25+43 = 178. |
| Coverage | **92.69%** (11,402 statements, 834 missed). CI floor 85% reached. Execution-prompt floor is "not below baseline (92%+)". |
| Frontend tests | **NONE EXIST** — no test script in `frontend/package.json`, no `*.test.*` files, no vitest/jest. N/A. |
| `ruff check` | PASS ("All checks passed!"). |
| `ruff format --check` | **FAIL — 1 file: `backend/main.py:139`** (the Stage 5 `build_kv_employers_router(...)` mount call; ruff wants it on one line). Pre-existing, committed in Stage 5 — not caused by Stage 6. To be fixed by the Stage 6 `main.py` edit (the kv_consent mount lands in the same block). |
| `tsc --noEmit` | PASS (exit 0, no output). |
| `eslint .` (frontend) | PASS — 0 errors, 3 warnings (all pre-existing `import/no-anonymous-default-export` warnings in `eslint.config.mjs` / `postcss.config.mjs`). |
| Production build (`NEXT_EXPORT=1`, isolated copy) | **PASS** (exit 0) — but see the method note below. `out/` 26M. First Load JS shared by all: 103 kB. Key routes (size / first load): `/voice` 31.1 kB / 217 kB, `/employers` 7.31 kB / 163 kB, `/jobs` 4.09 kB / 116 kB, `/login` 44.5 kB / 230 kB. `/careers/[id]` generated all 974 paths. |
| Golden eval | PASS (exit 0). skills Hit@5 1.0, MRR 0.827, p95 207.6 ms (50 cases); interests Hit@5 1.0, p95 89.1 ms (7 cases). |
| Chat eval | PASS (exit 0). faithfulness 4/4, chat grounding 8/8. |
| KV eval | **PASS** (exit 0). 113 cases, snapshot v1 (1,040 chunks). profile 1.000 (min 0.90); recall@5 0.954, MRR 0.926 (min 0.85); faithfulness 0.907 (min 0.90 — thin margin, one case above the line); refusal 0.933 (min 0.90). Latency p50 2 ms, p95 52 ms, max 136 ms. Retrieval misses: kv-r042, kv-r043. Refusal miss: kv-x007. Unfaithful: kv-r015, kv-r033, kv-r042, kv-r043. |

## Build method note (honest record of a mistake)

The first isolated-copy build in this session FAILED with
`Page "/careers/[id]" is missing "generateStaticParams()"`. The page
HAS `generateStaticParams()` — it reads the catalogue from
`../data/catalog/occupations.json` (repo root) or
`frontend/data/catalog/occupations.json`, and returns `[]` when
neither exists. My copy contained only `frontend/`, so the catalogue
was missing, the params list was empty, and Next.js reported the
route as missing the export. **This was a method error in my copy,
not a code defect.** After placing `data/catalog/occupations.json`
at `../data/catalog/` in the copy, the build passed (exit 0, all
974 career paths). The Stage 6 gate build must include the
catalogue the same way.

## Step 5 verification (execution prompt Step 5 — verify, do not rebuild)

Seed script run on a scratch DB (`/tmp/kv-baseline-scratch.db`),
exit 0:

- Employers: verified 5, pending 1, flagged 1.
- Listings: verified 37, pending 3, flagged 5 (40 legit + 5 fake).
- Listings with risk_score ≥ 70: 5 (exactly the 5 deliberately fake
  listings).
- Verified listings with risk_score ≥ 70: 0.

Step 5 DONE criteria met: the 5 fake listings are flagged by the
checker while the verified ones are not. Note vs the prompt's
sketch: the as-built Stage 5 has no separate `verification_events`
table and no standalone state-machine module — transitions live in
`EmployerStore` methods (verified by the 43 Stage 5 tests, incl.
transition and scam-rule tests). Stage 5 was verified by the parent
and is not rebuilt here.

## Environment notes

- `/tmp` (512M tmpfs) peaked at 45% (229M) during the coverage run;
  a stale `pytest-0` dir (18M, from a prior run) was removed to buy
  headroom. The design agent's `/tmp/chrome-kv-design-*` dirs and
  `/tmp/kv-design-scratch.db` were NOT touched.
- The KV eval re-ran as part of this gate and re-dirtied
  `eval/kv_report.json` with a latency-only diff; committed with the
  orientation commit.
- Pre-existing red item carried into Stage 6: `ruff format --check`
  on `backend/main.py` (see above). Everything else in the gate is
  green at baseline.
