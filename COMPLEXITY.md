# Kaam-Vaani — Complexity and Measured Performance

Big-O complexity and MEASURED numbers for the whole Kaam-Vaani
system (Steps 0–8, 20–21 Nov 2026). Nothing here is estimated:
every latency, memory figure and accuracy number comes from a
benchmark, an eval run, or a test run listed in §18. Where a
number was measured twice with different results, both are shown
and the spread is explained.

**Machine:** the development sandbox VM — 4 CPU threads (AMD EPYC
9D25), ~8 GB RAM, no GPU. Latencies on this box are indicative
for the pilot, not a production SLA: the same run on a different
day or under load differs by tens of percent. The Big-O column
is the part that survives a machine change.

**Companion docs:** `ARCHITECTURE.md` §7 holds the same
complexity analysis per component (the prose version, kept in
sync with the code); this file is the consolidated measured
reference. `docs/PERFORMANCE.md` covers the pre-Kaam-Vaani
Phase 10 paths (public catalog cache, `/recommend` latency,
DB index review) — not repeated here.

## 1. Variables

| Symbol | Meaning | Pilot value |
|---|---|---|
| C | RAG chunks in the snapshot | 1,048 (snapshot v2) |
| n | Occupations in the taxonomy | 974 |
| L | Verified listings | 45 (seed) |
| W | Words in a listing description | ~30–80 |
| S | Shingles in a listing | ~W |
| G | Gap skills for one profile | 6–9 |
| V, E | Nodes / edges in a gap graph | 9–14 |
| q | Query tokens | ~5–15 |
| d | Dense embedding dimension | 384 (e5-small) |

## 2. RAG retrieval (`career_guidance/kaamvaani/rag.py`)

BM25 + TF-IDF hybrid over the snapshot, held in memory per
process. One query = translate → sparse scoring over all C
chunks → title-evidence rescue → extractive answer → citation
verification.

| | |
|---|---|
| Time per query | **O(C)** sparse dot products over the query's terms, plus O(S × T) verification (§9) |
| Index build | O(C × terms) once per process (lazy, on first request) |
| Space | O(C × avg terms) — a few MB at snapshot scale |

**Measured (KV eval, 189 cases, snapshot v2, 21 Nov 2026):**
p50 **39.6 ms**, p95 **58.9 ms**, max 145.9 ms, mean 31.2 ms.
An earlier same-day run showed p50 63 ms — the spread is machine
load, not the code. A focused benchmark of `answer_question`
alone (20 questions × 3, 8.6) gave p50 21.8 ms / p95 33.6 ms /
mean 23.3 ms; the router adds ~6 ms of overhead on a cold call
(§15).

**Retriever build (first request):** 4,262 ms the first time in
a fresh process (sklearn/numpy warm-up on the first TF-IDF fit),
then 762 / 693 ms on repeat builds — the ~0.7 s warm cost is the
real index build; the ~4.3 s first build is a cold-start tax
paid once per process (L59). A third measurement (8.9 bench,
sklearn already imported) gave 1,728 ms with peak RSS rising
~33 MB during the build — that peak includes transient sklearn
fit allocations, not just the steady-state index. No request
pays it twice: the retriever is cached on the store for the
process lifetime.

**Quality (same eval):** profile 1.000, recall@5 1.000,
MRR 0.970, faithfulness 0.948 (109/115), refusal 0.947.
Per-language recall@5 is 1.000 in EN, HI and TA.

## 3. Glossary translation (`translate.py`)

Longest-phrase-first lookup over the Tamil/Hindi/Roman glossary
(~130 terms, ~8 KB YAML, loaded once per process), with Tamil
suffix-strip + pulli retry.

| | |
|---|---|
| Time per query | **O(q × w)**, max phrase width w = 3 — dict lookups only |
| Space | O(glossary) ≈ 8 KB |

**Measured:** 0.019 ms per question (69 questions, 1.3 ms total
cold vs 0.1 ms warm — the 8.6 translation cache is a negligible
win in absolute terms, kept because it is free and correct).
English queries are a verified no-op: the translation returns
the input unchanged and retrieval is byte-identical with or
without the translation step.

## 4. Occupation ranker (`matching.py` + `ranker.py`)

`KVScorer.rank` scores every occupation the zone filter keeps
(~800 of 974 for a 12th-pass profile) and orders them through
`MultiCriteriaRanker`.

