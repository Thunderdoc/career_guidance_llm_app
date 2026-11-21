"""Build the LoRA fine-tuning dataset for profile extraction (Step 8.8).

Task: profile extraction — the ONE place an LLM generates structured
output in the main flow (Stage 3, ``prompts/profile-extractor.md``).
The measured 0.5B local model makes semantic field errors there
(L60); LoRA on gold extraction examples is the targeted fix. The
deliverable is the PIPELINE (this builder + config + notebook +
runbook), not a trained model: training was NOT run here (no GPU),
and the notebook was NOT executed — see ``docs/LORA_RUNBOOK.md``.

Sources — real only, never invented:
- The 55 gold profile cases in ``eval/kv_golden.json``. The target
  is the deterministic extractor's full 7-field output, VALIDATED
  against the case's gold ``expected``: all 5 gold fields must
  match, else the case is skipped and reported. A mismatch means
  the extractor and the gold set disagree, and the example must
  not be built on a lie. (The KV eval proves they agree today:
  profile 1.000.)

Deliberately NOT sources (documented decisions, not omissions):
- The 115 retrieval cases: training on them would teach the model
  to answer questions from its weights, against the
  grounded-extractive design (the RAG pipeline answers from cited
  chunks, never from the model). They stay eval-only.
- The 19 refusal cases: questions, not transcripts — the wrong
  task shape for an extraction fine-tune.
- The seed workers (``data/kv_sample_workers.json``): they have no
  transcripts, and 9 of 10 are Tamil — templating Tamil text I
  cannot verify would be invented data. One English worker is not
  a dataset. They are not an SFT source.

Format: JSONL, one example per line, TRL messages format::

    {"messages": [{"role": "system", ...}, {"role": "user", ...},
                  {"role": "assistant", ...}],
     "source": "gold_profile", "gold_case_id": "kv-p001",
     "language": "en", "prompt_version": "1.0.0"}

The system prompt is the production profile-extractor prompt
(``load_prompt``, version recorded per example); the user content
is the gold transcript in the production format
(``"Language: <lang>.\\nTranscript: <text>"``); the assistant
content is the 7-field profile JSON (``raw_text`` excluded — it
is the input, not the target).

Determinism: the builder is fully deterministic given the gold
file and the prompt file — the train/val split shuffles with a
fixed seed (42), so re-running reproduces byte-identical files.
The build report records the gold file's SHA-256 so a dataset
is always traceable to the exact gold version it came from.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

from career_guidance.kaamvaani.extract import VoiceProfile, extract_profile
from career_guidance.kaamvaani.profile import load_prompt

# Fields the gold profile cases assert on (eval/run_kv.py
# PROFILE_FIELDS): skills as a set, the rest exactly.
GOLD_FIELDS = ("skills", "education", "city", "income_monthly", "goal_type")

# The 7 fields the production prompt requires in the assistant reply.
OUTPUT_FIELDS = (
    "skills",
    "interests",
    "education",
    "city",
    "income_text",
    "income_monthly",
    "goal_type",
)

# Safety net: a training example must never contain a phone number or
# an email address. Gold transcripts contain incomes (e.g. 15000),
# which are NOT PII — the phone pattern needs 10 consecutive digits
# (optionally with a +91 / spaces), which no gold transcript has.
_PHONE_RE = re.compile(r"(\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

DEFAULT_SEED = 42
DEFAULT_VAL_FRACTION = 0.1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gold_profile_cases(gold_path: str | Path) -> list[dict[str, Any]]:
    """Return the profile-kind cases from the gold file, in file order."""
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    return [c for c in gold["cases"] if c.get("kind") == "profile"]


def _profile_target(case: dict[str, Any]) -> dict[str, Any] | str:
    """The assistant target for one gold case: the deterministic
    extractor's 7-field output — or a skip reason (str) when the
    extractor disagrees with the gold ``expected`` on any field.
    Comparison follows the KV eval's semantics (eval/run_kv.py):
    skills as a SET (order is meaningless), the rest exactly."""
    profile: VoiceProfile = extract_profile(case["text"])
    dumped = profile.model_dump()
    if set(dumped["skills"]) != set(case["expected"].get("skills", [])):
        return (
            f"extractor skills={sorted(dumped['skills'])} != "
            f"gold {sorted(case['expected'].get('skills', []))}"
        )
    for field in ("education", "city", "income_monthly", "goal_type"):
        if dumped[field] != case["expected"].get(field):
            return f"extractor {field}={dumped[field]!r} != gold {case['expected'].get(field)!r}"
    return {field: dumped[field] for field in OUTPUT_FIELDS}


def build_examples(
    gold_path: str | Path, prompt_name: str = "profile-extractor"
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Build one training example per gold profile case.

    Returns ``(examples, skipped)`` where ``skipped`` is a list of
    ``{"id": ..., "reason": ...}`` — a non-empty skip list means the
    extractor and the gold set have drifted apart and must be
    reconciled before the dataset is trusted.
    """
    prompt = load_prompt(prompt_name)
    examples: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for case in load_gold_profile_cases(gold_path):
        target = _profile_target(case)
        if isinstance(target, str):
            skipped.append({"id": case["id"], "reason": target})
            continue
        language = case.get("language") or "en"
        examples.append(
            {
                "messages": [
                    {"role": "system", "content": prompt.system_prompt},
                    {
                        "role": "user",
                        "content": f"Language: {language}.\nTranscript: {case['text']}",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(target, ensure_ascii=False),
                    },
                ],
                "source": "gold_profile",
                "gold_case_id": case["id"],
                "language": language,
                "prompt_version": prompt.version,
            }
        )
    return examples, skipped


