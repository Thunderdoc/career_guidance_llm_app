# 3-Minute Demo Script — Kaam-Vaani

_For the GAVS Tech4Bharat prototype round. Every line below is a
real flow in the built system; every number is measured. Timings
assume the deployed URL is warm (first request after a cold start
pays ~4.3 s for the retriever build — warm it before the demo)._

## 0:00–0:20 — The problem (20 s)

> "A school-leaver in a Tamil Nadu village finishes 12th standard
> and needs work. Job portals are in English, text-first, and full
> of listings that ask for a 'registration fee' before you start.
> She speaks Tamil. She has a cheap phone. Nothing built for her
> talks back. Kaam-Vaani does — she speaks, it listens, and it
> answers from real sources, never from guesses."

## 0:20–1:10 — The voice flow, live (50 s)

Open `/voice`. Tap the mic and speak in Tamil:

> "நான் கொத்தனார், மதுரையில் இருக்கிறேன், மாதம் 20000 ரூபாய் வேண்டும்"
> ("I'm a mason, I'm in Madurai, I need ₹20,000 a month.")

- The profile appears: skills masonry, city Madurai, income
  ₹20,000/month, goal job. **Say it:** "The extraction is
  deterministic — no LLM call, no API key, no cost. On our
  55-case gold set it scores 1.000."
- Tap confirm. Matches appear from 974 real occupations, with
  a skill-gap plan for each. **Say it:** "Matching runs on the
  full O*NET taxonomy with a skill-graph engine — 28 of 38
  skills covered by real learning paths."

## 1:10–1:50 — A grounded answer with a citation (40 s)

Ask (type or speak): "What is the minimum wage for unskilled
construction work?"

- The answer quotes the Labour Bureau VDA order (File No.
  6/1/2026-VDA, effective 1 Oct 2026): **₹840 a day in Area A**
  (basic ₹523 + VDA ₹317), with the citation on screen.
  **Say it:** "That number was read by OCR from the official
  order and verified — all 52 printed sums re-added, zero
  mismatches. And when we DON'T have a number — Tamil Nadu
  state rates, where the official PDFs are all 404 — the system
  refuses instead of inventing one. Refusal accuracy on our
  gold set: 18 of 19."

## 1:50–2:20 — The scam check (30 s)

Open `/jobs`, pick a listing that demands a fee (seed data
includes 5 fake listings for exactly this).

- The listing shows a scam flag with reasons: fee demanded,
  pay far above normal, WhatsApp-only contact.
  **Say it:** "Ten deterministic rules score every listing.
  A fee demand alone is enough to flag it. And the rights
  assistant — `/rights` — answers scam questions from cited
  sources and escalates only to two verified helplines: 1930
  for cyber-crime, 1514 for the National Career Service. We
  never invent a helpline number."

## 2:20–2:50 — Consent, then the numbers (30 s)

Open `/sharing` (signed in as the worker).

- Show the consent toggle: this employer can see my profile
  for 30 days; revoke takes one tap; every access is logged.
  **Say it:** "No employer sees a worker without their active,
  revocable consent. Deletion is real — one endpoint erases
  the worker's data."
- **Close with the honest numbers:** "1,132 automated tests,
  93.5% coverage. Retrieval: recall@5 1.000 in English, Hindi
  and Tamil. Faithfulness 0.948 — every cited answer grounded
  in a real source. Load-tested: 500 requests, zero errors.
  And the whole thing runs on free tiers — no API keys at all."

## 2:50–3:00 — The ask (10 s)

> "Kaam-Vaani is ready for a pilot with one institute and its
> school-leavers. The system is built; what we need now is real
> users, real feedback, and a Tamil Nadu wage source that isn't
> a 404."

## Backup lines (if the mic fails live)

- The typed fallback is the same flow: type the Tamil sentence
  instead of speaking it. Say: "Voice is the front door, typing
  is always available — the mic path needs a real phone, and
  this room's Wi-Fi is doing its best."
- If the deploy is cold: "First request builds the retriever —
  about 4 seconds, once per deploy."
