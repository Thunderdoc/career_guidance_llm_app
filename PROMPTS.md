# PROMPTS — Kaam-Vaani system prompts

Every LLM prompt the system uses lives in `prompts/` as a versioned
Markdown file. Code loads them through `load_prompt(name)` in
`career_guidance/kaamvaani/profile.py`, which reads the version from
the header comment and raises if the header is missing or the prompt
is empty — a prompt can never silently load half-written.

**Status (21 Nov 2026): both prompts exist for the local-LLM path
only.** The live default is the deterministic path (rule-based
extraction in `extract.py`, deterministic scam rules in `scam.py`);
the local LLM (Qwen2.5-0.5B, `llama-cpp-python`) was executed and
measured in Step 8.7 but is NOT the default — 35.9 s per extraction
on CPU, with semantic errors Pydantic cannot catch (LIMITATIONS.md
L60). No hosted LLM is wired anywhere, and no API key exists.

| Prompt | Version | Purpose | Used by | Output schema |
| --- | --- | --- | --- | --- |
| `prompts/profile-extractor.md` | 1.0.0 | Extract a structured `VoiceProfile` from one spoken/typed answer (EN/HI/TA, Devanagari/Roman/Tamil script) | `profile.py` (`extract_profile_llm`), LoRA training data (`lora_data.py` — the system prompt in every training row) | `VoiceProfile`: skills[], interests, education, city, income_text, income_monthly, goal_type |
| `prompts/scam-risk.md` | 1.0.0 | Score a job listing for scam risk, 0–100, with plain-language reasons | `scam.py` (`score_with_llm`); advisory only — the deterministic 10-rule scorer is the tested decision path | `{"risk_score": 0–100, "reasons": [...]}` |

## Rules shared by both prompts

1. **Extract/score ONLY what the input says.** Never invent a skill,
   city, income, fee, promise or contact method.
2. **Answer ONLY with a single JSON object** — no explanation, no
   markdown fence, no extra text. The caller parses JSON strictly;
   anything else is a failed extraction, not a partial answer.
3. **No key is ever omitted** — empty values use `""` / `[]` /
   `null`, never a missing key.
4. **Speech errors are read through, meaning is not corrected:**
   "electrition" is electrician; the person's intent is never
   rewritten.

## Versioning

- Bump the version in the header comment on any wording change
  (semver: wording clarifications = patch, schema/behaviour
  changes = minor, incompatible schema = major).
- The LoRA training data (`lora_data.py`) embeds the
  profile-extractor prompt text at generation time — regenerate
  the JSONL if the prompt changes, or the training rows and the
  production prompt drift apart.
- There is no prompt for the RAG answerer: answers are verbatim
  quotes from retrieved chunks, not LLM generations. The citation
  verifier (`citations.py`) is deterministic code, not a prompt.
