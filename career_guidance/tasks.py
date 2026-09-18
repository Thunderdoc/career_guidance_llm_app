"""Typical activities ("tasks") for an occupation, derived and labelled.

Our bundled catalog ships title, description, skills, knowledge and tools — but
no O*NET task statements. Rather than inventing tasks, this module *derives*
activity statements from the description text we do have (sentence splitting +
verb detection) and labels the source as
``Source: O*NET occupation description (derived activities)``.

The interview-question generator and the career detail page both use these
statements, so nothing is presented as an authoritative O*NET task list.
"""

from __future__ import annotations

import re

from career_guidance.taxonomy import Occupation

SOURCE = "Source: O*NET occupation description (derived activity statements)"

_SPLIT = re.compile(r"(?<=[.;])\s+")
_ACTIVITY_SIGNALS = (
    "may ",
    "design",
    "develop",
    "analyse",
    "analyze",
    "prepare",
    "maintain",
    "inspect",
    "install",
    "repair",
    "operate",
    "supervise",
    "teach",
    "coordinate",
    "manage",
    "plan",
    "review",
    "assist",
    "provide",
    "test",
    "monitor",
    "evaluate",
    "advise",
    "train",
    "perform",
)


def derive_tasks(occupation: Occupation, limit: int = 6) -> list[dict]:
    """Activity statements inferred from the description sentences."""
    text = (occupation.description or "").strip()
    if not text:
        return []
    candidates: list[str] = []
    for raw in _SPLIT.split(text):
        sentence = raw.strip().rstrip(".")
        if len(sentence) < 25:
            continue
        head = sentence.lower()
        if any(signal in head for signal in _ACTIVITY_SIGNALS):
            candidates.append(sentence[0].upper() + sentence[1:])
    if not candidates:  # fall back to the longest sentences
        candidates = [s.strip().rstrip(".") for s in _SPLIT.split(text) if len(s.strip()) > 30]
    out: list[str] = []
    seen: set[str] = set()
    for sentence in candidates:
        key = sentence.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(sentence)
        if len(out) >= limit:
            break
    return [{"text": t, "source": SOURCE} for t in out]


def task_phrases(occupation: Occupation, limit: int = 10) -> list[str]:
    """Short, lower-case activity phrases for question templates."""
    tasks = derive_tasks(occupation, limit=limit)
    phrases = []
    for task in tasks:
        text = task["text"]
        text = re.sub(r"^(may|must|should)\s+", "", text, flags=re.I)
        # Keep the first clause so the phrase fits inside a question.
        text = re.split(r"[,;]| in order to | so that ", text, maxsplit=1)[0].strip()
        words = text.split()
        phrase = " ".join(words[:12]).rstrip(".")
        if phrase:
            phrases.append(phrase[0].lower() + phrase[1:])
    if not phrases:
        phrases = [
            f"apply {skill.lower()}"
            for skill in (occupation.skills[:3] or occupation.knowledge[:3])
        ]
    return phrases


def education_path(occupation: Occupation) -> list[dict]:
    """Job-zone based education path (O*NET job-zone definition), source-labelled."""
    zone = occupation.job_zone
    levels = {
        1: ("Little or no preparation", "Short on-the-job training; 10th pass is usually enough."),
        2: ("Some preparation", "A certificate, ITI/12th pass or a few months of training."),
        3: ("Medium preparation", "Diploma, ITI trade or a vocational certification."),
        4: ("Considerable preparation", "Bachelor's degree (B.Tech/B.Sc/B.Com/BA) or equivalent."),
        5: ("Extensive preparation", "Postgraduate degree (M.Tech/MBA/MD/M.Sc) or PhD."),
    }
    label, typical = levels.get(zone, ("Medium preparation", "Diploma or bachelor's degree."))
    path = [
        {
            "level": f"Job zone {zone}: {label}",
            "typical": typical,
            "source": "Source: O*NET job-zone definitions",
        }
    ]
    if zone >= 4:
        path.append(
            {
                "level": "Add a specialisation",
                "typical": "Certification in the tool stack this role uses (see the tools list).",
                "source": "Source: curated guidance",
            }
        )
    return path
