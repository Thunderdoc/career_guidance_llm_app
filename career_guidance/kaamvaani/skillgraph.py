"""Kaam-Vaani skill-gap path engine (Step 8.2): a prerequisite DAG +
Dijkstra over (paid courses, course count), free resources first.

Why this module exists: the Stage 4 gap view hands the user a flat
list — the first resource per gap skill, capped at 5, with no order,
no cheapest-first choice, and no word about the gaps the catalogue
cannot cover (measured on the five probe profiles: the flat path
covers 5/8, 5/7, 5/6, 3/9, 5/8 gaps and silently drops the rest).
This engine returns an ORDERED plan: for each gap skill the
cheapest learning path (Dijkstra), topologically ordered so
prerequisites come first, shared courses counted once, paid courses
minimised, and uncovered gaps listed honestly with the reason.

The graph
---------

* :class:`SkillGraph` is a general directed graph with
  lexicographic tuple weights ``(paid, count)`` — paid courses
  first, then course count, so a free two-course path beats a paid
  one-course path. :meth:`SkillGraph.topological_order` is Kahn's
  algorithm (deterministic: ready nodes break ties by a caller
  priority, alphabetical by default) and raises ``ValueError`` on
  a cycle. :meth:`SkillGraph.shortest_path` is Dijkstra over the
  tuple weights (``heapq``); it returns ``None`` when the goal is
  unreachable.
* :func:`build_gap_graph` builds the production graph from real
  data only: nodes are the gap skills + the catalogue courses
  that teach them (``resources_for`` per skill, up to 2 candidates
  each so Dijkstra has a free/paid choice); edges are
  course → skill with the course's cost. Gap skills implied by a
  held skill through ``DOMAIN_HINTS`` (the "covers" relation) are
  dropped before the graph is built — the user already has them.

Honest limits (see LIMITATIONS.md L56)
--------------------------------------

* **No prerequisite edges exist in the production graph** — no
  prerequisite data exists anywhere in the repo (O*NET importance
  order is importance, NOT a prerequisite; the bridge-paths YAML
  is profession-change routes, not skill prerequisites; NSQF
  appears twice in the KB and is not a progression structure).
  The engine fully supports prerequisite edges (proven on
  hand-made graphs where the right answer is known), and the
  builder adds them the day real data lands — but until then the
  graph has none, and the plan order is gap-importance order
  (the missing list is already importance-ordered).
* **Time is course count.** The catalogue carries no durations,
  so one course = one unit of effort (ASSUMPTIONS.md A56). The
  (time, cost) weights from the spec are therefore (course count,
  paid count) — both measured, neither invented.
* **The plan is the union of per-skill cheapest paths, not a
  global set-cover optimum.** Dijkstra finds the cheapest path to
  EACH gap skill; the plan unions those paths and counts shared
  courses once. A single course covering several gaps at a lower
  total cost than the per-skill cheapest picks is not searched
  for (that is set cover, NP-hard). The union is honest and
  explainable — "for each skill you lack, the cheapest way to
  learn it" — and the limitation is stated, not hidden.

Complexity: Dijkstra is O((V + E) log V) per gap skill;
topological order is O(V + E); the builder is O(G x R) resource
lookups for G gaps and R resources per skill. Production graphs
are tiny (V <= ~30) — the whole plan computes in well under a
millisecond (measured in ARCHITECTURE.md §7.6).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from career_guidance.learning import resources_for
from career_guidance.models import LearningResource
from career_guidance.taxonomy import DOMAIN_HINTS, normalize_skill

#: Lexicographic edge/path cost: (paid courses, course count).
#: Tuples compare lexicographically, so "free first, then fewest
#: courses" falls out of plain tuple comparison and addition.
Cost = tuple[int, int]

ZERO_COST: Cost = (0, 0)

START = "__start__"


def _add_cost(a: Cost, b: Cost) -> Cost:
    return (a[0] + b[0], a[1] + b[1])


class SkillGraph:
    """A directed graph with lexicographic tuple weights.

    Nodes are string ids; edges carry a :data:`Cost`. An edge
    ``source -> target`` means "source must come before target"
    (a prerequisite edge) or "source teaches / leads to target"
    (a course edge) — both are order constraints the topological
    sort respects and Dijkstra traverses.
    """

    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.edges: dict[str, list[tuple[str, Cost]]] = {}
        self.attrs: dict[str, dict] = {}

    def add_node(self, node_id: str, **attrs) -> None:
        """Add a node (idempotent; later attrs update earlier ones)."""
        self.nodes.add(node_id)
        self.edges.setdefault(node_id, [])
        self.attrs.setdefault(node_id, {}).update(attrs)

    def add_edge(self, source: str, target: str, cost: Cost = ZERO_COST) -> None:
        """Add an edge, creating its endpoints if needed."""
        self.add_node(source)
        self.add_node(target)
        self.edges[source].append((target, cost))

    def has_cycle(self) -> bool:
        """True when the graph has a cycle (via the topological sort)."""
        try:
            self.topological_order()
        except ValueError:
            return True
        return False

    def topological_order(self, priority: dict[str, int] | None = None) -> list[str]:
        """Kahn's topological order (deterministic).

        Among ready nodes (in-degree 0), the lowest ``priority``
        value goes first; ties (or no priority map) break
        alphabetically. Raises ``ValueError`` naming the nodes
        left unprocessed when the graph has a cycle.
        """
        in_degree: dict[str, int] = {node: 0 for node in self.nodes}
        for source in self.edges:
            for target, _ in self.edges[source]:
                in_degree[target] += 1
        rank = priority or {}
        ready = sorted(
            (node for node, degree in in_degree.items() if degree == 0),
            key=lambda n: (rank.get(n, 0), n),
        )
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for target, _ in self.edges.get(node, []):
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    ready.append(target)
            ready.sort(key=lambda n: (rank.get(n, 0), n))
        if len(order) != len(self.nodes):
            stuck = sorted(set(self.nodes) - set(order))
            raise ValueError(f"skill graph has a cycle involving: {stuck}")
        return order

    def shortest_path(self, start: str, goal: str) -> tuple[Cost, list[str]] | None:
        """Cheapest path from ``start`` to ``goal`` (Dijkstra over
        lexicographic tuple costs), or ``None`` when unreachable.
        Returns ``(cost, node ids including start and goal)``."""
        if start not in self.nodes or goal not in self.nodes:
            return None
        dist: dict[str, Cost] = {start: ZERO_COST}
        prev: dict[str, str] = {}
        heap: list[tuple[Cost, str]] = [(ZERO_COST, start)]
        visited: set[str] = set()
        while heap:
            cost, node = heapq.heappop(heap)
            if node in visited:
                continue
            visited.add(node)
            if node == goal:
                break
            for target, edge_cost in self.edges.get(node, []):
                if target in visited:
                    continue
                new_cost = _add_cost(cost, edge_cost)
                if target not in dist or new_cost < dist[target]:
                    dist[target] = new_cost
                    prev[target] = node
                    heapq.heappush(heap, (new_cost, target))
        if goal not in dist:
            return None
        path = [goal]
        while path[-1] != start:
            path.append(prev[path[-1]])
        path.reverse()
        return dist[goal], path


# --------------------------------------------------------------------------- #
# Production graph: gap skills + catalogue courses (real data only)
# --------------------------------------------------------------------------- #


def _course_node_id(resource: LearningResource) -> str:
    return f"course:{resource.url}"


def _skill_node_id(skill: str) -> str:
    return f"skill:{skill.strip().lower()}"


def implied_by_held(missing: str, held: list[str]) -> str | None:
    """The held skill implying ``missing`` through DOMAIN_HINTS (the
    "covers" relation: knowing the held skill means having the
    competency), or the held skill itself on an exact match, or
    None when no held skill covers it."""
    wanted = missing.strip().lower()
    for skill in held:
        key = skill.strip().lower()
        if key == wanted:
            return skill
        hints = {h.lower() for h in DOMAIN_HINTS.get(normalize_skill(skill), ())}
        if wanted in hints:
            return skill
    return None


@dataclass
class PlanStep:
    """One course in the plan + the gap skills it covers."""

    title: str
    url: str
    provider: str
    free: bool
    skills: list[str] = field(default_factory=list)

    @property
    def cost(self) -> Cost:
        return (0, 1) if self.free else (1, 1)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "free": self.free,
            "skills": list(self.skills),
            "source": "curated catalogue",
        }


@dataclass
class LearningPlan:
    """The ordered learning plan for one occupation's gap list."""

    steps: list[PlanStep] = field(default_factory=list)
    covered_by_held: list[dict] = field(default_factory=list)
    uncovered: list[dict] = field(default_factory=list)
    skills_total: int = 0

    @property
    def total_cost(self) -> Cost:
        paid = sum(1 for step in self.steps if not step.free)
        return (paid, len(self.steps))

    @property
    def skills_covered(self) -> int:
        return len({skill for step in self.steps for skill in step.skills})

    def to_dict(self) -> dict:
        paid, count = self.total_cost
        return {
            "steps": [step.to_dict() for step in self.steps],
            "totals": {
                "courses": count,
                "paid_courses": paid,
                "free_courses": count - paid,
                "skills_covered": self.skills_covered,
                "skills_total": self.skills_total,
                "skills_already_held": len(self.covered_by_held),
                "skills_uncovered": len(self.uncovered),
            },
            "covered_by_held": list(self.covered_by_held),
            "uncovered": list(self.uncovered),
            "ordering": (
                "gap-importance order (no prerequisite data exists — "
                "see LIMITATIONS.md L56); prerequisites would order first"
            ),
        }