| | |
|---|---|
| Score one occupation | O(core + phrases × title words) — core competencies ≤ 10, all inputs small |
| Combine features | O(F), F = 5 live features |
| Order | O(n log n) via the injected comparator, each comparison O(1) |
| IDF table build | O(n × core), once per scorer construction |
| Space | O(n × core) core-competency cache + O(competencies) IDF table, both per-scorer (the router holds one scorer for the process lifetime) |

**Measured:** the title-evidence rescue (8.1) is one float
comparison per answer — no measurable latency (KV eval after
the change: p50 103 ms, p95 204 ms over 189 cases, dominated by
retrieval, not ranking). The dominant cost inside `rank` is the
base matcher: `_base_scores` runs MatcherV2 over the full
taxonomy once per call. End-to-end `/matches` latency is in §15.

**Quality:** the ranker fixed kv-r013/r039 (title-evidence
rescue) and moved faithfulness 0.930 → 0.948. Six unfaithful
cases remain (kv-r015, kv-r033, kv-r056, kv-r059, kv-r086,
kv-r089) — all rank 2–3 sibling near-misses, recall passes
everywhere.

## 5. Employer matching (`consent.py`, Stage 6)

`rank_candidates_for_listing`: one query for granted consents,
one bulk profile fetch, `score_candidate` per consented worker,
then a sort.

| | |
|---|---|
| Score one candidate | O(R + W + P) — required competencies, worker competencies, phrase-variant sets; all single-digit to low-teens |
| Rank | O(C log C) for C consented candidates, plus O(C) audit INSERTs (one `accessed` event per returned candidate, in a single transaction) |
| Grant / revoke / profile-save | O(1) row operations + one audit INSERT |
| Lazy expiry | **O(log consents + expired)** — the expiry query
  (`status='granted' AND expires_at <= now`) uses
  `idx_kv_consents_expiry` on `(status, expires_at)`, shipped
  in v14; verified by `test_expiry_query_uses_index` (Step 9.4
  closed L50) |
| Space | One row per worker profile, one per consent, one audit row per candidate returned per search — the audit log grows **O(searches × candidates returned)**; no archival/rotation exists yet (L49) |

**Measured (seeded DB, listing 1, 13 consented candidates):**
31–58 ms per ranking call, mean 41.2 ms over 5 runs (includes
the 13 audit inserts; the spread is SQLite fsync variance).
The 20-candidate default cap (`limit`, max 100) bounds the
per-call work.

## 6. Skill-gap path engine (`skillgraph.py`, 8.2)

Builds the production graph (gap skills + catalogue courses,
one node per course URL), runs Dijkstra per gap skill from a
START node over lexicographic `(paid, count)` costs, then
orders the chosen courses by topological order with
gap-importance priority.

| | |
|---|---|
| Dijkstra | O((V + E) log V) per gap skill; G gaps cost O(G × (V + E) log V) |
| Topological order (Kahn's) | O(V + E) |
| Graph build | O(G × R) resource lookups (R ≤ 2 candidates per skill) + a DOMAIN_HINTS scan for covered-gap compression |
| Space | O(V + E), built per request and discarded — no cache (the catalogue is small and the build is sub-millisecond) |

**Measured (five probe profiles, 20 runs each):** mean **0.36 ms**
per plan (min 0.28, max 0.43 ms). Production graphs are tiny
(9–14 nodes, 9–14 edges) — the engine is nowhere near a
bottleneck at any plausible scale; a catalogue 100× larger would
still plan in milliseconds.

**Coverage (same five profiles, flat path vs engine):**
23/38 → 28/38. All engine courses free (0 paid) on these
profiles; paid-minimisation is proven on hand-made graphs, not
exercised by the probe set. The 10 still-uncovered gaps have no
curated resource at all (L32/L56) and are listed as uncovered,
not silently dropped. No prerequisite data exists (L56) — plan
order is gap-importance until NSQF data lands.

## 7. Geohash location index (`geo.py`, 8.3)

Encodes every verified listing once (precision 6, ~1.2 km ×
0.61 km cells), keeps `(hash, item_id)` pairs sorted. A radius
query picks a query precision from the radius (p6 to 5 km, p5
to 60 km, p4 to 150 km, p3 beyond), enumerates the geohash
cells intersecting the query disc's bounding box (padded one
cell per side), pulls each cell's entries with a binary-search
prefix range, and filters with an exact haversine distance.
The geohash only prunes; the haversine decides.

