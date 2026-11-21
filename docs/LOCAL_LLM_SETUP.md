# Local LLM setup — Kaam-Vaani (Step 8.7)

Two free, no-key ways to give Kaam-Vaani a local LLM. Both go through
the same `ChatCompleter` interface (`career_guidance/providers.py`),
so the voice extraction, scam risk score and suggestion paths work
identically whichever one is configured — and everything still falls
back to the deterministic offline path when no LLM is configured or
the model call fails.

## Which path to pick

| | llama.cpp in-process (`llamacpp`) | Ollama server (`ollama`) |
| --- | --- | --- |
| What it is | `llama-cpp-python` loads a GGUF file in the app process | A separate Ollama server on localhost; the app calls its HTTP API |
| Server to run | None | Yes — `ollama serve` |
| Extra install | `pip install llama-cpp-python` + a GGUF file | The Ollama binary + `ollama pull <model>` |
| Executed in this sandbox? | **Yes — measured 21 Nov 2026 (below)** | **No — interface exists, not executed here** |
| Best for | A single-process deploy, a demo laptop | Sharing one model across apps, easy model switching |

## Measured here (21 Nov 2026, Step 8.7)

Environment: 4 CPU threads (AMD EPYC, shared), ~1.4–2.2 GB RAM
available, 74 GB disk free, no GPU.

- **Package:** `llama-cpp-python 0.3.37`. There was **no prebuilt
  wheel for this platform/Python**, so pip compiled llama.cpp from
  source — it took ~11 minutes on the shared cores. The first
  install attempt failed with "No space left on device" because pip
  unpacks in `/tmp` (a 512 MB tmpfs, then 59% full from pytest
  dirs); setting `TMPDIR` to a workspace directory fixed it.
- **Model:** Qwen2.5-0.5B-Instruct, Q4_K_M GGUF, 469 MB, from
  `Qwen/Qwen2.5-0.5B-Instruct-GGUF` on Hugging Face
  (`qwen2.5-0.5b-instruct-q4_k_m.gguf`).
- **Load:** 0.4 s. **Peak RSS: 670 MB** at `n_ctx` 2048 (603 MB at
  512 — the context window costs little at this model size).
  **Generation: 10.1 tokens/s** (60 tokens in 5.9 s for a short
  extraction reply with a short prompt).
- **Context:** the production profile-extractor prompt needs
  **~1440 tokens**, so the default `n_ctx` is **2048** — the
  original 512 default failed with "Requested tokens (1439)
  exceed context window of 512" on the real prompt.
- **Full extraction with the real prompt:** 35.9 s end to end
  (prompt processing of ~1200 tokens dominates on CPU; generation
  is ~10 tokens/s). That is slow for an interactive voice flow —
  the deterministic extractor answers instantly and the LLM path
  is the slow, higher-quality alternative, not the default.
- **Quality (honest):** with the real prompt, the model follows
  the JSON schema reliably and gets the concrete fields right —
  on a transcript that is NOT one of the prompt's examples
  (tailor in Salem, 10th pass, ₹20,000/month) it returned
  skills `["tailoring"]`, education "10th pass", city "Salem",
  income 20000, all correct — but it made two semantic errors:
  `interests` came back as "job_6_months" and `goal_type` as
  "explore" for a person who explicitly wants a job. Pydantic
  validation does NOT catch these (the types are all valid), so
  the deterministic fallback and the voice flow's confirm step
  stay mandatory (L60). With a short prompt that did not spell
  out the schema, the same model invented its own keys
  (job_title / job_description) — the detailed production prompt
  is doing real work here. A simple arithmetic check
  ("12 + 7?") answered `19` correctly.
- **Ollama was not executed here.** The `OllamaCompleter` interface
  predates this step and is wired into the factory; Ollama uses the
  same llama.cpp engine underneath, so the measured llama.cpp
  result is the evidence that a local model of this size runs in
  this environment class — but the Ollama server itself, its
  install and its model pull were not run in this sandbox.

## Setup: llama.cpp in-process (measured path)

```bash
# 1. Install the binding (into the project venv, or a separate one).
#    Use a workspace TMPDIR: /tmp is a 512 MB tmpfs and pip needs
#    room to unpack + compile. No prebuilt wheel exists for this
#    platform, so expect a ~10 minute source compile.
TMPDIR=$HOME/workspace/tmp/pip-tmp pip install llama-cpp-python

# 2. Download a model (469 MB for the measured 0.5B Q4_K_M).
mkdir -p models
curl -L -o models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
  "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"

# 3. Configure (in .env or the environment).
LLM_PROVIDER=llamacpp
LLAMACPP_MODEL_PATH=models/qwen2.5-0.5b-instruct-q4_k_m.gguf
LLAMACPP_N_CTX=2048        # the production prompt needs ~1440 tokens
LLAMACPP_N_THREADS=4      # match the machine's cores
LLAMACPP_MAX_TOKENS=512   # cap per completion
```

The model loads lazily on the first completion (not at startup), so
a missing file or package fails on first use with a clear
`ProviderError`, never at import. Verify it with the live test:

```bash
KV_TEST_LLAMACPP_MODEL=models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
  python -m pytest tests/test_kv_step8_7.py -q -k live
```

## Setup: Ollama server (interface ready, not executed here)

```bash
# 1. Install Ollama (see https://ollama.com/download) and start it.
ollama serve
# 2. Pull a small model (0.5B class; the 3B/8B models need more RAM).
ollama pull qwen2.5:0.5b
# 3. Configure.
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:0.5b
```

## Choosing a model

The 0.5B model is the smallest usable one: it runs anywhere
(~600 MB RAM) but makes field errors. Larger models in the same
family (Qwen2.5-Instruct 1.5B / 3B / 7B, Q4_K_M GGUFs) should be
more accurate — RAM scales roughly with the file size, so a 3B
model needs on the order of 2 GB free. **No larger model was
measured in this step**: if you switch models, re-run the live
test above and the extraction eval before trusting it, and record
the numbers here.

## Requirements

- CPU-only; no GPU needed. 4 threads give ~10 tokens/s at 0.5B.
  A full extraction with the production prompt takes ~36 s on
  this hardware (prompt processing dominates) — plan the UX
  around that, or shorten the prompt.
- RAM: ~670 MB peak measured for the 0.5B model with a 2048-token
  context. Keep at least 2 GB free on the machine for headroom
  (the app + retriever + model together).
- Disk: ~500 MB per 0.5B model file, plus ~300 MB for the
  compiled `llama-cpp-python` package.
- **Never commit a model file to the repo.** Model files live
  outside the repo (a `models/` directory or anywhere
  `LLAMACPP_MODEL_PATH` points); the repo only carries the path
  setting, never the weights.

## Troubleshooting

- `pip install llama-cpp-python` fails with "No space left on
  device": pip unpacks in `/tmp` (512 MB tmpfs). Set
  `TMPDIR` to a workspace directory and retry.
- The install takes ~10 minutes: that is the from-source compile
  (no prebuilt wheel for this platform). It is a one-time cost.
- `ProviderError: The 'llama-cpp-python' package is not installed`:
  the binding is an optional dependency — install it (step 1).
- `ProviderError: LLM model file not found`: `LLAMACPP_MODEL_PATH`
  points at a missing file. Check the path (relative paths resolve
  from the process working directory).
- Out of memory at load: lower `LLAMACPP_N_CTX` (256) and use the
  0.5B model; check `free -m` before loading.
- Slow first completion: the model loads on first use (~0.4 s for
  0.5B) and the first tokens are slower while caches warm up.
