# LoRA runbook — Kaam-Vaani profile extraction (Step 8.8)

## What this is

A fine-tuning pipeline for the ONE place an LLM generates structured
output in Kaam-Vaani: profile extraction (Stage 3,
`prompts/profile-extractor.md`). The measured 0.5B local model
follows the JSON schema but makes semantic field errors on unseen
input (Step 8.7 / L60). LoRA on gold extraction examples is the
targeted fix — a small adapter that teaches the model this one
task, without touching the grounded RAG pipeline (which never
generates answers from model weights).

## What ran here vs what did not

| Step | Status |
| --- | --- |
| Data builder (`career_guidance/kaamvaani/lora_data.py` + `scripts/build_lora_data.py`) | **Ran, tested** — 55 examples, 0 skipped, byte-identical on re-run |
| Train/val files (`training/data/kv_lora_*.jsonl`) | **Built here**, committed |
| Config (`training/lora_config.yaml`) | **Written here** — values chosen, not tuned |
| Notebook (`training/train_lora_colab.ipynb`) | **Written here, NOT executed** — no GPU in this sandbox |
| Training run | **NOT run** — needs a free Colab T4 / Kaggle GPU |
| Adapter | **Does not exist yet** — produced by the first training run |
| Val numbers for the adapter | **Do not exist yet** — the notebook's last cell produces them |

Nothing in this step claims a trained model, a measured accuracy
gain, or a training time. The first run's numbers go in
`EVAL_REPORT.md` when they exist.

## The dataset (55 examples — a seed set, not a production fine-tune)

- **Source:** the 55 gold profile cases in `eval/kv_golden.json`
  only. Target = the deterministic extractor's full 7-field
  output, validated against the gold `expected` (skills as a set,
  like the KV eval). Any case where extractor and gold disagree
  is skipped and reported — 0 skipped today.
- **Split:** 49 train / 6 val (seed 42, deterministic).
- **Languages:** en 17, hi 10, hi-roman 9, ta 10, ta-roman 5,
  en-noisy 4 — the multilingual coverage comes free with the
  gold set.
- **Format:** JSONL, TRL messages format; system prompt is the
  production prompt (v1.0.0, recorded per example); every example
  carries `source`, `gold_case_id`, `language`, `prompt_version`.
- **55 examples is small.** It smoke-tests the pipeline and may
  fix the narrowest errors (the interests/goal_type confusion),
  but a production fine-tune wants hundreds of reviewed examples.
  The 6-example val set can only signal, not prove — treat a win
  as a reason to grow the dataset, not as a shipped result.

Deliberate exclusions (decisions, not oversights):
- **Retrieval cases (115):** training on them would teach the
  model to answer from weights — against the grounded-extractive
  design. Eval-only, forever.
- **Refusal cases (19):** questions, not transcripts — wrong task.
- **Seed workers:** no transcripts exist, and 9 of 10 are Tamil;
  templating Tamil text nobody verified would be invented data.

## Growing the dataset honestly

1. **More gold cases** — the cleanest path. Every new gold
   profile case (transcript + expected fields, reviewed by a
   human) becomes a training example automatically on the next
   builder run. Aim for 200+ before calling a fine-tune serious.
2. **Human-reviewed traces (Step 8.9)** — real voice transcripts
   from the trace log, PII-stripped, with the extracted profile
   reviewed and corrected by a human. Never train on raw traces:
   they may contain real names, and the model's own output is
   not ground truth until a human has checked it.
3. **Never:** synthetic transcripts presented as real user speech,
   or machine-translated transcripts without a native-speaker
   review. The dataset's value is that every example is real or
   mechanically derived from real records.

Rebuild after any gold change:
`python scripts/build_lora_data.py` (re-run is deterministic;
the report records the gold file's SHA-256).

## Running the training (free tiers only)

1. Open `training/train_lora_colab.ipynb` in Colab, Runtime >
   Change runtime type > **T4 GPU** (free tier). Kaggle's free
   GPU notebooks are the alternative (check the current weekly
   quota on the site before starting).
2. Upload `kv_lora_train.jsonl`, `kv_lora_val.jsonl` and
   `lora_config.yaml` when the notebook asks (or clone the repo
   — the notebook shows the command).
3. Run all cells. The notebook fails fast without a GPU, trains
   with completion-only loss, saves the adapter, and evaluates
   adapter-vs-base on the val set.
4. **Record both rows** (base + adapter, per-field + exact-match)
   in `EVAL_REPORT.md` with the date and config. If the adapter
   does not beat the base, the honest result is "LoRA on 55
   examples did not help" — grow the dataset before retrying.

## Using an adapter (only after the val numbers justify it)

1. Merge the adapter into the base model (PEFT
   `merge_and_unload`) and export to GGUF, or load the adapter
   alongside the base in llama.cpp — either way, the result is a
   model file, never a repo commit.
2. Re-run the 8.7 live extraction check
   (`KV_TEST_LLAMACPP_MODEL=<merged.gguf> pytest
   tests/test_kv_step8_7.py -k live`) with the merged model.
3. The deterministic fallback and the voice confirm step stay in
   place regardless — a fine-tuned model is still a model.

## Troubleshooting

- Builder reports skipped cases: the extractor and the gold set
  have drifted. Reconcile them (fix the extractor or the gold
  case) — do not weaken the validation to force a build.
- Builder raises "invalid example(s)": a generated example failed
  validation (bad JSON, wrong keys, or a PII-pattern hit). Fix
  the builder or the gold case; never hand-edit the JSONL.
- Colab disconnects mid-run: the run is short (49 examples,
  0.5B); re-run from the top. Checkpoints save per epoch.
- `Requested tokens exceed context window` in training: an
  example is longer than `max_length` (2048). The builder's
  examples fit (the prompt is ~1200 tokens); if a longer prompt
  version lands, raise `max_length` in the config.
