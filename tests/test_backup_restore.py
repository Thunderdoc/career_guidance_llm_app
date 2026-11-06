"""Phase 6: backup / restore scripts against throwaway databases."""

from __future__ import annotations

import sqlite3

import pytest

from scripts.backup_db import integrity_ok, make_backup
from scripts.restore_db import applied_versions, restore


def _make_db(path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (marker,))
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (7, 'v7', 'now')")


def _marker(path) -> str:
    with sqlite3.connect(str(path)) as conn:
        return conn.execute("SELECT v FROM t").fetchone()[0]


def test_backup_creates_verified_timestamped_copy(tmp_path):
    db = tmp_path / "app.db"
    _make_db(db, "original")
    target = make_backup(db, tmp_path / "backups")
    assert target.exists()
    assert "app-" in target.name and target.suffix == ".db"
    assert integrity_ok(target)
    assert _marker(target) == "original"


def test_backup_retention_prunes_oldest(tmp_path):
    db = tmp_path / "app.db"
    _make_db(db, "x")
    out = tmp_path / "backups"
    out.mkdir()
    for i in range(3):
        (out / f"app-2026010{i}T000000Z.db").write_bytes(b"old")
    make_backup(db, out, keep=2)
    names = sorted(p.name for p in out.glob("app-*.db"))
    assert len(names) == 2
    assert names[-1] not in {f"app-2026010{i}T000000Z.db" for i in range(3)}


def test_backup_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_backup(tmp_path / "nope.db", tmp_path / "backups")


def test_integrity_check_rejects_garbage(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all")
    assert integrity_ok(junk) is False


def test_restore_swaps_and_keeps_pre_restore_copy(tmp_path):
    db = tmp_path / "app.db"
    _make_db(db, "newer")
    backup = make_backup(db, tmp_path / "backups")
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE t SET v = 'changed-after-backup'")
    safety = restore(backup, db)
    assert _marker(db) == "newer"
    assert safety.exists() and "pre-restore" in safety.name
    assert _marker(safety) == "changed-after-backup"
    assert applied_versions(backup) == [7]


def test_restore_refuses_corrupt_backup(tmp_path):
    db = tmp_path / "app.db"
    _make_db(db, "safe")
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"garbage")
    with pytest.raises(RuntimeError, match="integrity"):
        restore(junk, db)
    assert _marker(db) == "safe"  # untouched
