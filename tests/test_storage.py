"""Tests for SQLite persistence and analytics."""

from career_guidance.analytics import summarize
from career_guidance.models import CareerRecommendation
from career_guidance.storage import Database, runs_to_json, runs_to_markdown


def _recommendation(title: str = "Software Developer") -> CareerRecommendation:
    return CareerRecommendation(
        title=title,
        match_reason="Good fit",
        suitability="beginner",
        matching_skills=["python"],
        missing_skills=["sql"],
        learning_path=["learn sql"],
        next_steps=["build a project"],
    )


def _db(tmp_path) -> Database:
    return Database(str(tmp_path / "test.db"))


def test_save_and_list_runs(tmp_path):
    db = _db(tmp_path)
    run_id = db.save_run({"skills": "python"}, [_recommendation()], provider="Demo", is_demo=True)
    assert run_id > 0
    runs = db.list_runs()
    assert len(runs) == 1
    assert runs[0].provider == "Demo"
    assert runs[0].recommendations[0].title == "Software Developer"
    assert runs[0].profile["skills"] == "python"


def test_count_and_clear(tmp_path):
    db = _db(tmp_path)
    db.save_run({"skills": "a"}, [_recommendation()], provider="Demo", is_demo=True)
    db.save_run({"skills": "b"}, [_recommendation()], provider="OpenAI", is_demo=False)
    assert db.count_runs() == 2
    db.clear()
    assert db.count_runs() == 0


def test_exports_contain_run_data(tmp_path):
    db = _db(tmp_path)
    db.save_run({"skills": "python"}, [_recommendation()], provider="Demo", is_demo=True)
    runs = db.list_runs()
    assert "Software Developer" in runs_to_json(runs)
    assert "Software Developer" in runs_to_markdown(runs)


def test_analytics_summary(tmp_path):
    db = _db(tmp_path)
    db.save_run(
        {"skills": "a"},
        [_recommendation(), _recommendation("Data Analyst")],
        provider="Demo",
        is_demo=True,
    )
    db.save_run({"skills": "b"}, [_recommendation()], provider="OpenAI", is_demo=False)
    summary = summarize(db.list_runs())
    assert summary.total_runs == 2
    assert summary.ai_runs == 1
    assert summary.demo_runs == 1
    assert ("Software Developer", 2) in summary.top_careers
    assert ("sql", 3) in summary.top_missing_skills
    assert len(summary.runs_per_day) >= 1
