# MODEL CARD — Kaam-Vaani

## What "the model" is (read this first)

Kaam-Vaani has **no fine-tuned model in production**. The deployed
system is deterministic code + retrieval:

| Component | What it is | Learned parameters? |
| --- | --- | --- |
| Profile extraction (`extract.py`) | Rule-based: keyword/pattern matching over the transcript, with a canonical skill list | None |
| Query translation (`translate.py`) | Glossary lookup (Tamil/Hindi → English), hand-built | None (a word list) |
| Retrieval (`rag.py`) | BM25 (pure Python) + TF-IDF cosine, 0.5/0.5 blend | None — the blend weights were chosen on the Stage 2 gold set (see EVAL_REPORT.md tuning history), not learned |
| Matching (`matching.py`) | KVScorer: deterministic weighted scoring over the 974-occupation taxonomy + DAG/Dijkstra skill-gap engine | None |
| Scam check (`scam.py`) | 10 deterministic weighted rules (FLAG 70 / WARN 40) | None |
| Citation verifier (`citations.py`) | Deterministic sentence-to-chunk overlap check | None |

Two LLM artefacts exist and are **measured, not deployed as the
default**:

| Artefact | Status | Measured result |
| --- | --- | --- |
| Qwen2.5-0.5B-Instruct, Q4_K_M GGUF via `llama-cpp-python` 0.3.37 (`profile.py`, `KV_TEST_LLAMACPP_MODEL`) | Executed once (Step 8.7). NOT the default extractor. No hosted LLM is wired; no API key exists. | 670 MB peak RSS, 10.1 tok/s, **35.9 s per full extraction on CPU**, makes semantic errors Pydantic cannot catch (L60) |
| LoRA fine-tuning pipeline (`lora_data.py`, notebook) | Pipeline built; **training was never run**, notebook never executed | No accuracy gain claimed or measured |
| Dense retrieval (multilingual-e5, `dense.py`) | Measured (Step 7A), NOT adopted; opt-in only, uncalibrated (L52) | RRF fusion: faithfulness 0.728, refusal 0.600 — worse than hybrid on both |

## Intended use

Voice-first career guidance for rural school-leavers (17–24) in
Tamil Nadu: extract a work profile from speech, match it to real
local work, explain skill gaps, answer rights/wage/scam questions
from cited sources, and connect workers to verified employers
only with consent.

## Out-of-scope uses (do not use it for these)

- Hiring decisions, credit scoring, or any automated decision
  with legal effect on a person.
- Medical, legal, or financial advice. The rights assistant
  quotes public information with citations; it is not a lawyer.
- Skill certification. The video check is explicitly
  "indicative, not a certificate" and assesses clip validity
  only, never skill quality.
- Any use where an ungrounded answer would be acted on without
  a human checking the citation.

## Performance (measured, 21 Nov 2026)

On the 189-case gold set (`eval/kv_golden.json`, snapshot v2):
profile accuracy 1.000, recall@5 1.000, MRR 0.970, faithfulness
0.948 (109/115), refusal accuracy 0.947 (18/19). Per-language
retrieval: English, Hindi and Tamil all recall@5 1.000. Load:
500 requests, 0 errors, 18.46 req/s, RSS peak 293 MB (single
worker). Full numbers: EVAL_REPORT.md, docs/PERFORMANCE.md.

## Limitations (the honest list)

- Answers are quoted in **English** even for Tamil/Hindi
  questions (L16).
- Tamil Nadu STATE minimum wages are absent (official G.O.
  PDFs 404); only central-sphere rates are in the KB.
- The 6 unfaithful gold cases (kv-r015, kv-r033, kv-r056,
  kv-r059, kv-r086, kv-r089) are ranking near-misses, not
  grounding failures — the right source is in the top 5 but
  not cited first.
- The scam checker is advisory (10 rules); it cannot catch
  novel scam patterns.
- The local LLM path is slow and semantically unreliable on
  CPU; the LoRA model does not exist (never trained).
- Fairness: a test proves the scorer ignores language and
  identity inputs (`test_scorer_ignores_language_and_identity`),
  and a source test proves no protected inputs exist in the
  scorer — but no demographic fairness evaluation on real
  users has been run. Do not claim fairness beyond the tests.

## Training data

None for the deployed system (deterministic). The LoRA pipeline
would train on 49 gold profile cases (55 total, 6 held out) —
hand-written by the builders, no user data. No user data was
ever used to train anything.

## Ethical considerations

The users are young, often first-generation job seekers, and
cannot easily verify an AI's claims — which is why the system
is extractive (verbatim quotes + citations), refuses when
ungrounded, and never invents a wage, a scheme, or a helpline
number. Consent is revocable and time-boxed; deletion is real;
the audit log exists so a worker can see who accessed their
profile. See docs/COMPLIANCE.md (DPDP items flagged for legal
review — compliance is NOT claimed).
