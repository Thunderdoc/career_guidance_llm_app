"""Kaam-Vaani RAG ingestion runner (Stage 2).

Fetch → clean → chunk → snapshot (+ optional DB upsert):

    # Full refresh: O*NET (local) + all web sources → versioned snapshot
    python -m scripts.ingest.run --version v1
    # O*NET only (no network)
    python -m scripts.ingest.run --version v1 --sources onet
    # Web sources only
    python -m scripts.ingest.run --version v1 --sources web
    # Minimum-wage tables only (no network: reads the verified data file)
    python -m scripts.ingest.run --version v2 --sources wages
    # Also load the snapshot into a database (migrations must be applied)
    python -m scripts.ingest.run --version v1 --db data/career_guidance.db

Outputs: ``data/kv_rag_snapshot_<version>.jsonl`` (one chunk per line) +
``data/kv_rag_snapshot_<version>.meta.json`` (provenance + fetch log).
The snapshot is committed to the repo so the eval harness (``eval/run_kv.py``)
and CI run deterministically offline; refresh it with this command when
sources change (see ``scripts/ingest/README.md``).

A source that fails to fetch is logged and skipped — the run still
succeeds with the sources that worked. The run FAILS (exit 1) only when
zero chunks are produced, because an empty knowledge base is never a
valid snapshot.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career_guidance.kaamvaani.rag import Chunk, RagStore  # noqa: E402
from scripts.ingest.common import SnapshotMeta, now_iso, write_snapshot  # noqa: E402
from scripts.ingest.onet import ingest_onet  # noqa: E402
from scripts.ingest.wages import ingest_wages  # noqa: E402
from scripts.ingest.web import ingest_all_web  # noqa: E402

logger = logging.getLogger("kaamvaani.ingest.run")


def build_snapshot(version: str, sources: str) -> tuple[list[Chunk], SnapshotMeta]:
    """Run the selected ingesters and assemble the snapshot + metadata."""
    wanted = {s.strip() for s in sources.split(",") if s.strip()}
    chunks: list[Chunk] = []
    fetch_log: list[dict] = []
    if "onet" in wanted:
        onet_chunks = ingest_onet(snapshot_version=version)
        chunks.extend(onet_chunks)
        fetch_log.append(
            {
                "source_id": "onet",
                "url": "data/catalog/occupations.json (local)",
                "ok": True,
                "status": None,
                "bytes": 0,
                "chunks": len(onet_chunks),
                "error": "",
            }
        )
        logger.info("ingest onet: %d chunks", len(onet_chunks))
    if "web" in wanted:
        web_chunks, web_log = ingest_all_web(version)
        chunks.extend(web_chunks)
        fetch_log.extend(web_log)
    if "wages" in wanted:
        wage_chunks, wage_log = ingest_wages(version)
        chunks.extend(wage_chunks)
        fetch_log.append(wage_log)
        logger.info("ingest wages: %d chunks", len(wage_chunks))
    meta = SnapshotMeta(
        version=version,
        generated_at=now_iso(),
        sources=dict(Counter(c.source_id for c in chunks)),
        fetch_results=fetch_log,
    )
    return chunks, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1", help="snapshot version (default: v1)")
    parser.add_argument(
        "--sources",
        default="onet,web",
        help="comma list: onet, web, wages (default: onet,web)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="snapshot path without suffix (default: data/kv_rag_snapshot_<version>)",
    )
    parser.add_argument(
        "--db",
        default="",
        help="optional database target to upsert the snapshot into",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")

    out = Path(args.out) if args.out else ROOT / "data" / f"kv_rag_snapshot_{args.version}"
    chunks, meta = build_snapshot(args.version, args.sources)
    if not chunks:
        print("ERROR: zero chunks ingested — refusing to write an empty snapshot", file=sys.stderr)
        return 1
    snapshot_path = write_snapshot(out.with_suffix(".jsonl"), [c.to_dict() for c in chunks], meta)
    print(f"snapshot: {snapshot_path} ({len(chunks)} chunks, {len(meta.sources)} sources)")
    for source_id, count in sorted(meta.sources.items()):
        print(f"  {source_id}: {count}")
    failed = [f for f in meta.fetch_results if not f["ok"]]
    for entry in failed:
        print(f"  FAILED {entry['source_id']} ({entry['url']}): {entry['error']}")
    if args.db:
        store = RagStore(args.db)
        stored = store.replace_snapshot(chunks, args.version)
        print(f"upserted {stored} chunks into {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