def build_gap_graph(
    missing: list[str],
    held: list[str],
    resources_fn=resources_for,
    per_skill: int = 2,
) -> tuple[SkillGraph, LearningPlan]:
    """Build the production graph + plan for a gap list.

    ``missing`` is importance-ordered (the match's missing core
    competencies); ``held`` is the matched list. Returns
    ``(graph, plan)`` — the graph for inspection/tests, the plan
    for the API. ``resources_fn`` is injectable for tests
    (signature: ``(skill, limit) -> list[LearningResource]``).
    """
    plan = LearningPlan(skills_total=len(missing))
    graph = SkillGraph()
    graph.add_node(START, kind="start")

    # 1. Drop gaps the user already covers (exact or via DOMAIN_HINTS).
    open_gaps: list[str] = []
    for skill in missing:
        via = implied_by_held(skill, held)
        if via is not None:
            plan.covered_by_held.append({"skill": skill, "via": via})
        else:
            open_gaps.append(skill)

    # 2. Courses per open gap (up to `per_skill` candidates each, so
    # Dijkstra has a free/paid choice); one node per URL.
    importance = {skill.strip().lower(): rank for rank, skill in enumerate(missing)}
    course_skills: dict[str, list[str]] = {}
    course_resource: dict[str, LearningResource] = {}
    for skill in open_gaps:
        resources = resources_fn(skill, per_skill) or []
        if not resources:
            plan.uncovered.append(
                {
                    "skill": skill,
                    "reason": "no curated resource in the catalogue for this skill",
                }
            )
            continue
        skill_node = _skill_node_id(skill)
        graph.add_node(skill_node, kind="skill", skill=skill)
        for resource in resources:
            course_node = _course_node_id(resource)
            if course_node not in graph.nodes:
                graph.add_node(
                    course_node,
                    kind="course",
                    title=resource.title,
                    url=resource.url,
                    provider=resource.provider,
                    free=resource.free,
                )
                graph.add_edge(START, course_node, (0, 1) if resource.free else (1, 1))
                course_resource[course_node] = resource
                course_skills[course_node] = []
            graph.add_edge(course_node, skill_node, ZERO_COST)
            if skill not in course_skills[course_node]:
                course_skills[course_node].append(skill)

    # 3. Cheapest path per open gap (Dijkstra from START); the plan
    # is the union of those paths. A gap with no path is uncovered
    # (defensive — step 2 already lists resourceless gaps).
    chosen_courses: dict[str, list[str]] = {}
    for skill in open_gaps:
        skill_node = _skill_node_id(skill)
        if skill_node not in graph.nodes:
            continue
        found = graph.shortest_path(START, skill_node)
        if found is None:
            plan.uncovered.append({"skill": skill, "reason": "no learning path in the graph"})
            continue
        _cost, path = found
        for node in path:
            if node.startswith("course:"):
                chosen_courses.setdefault(node, [])
                if skill not in chosen_courses[node]:
                    chosen_courses[node].append(skill)

    # 4. Order: topological order of the graph with gap-importance
    # priority (prerequisites first when edges exist; importance
    # order otherwise — the production graph has no prerequisite
    # edges, L56). Raises on a cycle instead of emitting a bad plan.
    priority: dict[str, int] = {START: -1}
    for node in graph.nodes:
        if node.startswith("skill:"):
            priority[node] = importance.get(node[len("skill:") :], len(missing))
        elif node.startswith("course:"):
            # Order by the most important gap the course actually
            # serves in this plan (chosen skills), not every skill
            # it teaches — a course can teach a skill another
            # course covers more cheaply.
            covered = chosen_courses.get(node) or course_skills.get(node, [])
            priority[node] = min(
                (importance.get(s.strip().lower(), len(missing)) for s in covered),
                default=len(missing),
            )
    ordered = graph.topological_order(priority)
    for node in ordered:
        if node in chosen_courses:
            resource = course_resource[node]
            plan.steps.append(
                PlanStep(
                    title=resource.title,
                    url=resource.url,
                    provider=resource.provider,
                    free=resource.free,
                    skills=sorted(
                        chosen_courses[node],
                        key=lambda s: importance.get(s.strip().lower(), len(missing)),
                    ),
                )
            )
    return graph, plan


def skill_plan_for(
    missing: list[str],
    held: list[str],
    resources_fn=resources_for,
) -> dict:
    """The ordered learning plan for a match's gap list, as an API
    dict (see :func:`build_gap_graph`). An empty gap list returns
    an empty plan — never invented courses."""
    _graph, plan = build_gap_graph(missing, held, resources_fn=resources_fn)
    return plan.to_dict()
