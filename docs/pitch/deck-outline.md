# Pitch Deck Outline — Kaam-Vaani (12 slides)

_For the GAVS Tech4Bharat prototype round. Speaker notes are
written to be spoken, not read. Every number is measured —
nothing here is a projection presented as a result._

## Slide 1 — Title

**Kaam-Vaani: talk through what you can do, find work that
actually fits.** Voice-first AI career companion for rural
school-leavers. Team Hackastra.

_Speaker notes: "One line: a school-leaver speaks Tamil, and an
AI helps her find real work — grounded in real sources, never
guesses."_

## Slide 2 — Problem

Rural youth can't find work that fits; small employers can't
find them (statement 8.2). Portals are English, text-first, and
full of fee scams. The user speaks Tamil or Hindi, has a cheap
phone, and has no one to ask.

_Speaker notes: "This is not a discovery problem — the jobs
exist locally. It is a language, trust, and access problem.
Every existing tool assumes English literacy and a desktop."_

## Slide 3 — Product (what it is, what it is not)

Voice-first companion: speak → profile → matches → skill gaps
→ rights answers. NOT a job portal, NOT a LinkedIn clone. The
employer side exists only so the AI's answers are real.

_Speaker notes: "If you remember one thing: the product is the
AI, not a listings board. Listings are the AI's evidence, not
the product."_

## Slide 4 — Live demo (the voice flow)

Screenshot/flow of `/voice`: Tamil speech → extracted profile
→ confirm → matches + gap plan.

_Speaker notes: "Run the live demo here if the slot allows —
the 3-minute script. If not, walk the screenshots: speak,
confirm, match. The extraction is deterministic — no LLM call,
no key, no cost — and it scores 1.000 on our 55-case gold set."_

## Slide 5 — Grounded answers (RAG)

1,048-chunk knowledge base (974 occupations + government and
Wikipedia sources + verified wage data). Answers are verbatim
quotes with citations; ungrounded questions get a refusal, not
an invention. Example: ₹840/day unskilled construction, Area A,
Labour Bureau VDA order.

_Speaker notes: "The design choice that matters most: the
system never generates an answer. It quotes a source, or it
says it doesn't know. For a user who cannot verify a claim,
a hallucinated wage figure is harm, not a bug."_

## Slide 6 — Trust: scams, consent, rights

10-rule scam checker (fee demand = flag); employer + listing
review queues; per-employer revocable consent (7/30/90 days);
append-only audit log; real deletion; rights assistant with two
verified helplines only (1930, 1514).

_Speaker notes: "Trust is the product for this user. She has
been asked for 'registration fees' before. Every listing is
scored, every employer is reviewed, and no employer sees her
without her consent — revocable in one tap."_

## Slide 7 — Measured quality (the numbers slide)

| Metric | Measured |
| --- | --- |
| Profile accuracy | 1.000 (55/55) |
| Recall@5 (EN/HI/TA) | 1.000 in all 6 variants |
| Faithfulness | 0.948 (109/115) |
| Refusal accuracy | 0.947 (18/19) |
| Tests | 1,132 passed, 93.52% coverage |
| Load | 500 requests, 0 errors, 18.46 req/s |

_Speaker notes: "These are gold-set measurements, not user
results — I will say that out loud. The gold set is 189
hand-written cases. Real-user measurement is the pilot's job,
and the impact plan says how we'll do it."_

## Slide 8 — What we measured and REJECTED

Dense embeddings (faithfulness 0.728 — worse); local LLM as
default (35.9 s per profile on CPU, semantic errors); BM25-only
and TF-IDF-only (0.887 / 0.870 vs hybrid 0.948). Ablation table
in EVAL_REPORT.md.

_Speaker notes: "We tried the obvious fancy things and measured
them losing. The hybrid wins, the local LLM is too slow to be
the default, and dense embeddings made answers worse. We kept
the receipts — every rejection is documented with numbers."_

## Slide 9 — Architecture (one diagram)

Voice → extraction → translation → hybrid retrieval → verifier
→ matching → consent-gated contact. SQLite default, Postgres
path verified. Single free-tier instance; no API keys anywhere.

_Speaker notes: "One box per component, one sentence each. The
point: no paid service, no key, no hosted model — the whole
system runs on free tiers, which is why a student team can
actually ship and run it."_

## Slide 10 — Honest gaps (what is NOT built)

Answers are English even for Tamil/Hindi questions; TN state
wages absent (official PDFs 404); no offline voice shell; no
SMS/WhatsApp share; no accessibility audit yet; audit-log prune
is policy-only; Postgres cutover blocked on a legacy port.

_Speaker notes: "Say the gaps before the judges find them. The
biggest is answer language — retrieval works in Tamil, but the
answer is quoted in English. That is the next build, and it is
honest to name it now."_

## Slide 11 — Pilot plan + impact measurement

One institute, its school-leavers, 4 weeks: baseline (how they
find work today) → usage → outcomes (profiles completed,
matches viewed, consents granted, interviews, hires — measured,
not claimed in advance). Full plan:
`docs/pitch/impact-measurement-plan.md`.

_Speaker notes: "We claim no outcomes yet — there are no users
yet. The plan names the baseline, the metrics, and the targets
we will hold ourselves to. If the pilot fails, the numbers will
say so."_

## Slide 12 — Ask + close

What we need: a pilot institute, a Tamil Nadu wage source that
isn't a 404, and feedback from real school-leavers. The system
is built, tested, and documented — ready to meet its first real
user.

_Speaker notes: "Close on the user, not the tech: a girl in a
village who speaks Tamil should be able to ask a phone what
work fits her — and get an answer she can trust. That is built.
Now it needs its first real users."_
