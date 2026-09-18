"""Transition-path engine: current career → target career in ≤ 3 hops.

Uses the ``related`` matrix that ships with the O*NET catalog (each occupation
lists related occupations) and breadth-first search, so the path is the shortest
chain of realistic moves. Each hop reports the **delta skills** you would have
to add to make that step, and the skills the two occupations share.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from career_guidance.taxonomy import Occupation, Taxonomy, load_taxonomy

MAX_HOPS = 3


@dataclass
class Hop:
    occupation: Occupation
    delta_skills: list[str] = field(default_factory=list)
    shared_skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.occupation.id,
            "title": self.occupation.title,
            "job_zone": self.occupation.job_zone,
            "delta_skills": self.delta_skills,
            "shared_skills": self.shared_skills,
        }


@dataclass
class TransitionPath:
    source: Occupation
    target: Occupation
    hops: list[Hop] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.hops)

    def to_dict(self) -> dict:
        return {
            "from": {"id": self.source.id, "title": self.source.title},
            "to": {"id": self.target.id, "title": self.target.title},
            "hops": len(self.hops),
            "found": self.found,
            "path": [h.to_dict() for h in self.hops],
            "total_delta_skills": _dedupe(s for h in self.hops for s in h.delta_skills),
            "note": (
                "Source: O*NET related-occupations matrix, breadth-first search "
                f"(max {MAX_HOPS} hops)"
            ),
        }


def core_skills(occupation: Occupation, limit: int = 10) -> list[str]:
    """The occupation's headline skills (skills first, then knowledge)."""
    seen: dict[str, None] = {}
    for term in [
        *occupation.skills[:limit],
        *occupation.knowledge[: max(0, limit - len(occupation.skills[:limit]))],
    ]:  # noqa: E501
        seen.setdefault(term.lower(), None)
    return [occupation.skills[i] for i in range(min(limit, len(occupation.skills)))] or list(seen)


def delta_skills(
    source: Occupation, target: Occupation, limit: int = 6
) -> tuple[list[str], list[str]]:
    """(skills to add, skills already shared) moving from source to target."""
    source_terms = {t.lower() for t in [*source.skills, *source.knowledge]}
    target_terms = [*target.skills, *target.knowledge[:4]]
    shared = [t for t in target_terms if t.lower() in source_terms]
    delta = [t for t in target_terms if t.lower() not in source_terms]
    return _dedupe(delta)[:limit], _dedupe(shared)[:limit]


def find_path(
    from_id: str,
    to_id: str,
    taxonomy: Taxonomy | None = None,
    max_hops: int = MAX_HOPS,
) -> TransitionPath:
    """Shortest related-careers path between two occupations (≤ ``max_hops``)."""
    taxonomy = taxonomy or load_taxonomy()
    source = taxonomy.get(from_id)
    target = taxonomy.get(to_id)
    if source is None or target is None:
        raise KeyError(f"unknown occupation: {from_id if source is None else to_id}")
    if source.id == target.id:
        return TransitionPath(source, target, [])

    # BFS over the related matrix.
    queue: deque[list[str]] = deque([[source.id]])
    seen = {source.id}
    found_path: list[str] | None = None
    while queue:
        path = queue.popleft()
        if len(path) > max_hops:
            break
        current = taxonomy.get(path[-1])
        if current is None:
            continue
        for neighbour in current.related:
            if neighbour in seen or taxonomy.get(neighbour) is None:
                continue
            if neighbour == target.id:
                found_path = [*path, neighbour]
                queue.clear()
                break
            seen.add(neighbour)
            queue.append([*path, neighbour])

    if found_path is None:
        return TransitionPath(source, target, [])

    hops: list[Hop] = []
    for previous_id, current_id in zip(found_path, found_path[1:], strict=False):
        previous = taxonomy.get(previous_id)
        current = taxonomy.get(current_id)
        delta, shared = delta_skills(previous, current)
        hops.append(Hop(occupation=current, delta_skills=delta, shared_skills=shared))
    return TransitionPath(source, target, hops)


def transitions_into(
    target_id: str, taxonomy: Taxonomy | None = None, limit: int = 6
) -> list[dict]:
    """Careers from which the target is reachable in one hop (used on career pages)."""
    taxonomy = taxonomy or load_taxonomy()
    target = taxonomy.get(target_id)
    if target is None:
        return []
    out: list[dict] = []
    for occupation in taxonomy.occupations:
        if occupation.id == target.id or target_id not in occupation.related:
            continue
        delta, shared = delta_skills(occupation, target, limit=4)
        out.append(
            {
                "id": occupation.id,
                "title": occupation.title,
                "job_zone": occupation.job_zone,
                "delta_skills": delta,
                "shared_skills": shared,
            }
        )
        if len(out) >= limit:
            break
    return out


def _dedupe(values) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value and value.lower() not in seen:
            seen[value.lower()] = None
    out: list[str] = []
    for key in seen:
        out.append(key if key.islower() else key)
    # Preserve display casing from the first occurrence.
    display: dict[str, str] = {}
    for value in values:
        display.setdefault(value.lower(), value)
    return [display[k] for k in seen]
