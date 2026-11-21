"""Step 8.2 tests: the DAG + Dijkstra skill-gap path engine.

Engine correctness is proven on small hand-made graphs where the
right answer is known (spec 8.2); the production builder is tested
with a fake catalogue (free/paid choice, shared-course dedupe,
covered-gap compression, uncovered reporting) and against the real
catalogue on the demo profile; the router test pins the additive
``skill_plan`` key on the gap-learning response.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.kv_matching import build_router as build_kv_matching_router
from career_guidance.config import Settings
from career_guidance.kaamvaani.extract import VoiceProfile
from career_guidance.kaamvaani.matching import KVScorer
from career_guidance.kaamvaani.profile import (
    extract_profile_guided,
    new_session,
    transition,
)
from career_guidance.kaamvaani.rag import RagStore, load_snapshot_file
from career_guidance.kaamvaani.skillgraph import (
    START,
    SkillGraph,
    build_gap_graph,
    implied_by_held,
    skill_plan_for,
)
from career_guidance.learning import resources_for
from career_guidance.migrations import migrate
from career_guidance.models import LearningResource

ROOT = Path(__file__).resolve().parent.parent

DEMO_ANSWERS = {
    "skills": "farming and basic computer work, and I can type",
    "education": "12th pass",
    "city": "Madurai",
    "income": "15000 rupees a month",
    "goal": "I need a job",
}


def _demo_profile() -> VoiceProfile:
    profile, _ = extract_profile_guided(DEMO_ANSWERS, None)
    return profile


def _confirmed_session(profile: VoiceProfile):
    session = new_session("en")
    session = transition(session, "start")
    session = transition(session, "set_language", language="en")
    for qid, text in DEMO_ANSWERS.items():
        session = transition(session, "answer", question_id=qid, transcript=text, source="typed")
    session = transition(session, "extracted", profile=profile)
    return transition(session, "confirm", confirmed=True)


# --------------------------------------------------------------------------- #
# Engine: hand-made graphs with known answers
# --------------------------------------------------------------------------- #


def test_dijkstra_linear_chain_sums_costs():
    graph = SkillGraph()
    graph.add_edge("a", "b", (0, 1))
    graph.add_edge("b", "c", (1, 1))
    assert graph.shortest_path("a", "c") == ((1, 2), ["a", "b", "c"])


def test_dijkstra_free_path_beats_paid_shortcut():
    """Lexicographic (paid, count): a free two-course path (0, 2)
    beats a paid one-course path (1, 1) — free resources first."""
    graph = SkillGraph()
    graph.add_edge("s", "x", (0, 1))
    graph.add_edge("x", "g", (0, 1))
    graph.add_edge("s", "g", (1, 1))
    assert graph.shortest_path("s", "g") == ((0, 2), ["s", "x", "g"])


def test_dijkstra_fewest_courses_among_free():
    """Among free paths, fewer courses wins: (0, 2) < (0, 5)."""
    graph = SkillGraph()
    graph.add_edge("s", "a", (0, 1))
    graph.add_edge("a", "g", (0, 1))
    graph.add_edge("s", "b", (0, 1))
    graph.add_edge("b", "c", (0, 1))
    graph.add_edge("c", "d", (0, 1))
    graph.add_edge("d", "e", (0, 1))
    graph.add_edge("e", "g", (0, 1))
    assert graph.shortest_path("s", "g") == ((0, 2), ["s", "a", "g"])


def test_dijkstra_diamond_picks_cheaper_branch():
    graph = SkillGraph()
    graph.add_edge("s", "b", (0, 2))
    graph.add_edge("s", "c", (1, 1))
    graph.add_edge("b", "d", (0, 1))
    graph.add_edge("c", "d", (0, 1))
    # Via b: (0, 3). Via c: (1, 2). Free wins.
    assert graph.shortest_path("s", "d") == ((0, 3), ["s", "b", "d"])


def test_dijkstra_unreachable_and_unknown_are_none():
    graph = SkillGraph()
    graph.add_edge("a", "b")
    graph.add_node("lonely")
    assert graph.shortest_path("a", "lonely") is None
    assert graph.shortest_path("a", "nope") is None
    assert graph.shortest_path("nope", "b") is None


def test_dijkstra_start_is_goal():
    graph = SkillGraph()
    graph.add_node("a")
    assert graph.shortest_path("a", "a") == ((0, 0), ["a"])


def test_topological_order_respects_edges_and_is_deterministic():
    graph = SkillGraph()
    graph.add_edge("a", "b")
    graph.add_edge("a", "c")
    graph.add_edge("b", "d")
    graph.add_edge("c", "d")
    first = graph.topological_order()
    second = graph.topological_order()
    assert first == second
    assert first[0] == "a"
    assert first[-1] == "d"
    assert first.index("b") < first.index("d")
    assert first.index("c") < first.index("d")


def test_topological_order_uses_priority():
    """Among ready nodes the lowest priority value goes first."""
    graph = SkillGraph()
    graph.add_node("zebra")
    graph.add_node("apple")
    graph.add_node("mango")
    assert graph.topological_order() == ["apple", "mango", "zebra"]
    assert graph.topological_order({"zebra": 0, "mango": 1, "apple": 2}) == [
        "zebra",
        "mango",
        "apple",
    ]


def test_cycle_detection_names_the_cycle():
    graph = SkillGraph()
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("c", "b")
    assert graph.has_cycle() is True
    with pytest.raises(ValueError, match="cycle"):
        graph.topological_order()
    acyclic = SkillGraph()
    acyclic.add_edge("a", "b")
    assert acyclic.has_cycle() is False


# --------------------------------------------------------------------------- #
# Builder: fake catalogue
# --------------------------------------------------------------------------- #


def _resource(skill: str, title: str, url: str, *, free: bool) -> LearningResource:
    return LearningResource(skill=skill, title=title, url=url, provider="Test Provider", free=free)


def _fake_resources(skill: str, limit: int = 2) -> list[LearningResource]:
    table = {
        "welding": [
            _resource(
                "welding", "Welding Basics (paid)", "https://example.com/weld-paid", free=False
            ),
            _resource(
                "welding", "Welding Basics (free)", "https://example.com/weld-free", free=True
            ),
        ],
        "safety": [
            _resource(
                "safety", "Welding Basics (free)", "https://example.com/weld-free", free=True
            ),
        ],
        "drawing": [],
    }
    return table.get(skill.strip().lower(), [])[:limit]


def test_builder_picks_free_over_paid_for_same_skill():
    _graph, plan = build_gap_graph(["welding"], [], resources_fn=_fake_resources)
    assert len(plan.steps) == 1
    assert plan.steps[0].url == "https://example.com/weld-free"
    assert plan.steps[0].free is True
    assert plan.total_cost == (0, 1)


def test_builder_dedupes_shared_course():
    """One course covering two gaps appears once and is counted once."""
    _graph, plan = build_gap_graph(["welding", "safety"], [], resources_fn=_fake_resources)
    assert len(plan.steps) == 1
    assert plan.steps[0].skills == ["welding", "safety"]
    assert plan.total_cost == (0, 1)
    assert plan.skills_covered == 2


def test_builder_reports_uncovered_gaps():
    _graph, plan = build_gap_graph(["welding", "drawing"], [], resources_fn=_fake_resources)
    assert plan.skills_covered == 1
    assert plan.uncovered == [
        {
            "skill": "drawing",
            "reason": "no curated resource in the catalogue for this skill",
        }
    ]
    assert plan.skills_total == 2


def test_builder_orders_steps_by_gap_importance():
    """Steps follow the missing list's order (importance order)."""
    _graph, plan = build_gap_graph(["safety", "welding"], [], resources_fn=_fake_resources)
    # The shared free course serves both; its skills list is importance-ordered.
    assert plan.steps[0].skills == ["safety", "welding"]


