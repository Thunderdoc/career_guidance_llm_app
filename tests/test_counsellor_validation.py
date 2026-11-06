"""Phase 5 eval tooling: the counsellor-validation agreement script."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.counsellor_validation import agreement_stats, load_rows

SAMPLE = Path(__file__).resolve().parent.parent / "eval" / "counsellor_sample.csv"


def test_sample_csv_is_fake_and_script_computes_agreement():
    rows = load_rows(SAMPLE)
    assert len(rows) == 5
    assert all(r["run_id"].startswith("SAMPLE-") for r in rows)  # clearly fake
    stats = agreement_stats(rows)
    assert stats["runs_reviewed"] == 5
    assert stats["top1_agreement"] == 2
    assert stats["top1_agreement_percent"] == 40.0
    assert stats["top5_inclusion"] == 5
    assert stats["ratings"] == {"agree": 2, "partial": 2, "disagree": 1}


def test_missing_column_and_bad_rating_are_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("run_id,rating\n1,agree\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_rows(bad)
    bad.write_text(
        "run_id,counsellor_top_pick,system_top_pick,system_top5,rating\n1,A,A,A,loved-it\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        load_rows(bad)
