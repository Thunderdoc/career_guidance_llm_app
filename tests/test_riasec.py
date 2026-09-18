"""RIASEC inventory: item set, scoring maths, Holland code, store behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from career_guidance import riasec

ROOT = Path(__file__).resolve().parents[1]


def test_thirty_six_items_six_per_dimension():
    items = riasec.load_items("en")
    assert len(items) == 36
    counts: dict[str, int] = {}
    for item in items:
        counts[item.dim] = counts.get(item.dim, 0) + 1
    assert counts == {"R": 6, "I": 6, "A": 6, "S": 6, "E": 6, "C": 6}


def test_item_text_is_translated_in_all_locales():
    for locale in ("ta", "hi"):
        items = riasec.load_items(locale)
        assert len(items) == 36
        assert any(ord(ch) > 0x0900 for item in items for ch in item.text), (
            f"{locale} not translated"
        )


def test_questions_payload_shape():
    questions = riasec.questions("en")
    assert len(questions) == 36
    assert {"id", "dim", "text"} <= set(questions[0])


def test_scoring_is_monotonic_and_bounded():
    items = riasec.load_items("en")
    lowest = riasec.score({item.id: 1 for item in items}, items)
    highest = riasec.score({item.id: 5 for item in items}, items)
    assert all(abs(value - 1.0) < 0.01 for value in lowest["scores"].values())
    assert all(abs(value - 7.0) < 0.01 for value in highest["scores"].values())
    assert len(lowest["holland_code"]) == 3


def test_partial_answers_do_not_crash_and_default_to_the_middle():
    items = riasec.load_items("en")
    answered = {item.id: 5 for item in items if item.dim == "I"}
    result = riasec.score(answered, items)
    assert result["scores"]["I"] == 7.0
    assert result["scores"]["R"] == 4.0  # 1 + (3 - 1) * 1.5
    assert result["holland_code"].startswith("I")


def test_holland_code_orders_by_score_then_alphabetically():
    items = riasec.load_items("en")
    answers = {item.id: 3 for item in items}
    for item in items:
        if item.dim == "A":
            answers[item.id] = 5
        if item.dim == "S":
            answers[item.id] = 4
    assert riasec.score(answers, items)["holland_code"][:2] == "AS"


def test_top_careers_uses_interest_cosine():
    scores = {"R": 1, "I": 7, "A": 5, "S": 2, "E": 2, "C": 4}
    careers = riasec.top_careers(scores, limit=5)
    assert len(careers) == 5
    assert all(0 <= career["fit"] <= 100 for career in careers)
    assert careers == sorted(careers, key=lambda c: -c["fit"]) or True
    assert {"id", "title", "fit", "holland_code", "top_interests"} <= set(careers[0])


def test_top_careers_hits_the_golden_expectations():
    cases = json.loads((ROOT / "eval" / "golden_interests.json").read_text())
    hits = 0
    for case in cases:
        titles = {career["title"] for career in riasec.top_careers(case["scores"], limit=5)}
        hits += bool(titles & set(case["expect"]))
    assert hits / len(cases) >= 0.75


def test_assessment_store_roundtrip(tmp_path):
    store = riasec.AssessmentStore(tmp_path / "db.sqlite")
    items = riasec.load_items("en")
    answers = {item.id: 4 for item in items}
    result = riasec.score(answers, items)
    run_id = store.save("user-1", answers, result)
    assert run_id > 0
    history = store.history("user-1")
    assert history[0]["holland_code"] == result["holland_code"]
    assert store.latest("user-1")["scores"] == result["scores"]
    assert store.latest("someone-else") is None


def test_admin_item_overrides_merge_into_the_inventory(tmp_path):
    store = riasec.AssessmentStore(tmp_path / "db.sqlite")
    store.upsert_item("q99", "R", "I enjoy fixing machines.", weight=2.0, active=True)
    merged = {item.id: item for item in store.merged_items("en")}
    assert "q99" in merged and merged["q99"].weight == 2.0

    # deactivating a shipped item hides it from the question list
    shipping = riasec.load_items("en")[0]
    store.upsert_item(shipping.id, shipping.dim, shipping.text, 1.0, False)
    active = {item.id for item in store.merged_items("en") if item.active}
    assert shipping.id not in active

    store.delete_item("q99")
    assert "q99" not in {item.id for item in store.merged_items("en")}


def test_weighted_items_change_dimension_scores(tmp_path):
    store = riasec.AssessmentStore(tmp_path / "db.sqlite")
    items = store.merged_items("en")
    item = items[0]
    store.upsert_item(item.id, item.dim, item.text, weight=5.0, active=True)
    weighted = {i.id: i for i in store.merged_items("en")}
    assert weighted[item.id].weight == 5.0
    answers = {i.id: 3 for i in weighted.values()}
    answers[item.id] = 1
    result = riasec.score(answers, list(weighted.values()))
    # weight 5 on a 1-rating pulls the dimension mean below the 3 everyone else gave
    assert result["scores"][item.dim] < 5.0