def validate_example(example: dict[str, Any]) -> list[str]:
    """Return the list of problems with one example (empty = valid)."""
    problems: list[str] = []
    messages = example.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        return ["messages must be a 3-turn [system, user, assistant] list"]
    roles = [m.get("role") for m in messages]
    if roles != ["system", "user", "assistant"]:
        problems.append(f"roles must be [system, user, assistant], got {roles}")
    for i, message in enumerate(messages):
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            problems.append(f"message {i} has empty or non-string content")
    assistant = messages[2].get("content", "")
    try:
        target = json.loads(assistant)
    except (json.JSONDecodeError, TypeError):
        problems.append("assistant content is not valid JSON")
    else:
        if not isinstance(target, dict):
            problems.append("assistant JSON is not an object")
        elif set(target) != set(OUTPUT_FIELDS):
            problems.append(
                f"assistant JSON keys must be exactly {sorted(OUTPUT_FIELDS)}, got {sorted(target)}"
            )
    if example.get("source") != "gold_profile":
        problems.append(f"unknown source: {example.get('source')!r}")
    if not example.get("gold_case_id"):
        problems.append("missing gold_case_id")
    if not example.get("prompt_version"):
        problems.append("missing prompt_version")
    # PII safety net over the user + assistant text (the system prompt
    # is the team's own prompt file, not user data).
    text = messages[1].get("content", "") + "\n" + assistant
    if _PHONE_RE.search(text):
        problems.append("possible phone number in example text")
    if _EMAIL_RE.search(text):
        problems.append("possible email address in example text")
    return problems


def split(
    examples: list[dict[str, Any]],
    val_fraction: float = DEFAULT_VAL_FRACTION,
    seed: int = DEFAULT_SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic train/val split (seeded shuffle; val first).

    ``val_fraction`` is a fraction of the total; the val set holds at
    least 1 example and never the whole set.
    """
    if not 0.0 < val_fraction < 1.0:
        raise ValueError("val_fraction must be between 0 and 1 (exclusive)")
    shuffled = list(examples)
    random.Random(seed).shuffle(shuffled)
    val_n = max(1, min(len(shuffled) - 1, round(len(shuffled) * val_fraction)))
    return shuffled[val_n:], shuffled[:val_n]


def write_jsonl(path: str | Path, examples: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_dataset(
    gold_path: str | Path,
    out_dir: str | Path,
    val_fraction: float = DEFAULT_VAL_FRACTION,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Build + validate + split + write the dataset. Returns the
    build report (counts, sources, languages, skips, file hashes).
    Raises ValueError if any example fails validation — an invalid
    example must never be written to disk."""
    gold_path = Path(gold_path)
    out_dir = Path(out_dir)
    examples, skipped = build_examples(gold_path)
    invalid = [
        {"gold_case_id": ex.get("gold_case_id"), "problems": validate_example(ex)}
        for ex in examples
        if validate_example(ex)
    ]
    if invalid:
        raise ValueError(f"{len(invalid)} invalid example(s): {invalid[:3]}")
    train, val = split(examples, val_fraction=val_fraction, seed=seed)
    train_path = out_dir / "kv_lora_train.jsonl"
    val_path = out_dir / "kv_lora_val.jsonl"
    write_jsonl(train_path, train)
    write_jsonl(val_path, val)
    languages: dict[str, int] = {}
    for example in examples:
        languages[example["language"]] = languages.get(example["language"], 0) + 1
    return {
        "gold_path": str(gold_path),
        "gold_sha256": _sha256(gold_path),
        "prompt_version": examples[0]["prompt_version"] if examples else None,
        "examples": len(examples),
        "train": len(train),
        "val": len(val),
        "val_fraction": val_fraction,
        "seed": seed,
        "languages": languages,
        "skipped": skipped,
        "train_file": str(train_path),
        "val_file": str(val_path),
        "train_sha256": _sha256(train_path),
        "val_sha256": _sha256(val_path),
    }
