"""Interview question generator — templates over O*NET tasks and skills.

10 behavioural + 10 technical questions per occupation, assembled from the
occupation's own tasks and skills with a **deterministic seed** (so the same
career + seed always produces the same set, which keeps caching and tests
simple, and lets a user “shuffle” by passing a new seed).

Admins can add their own templates (``interview_templates`` table); those are
appended to the built-in ones.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache

from career_guidance.tasks import derive_tasks, task_phrases
from career_guidance.taxonomy import Occupation, load_taxonomy

SOURCE = "Source: template engine over O*NET tasks, skills and tools"

BEHAVIOURAL_TEMPLATES = (
    "Describe a time you used {skill} to {task}.",
    "Tell me about a project where {task} was the main goal — what was your part?",
    "How have you handled a situation where {task} did not go to plan?",
    "Give an example of working with a team to {task}.",
    "Describe a time you had to learn {skill} quickly.",
    "Tell me about feedback you received on {skill} and what you changed.",
    "How did you prioritise when you had to {task} under a deadline?",
    "Describe a moment you disagreed with a colleague about how to {task}.",
    "What is the most difficult problem you solved with {skill}?",
    "Tell me about a time you improved a process instead of just following it.",
    "How did you handle a stakeholder who kept changing the requirements for {task}?",
    "Describe how you measure whether you did a good job at {task}.",
)

TECHNICAL_TEMPLATES = (
    "Walk me through how you would approach {task} using {skill}.",
    "What does “good” look like when you {task}? How would you check it?",
    "Which {skill} concepts do you use most often, and why?",
    "You are asked to {task} with half the usual time. What do you cut?",
    "Explain {skill} to a colleague from another department.",
    "How would you debug a problem while trying to {task}?",
    "Which tools do you use for {skill}, and what are their trade-offs?",
    "What are the most common mistakes people make when they {task}?",
    "How would you document your work so someone else can {task} next month?",
    "Describe a scenario where using {skill} would be the wrong choice.",
    "What would you check first if the output of {task} looked wrong?",
    "How do you keep your {skill} knowledge current?",
)

STAR_FIELDS = ("situation", "task", "action", "result")


@dataclass
class Question:
    id: str
    kind: str  # behavioural | technical
    question: str
    hint: str
    star: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "question": self.question,
            "hint": self.hint,
            "star": self.star,
        }


@dataclass
class InterviewKit:
    occupation: Occupation
    seed: int
    questions: list[Question]

    def to_dict(self) -> dict:
        return {
            "career_id": self.occupation.id,
            "title": self.occupation.title,
            "seed": self.seed,
            "questions": [q.to_dict() for q in self.questions],
            "source": SOURCE,
        }


def _star_template() -> dict[str, str]:
    return dict.fromkeys(STAR_FIELDS, "")


@lru_cache(maxsize=64)
def _occupation_bits(career_id: str, seed: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    taxonomy = load_taxonomy()
    occupation = taxonomy.get(career_id)
    if occupation is None:
        return (), ()
    skills = [s for s in occupation.skills[:12]]
    if len(skills) < 6:
        skills += [k for k in occupation.knowledge[:6] if k not in skills]
    tasks = task_phrases(occupation, limit=14)
    return tuple(skills), tuple(tasks)


def generate(
    career_id: str,
    count_behavioural: int = 10,
    count_technical: int = 10,
    seed: int = 42,
    extra_behavioural: list[str] | None = None,
    extra_technical: list[str] | None = None,
) -> InterviewKit:
    """Deterministic 10 + 10 question kit for one occupation."""
    taxonomy = load_taxonomy()
    occupation = taxonomy.get(career_id)
    if occupation is None:
        raise KeyError(career_id)
    skills, tasks = _occupation_bits(career_id, seed)
    if not skills:
        skills = ("communication", "problem solving")
    if not tasks:
        tasks = (f"work as a {occupation.title.lower()}",)
    rng = random.Random(f"{career_id}:{seed}")

    questions: list[Question] = []
    for kind, templates, count, extras in (
        ("behavioural", BEHAVIOURAL_TEMPLATES, count_behavioural, extra_behavioural or []),
        ("technical", TECHNICAL_TEMPLATES, count_technical, extra_technical or []),
    ):
        pool = list(templates) + list(extras)
        skill_order = _rotate(skills, rng.randint(0, len(skills) - 1))
        task_order = _rotate(tasks, rng.randint(0, len(tasks) - 1))
        seen: set[str] = set()
        for index in range(count):
            for attempt in range(len(pool) * 3):
                template = pool[(index + attempt) % len(pool)]
                skill = skill_order[(index + attempt) % len(skill_order)]
                task = task_order[(index * 2 + attempt) % len(task_order)]
                question = template.format(skill=skill, task=task)
                if question not in seen:
                    seen.add(question)
                    break
            hint = (
                f"Anchor it in {skill} and keep it to 90 seconds."
                if kind == "behavioural"
                else f"Explain the trade-offs you considered with {skill}."
            )
            questions.append(
                Question(
                    id=f"{kind[0]}{index + 1}",
                    kind=kind,
                    question=question,
                    hint=hint,
                    star=_star_template(),
                )
            )
    return InterviewKit(occupation=occupation, seed=seed, questions=questions)


def _rotate(items: tuple[str, ...], offset: int) -> list[str]:
    items = list(items)
    if not items:
        return []
    offset %= len(items)
    return items[offset:] + items[:offset]


def tasks_preview(career_id: str, limit: int = 6) -> list[dict]:
    occupation = load_taxonomy().get(career_id)
    return derive_tasks(occupation, limit=limit) if occupation else []
