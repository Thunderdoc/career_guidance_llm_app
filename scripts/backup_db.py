#!/usr/bin/env python3
"""Back up the SQLite database (Phase 6).

Creates a timestamped copy of the database file, verifies the copy with
SQLite's own ``PRAGMA integrity_check`` and prunes older backups beyond
the retention count. Uses the sqlite3 backup API, so it is safe to run
while the app is serving (no torn copies from a live file).

Usage:
    python scripts/backup_db.py [--db data/career_guidance.db]
                                [--out-dir backups] [--keep 14]

Postgres deployments: use ``pg_dump`` instead — see docs/DEPLOY.md.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def integrity_ok(path: Path) -> bool:
    """True when SQLite reports the file's integrity check as ok."""
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"
    except sqlite3.Error:
        return False


def backup_name(db_path: Path, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{db_path.stem}-{stamp}{db_path.suffix}"


def make_backup(db_path: Path, out_dir: Path, keep: int = 14) -> Path:
    """Copy ``db_path`` into ``out_dir`` (verified) and prune old backups."""
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / backup_name(db_path)
    with sqlite3.connect(str(db_path)) as source, sqlite3.connect(str(target)) as dest:
        source.backup(dest)
    if not integrity_ok(target):
        target.unlink(missing_ok=True)
        raise RuntimeError(f"backup failed integrity check, discarded: {target}")
    backups = sorted(out_dir.glob(f"{db_path.stem}-*{db_path.suffix}"))
    for stale in backups[: max(0, len(backups) - keep)]:
        stale.unlink()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/career_guidance.db")
    parser.add_argument("--out-dir", default="backups")
    parser.add_argument("--keep", type=int, default=14, help="backups to retain")
    args = parser.parse_args(argv)
    try:
        target = make_backup(Path(args.db), Path(args.out_dir), keep=args.keep)
    except (FileNotFoundError, RuntimeError) as error:
        print(f"backup failed: {error}", file=sys.stderr)
        return 1
    print(f"backup ok: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