def test_builder_drops_gaps_covered_by_held_skills():
    """Held 'python' covers the 'programming' gap through DOMAIN_HINTS;
    an exact held match covers too."""
    assert implied_by_held("programming", ["python"]) == "python"
    assert implied_by_held("welding", ["welding"]) == "welding"
    assert implied_by_held("welding", ["python"]) is None
    _graph, plan = build_gap_graph(
        ["programming", "welding"], ["python"], resources_fn=_fake_resources
    )
    assert plan.covered_by_held == [{"skill": "programming", "via": "python"}]
    assert [s for step in plan.steps for s in step.skills] == ["welding"]


def test_builder_empty_gaps_is_empty_plan():
    _graph, plan = build_gap_graph([], [], resources_fn=_fake_resources)
    assert plan.steps == []
    assert plan.total_cost == (0, 0)
    assert plan.to_dict()["totals"]["skills_total"] == 0


def test_plan_dict_shape_and_totals():
    _graph, plan = build_gap_graph(
        ["welding", "safety", "drawing"], [], resources_fn=_fake_resources
    )
    data = plan.to_dict()
    assert data["totals"] == {
        "courses": 1,
        "paid_courses": 0,
        "free_courses": 1,
        "skills_covered": 2,
        "skills_total": 3,
        "skills_already_held": 0,
        "skills_uncovered": 1,
    }
    assert data["steps"][0]["source"] == "curated catalogue"
    assert "L56" in data["ordering"]


