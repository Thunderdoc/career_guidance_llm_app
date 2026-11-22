# TECHNICAL SUMMARY — Kaam-Vaani (one page)

**What it is.** A voice-first AI career companion for rural
school-leavers (17–24) in Tamil Nadu. The user speaks what they
can do (Tamil, Hindi, or English); the system extracts a profile,
matches it to real local work, explains skill gaps, and answers
rights/wage/scam questions from cited sources — refusing when it
has no grounding. Employers are verified, contact is
consent-gated, and every access is audit-logged. It is NOT a job
portal: the product is the AI, not a listings board.

**How it works.** Browser speech recognition → deterministic
profile extraction (rule-based, 55/55 gold cases) → glossary
translation (Tamil/Hindi → English) → hybrid retrieval (BM25 +
TF-IDF over a 1,048-chunk knowledge base) → extractive answers
(verbatim quotes with citations, never generated text) → citation
verification → consent-gated employer contact. A local LLM
(Qwen2.5-0.5B) was measured as an alternative extractor and NOT
adopted (35.9 s/profile on CPU, semantic errors). No API keys,
no paid services, no hosted model — one Render free instance +
Vercel Hobby + Firebase Spark.

**Measured quality (21 Nov 2026, 189-case gold set).** Profile
accuracy 1.000; recall@5 1.000 in all six language variants
(English, Hindi, Tamil, Roman, noisy); MRR 0.970; faithfulness
0.948 (109/115 cited answers grounded in an expected source);
refusal accuracy 0.947 (18/19 — refuses TN state wages, e-Shram,
future rates, out-of-scope questions). Ablation: the hybrid
blend beats BM25-only (0.887) and TF-IDF-only (0.870); the
title-rescue ranker adds 2 cases (0.930 → 0.948); dense
embeddings were measured and rejected (faithfulness 0.728).
Load: 500 requests, 0 errors, 18.46 req/s, 293 MB peak RSS;
`/matches` is the slowest endpoint (p50 2.51 s at 20-user load
vs ~380 ms single-user). Tests: 1,132 passed, coverage 93.52%.

**Trust & safety.** Deterministic 10-rule scam checker; employer
+ listing review queues; per-employer revocable consent (7/30/90
days); append-only audit log; real data deletion (outcomes
anonymised, audit kept as evidence); rate limits on every AI
endpoint; two sourced helplines only (1930, 1514). DPDP items
flagged for legal review — compliance is not claimed.

**Honest gaps.** Answers are quoted in English even for
Tamil/Hindi questions; Tamil Nadu state minimum wages are absent
(official PDFs 404); no offline shell for the voice flow; no
SMS/WhatsApp share; no automated accessibility audit; the audit
log has a retention policy but no automated prune; full Postgres
cutover is blocked on a legacy-store port. Full list:
LIMITATIONS.md.

**Status.** Built, tested, and documented on local branch
`kaam-vaani` (Stages 0–6 + Steps 7–9, 21 Nov 2026). Not deployed
— see DEPLOY_CHECKLIST.md for the deploy decision.
