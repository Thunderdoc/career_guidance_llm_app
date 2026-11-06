"""Proof of skill (Phase 3): short quizzes + project evidence.

State machine per (user, skill)::

    unverified ── quiz attempt with score ≥ PASS_PERCENT ──▶ quiz_passed
    quiz_passed ── (automatic) ──▶ verified   (method: "quiz")
    unverified / quiz_passed ── project submitted ──▶ project_submitted
                                                       (flagged self_reported)
    project_submitted ── admin/counsellor review ──▶ verified (method: "project")

Honesty rules baked in:

- Answer keys live only in ``data/skill_quizzes/*.json`` on the server. The
  functions that shape the client payload (:func:`public_quiz`) never include
  the correct option or the explanation.
- A project submission is *self-reported* until a human reviewer approves it;
  nothing in this module claims otherwise.
- Only skills with a quiz file can be quiz-verified; anything else raises
  :class:`QuizUnavailable` (the API turns that into an honest 404).

Anti-abuse: after a *failed* attempt the user must wait
``RETAKE_COOLDOWN_HOURS`` before trying the same skill again. Question order
and option order are randomised per attempt; the attempt token handed to the
client is an HMAC over the shuffled layout, so the client cannot reorder its
way to the key and the server can grade without storing attempt state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from career_guidance.migrations import migrate

PASS_PERCENT = 70.0
RETAKE_COOLDOWN_HOURS = 24

_QUIZ_DIR = Path(__file__).resolve().parent.parent / "data" / "skill_quizzes"

#: Plan/roadmap skill names (O*NET-flavoured) that map onto a quiz skill.
SKILL_ALIASES: dict[str, str] = {
    "python": "python",
    "programming": "python",
    "sql": "sql",
    "html": "html-css",
    "css": "html-css",
    "html/css": "html-css",
    "web development": "html-css",
    "excel": "excel",
    "spreadsheet software": "excel",
    "spreadsheets": "excel",
    "communication": "communication",
    "speaking": "communication",
    "active listening": "communication",
}


class QuizUnavailable(Exception):
    """No quiz exists for this skill (honest 404 at the API layer)."""


class CooldownActive(Exception):
    """A failed attempt is still inside the retake cooldown window."""

    def __init__(self, retry_after_hours: float) -> None:
        super().__init__(f"Retake available in {retry_after_hours:.1f} h")
        self.retry_after_hours = retry_after_hours


def quiz_skill_for(skill: str) -> str | None:
    """Map any skill label to a quiz skill slug, or None when no quiz exists."""
    return SKILL_ALIASES.get((skill or "").strip().lower())


# --------------------------------------------------------------------------- #
# Quiz loading (answer keys never leave this module's server-side structures) #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    options: tuple[str, ...]
    correct: int
    explanation: str


@dataclass(frozen=True)
class Quiz:
    skill: str
    title: str
    questions: tuple[Question, ...]


@lru_cache(maxsize=1)
def _load_quizzes() -> dict[str, Quiz]:
    quizzes: dict[str, Quiz] = {}
    if not _QUIZ_DIR.exists():
        return quizzes
    for path in sorted(_QUIZ_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = tuple(
            Question(
                id=str(q["id"]),
                question=str(q["question"]),
                options=tuple(str(o) for o in q["options"]),
                correct=int(q["correct"]),
                explanation=str(q.get("explanation", "")),
            )
            for q in data["questions"]
        )
        quizzes[str(data["skill"]).strip().lower()] = Quiz(
            skill=str(data["skill"]).strip().lower(),
            title=str(data.get("title", data["skill"])),
            questions=questions,
        )
    return quizzes


def available_quizzes() -> list[dict]:
    """Metadata for every quiz (no questions, no answers)."""
    return [
        {"skill": q.skill, "title": q.title, "questions": len(q.questions)}
        for q in _load_quizzes().values()
    ]


def get_quiz(skill: str) -> Quiz:
    quiz = _load_quizzes().get((skill or "").strip().lower())
    if quiz is None:
        raise QuizUnavailable(skill)
    return quiz


# --------------------------------------------------------------------------- #
# Attempt tokens: the shuffled layout is signed, not stored                  #
# --------------------------------------------------------------------------- #


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def _seal(payload: str, secret: str) -> str:
    """Encrypt + sign the attempt layout.

    The layout names the correct option position per question, so a plain
    signed JSON blob would hand the answer key to anyone who base64-decodes
    it. The payload is therefore XOR-sealed with an HMAC keystream keyed by
    the server secret; the client only ever sees opaque bytes.
    """
    import base64
    import secrets as _secrets

    raw = payload.encode()
    nonce = _secrets.token_bytes(16)
    stream = _keystream(secret.encode(), nonce, len(raw))
    sealed = bytes(b ^ k for b, k in zip(raw, stream, strict=True))
    blob = base64.urlsafe_b64encode(nonce + sealed).decode()
    return f"{blob}.{_sign(blob, secret)}"


def _unseal(token: str, secret: str) -> str:
    import base64

    try:
        blob, signature = token.rsplit(".", 1)
    except ValueError as error:
        raise ValueError("Malformed attempt token.") from error
    if not hmac.compare_digest(signature, _sign(blob, secret)):
        raise ValueError("Invalid attempt token.")
    try:
        data = base64.urlsafe_b64decode(blob.encode())
    except Exception as error:  # noqa: BLE001
        raise ValueError("Malformed attempt token.") from error
    nonce, sealed = data[:16], data[16:]
    stream = _keystream(secret.encode(), nonce, len(sealed))
    return bytes(b ^ k for b, k in zip(sealed, stream, strict=True)).decode()


def start_attempt(skill: str, secret: str, rng: random.Random | None = None) -> dict:
    """A shuffled, answer-free quiz payload plus its signed attempt token.

    The token encodes, per question, the position of the correct option in
    the shuffled option list — HMAC-signed so the client cannot forge or
    read it (the signature key never leaves the server; the layout itself
    reveals nothing without knowing which position is correct).
    """
    quiz = get_quiz(skill)
    rng = rng or random.Random()
    order = list(range(len(quiz.questions)))
    rng.shuffle(order)
    questions_out: list[dict] = []
    layout: list[dict] = []
    for qi in order:
        q = quiz.questions[qi]
        perm = list(range(len(q.options)))
        rng.shuffle(perm)
        questions_out.append(
            {"id": q.id, "question": q.question, "options": [q.options[p] for p in perm]}
        )
        layout.append({"id": q.id, "correct_pos": perm.index(q.correct)})
    payload = json.dumps({"skill": quiz.skill, "layout": layout}, separators=(",", ":"))
    token = _seal(payload, secret)
    return {
        "skill": quiz.skill,
        "title": quiz.title,
        "pass_percent": PASS_PERCENT,
        "questions": questions_out,
        "attempt_token": token,
    }


def grade_attempt(token: str, answers: dict[str, int], secret: str) -> dict:
    """Grade ``{question_id: chosen_option_index}`` against a sealed token."""
    payload = _unseal(token, secret)
    data = json.loads(payload)
    quiz = get_quiz(str(data["skill"]))
    layout = {entry["id"]: int(entry["correct_pos"]) for entry in data["layout"]}
    if set(layout) != {q.id for q in quiz.questions}:
        raise ValueError("Attempt token does not match this quiz.")
    detail: list[dict] = []
    correct_count = 0
    by_id = {q.id: q for q in quiz.questions}
    for qid, correct_pos in layout.items():
        chosen = answers.get(qid)
        ok = chosen is not None and int(chosen) == correct_pos
        correct_count += int(ok)
        detail.append(
            {
                "id": qid,
                "correct": ok,
                "explanation": by_id[qid].explanation,
            }
        )
    total = len(layout) or 1
    percent = round(100.0 * correct_count / total, 1)
    return {
        "skill": quiz.skill,
        "total": total,
        "correct": correct_count,
        "score_percent": percent,
        "passed": percent >= PASS_PERCENT,
        "detail": detail,
    }


# --------------------------------------------------------------------------- #
# Store: verification state, attempts, projects                              #
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@dataclass
class Verification:
    skill: str
    status: str = "unverified"  # unverified | quiz_passed | project_submitted | verified
    source: str = ""  # "" | quiz | project
    self_reported: bool = False
    updated_at: str = ""
    best_score: float | None = None
    projects: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "status": self.status,
            "source": self.source,
            "self_reported": self.self_reported,
            "updated_at": self.updated_at,
            "best_score": self.best_score,
            "projects": self.projects,
        }


class VerificationStore:
    """SQLite store for verification state (tables from migration v5)."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        migrate(self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------- cooldown
    def cooldown_remaining(self, user_id: str, skill: str, now: datetime | None = None) -> float:
        """Hours left in the retake cooldown (0 when the user may attempt)."""
        now = now or _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at, passed FROM quiz_attempts WHERE user_id = ? AND skill = ? "
                "ORDER BY id DESC LIMIT 1",
                (user_id, skill),
            ).fetchone()
        if row is None or int(row["passed"]):
            # No attempt yet, or the last attempt passed — a pass never blocks.
            return 0.0
        last = datetime.fromisoformat(row["created_at"])
        elapsed = (now - last).total_seconds() / 3600.0
        return max(0.0, RETAKE_COOLDOWN_HOURS - elapsed)

    def assert_can_attempt(self, user_id: str, skill: str) -> None:
        remaining = self.cooldown_remaining(user_id, skill)
        if remaining > 0:
            raise CooldownActive(remaining)

    # -------------------------------------------------------------- attempts
    def record_attempt(self, user_id: str, skill: str, result: dict) -> Verification:
        """Persist a graded attempt and advance the state machine."""
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quiz_attempts (user_id, skill, score_percent, passed, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, skill, float(result["score_percent"]), int(result["passed"]), now),
            )
            if result["passed"]:
                current = self._status_row(conn, user_id, skill)
                # A quiz pass auto-verifies — unless a *project* verification
                # already stands (stronger evidence; never downgrade it).
                if not (
                    current and current["status"] == "verified" and current["source"] == "project"
                ):  # noqa: E501
                    conn.execute(
                        "INSERT INTO skill_verifications (user_id, skill, status, source, updated_at) "  # noqa: E501
                        "VALUES (?, ?, 'verified', 'quiz', ?) ON CONFLICT(user_id, skill) DO UPDATE "  # noqa: E501
                        "SET status = 'verified', source = 'quiz', updated_at = excluded.updated_at",  # noqa: E501
                        (user_id, skill, now),
                    )
        return self.get(user_id, skill)

    # -------------------------------------------------------------- projects
    def submit_project(
        self,
        user_id: str,
        skill: str,
        title: str,
        link: str,
        description: str,
        checklist: list[str],
    ) -> Verification:
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_projects (user_id, skill, title, link, description, "
                "checklist_json, self_reported, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (user_id, skill, title, link, description, json.dumps(checklist), now),
            )
            current = self._status_row(conn, user_id, skill)
            if not (current and current["status"] == "verified"):
                conn.execute(
                    "INSERT INTO skill_verifications (user_id, skill, status, source, updated_at) "  # noqa: E501
                    "VALUES (?, ?, 'project_submitted', 'project', ?) "
                    "ON CONFLICT(user_id, skill) DO UPDATE SET status = 'project_submitted', "
                    "source = 'project', updated_at = excluded.updated_at",
                    (user_id, skill, now),
                )
        return self.get(user_id, skill)

    def review_project(self, user_id: str, skill: str, approve: bool) -> Verification:
        """Admin/counsellor review of the project path (the only human gate)."""
        now = _iso(_now())
        with self._connect() as conn:
            current = self._status_row(conn, user_id, skill)
            if current is None or current["status"] != "project_submitted":
                raise ValueError("No submitted project is waiting for review for this skill.")
            new_status = "verified" if approve else "unverified"
            conn.execute(
                "UPDATE skill_verifications SET status = ?, updated_at = ? "
                "WHERE user_id = ? AND skill = ?",
                (new_status, now, user_id, skill),
            )
        return self.get(user_id, skill)

    # ---------------------------------------------------------------- reads
    @staticmethod
    def _status_row(conn: sqlite3.Connection, user_id: str, skill: str):
        return conn.execute(
            "SELECT * FROM skill_verifications WHERE user_id = ? AND skill = ?",
            (user_id, skill),
        ).fetchone()

    def get(self, user_id: str, skill: str) -> Verification:
        with self._connect() as conn:
            row = self._status_row(conn, user_id, skill)
            projects = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, skill, title, link, description, checklist_json, self_reported, "
                    "created_at FROM skill_projects WHERE user_id = ? AND skill = ? ORDER BY id",
                    (user_id, skill),
                )
            ]
            best = conn.execute(
                "SELECT MAX(score_percent) AS best FROM quiz_attempts WHERE user_id = ? AND skill = ?",  # noqa: E501
                (user_id, skill),
            ).fetchone()
        for project in projects:
            project["checklist"] = json.loads(project.pop("checklist_json") or "[]")
            project["self_reported"] = bool(project["self_reported"])
        if row is None:
            return Verification(skill=skill, projects=projects, best_score=best["best"])
        verified_by_project = row["status"] == "verified" and row["source"] == "project"
        return Verification(
            skill=skill,
            status=row["status"],
            source=row["source"],
            # A project-path record stays "self-reported" until review flips it
            # to verified; quiz verification was never self-reported.
            self_reported=bool(projects) and not verified_by_project and row["source"] == "project",
            updated_at=row["updated_at"],
            best_score=best["best"],
            projects=projects,
        )

    def list_for_user(self, user_id: str) -> list[Verification]:
        with self._connect() as conn:
            skills = [
                r["skill"]
                for r in conn.execute(
                    "SELECT skill FROM skill_verifications WHERE user_id = ? "
                    "UNION SELECT skill FROM skill_projects WHERE user_id = ?",
                    (user_id, user_id),
                )
            ]
        return [self.get(user_id, skill) for skill in sorted(skills)]

    def verified_skills(self, user_id: str) -> list[dict]:
        """Only the verified skills — the public-profile safe projection."""
        return [
            {"skill": v.skill, "method": v.source, "verified_at": v.updated_at}
            for v in self.list_for_user(user_id)
            if v.status == "verified"
        ]

    def public_projects(self, user_id: str) -> list[dict]:
        """Project titles/links for the public profile (review state shown)."""
        out: list[dict] = []
        for v in self.list_for_user(user_id):
            for project in v.projects:
                out.append(
                    {
                        "skill": v.skill,
                        "title": project["title"],
                        "link": project["link"],
                        "verified": v.status == "verified" and v.source == "project",
                    }
                )
        return out
