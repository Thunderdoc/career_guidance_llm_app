"""Skill normaliser v2: aliases, expansions, unmatched logging."""

from __future__ import annotations

from career_guidance.synonyms import (
    SkillNormalizer,
    SynonymEntry,
    SynonymStore,
    load_normalizer,
)


def test_indian_and_english_variants_map_to_canonical():
    n = load_normalizer()
    assert n.normalize("js") == "javascript"
    assert n.normalize("ML") == "machine learning"
    assert n.normalize("Tally") == "accounting software"
    assert n.normalize("gst filing") == "tax"
    assert n.normalize("spreadsheets") in {"excel", "spreadsheet software"}
    assert n.normalize("K8s") == "docker"
    assert n.normalize("photoshop") == "graphic design"


def test_tamil_and_hindi_transliterations_map():
    n = load_normalizer()
    assert n.normalize("எக்செல்") == "excel"
    assert n.normalize("टैली") == "accounting software"
    assert n.normalize("डेटा विश्लेषण") == "data analysis"
    assert n.normalize("प्रोग्रामिंग") == "computer programming"


def test_expansions_cover_taxonomy_terms():
    n = load_normalizer()
    expansions = n.expansions_for("accounting software")
    assert "accounting software" in expansions
    assert "bookkeeping software" in expansions
    excel = n.expansions_for("excel")
    assert "spreadsheet software" in excel


def test_resolve_splits_matched_and_unmatched():
    n = load_normalizer()
    result = n.resolve("python, quantum origami, tally")
    assert "python" in result.matched
    assert "accounting software" in result.matched or "accounting" in result.matched
    assert result.unmatched == ["quantum origami"]
    assert 0 < result.coverage < 1


def test_resolve_includes_resume_text():
    n = load_normalizer()
    result = n.resolve("excel", resume_text="Built dashboards in Tableau with SQL")
    assert {"excel", "tableau", "sql"} <= set(result.matched)


def test_custom_entries_override_and_merge():
    n = SkillNormalizer(entries=[SynonymEntry(canonical="sql", aliases=("ansi sql",))])
    assert n.normalize("ansi sql") == "sql"
    n.add_entry(SynonymEntry(canonical="sql", aliases=("structured ql",)))
    assert n.normalize("ansi sql") == "sql" and n.normalize("structured ql") == "sql"


def test_unmatched_store_counts_and_maps(tmp_path):
    store = SynonymStore(tmp_path / "s.db")
    store.log_unmatched(["quantum origami", "Quantum Origami", "zorbing"])
    rows = {r["term"]: r["count"] for r in store.unmatched()}
    # duplicates inside one call collapse; a later call increments the counter
    assert rows["quantum origami"] == 1 and rows["zorbing"] == 1
    store.log_unmatched(["quantum origami"])
    rows = {r["term"]: r["count"] for r in store.unmatched()}
    assert rows["quantum origami"] == 2

    store.map_unmatched("quantum origami", "physics")
    mapped = next(r for r in store.unmatched(include_mapped=True) if r["term"] == "quantum origami")
    assert mapped["mapped_to"] == "physics"
    assert any(s["alias"] == "quantum origami" for s in store.all())
    assert store.stats()["mapped"] == 1


def test_store_entries_feed_normalizer(tmp_path):
    store = SynonymStore(tmp_path / "s2.db")
    store.upsert("busy accounting", "accounting software")
    entries = store.as_entries()
    n = SkillNormalizer(entries=entries)
    assert n.normalize("busy accounting") == "accounting software"