| | |
|---|---|
| Build | O(n log n) sort, O(n) space |
| Query | O(cells × log n + candidates) haversines, cells ≤ ~40 for the precision table — vs O(n) haversines for a linear scan |
| Cache | The index is cached on the store instance and invalidated by every listing write; without the cache the build (~1 s at 100k) would dwarf the per-query saving |

**Measured (50 random queries each, radii 10/25/50 km,
synthetic points in a Tamil Nadu bounding box — labelled
synthetic, the seed has only 45 real listings):**

| Listings | Index | Linear scan | Speedup |
|---|---|---|---|
| 1,000 | 2.28 ms | 0.67 ms | **0.3×** — the ~2 ms cell-enumeration overhead dominates below ~5k listings |
| 10,000 | 2.09 ms | 7.18 ms | **3.4×** |
| 100,000 | 7.13 ms | 70.70 ms | **9.9×** |

Build: 8.6 ms / 86 ms / 1,005 ms. The first precision table
(coarse cells, p3 for 50 km) pulled ~56% of a 100k table into
the filter and measured only 1.8× — the retune to fine cells is
what the numbers above reflect.

**Correctness:** the property test pins exact agreement with a
linear scan on seeded random data (300 trials, two seeds, two
regions, radii 1–500 km, 0 mismatches). The one-cell padding
was found by measurement: without it, 13 misses in 60 trials
(cells touching the box in a sliver fall between grid points).

**Limits:** the radius is city-centre to city-centre (A57) —
listings carry a city name only. Only the 6 seed cities have
coordinates (L57).

## 8. Duplicate detection (`dedup.py`, 8.4)

Three layers: exact SHA-256 fingerprint over normalised title
+ city + description; a Bloom filter over the fingerprints as
the pre-filter (a "definitely not present" skips the dict
lookup; a "possibly present" is confirmed by the dict, so a
Bloom false positive can never flag a listing); and word
3-shingle Jaccard (adaptive shingle size for short texts)
against the same employer's listings in the same city, at or
above the tuned threshold of 0.5.

| | |
|---|---|
| Build | O(L × W) for L listings of W words (shingle sets) |
| Exact lookup | O(k) Bloom hashes + O(1) dict |
| Near lookup | O(E × S) Jaccard comparisons against the employer's E listings in the city with S shingles each |
| Space | O(L × S) shingle sets + 95,851 bits (~12 KB) for the Bloom filter |
| Cache | Cached on the store, invalidated by every listing write |

**Measured (labelled set, 369 pairs):** precision **1.000**,
recall **0.907** at threshold 0.5 (F1 0.951). The full sweep:
0.3 → P 1.000 / R 0.982; 0.4 → 1.000 / 0.953; 0.5 → 1.000 /
0.907; 0.6 → 1.000 / 0.832; 0.8 → 1.000 / 0.405. 0.5 was chosen
over 0.3 for its 0.389 margin above the highest negative
(0.111). Bloom FP rate: 0/10,000 probes at pilot scale
(45 items); at the 10k design point, measured 0.0095 vs
theoretical 0.0100. Zero false negatives on real fingerprints
(by construction — a Bloom filter never misses a member).

**Scope:** same title + different description is a new opening,
not a duplicate (deliberate). Cross-employer duplication is out
of scope (L42).

## 9. Citation verifier (`citations.py`, 8.5)

`verify_answer` checks every answer sentence against its cited
chunk with token overlap (stopwords dropped, light stemming):
a sentence is supported when ≥ 0.8 of its content tokens appear
in the chunk. Unsupported sentences are dropped; if nothing
grounded remains the answer refuses with reason `"unverified"`.

| | |
|---|---|
| Time | O(S × T) for S sentences and T chunk tokens (set intersections) — negligible next to retrieval |
| Space | O(T) token sets per answer |

**Measured on the 115 gold retrieval cases: 115/115 answers
verified, 591/591 sentences supported** (support rate 1.000;
complete sentences 476/476), 0 dropped, 0 unverified refusals,
0 answers changed — the verifier proves the extractive
guarantee rather than changing behaviour. All 115 answers hit
the 600-char cap, so the truncation path is the common path,
not an edge case. The 6 unfaithful cases are all verified
(faithful=False, verified=True): grounding is not relevance
(L58), and faithfulness stays 0.948.

## 10. Caches (`cache.py`, 8.6)

Bounded, thread-safe LRU caches (`LruCache`, SHA-256 keys,
optional per-entry TTL, deepcopy of values on put and read so
a caller can never mutate a cached value).

