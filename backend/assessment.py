"""18-item RIASEC (Holland) interest mini-assessment.

Scores map to O*NET interest profiles (R, I, A, S, E, C) so they can be
blended into matching. Items are original, plain-language statements.
"""

from __future__ import annotations

QUESTIONS: list[dict] = [
    {"id": "r1", "dim": "R", "text": "I enjoy fixing or building physical things with my hands."},
    {"id": "r2", "dim": "R", "text": "I'd rather work outdoors or with machines than at a desk."},
    {"id": "r3", "dim": "R", "text": "I like understanding how engines, circuits or tools work."},
    {
        "id": "i1",
        "dim": "I",
        "text": "I like solving puzzles and figuring out why something happens.",
    },
    {"id": "i2", "dim": "I", "text": "I enjoy reading about science, data or technology."},
    {"id": "i3", "dim": "I", "text": "I prefer analysing a problem deeply before acting."},
    {"id": "a1", "dim": "A", "text": "I enjoy drawing, writing, music, design or making videos."},
    {"id": "a2", "dim": "A", "text": "I like work where there's no single right answer."},
    {
        "id": "a3",
        "dim": "A",
        "text": "Expressing ideas creatively matters more to me than routine.",
    },
    {"id": "s1", "dim": "S", "text": "I feel energised when helping or teaching someone."},
    {"id": "s2", "dim": "S", "text": "People come to me for advice or support."},
    {"id": "s3", "dim": "S", "text": "I'd like a job focused on people's wellbeing or learning."},
    {"id": "e1", "dim": "E", "text": "I enjoy persuading people or leading a group."},
    {"id": "e2", "dim": "E", "text": "Starting a business or selling something excites me."},
    {"id": "e3", "dim": "E", "text": "I'm comfortable taking risks to reach a goal."},
    {"id": "c1", "dim": "C", "text": "I like organising information, records or schedules."},
    {
        "id": "c2",
        "dim": "C",
        "text": "I prefer clear procedures and knowing exactly what's expected.",
    },
    {"id": "c3", "dim": "C", "text": "Working carefully with numbers or details suits me."},
]

_NAMES = {
    "R": "Realistic",
    "I": "Investigative",
    "A": "Artistic",
    "S": "Social",
    "E": "Enterprising",
    "C": "Conventional",
}
_BLURB = {
    "R": "Doers — practical, hands-on, mechanical or outdoor work.",
    "I": "Thinkers — analysing, researching, understanding how things work.",
    "A": "Creators — design, writing, media and self-expression.",
    "S": "Helpers — teaching, care, counselling and service.",
    "E": "Persuaders — leading, selling, launching and negotiating.",
    "C": "Organisers — data, procedures, finance and accuracy.",
}


def score_assessment(answers: dict[str, int]) -> dict:
    """Return per-dimension scores on O*NET's 1..7 scale plus a Holland code."""
    totals: dict[str, list[int]] = {d: [] for d in _NAMES}
    for q in QUESTIONS:
        v = answers.get(q["id"])
        if isinstance(v, int) and 1 <= v <= 5:
            totals[q["dim"]].append(v)
    scores = {}
    for dim, vals in totals.items():
        mean = sum(vals) / len(vals) if vals else 3.0
        scores[dim] = round(1 + (mean - 1) * 1.5, 2)  # 1..5 -> 1..7
    ordered = sorted(scores, key=lambda d: -scores[d])
    code = "".join(ordered[:3])
    return {
        "scores": scores,
        "holland_code": code,
        "profile": [
            {"dim": d, "name": _NAMES[d], "score": scores[d], "blurb": _BLURB[d]} for d in ordered
        ],
        "answered": sum(len(v) for v in totals.values()),
        "total": len(QUESTIONS),
    }
