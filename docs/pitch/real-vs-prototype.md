# Real vs Prototype — what works, what is demo-only, what is not built

_Honest labelling for judges, the pilot institute, and future
builders. "Real" means: implemented, tested, and measured.
"Prototype" means: implemented but with known limits that
matter. "Not built" means: documented as a gap, not faked._

## Real (implemented, tested, measured)

| Feature | Evidence |
| --- | --- |
| Voice profile extraction (EN/HI/TA, Roman + scripts) | 55/55 gold cases; 1,132 tests; deterministic, no LLM call |
| Multilingual retrieval (glossary translation) | Recall@5 1.000 in all 6 language variants |
| Hybrid retrieval + title rescue + citation verifier | Faithfulness 0.948; ablation table in EVAL_REPORT.md |
| Grounded answers with citations + refusal | Refusal 18/19; 591/591 sentences supported |
| Minimum-wage answers (central sphere) | VDA order, all 52 sums verified, 0 mismatches |
| Matching + skill-gap engine + geohash + dedup | Coverage 28/38; geohash 9.9× at 100k; dedup P 1.000/R 0.907 |
| Scam checker (10 rules) + review queues | 40 legit + 5 fake seed listings; FLAG/WARN thresholds tested |
| Consent (grant/revoke/expiry) + audit log + deletion | Revocable, time-boxed; deletion tested incl. idempotency; audit append-only by test |
| Rights assistant + 2 verified helplines | 56 chunks; 1930 via PIB, 1514 via NCS chunk |
| Pilot console (metrics, bulk onboarding, CSV) | Coordinators + admins; bulk max 100 rows, per-row errors |
| Rate limits + security headers + dependency audit | 9.4 gate; pip-audit 9 → 4 vulns |
| Load performance (single worker) | 500 requests, 0 errors, 18.46 req/s, RSS peak 293 MB |

## Prototype (works, with limits that matter)

| Feature | Limit |
| --- | --- |
| Video skill check | Clip validity + presence ONLY. Cannot assess skill quality. Tested on synthetic clips only — no real recordings exist. Always labelled "indicative, not a certificate". |
| Local LLM extractor (Qwen2.5-0.5B) | Executed once, 35.9 s/profile on CPU, semantic errors. NOT the default. Kept as a measured option, not a shipped path. |
| Dense retrieval (multilingual-e5) | Measured and rejected (0.728/0.600). Opt-in only, uncalibrated. |
| LoRA pipeline | Data generated (49 train / 6 val). Training never run. No model exists. |
| Employer verification | Human review queue + phone OTP (Firebase enablement is an owner step). No auto-verify; no scale story beyond humans. |
| PWA/offline | Only the existing `/offline` route + service-worker fallback. No offline voice shell. |
| Postgres support | Migrations verified on 16.2, but 16 legacy stores still open SQLite directly. Do not point production at Postgres yet. |

## Not built (documented gaps, not faked)

| Gap | Reference |
| --- | --- |
| Answer-language translation (answers are English) | L16 — biggest UX gap |
| TN state minimum wages | L15/SOURCES.md §5.3 — official PDFs 404 |
| e-Shram coverage | L15 — site is a JS shell, no Wikipedia article |
| SMS/WhatsApp share | L64 — needs the owner's phone pairing |
| TTS / spoken answers | No key; non-reading users need a helper |
| Automated accessibility audit | L68 — no axe/Lighthouse run on KV screens |
| Audit-log pruning | L49 — 365-day policy recorded, no automated prune |
| Answer-language + dialect STT measurement | R4 — Tamil dialect accuracy unmeasured |
| Real-user evaluation | No users yet; the gold set is hand-written |
| Business model / monetisation | None. Deliberately not invented for the pitch. |
