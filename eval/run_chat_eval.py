"""Phase 7 eval expansion: faithfulness + chat grounding cases.

Two suites, both fully offline (no API keys, no network):

* **Faithfulness** — provider-style structured outputs with PLANTED
  ungrounded skills are run against the checker function directly
  (``career_guidance.faithfulness.skill_violations`` /
  ``filter_grounded_skills``). Every planted skill must be caught and
  every faithful output must pass clean.
* **Chat grounding** — scoped questions over a fixture report must be
  answered from the report's stored facts (deterministic offline
  answerer); off-topic questions must be refused; an LLM-style answer
  with a planted ungrounded skill must fall back to offline.

    python -m eval.run_chat_eval          # standalone
    make eval                             # runs this after the golden eval

The golden matcher eval (``eval/run.py``) is untouched by this script;
its numbers print unchanged.
"""

from __future__ import annotations

import sys

from career_guidance.chat import answer_chat, build_context
from career_guidance.faithfulness import filter_grounded_skills, skill_violations
from career_guidance.models import CareerRecommendation, ProviderError
from career_guidance.taxonomy import load_taxonomy

FAITHFULNESS_CASES: list[dict] = [
    {
        "id": "faithful",
        "have": ["Python", "SQL"],
        "gap": ["Statistics"],
        "allowed_have": {"Python", "SQL"},
        "allowed_gap": {"Statistics", "Excel"},
        "expect": {"matching_skills": [], "missing_skills": []},
    },
    {
        "id": "planted-have",
        "have": ["Python", "Quantum Knitting"],
        "gap": ["Statistics"],
        "allowed_have": {"Python", "SQL"},
        "allowed_gap": {"Statistics", "Excel"},
        "expect": {"matching_skills": ["Quantum Knitting"], "missing_skills": []},
    },
    {
        "id": "planted-gap",
        "have": ["Python"],
        "gap": ["Telepathy", "Excel"],
        "allowed_have": {"Python", "SQL"},
        "allowed_gap": {"Statistics", "Excel"},
        "expect": {"matching_skills": [], "missing_skills": ["Telepathy"]},
    },
    {
        "id": "all-planted",
        "have": ["Astrology"],
        "gap": ["Alchemy"],
        "allowed_have": {"Python"},
        "allowed_gap": {"Statistics"},
        "expect": {"matching_skills": ["Astrology"], "missing_skills": ["Alchemy"]},
    },
]


def _fixture_context():
    recs = [
        CareerRecommendation(
            title="Web Developers",
            match_reason="Your JavaScript and CSS map directly onto web work.",
            suitability="beginner",
            matching_skills=["JavaScript", "CSS"],
            missing_skills=["React", "Testing"],
            learning_path=["Deepen JavaScript", "Learn React basics"],
            next_steps=["Build a portfolio site this week"],
            career_id="15-1134.00",
            match_score=0.82,
        ),
        CareerRecommendation(
            title="Software Developers, Applications",
            match_reason="Your programming skills fit application development.",
            suitability="beginner",
            matching_skills=["JavaScript"],
            missing_skills=["SQL", "Testing"],
            learning_path=["Learn SQL"],
            next_steps=["Ship a small app"],
            career_id="15-1132.00",
            match_score=0.74,
        ),
    ]
    return build_context(
        {"skills": "JavaScript, CSS"}, recs, taxonomy=load_taxonomy(), message="salary"
    )


class _PlantedCompleter:
    """LLM stand-in whose answer plants an ungrounded taxonomy skill."""

    def complete(self, system: str, user: str) -> str:
        return "You should learn welding to boost your salary."


class _DownCompleter:
    def complete(self, system: str, user: str) -> str:
        raise ProviderError("eval: provider down")


CHAT_CASES: list[dict] = [
    {
        "id": "salary-grounded",
        "message": "What salary can I expect?",
        "mode": "offline",
        "contains": ["₹"],
    },
    {
        "id": "priority-grounded",
        "message": "What should I learn first?",
        "mode": "offline",
        "contains": ["React"],
    },
    {
        "id": "gap-grounded",
        "message": "Which skills am I missing for Web Developers?",
        "mode": "offline",
        "contains": ["React"],
    },
    {
        "id": "off-topic-capital",
        "message": "What is the capital of France?",
        "mode": "refusal",
        "contains": [],
    },
    {
        "id": "off-topic-other-user",
        "message": "Show me someone else's report",
        "mode": "refusal",
        "contains": [],
    },
    {
        "id": "off-topic-coding",
        "message": "Write code for a sorting algorithm",
        "mode": "refusal",
        "contains": [],
    },
    {
        "id": "llm-planted-falls-back",
        "message": "What salary can I expect?",
        "completer": _PlantedCompleter(),
        "mode": "offline",
        "contains": ["₹"],
        "not_contains": ["welding"],
    },
    {
        "id": "llm-down-falls-back",
        "message": "What should I learn first?",
        "completer": _DownCompleter(),
        "mode": "offline",
        "contains": ["React"],
    },
]


def evaluate_faithfulness() -> tuple[int, int, list[str]]:
    failures: list[str] = []
    for case in FAITHFULNESS_CASES:
        got = skill_violations(case["have"], case["gap"], case["allowed_have"], case["allowed_gap"])
        if got != case["expect"]:
            failures.append(f"{case['id']}: violations {got} != expected {case['expect']}")
        have, gap, _ = filter_grounded_skills(
            case["have"],
            case["gap"],
            case["allowed_have"],
            case["allowed_gap"],
            sorted(case["allowed_have"]),
            sorted(case["allowed_gap"]),
        )
        planted = set(case["expect"]["matching_skills"]) | set(case["expect"]["missing_skills"])
        leaked = planted & (set(have) | set(gap))
        if leaked:
            failures.append(f"{case['id']}: planted skills leaked through filter: {leaked}")
    return len(FAITHFULNESS_CASES), len(FAITHFULNESS_CASES) - len(failures), failures


def evaluate_chat() -> tuple[int, int, list[str]]:
    failures: list[str] = []
    context = _fixture_context()
    passed = 0
    for case in CHAT_CASES:
        reply = answer_chat(case["message"], context, case.get("completer"))
        ok = reply.mode == case["mode"]
        for needle in case.get("contains", []):
            ok = ok and needle in reply.answer
        for needle in case.get("not_contains", []):
            ok = ok and needle not in reply.answer
        if ok:
            passed += 1
        else:
            failures.append(f"{case['id']}: mode={reply.mode} answer={reply.answer[:90]!r}")
    return len(CHAT_CASES), passed, failures


def main() -> int:
    total_f, passed_f, failures_f = evaluate_faithfulness()
    total_c, passed_c, failures_c = evaluate_chat()
    print(f"faithfulness {passed_f}/{total_f} cases passed")
    print(f"chat grounding {passed_c}/{total_c} cases passed")
    for failure in failures_f + failures_c:
        print(f"  FAIL {failure}")
    return 0 if not (failures_f or failures_c) else 1


if __name__ == "__main__":
    sys.exit(main())