def test_graph_nodes_carry_course_attrs():
    graph, _plan = build_gap_graph(["welding"], [], resources_fn=_fake_resources)
    node = graph.attrs["course:https://example.com/weld-free"]
    assert node["kind"] == "course"
    assert node["free"] is True
    assert node["title"] == "Welding Basics (free)"
    assert START in graph.nodes


# --------------------------------------------------------------------------- #
# Production builder: real catalogue, demo profile
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def scorer() -> KVScorer:
    return KVScorer()


def test_real_catalogue_plan_covers_every_resourced_gap(scorer):
    """On the demo profile's top match, the engine covers exactly the
    gaps the catalogue has a resource for — and lists the rest as
    uncovered instead of silently dropping them (the flat path's
    flaw)."""
    ranked, _ = scorer.rank(_demo_profile(), top_k=1)
    match = ranked[0]
    plan = skill_plan_for(match.missing, match.matched)
    resourced = [s for s in match.missing if resources_for(s, 2)]
    assert plan["totals"]["skills_covered"] == len(resourced)
    assert plan["totals"]["skills_total"] == len(match.missing)
    uncovered = {u["skill"] for u in plan["uncovered"]}
    assert uncovered == set(match.missing) - set(resourced)
    assert plan["totals"]["skills_covered"] + len(uncovered) == len(match.missing)
    for step in plan["steps"]:
        assert step["url"].startswith("http")
        assert step["skills"]
    paid = sum(1 for step in plan["steps"] if not step["free"])
    assert plan["totals"]["paid_courses"] == paid
    assert plan["totals"]["courses"] == len(plan["steps"])


def test_real_catalogue_plan_beats_flat_path_coverage(scorer):
    """The engine covers at least as many gaps as the flat path
    (which caps at 5) on the demo profile — and strictly more when
    resourced gaps sit beyond the cap."""
    from career_guidance.kaamvaani.matching import learning_path_for

    ranked, _ = scorer.rank(_demo_profile(), top_k=1)
    match = ranked[0]
    flat = learning_path_for(match.missing)
    plan = skill_plan_for(match.missing, match.matched)
    flat_covered = len({item["skill"] for item in flat})
    assert plan["totals"]["skills_covered"] >= flat_covered
    assert plan["totals"]["skills_covered"] > flat_covered  # demo has resourced gaps past the cap


# --------------------------------------------------------------------------- #
# Router: gap-learning returns the additive skill_plan
# --------------------------------------------------------------------------- #


@pytest.fixture()
def matching_client(tmp_path):
    db = str(tmp_path / "kv.db")
    migrate(db)
    chunks, _meta = load_snapshot_file(ROOT / "data" / "kv_rag_snapshot_v2.jsonl")
    RagStore(db).replace_snapshot(chunks, "v2")
    settings = Settings(database_path=db)
    app = FastAPI()
    app.include_router(build_kv_matching_router(settings))
    with TestClient(app) as client:
        yield client


def test_gap_learning_returns_skill_plan(matching_client):
    profile = _demo_profile()
    session = _confirmed_session(profile)
    body = {
        "session": session.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "occupation_id": "43-9021.00",  # Data Entry Keyers
    }
    r = matching_client.post("/api/v1/kv/gap-learning", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["learning_path"]  # existing contract untouched
    plan = data["skill_plan"]
    assert plan["totals"]["skills_total"] == data["gap"]["counts"]["missing"]
    assert plan["totals"]["courses"] == len(plan["steps"])
    assert plan["steps"]
    for step in plan["steps"]:
        assert step["url"].startswith("http")
        assert step["skills"]
