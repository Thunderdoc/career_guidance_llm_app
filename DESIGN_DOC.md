# DESIGN_DOC — Kaam-Vaani

_Voice-first GenAI/LLM/RAG career companion for rural school-leavers
(17–24) in Tamil Nadu. Built on the Career Guidance app. Status:
21 Nov 2026, Step 9.6 — Stages 0–6 + Steps 7–9 complete, local
branch `kaam-vaani`, not deployed._

## 1. Problem

A rural school-leaver who cannot find work that fits, and small
local employers who cannot find them (GAVS Tech4Bharat, Youth and
Women theme, statement 8.2). The user speaks Tamil or Hindi, may
not read English, has a cheap Android phone, and has been burned
by fee-charging "job" scams. A text-first English job portal does
not serve this user at all.

## 2. Product (what it is, what it is not)

**It is:** an AI companion the user TALKS to — speak what you can
do, get matched work, learn what you're missing, ask about rights
and scams, all grounded in cited sources, all in your language.

**It is NOT:** a job portal, a LinkedIn clone, or an
employer/recruiter portal. The employer side exists only to make
the AI's answers real (verified local listings the AI can match
against, with consent-gated contact). No recruiter features were
added beyond Stages 5–6, and none are planned.

## 3. Architecture (one paragraph per component)

```
voice (browser Web Speech) → profile extraction (deterministic)
  → matching (KVScorer over 974 occupations) → gap learning (DAG)
  → RAG answers (BM25 + TF-IDF hybrid, glossary translation)
  → citation verifier → consent-gated employer contact
```

- **Voice gateway** (`kaamvaani/voice.py`, `/voice`): browser Web
  Speech Recognition is the default (no key, no cost); OpenAI
  Whisper/TTS exists behind a key the deployment does not have.
  A `VoiceSession` state machine walks extract → confirm →
  results. The mic path is NOT verified headless (L25).
- **Profile extraction** (`extract.py`, deterministic default):
  rule-based extraction of skills/interests/education/city/
  income/goal from a transcript, in EN/HI/TA incl. Roman script
  and Devanagari/Tamil digits. Profile accuracy 1.000 on the 55
  gold cases. The local-LLM path (`profile.py` + Qwen2.5-0.5B)
  was measured, not adopted: 35.9 s/extraction on CPU with
  semantic errors (L60).
- **Translation** (`translate.py`): glossary translation of
  Tamil/Hindi queries to English before retrieval. Recall@5
  1.000 in all six language variants; Tamil/Hindi at English
  parity (Step 7A). Answers are still quoted in ENGLISH (L16 —
  answer-language translation is the biggest open UX gap).
- **Retrieval** (`rag.py`): BM25 (pure Python) + TF-IDF, 0.5/0.5
  blend, over a 1,048-chunk snapshot (974 O*NET occupations +
  74 web/Wikipedia/wage chunks). Title-evidence rescue (Step 8.1)
  for strong title matches. Dense embeddings (multilingual-e5)
  measured and NOT adopted: RRF fusion dropped faithfulness to
  0.728 and refusal to 0.600 (Step 7A). See EVAL_REPORT.md for
  the ablation.
- **Answering**: extractive, not generative. The answer IS a
  verbatim quote from the top chunk, with a citation. If nothing
  is grounded, the system REFUSES (refusal accuracy 0.947) —
  it never invents an answer. The citation verifier (Step 8.5)
  checks every sentence against the cited chunk: 591/591
  supported on the gold set. The verifier changes nothing on
  the current extractive path (ablation: no_verifier == full);
  it is the guardrail for the future LLM path.
- **Matching** (`matching.py`): KVScorer over the 974-occupation
  taxonomy + a DAG/Dijkstra skill-gap engine (coverage 28/38
  skills; no prerequisite data exists, L56). Geohash location
  index for nearby work (9.9× at 100k listings). Duplicate
  detection (P 1.000 / R 0.907). Slowest endpoint: /matches
  ~380 ms single-user, p50 2.51 s at 20-user load (Step 9.5).