| Cache | Max entries | TTL | Invalidates on |
|---|---|---|---|
| `translation_cache` | 512 | — | Process restart only (glossary is static per process) |
| `profile_cache` | 256 | — | Prompt-version change (keyed on payload + prompt version); process restart |
| `llm_cache` | 256 | 3600 s | TTL expiry; process restart. Failures are never cached |
| Router answer/search cache | 256 | — | **Snapshot version bump** (key includes the snapshot versions tuple) — a re-ingest can never serve stale answers |
| Profile cache in `/extract` | 256 | — | Same as `profile_cache` |

| | |
|---|---|
| Lookup / insert | O(1) amortised (OrderedDict) |
| Eviction | O(1) LRU |
| Space | O(max entries × value size); all caches are per-process, in-memory — a restart starts cold (L59) |

**Measured (8.6 benchmark, 20 questions × 3):**

| | p50 | p95 | mean |
|---|---|---|---|
| `answer_question` raw | 21.8 ms | 33.6 ms | 23.3 ms |
| Router `/ask` cold | 27.4 ms | 734 ms* | — |
| Router `/ask` warm (cache hit) | **3.6 ms** | — | — |

\* The cold p95 is the first request building the retriever
(§2). Warm calls are **~7.6× faster** than cold ones. Two
passes over 20 questions gave 20 hits / 20 misses (hit rate
0.50, as expected). LLM cache: 10 identical completions →
1 provider call (50 ms mock).

## 11. Voice profile extraction (`profile.py`, Stage 3)

LLM-first structured output + Pydantic validation + one repair
attempt, deterministic fallback, per-question guided mode.

| | |
|---|---|
| Deterministic fallback | O(answers × vocabulary) — vocabulary lookups over the alias tables |
| LLM extraction | The provider's cost (no key is configured in this build, so the fallback is the live path; see §12 for the measured local-LLM cost) |
| Space | The confirmed profile is held client-side in sessionStorage only — zero server-side storage, zero server-side retention |

**Measured:** deterministic extraction scores profile 1.000 on
the 55 gold cases (KV eval). LLM extraction quality is
unmeasured against a live provider (L23) — the only live LLM
measurement is the local 0.5B model in §12, which follows the
schema but makes semantic errors the validator cannot catch.

## 12. Local LLM provider (`providers.py`, 8.7)

`LlamaCppCompleter` (llama.cpp via llama-cpp-python) and the
pre-existing `OllamaCompleter` interface. The 0.5B model was
EXECUTED in this sandbox; Ollama was not (its server was never
run here — L60).

**Measured (Qwen2.5-0.5B-Instruct Q4_K_M, 469 MB GGUF, 21 Nov
2026):**

| | |
|---|---|
| Model load | 0.4 s |
| Peak RSS | 670 MB at n_ctx 2048 (603 MB at 512) |
| Generation | 10.1 tokens/s (60 tokens in 5.9 s, short prompt) |
| Full extraction, production prompt (~1440 tokens) | **35.9 s** — prompt processing dominates on CPU |
| Context needed | 2048 (the 512 default fails: "Requested tokens (1439) exceed context window of 512") |

**Quality (honest, L60):** with the real prompt the 0.5B model
follows the JSON schema reliably and gets concrete fields right
on unseen input (tailor in Salem, 10th pass, ₹20,000/month:
skills, education, city, income all correct) but makes two
semantic errors — `interests` "job_6_months" and `goal_type`
"explore" for a person who explicitly wants a job — and
Pydantic validation does NOT catch these (the types are all
valid). With a short prompt that did not spell out the schema,
the same model invented its own keys. The deterministic
fallback and the voice flow's confirm step stay mandatory.

**Dense retrieval (opt-in, Step 7A):** `intfloat/multilingual-
e5-small` — 470 MB fp32 weights, ~900 MB RAM measured,
p50 269 ms per query vs 39 ms glossary (p95 8,496 ms on the
first-call-included run — the p50 is the honest comparison).
Adopted: NO — RRF fusion scored faithfulness 0.728 and refusal
0.600 (sibling confusion at rank 1 + compressed cosine band
breaking the refusal floors). The model reads Tamil/Hindi
natively — proven, just not rank-safe yet (L52).

## 13. LoRA data builder (`lora_data.py`, 8.8)

The 55 gold profile cases → TRL messages-format JSONL
(49 train / 6 val, seed 42, deterministic — byte-identical
SHA-256 hashes on re-run). Target = the deterministic
extractor's full 7-field output, validated against the gold
`expected` (skills as a set); a drifted case is skipped with a
reason — 0 skipped. Every example validated before writing
(3-turn shape, 7-key JSON assistant reply, PII safety net).

