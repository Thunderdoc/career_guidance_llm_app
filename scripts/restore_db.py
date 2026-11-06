#!/usr/bin/env python3
"""Restore the SQLite database from a backup (Phase 6).

Safety order: the backup is integrity-checked and opened (its migration
version is printed) BEFORE anything is touched; the current database is
then copied aside as ``<db>.pre-restore-<timestamp>``; only then is the
backup copied into place and re-checked. A failed restore therefore
never leaves the app without a database.

Usage:
    python scripts/restore_db.py backups/career_guidance-20261106T120000Z.db
                                 [--db data/career_guidance.db]

Stop the app before restoring so no process holds the old file open.
Postgres deployments: use ``pg_restore``/``psql`` — see docs/DEPLOY.md.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # repo-root import (tests, `python -m scripts.restore_db`)
    from scripts.backup_db import integrity_ok
except ImportError:  # direct `python scripts/restore_db.py`
    from backup_db import integrity_ok  # type: ignore[no-redef]


def applied_versions(path: Path) -> list[int]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            return [int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")]
    except sqlite3.Error:
        return []


def restore(backup_path: Path, db_path: Path) -> Path:
    """Restore ``backup_path`` onto ``db_path``; return the safety copy."""
    if not backup_path.exists():
        raise FileNotFoundError(f"backup not found: {backup_path}")
    if not integrity_ok(backup_path):
        raise RuntimeError(f"backup failed integrity check, refusing to restore: {backup_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    safety: Path | None = None
    if db_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safety = db_path.with_name(f"{db_path.name}.pre-restore-{stamp}")
        shutil.copy2(db_path, safety)
    shutil.copy2(backup_path, db_path)
    if not integrity_ok(db_path):
        if safety is not None:
            shutil.copy2(safety, db_path)
        raise RuntimeError("restored file failed integrity check; previous database put back")
    return safety if safety is not None else db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", help="backup file created by scripts/backup_db.py")
    parser.add_argument("--db", default="data/career_guidance.db")
    args = parser.parse_args(argv)
    backup_path, db_path = Path(args.backup), Path(args.db)
    versions = applied_versions(backup_path)
    print(f"backup migration versions: {versions or 'none recorded'}")
    try:
        safety = restore(backup_path, db_path)
    except (FileNotFoundError, RuntimeError) as error:
        print(f"restore failed: {error}", file=sys.stderr)
        return 1
    print(f"restore ok: {backup_path} -> {db_path} (previous database kept at {safety})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
