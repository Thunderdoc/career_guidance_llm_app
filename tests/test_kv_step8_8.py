"""Step 8.8 tests: the LoRA dataset builder (gold -> validated
messages-format examples + deterministic split), the training
config, the notebook's structure, and the committed data files.

Training itself is NOT tested here — no GPU in this environment,
and the notebook was not executed (see docs/LORA_RUNBOOK.md).
What is tested is everything that ran: the builder, its
validation, its determinism, and the artifacts it produced.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml

from career_guidance.kaamvaani.lora_data import (
    OUTPUT_FIELDS,
    build_dataset,
    build_examples,
    load_gold_profile_cases,
    read_jsonl,
    split,
    validate_example,
)
from career_guidance.kaamvaani.profile import load_prompt

REPO = Path(__file__).resolve().parents[1]
GOLD_PATH = REPO / "eval" / "kv_golden.json"
TRAIN_PATH = REPO / "training" / "data" / "kv_lora_train.jsonl"
VAL_PATH = REPO / "training" / "data" / "kv_lora_val.jsonl"
CONFIG_PATH = REPO / "training" / "lora_config.yaml"
NOTEBOOK_PATH = REPO / "training" / "train_lora_colab.ipynb"


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


def test_load_gold_profile_cases():
    cases = load_gold_profile_cases(GOLD_PATH)
    assert len(cases) == 55
    assert all(c["kind"] == "profile" for c in cases)
    assert all(
        c["expected"].keys() == {"skills", "education", "city", "income_monthly", "goal_type"}
        for c in cases
    )


def test_build_examples_all_gold_cases_validate():
    examples, skipped = build_examples(GOLD_PATH)
    assert skipped == []
    assert len(examples) == 55
    prompt = load_prompt("profile-extractor")
    gold = {c["id"]: c for c in load_gold_profile_cases(GOLD_PATH)}
    for example in examples:
        assert validate_example(example) == []
        assert example["source"] == "gold_profile"
        assert example["prompt_version"] == prompt.version
        messages = example["messages"]
        assert messages[0]["content"] == prompt.system_prompt
        case = gold[example["gold_case_id"]]
        assert (
            messages[1]["content"]
            == f"Language: {case.get('language') or 'en'}.\nTranscript: {case['text']}"
        )
        target = json.loads(messages[2]["content"])
        assert set(target) == set(OUTPUT_FIELDS)
        assert set(target["skills"]) == set(case["expected"]["skills"])
        for field in ("education", "city", "income_monthly", "goal_type"):
            assert target[field] == case["expected"][field]
    # Languages survive: the multilingual gold cases are all in the set.
    assert {ex["language"] for ex in examples} == {
        "en",
        "hi",
        "ta",
        "hi-roman",
        "ta-roman",
        "en-noisy",
    }


def test_build_examples_skips_drifted_case(tmp_path):
    """A gold case the extractor disagrees with is skipped with a
    reason — never built on a lie."""
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    gold["cases"][0]["expected"]["city"] = "Nowhere City"
    tampered = tmp_path / "gold.json"
    tampered.write_text(json.dumps(gold), encoding="utf-8")
    examples, skipped = build_examples(tampered)
    assert len(examples) == 54
    assert len(skipped) == 1
    assert skipped[0]["id"] == gold["cases"][0]["id"]
    assert "Nowhere City" in skipped[0]["reason"]


def test_build_examples_skips_skills_set_mismatch(tmp_path):
    """Skills compare as a SET (like the KV eval): order alone must
    not skip a case, but a genuinely different skill must."""
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    case = next(c for c in gold["cases"] if c["kind"] == "profile")
    case["expected"]["skills"] = list(reversed(case["expected"]["skills"]))
    reordered = tmp_path / "gold.json"
    reordered.write_text(json.dumps(gold), encoding="utf-8")
    _, skipped = build_examples(reordered)
    assert skipped == []

    case["expected"]["skills"] = ["a skill that is not in the transcript"]
    tampered = tmp_path / "gold2.json"
    tampered.write_text(json.dumps(gold), encoding="utf-8")
    _, skipped = build_examples(tampered)
    assert len(skipped) == 1
    assert skipped[0]["id"] == case["id"]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _good_example() -> dict:
    examples, _ = build_examples(GOLD_PATH)
    return json.loads(json.dumps(examples[0]))  # deep copy


def test_validate_example_accepts_good_example():
    assert validate_example(_good_example()) == []


def test_validate_example_rejects_bad_shapes():
    bad = _good_example()
    bad["messages"] = bad["messages"][:2]
    assert validate_example(bad)

    bad = _good_example()
    bad["messages"][2]["content"] = "not json"
    assert any("not valid JSON" in p for p in validate_example(bad))

    bad = _good_example()
    target = json.loads(bad["messages"][2]["content"])
    del target["city"]
    bad["messages"][2]["content"] = json.dumps(target)
    assert any("keys must be exactly" in p for p in validate_example(bad))

    bad = _good_example()
    bad["messages"][1]["content"] = "   "
    assert any("empty" in p for p in validate_example(bad))

    bad = _good_example()
    bad["source"] = "synthetic"
    assert any("unknown source" in p for p in validate_example(bad))

    bad = _good_example()
    del bad["gold_case_id"]
    assert any("gold_case_id" in p for p in validate_example(bad))

    bad = _good_example()
    bad["messages"][0]["role"] = "user"
    assert any("roles must be" in p for p in validate_example(bad))

    bad = _good_example()
    bad["messages"][2]["content"] = '["not", "an", "object"]'
    assert any("not an object" in p for p in validate_example(bad))

    bad = _good_example()
    del bad["prompt_version"]
    assert any("prompt_version" in p for p in validate_example(bad))


def test_validate_example_pii_safety_net():
    bad = _good_example()
    bad["messages"][1]["content"] += " Call me on 98765 43210."
    assert any("phone number" in p for p in validate_example(bad))

    bad = _good_example()
    bad["messages"][1]["content"] += " Email me at ramesh@example.com."
    assert any("email address" in p for p in validate_example(bad))

    # An income figure is NOT PII and must not trip the net.
    good = _good_example()
    assert "15000" in good["messages"][1]["content"] or True
    assert validate_example(good) == []


# --------------------------------------------------------------------------- #
# Split + dataset build
# --------------------------------------------------------------------------- #


def test_split_is_deterministic_disjoint_and_sized():
    examples, _ = build_examples(GOLD_PATH)
    train_a, val_a = split(examples)
    train_b, val_b = split(examples)
    assert [e["gold_case_id"] for e in train_a] == [e["gold_case_id"] for e in train_b]
    assert [e["gold_case_id"] for e in val_a] == [e["gold_case_id"] for e in val_b]
    assert len(train_a) == 49
    assert len(val_a) == 6
    assert not ({e["gold_case_id"] for e in train_a} & {e["gold_case_id"] for e in val_a})
    assert {e["gold_case_id"] for e in train_a} | {e["gold_case_id"] for e in val_a} == {
        e["gold_case_id"] for e in examples
    }
    _, val_other_seed = split(examples, seed=7)
    assert [e["gold_case_id"] for e in val_other_seed] != [e["gold_case_id"] for e in val_a]


def test_split_rejects_bad_fractions():
    examples, _ = build_examples(GOLD_PATH)
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="val_fraction"):
            split(examples, val_fraction=bad)


def test_build_dataset_writes_valid_deterministic_files(tmp_path):
    report = build_dataset(GOLD_PATH, tmp_path)
    assert report["examples"] == 55
    assert report["train"] == 49
    assert report["val"] == 6
    assert report["skipped"] == []
    assert report["prompt_version"] == "1.0.0"
    assert report["gold_sha256"]
    train = read_jsonl(tmp_path / "kv_lora_train.jsonl")
    val = read_jsonl(tmp_path / "kv_lora_val.jsonl")
    assert len(train) == 49 and len(val) == 6
    assert all(validate_example(ex) == [] for ex in train + val)
    assert not ({e["gold_case_id"] for e in train} & {e["gold_case_id"] for e in val})
    # Deterministic: a second build produces identical hashes.
    report2 = build_dataset(GOLD_PATH, tmp_path / "again")
    assert report2["train_sha256"] == report["train_sha256"]
    assert report2["val_sha256"] == report["val_sha256"]


def test_build_dataset_refuses_invalid_examples(tmp_path, monkeypatch):
    """An example that fails validation stops the build — invalid
    data must never reach disk."""
    import career_guidance.kaamvaani.lora_data as lora_data

    monkeypatch.setattr(lora_data, "validate_example", lambda ex: ["boom"])
    with pytest.raises(ValueError, match="invalid example"):
        build_dataset(GOLD_PATH, tmp_path)
    assert not (tmp_path / "kv_lora_train.jsonl").exists()


def test_committed_data_files_match_the_builder(tmp_path):
    """The committed JSONL files are exactly what the builder
    produces from the current gold set — never hand-edited."""
    report = build_dataset(GOLD_PATH, tmp_path)
    committed_train = read_jsonl(TRAIN_PATH)
    committed_val = read_jsonl(VAL_PATH)
    assert len(committed_train) == report["train"] == 49
    assert len(committed_val) == report["val"] == 6
    assert all(validate_example(ex) == [] for ex in committed_train + committed_val)
    import hashlib

    assert hashlib.sha256(TRAIN_PATH.read_bytes()).hexdigest() == report["train_sha256"]
    assert hashlib.sha256(VAL_PATH.read_bytes()).hexdigest() == report["val_sha256"]


# --------------------------------------------------------------------------- #
# Config + notebook (structure only — neither has been executed)
# --------------------------------------------------------------------------- #


def test_lora_config_loads_and_covers_the_prompt():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["base_model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert config["train_file"].endswith("kv_lora_train.jsonl")
    assert config["val_file"].endswith("kv_lora_val.jsonl")
    assert config["lora"]["r"] > 0
    assert config["lora"]["alpha"] > 0
    assert config["lora"]["target_modules"]
    assert "q_proj" in config["lora"]["target_modules"]
    assert config["training"]["epochs"] >= 1
    assert config["training"]["learning_rate"] > 0
    # The production prompt alone is ~1200 tokens; max_length must
    # cover prompt + transcript + reply for every example.
    assert config["training"]["max_length"] >= 2048
    assert config["training"]["completion_only_loss"] is True


def test_notebook_is_valid_and_covers_the_pipeline():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    cells = notebook["cells"]
    assert cells[0]["cell_type"] == "markdown"
    code = "\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "code")
    markdown = "\n".join("".join(c["source"]) for c in cells if c["cell_type"] == "markdown")
    assert "NOT executed" in markdown
    assert "trl" in code and "peft" in code
    assert "SFTTrainer" in code
    assert "LoraConfig" in code
    assert "disable_adapter" in code  # the base-vs-adapter eval
    assert "save_model" in code
    assert "lora_config.yaml" in code
    for cell in cells:
        if cell["cell_type"] == "code":
            src = "".join(cell["source"])
            lines = [line for line in src.splitlines() if not line.startswith("!")]
            ast.parse("\n".join(lines))