| | |
|---|---|
| Time | O(cases × answers × vocabulary) — one deterministic extraction per case, plus O(examples) validation |
| Space | O(cases) in memory; the committed dataset is 55 lines of JSONL |

**Measured:** 0.69–0.82 s for the full 55-case build (mean
0.75 s over 3 runs, incl. Python startup). **Training was NOT
run** — no GPU in this sandbox — and the Colab notebook was
NOT executed (L61). No accuracy gain is claimed anywhere.

## 14. Agent trace log (`trace.py`, 8.9)

Per-request structured JSON trace (translation / retrieval /
ranking / verification stages with latencies). PII-free by
construction: the question is identified by a hash, span
details carry counts and scores only, and unsafe detail keys
or over-long values are rejected at write time.

**Measured (traced vs untraced, 20 gold retrieval questions × 3
runs each, snapshot v2, 21 Nov 2026):**

| | p50 | p95 | mean |
|---|---|---|---|
| `answer_question` untraced | 49.67 ms | 62.45 ms | 51.52 ms |
| `answer_question` traced + stored | 48.95 ms | 66.89 ms | 51.31 ms |

**Trace overhead: −0.21 ms mean delta (−0.4%) — unmeasurable,
inside run-to-run noise.** Span creation, detail validation,
`finish` and the sink store together cost less than the
measurement noise (~±2 ms between runs). A trace record is
small: mean **747 bytes** of JSON (743–749). 200 sink stores
take 0.26 ms total (**0.0013 ms per store**). Tracing is free
in practice; the retrieval it observes costs ~50 ms.

(The untraced p50 here, 49.67 ms, is higher than the 8.6
benchmark's 21.8 ms — different question mix (the first 20
gold retrieval cases include Tamil/Hindi and wage questions)
and machine load. The KV eval's p50 on the same day was
39.6 ms. The traced-vs-untraced comparison is what matters,
and it was run back-to-back in one process.)

| | |
|---|---|
| Span start / finish | O(1) — a timestamp and a dict entry |
| Detail validation | O(keys × values) per span, tiny (≤ 6 keys) |
| Sink store | O(1) amortised (OrderedDict insert + popitem eviction) |
| Sink read (`recent`) | O(limit) |
| Space | O(max traces × trace size) in memory (default 200 traces); optional JSONL file sink rotates at 10 MB, 3 files (~30 MB max) |

**Retention:** size-bounded, NOT time-based. Recommended ops
retention is 7 days, enforced by a logrotate/pruning cron on
the JSONL file — no time-based pruning is built in (L62).
Traces are process-local; a restart starts empty; the file is
the only durable copy.

## 15. End-to-end request latencies

Measured 21 Nov 2026 via TestClient on the real snapshot v2
(10 distinct payloads per endpoint, 20 distinct questions for
/ask — distinct inputs keep the caches cold):

| Endpoint | p50 | p95 | mean | Notes |
|---|---|---|---|---|
| `POST /api/v1/kv/rag/ask` | 63.88 ms | 158.66 ms | 144.48 ms* | * Mean skewed by the first request building the retriever (max 1,663 ms). The 8.6 bench on a different question set gave cold p50 27.4 ms — the spread is question mix + load |
| `POST /api/v1/kv/rag/ask` (warm, cache hit) | **3.6 ms** | — | — | 8.6 bench; ~7.6× faster than cold |
| `POST /api/v1/kv/voice/extract` (deterministic) | 6.79 ms | 146.09 ms† | 32.41 ms | † p95 is the first call (vocab/completer setup, max 256.55 ms); steady state is ~6–7 ms |
| `POST /api/v1/kv/matches` | 376.57 ms | 427.49 ms | 384.45 ms | The slowest endpoint — the base MatcherV2 pass over the full taxonomy runs once per call (§4); no cache on /matches (profile-dependent) |
| `GET /api/v1/kv/traces` | — | — | — | O(limit) read from the in-memory ring; admin only; not benchmarked (a dict slice) |

## 16. Space summary (per process, pilot scale)

