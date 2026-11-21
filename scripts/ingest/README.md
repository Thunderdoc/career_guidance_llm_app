# Kaam-Vaani RAG ingestion (Stage 2)

Fetch → clean → chunk (300–500 tokens, ~50 overlap) → snapshot (+ optional
DB upsert). The snapshot is committed to the repo so the eval harness and
CI run deterministically offline.

## Run it

```bash
# Full refresh (O*NET local + all web sources + wage tables) → data/kv_rag_snapshot_v2.jsonl
python -m scripts.ingest.run --version v2

# O*NET only (no network) / web only / wages only (no network: reads the verified data file)
python -m scripts.ingest.run --version v2 --sources onet
python -m scripts.ingest.run --version v2 --sources web
python -m scripts.ingest.run --version v2 --sources wages

# Also load into a database (migrations must already be applied)
python -m scripts.ingest.run --version v2 --db data/career_guidance.db
```

Outputs: `data/kv_rag_snapshot_<version>.jsonl` (one chunk object per line)
plus `data/kv_rag_snapshot_<version>.meta.json` (provenance: version,
generated_at, per-source chunk counts, per-source fetch log).

## Refresh procedure (new snapshot version)

1. Bump `--version` (v2, v3, …) — never overwrite a version in place; the
   eval report names the snapshot it measured.
2. Run the full refresh. Check the fetch log: a source that starts
   working appears in the new snapshot; one that stops working drops out
   with a log entry.
3. Update `docs/SOURCES.md` §5 with the new per-source fetchability.
4. Re-run the eval: `python -m eval.run_kv`. Update `EVAL_REPORT.md`
   with the new numbers (and the snapshot version).
5. Commit the snapshot + meta + docs together.

## Sources

Registry: `scripts/ingest/web.py` (`OFFICIAL_SOURCES`,
`WIKIPEDIA_SOURCES`); O*NET: `scripts/ingest/onet.py` (local catalogue,
no network); wages: `scripts/ingest/wages.py` (reads the verified
`data/kv_wage_tables_2026-10.json`, no network — the numbers were
OCR'd once from the scanned Labour Bureau PDF and verified two ways;
see `docs/SOURCES.md` §5.1 and `scripts/ingest/ocr_vda_order.py`,
which reproduces the raw OCR evidence). Per-source fetchability
(what works, what is blocked, and why Wikipedia is used as a
fallback where the official site is unfetchable) is documented in
`docs/SOURCES.md` §5 — read it before adding a source.

## Rules

- Official or openly licensed sources only; every chunk stores its full
  citation (URL, title, date, licence, language). A chunk without a
  citation must never enter the store (`Chunk.from_dict` fails loudly).
- No minimum-wage figures from Wikipedia (they go stale, and a stale
  wage quoted as fact would be worse than no wage at all). Specific wage
  questions stay refusal cases until an official minimum-wage source is
  fetchable. Statutory scheme thresholds Wikipedia does carry (EPF/ESI
  ceilings) are ingested with source + fetch date cited; see
  `docs/SOURCES.md` §5 for the EPFO article's two conflicting ceiling
  figures, recorded honestly.
- A failed fetch is logged and skipped — the run succeeds with the
  sources that worked. Zero chunks total fails the run (exit 1).
- Polite fetching: one descriptive User-Agent, 1 s between fetches.
- Never commit a snapshot containing invented content. If a source
  cannot be legally or technically fetched, say so in `SOURCES.md`.