- **Trust layer** (`scam.py`, `employers.py`, `consent.py`):
  deterministic 10-rule scam checker (FLAG 70 / WARN 40);
  employer verification + listing review queue; per-employer
  revocable consent (7/30/90 days, one active per pair);
  append-only audit log (one row per returned candidate per
  search — L49, the unbounded grower). Hire outcomes + 30/90-day
  retention tracked for the pilot.
- **Rights assistant** (`rights.py`, Step 9.1): the same
  retriever with topic filters (rights/scam/wages/employment,
  56 chunks); escalation ONLY to two sourced helplines (1930
  cyber-crime, 1514 NCS — SOURCES.md §5.6). Scam keywords are
  English-only (L63).
- **Pilot console** (`pilot.py`, Step 9.2): pilot OPERATIONS
  (bulk onboarding, verification, metrics, CSV export) for
  coordinators + admins. Not a recruiter portal.
- **Video skill check** (`video.py`, Step 9.3, EXPERIMENTAL):
  clip validity + presence only (30–60 s, visible, moving).
  It CANNOT assess skill quality; every result says so.
- **Storage**: SQLite default (`data/career_guidance.db`),
  Postgres optional via `DATABASE_URL`. Migrations v1–14 apply
  cleanly on Postgres 16.2 — but 16 legacy stores still open
  SQLite directly, so production must NOT point at Postgres
  until the store-by-store port lands (L54, split-brain
  boundary). Caches are per-process in-memory (L59).

## 4. Design decisions (with reasons)

1. **Extractive answers, not generative.** A generative LLM can
   hallucinate a wage figure or a scheme that does not exist —
   for a user who cannot verify it, that is harm, not a bug.
   Verbatim quotes + citations + refusal make every answer
   checkable. The LLM is used only where a wrong answer is
   cheap (profile extraction, with a human confirm step) and
   even there the deterministic path is the default.
2. **Deterministic first, LLM second.** Every AI surface has a
   deterministic implementation that is the tested, shipped
   path; the LLM is an optional layer behind it. This is what
   makes the system free-tier deployable with zero API keys.
3. **Refusal is a feature.** 19 refusal cases in the gold set;
   the system must say "I don't know" for TN state wages,
   e-Shram, future rates, and out-of-scope questions. A wrong
   confident answer is worse than a refusal.
4. **Consent before contact.** No employer sees a worker's
   profile without that worker's active, revocable, time-boxed
   consent; every access is audit-logged. Deletion is real:
   `DELETE /api/v1/kv/me/data` erases the worker's KV data
   (outcomes anonymised, audit trail kept as evidence).
5. **No invented data, ever.** Every number in the KB traces to
   a source in SOURCES.md; TN state wages were left OUT because
   the official PDFs 404 and aggregators conflict. Gaps are
   documented as limitations, not filled with guesses.
6. **Offline-first, free-tier-only.** No API keys, no paid
   services, no hosted model. The whole system runs on one
   Render free instance + Vercel Hobby + Firebase Spark.

## 5. Measured and rejected

- Dense embeddings (multilingual-e5 + RRF): faithfulness 0.728,
  refusal 0.600 — worse than hybrid on both. NOT adopted; dense
  stays opt-in, uncalibrated (L52).
- Local LLM as default extractor: 35.9 s/profile on CPU,
  semantic errors. Measured, not adopted (L60).
- LoRA fine-tuning: pipeline built (49 train / 6 val JSONL),
  training never run — no accuracy gain is claimed.
- BM25-only / TF-IDF-only: faithfulness 0.887 / 0.870 vs hybrid
  0.948. The blend earns its keep (EVAL_REPORT.md ablation).

## 6. What is NOT built (honest gaps)

Answer-language translation (answers are English even for
Tamil/Hindi questions, L16); TN state minimum wages; PWA/offline
shell for the voice flow (only the existing `/offline` route +
service-worker fallback exist); SMS/WhatsApp share (needs the
owner's phone pairing); automated accessibility audit (L68);
audit-log pruning (L49, policy only); full Postgres cutover
(L54). Full list: LIMITATIONS.md (L1–L68) + ARCHITECTURE.md
§7.19.
