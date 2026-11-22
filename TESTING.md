# TESTING — how to run the gates, and what they prove

Status: 21 Nov 2026 (Step 9.6). Backend: **1,132 passed + 3 skipped,
0 failed, coverage 93.52%** (Step 9.4 gate). Frontend: **no unit
tests exist** — the frontend gate is typecheck + lint + production
build (see §3). That gap is stated plainly, not hidden.

## 1. Backend tests (pytest)

Venv: `~/workspace/projects/career-venv/bin/python`. Config in
`pyproject.toml` (`testpaths = ["tests"]`, `addopts = "-q"`).

```bash
# Full suite (the gate) — ~24–28 min on a quiet machine, longer
# under shared load. ALWAYS use --basetemp on workspace disk:
~/workspace/projects/career-venv/bin/python -u -m pytest -q -p no:warnings \
  --basetemp ~/workspace/tmp/pytest-basetemp \
  --cov=career_guidance --cov=backend \
  --cov-report=term-missing --cov-fail-under=85

# One file (fast feedback while developing):
~/workspace/projects/career-venv/bin/python -m pytest tests/test_kv_step9_4.py -q -p no:warnings

# One test:
~/workspace/projects/career-venv/bin/python -m pytest tests/test_kv_step9_4.py::test_name -q -p no:warnings
```

### Why `--basetemp` (learned 21 Nov 2026, the hard way)

`/tmp` is a 512 MB tmpfs shared by every agent on the VM. A full
gate run writes ~260 MB of per-test temp dirs there; on 21 Nov
`/tmp` hit 99% full mid-run and the suite failed with 3 failures
+ 1 error + an error cascade — all environmental, all passing on
a clean re-run. `--basetemp` moves pytest's temp dirs to workspace
disk. Do NOT use `TMPDIR` instead: it also moves `tempfile`'s
default and makes the 9.3 temp-file-leak test vacuous (it globs
`/tmp/tmp*.clip`).

### Other rules that cost real time

- Capture pytest's REAL exit code with `> log 2>&1; echo $?` —
  piping through `tail` reports tail's 0.
- Log long runs to `~/workspace/tmp/`, never `/tmp` (a VM
  recycle wipes `/tmp` mid-run; one gate run was SIGTERMed
  exactly that way).
- Never `pkill -f` a pattern matching your own command; use
  `kill $PID`. Other agents run pytest in this VM — check a
  PID's cwd before killing anything.
- The 3 skips are intentional (ffmpeg-dependent tests skip when
  ffmpeg is absent; the live llama.cpp test skips without the
  model path — see §4).

### What the suite covers

- **Unit**: every Kaam-Vaani module (retrieval, translation,
  extraction, matching, skill graph, geohash, dedup, scam rules,
  consent, employers, rights, video, pilot, rate limits,
  deletion) with seeded in-memory/temporary SQLite stores.
- **Router**: every KV endpoint via TestClient — auth (401
  anonymous), roles (403 wrong role), validation (400/422),
  flag-off (404), rate limits (429), happy paths (200).
- **Invariants as tests**: the audit log is append-only (a
  source-grep test fails if any UPDATE/DELETE against
  `kv_consent_audit` appears); the L50 expiry query uses its
  index (EXPLAIN QUERY PLAN test); the video result always
  carries "indicative, not a certificate"; deletion never
  touches the audit log.
- **Regression tests** pin every bug found during the build
  (e.g. the 9.1 `topics=None` TypeError, the 9.4 mic
  Permissions-Policy). Never weaken a test to make it pass —
  fix the code, or fix the test only when the test itself is
  wrong (and say so in the commit).

## 2. Evaluations (the quality bar — separate from unit tests)

```bash
# Kaam-Vaani eval (189 gold cases: 55 profile, 115 retrieval,
# 19 refusal). MUST pass before any commit touching retrieval:
~/workspace/projects/career-venv/bin/python -m eval.run_kv
# Current: PASS — profile 1.000, recall@5 1.000, MRR 0.970,
# faithfulness 0.948 (109/115), refusal 0.947 (18/19).
# The 6 unfaithful cases: kv-r015, kv-r033, kv-r056, kv-r059,
# kv-r086, kv-r089. Any retrieval/ranking change MUST re-run this.

# Golden eval (legacy matching quality):
~/workspace/projects/career-venv/bin/python -m eval.run
# Current: skills Hit@5 1.0 / MRR 0.827.

# Chat eval (grounding/faithfulness of the chat surface):
~/workspace/projects/career-venv/bin/python -m eval.run_chat_eval
# Current: 4/4 + 8/8.
```

Every eval re-run re-dirties `eval/kv_report.json` with
latency-only changes — verify the diff is latency-only (no
metric values changed) and commit the regen with the next commit.
Never hand-edit an eval number.

## 3. Frontend gate (no unit tests — typecheck + lint + build)

```bash
cd frontend
npx tsc --noEmit        # must be clean
npx eslint .            # 0 errors (3 pre-existing warnings)
# Production build — ALWAYS in an isolated copy on workspace
# disk, NEVER `rm -rf frontend/out` in the repo:
#   rsync -a --exclude node_modules --exclude .next --exclude out \
#     frontend/ ~/workspace/tmp/<name>-build/frontend/
#   ln -s <repo>/frontend/node_modules <copy>/frontend/node_modules
#   cd <copy>/frontend && NEXT_EXPORT=1 npx next build
# Current: exit 0, 1019 pages.
```

## 4. Optional / environment-gated tests

- **Live llama.cpp test** (`KV_TEST_LLAMACPP_MODEL`): needs the
  0.5B GGUF model at
  `~/workspace/tmp/models/qwen2.5-0.5b-instruct-q4_k_m.gguf`.
  Set the env var to that path to run it; otherwise it skips.
- **ffmpeg tests** (video check): skip if ffmpeg/ffprobe are
  absent. They generate synthetic clips (testsrc) — no real
  task recordings exist in the repo.
- **Postgres tests**: run against a live Postgres 16.2 when
  `DATABASE_URL` is set (Step 7C verified migrations 1–14
  apply); otherwise SQLite.

## 5. Load test

```bash
~/workspace/projects/career-venv/bin/python -m eval.kv_load \
  --work-dir ~/workspace/tmp/kv95-run
# 20 users × 5 rounds = 500 requests, 0 errors, 18.46 req/s,
# RSS peak 293 MB. Numbers: docs/PERFORMANCE.md.
```

## 6. What is NOT tested

- No frontend unit/integration tests (see §3).
- No automated accessibility audit (axe/Lighthouse) on KV
  screens (L68).
- No end-to-end browser test of the voice flow — the mic path
  is unverified headless (L25); it needs a real phone.
- The LoRA notebook was never executed; the local LLM was
  executed once (Step 8.7) and is covered by the gated test
  above, not by the default suite.