| Component | Memory |
|---|---|
| RAG index (1,048 chunks, BM25 + TF-IDF) | A few MB |
| Glossary | ~8 KB |
| Ranker (core cache + IDF table) | O(n × core), small (974 occupations) |
| Geohash index (45 listings) | Negligible; O(n) at scale |
| Duplicate index (45 listings) | Negligible + 12 KB Bloom filter |
| Caches (512 + 256 + 256 + 256 entries) | Bounded by entry counts; values are small JSON |
| Trace ring (200 traces) | 200 × ~747 bytes ≈ **150 KB** (measured mean trace size) |
| Dense model (opt-in, NOT loaded by default) | ~900 MB RAM |
| Local LLM 0.5B (opt-in, NOT loaded by default) | 670 MB peak RSS |
| SQLite DB (seed data) | Small; grows O(searches × candidates) via the audit log (§5) |

## 17. What breaks first at scale

Honest ordering, worst first:

1. **Local LLM extraction (35.9 s per profile)** — unusable
   synchronously on CPU at any volume; the deterministic
   fallback is the live path for a reason. A hosted LLM or a
   GPU changes this, not a code tweak.
2. **Audit log growth O(searches × candidates)** — unbounded
   today (L49); the 365-day retention POLICY is recorded
   (Step 9.4, COMPLIANCE.md §4) but no automated prune exists
   — the prune is a deliberate future ops decision.
3. **Lazy consent expiry — CLOSED (Step 9.4).** v14 already
   ships `idx_kv_consents_expiry` on `(status, expires_at)`
   and the expiry query matches it exactly; a test proves the
   planner uses the index. Not a bottleneck.
4. **Retriever build (~0.7 s warm, ~4.3 s first)** — paid once
   per process; a deploy/restart makes the first request slow.
   Warm the retriever at startup (not built yet).
5. **Geohash index build (~1 s at 100k listings)** — cached
   and invalidated per write, so a write-heavy workload
   rebuilds it often; fine for the read-heavy pilot.
6. **Per-process in-memory caches** — a restart starts cold
   and two processes do not share state (L59). A shared cache
   (Redis) is a Step 9+ decision, not a pilot need.
7. **`/matches` at ~380 ms** — the base MatcherV2 pass over the
   full taxonomy runs once per call. Fine for the pilot (a
   human-paced voice flow), but the slowest endpoint; caching
   the base scores per profile signature is the obvious fix if
   it ever matters.
8. **Trace ring (200 traces)** — a busy process ages traces
   out in minutes; the JSONL file sink is the durable copy,
   and it needs the pruning cron (L62).

What does NOT break: the skill-graph engine (0.36 ms/plan),
translation (0.019 ms), the verifier (negligible vs
retrieval), the Bloom filter (12 KB to 10k items).

## 18. Measurement log

| Number | Source | Date |
|---|---|---|
| KV eval latencies p50 39.6 / p95 58.9 / max 145.9 ms | `eval/kv_report.json` (regenerated in the 8.9 gate) | 21 Nov 2026 |
| `answer_question` p50 21.8 / p95 33.6 ms; /ask cold 27.4 / warm 3.6 ms; retriever build 4262/762/693 ms; translation 0.019 ms | `~/workspace/tmp/kv86_bench.py` → `kv86_bench.log` | 21 Nov 2026 |
| Employer matching 31–58 ms, mean 41.2 ms | Stage 6 live verify, seeded DB | 21 Nov 2026 |
| Skill-graph plan 0.36 ms; coverage 23/38 → 28/38 | Step 8.2 probes | 21 Nov 2026 |
| Geohash 0.3× / 3.4× / 9.9×; build 8.6/86/1005 ms | `~/workspace/tmp/kv83_bench.py` | 21 Nov 2026 |
| Dedup P 1.000 / R 0.907; Bloom FP 0.0095 vs 0.0100 | `~/workspace/tmp/kv84_tune.py` | 21 Nov 2026 |
| Verifier 115/115, 591/591 sentences | `~/workspace/tmp/kv85_verify.py` | 21 Nov 2026 |
| Local LLM: load 0.4 s, RSS 670 MB, 10.1 tok/s, extraction 35.9 s | `~/workspace/tmp/kv87_live.py` | 21 Nov 2026 |
| Dense: ~900 MB RAM, p50 269 ms, faithfulness 0.728 | `EVAL_REPORT.md` (Step 7A) | 21 Nov 2026 |
| LoRA build 0.69–0.82 s (55 cases) | 3 runs, `scripts/build_lora_data.py` | 21 Nov 2026 |
| Trace overhead + /extract + /matches latencies | `~/workspace/tmp/kv89_bench.py` → `kv89_bench.log` | 21 Nov 2026 |
