# 30 Judge Questions — with honest answers

_Every answer is grounded in the built system. Where the honest
answer is "we don't know yet" or "that's a gap", it says so.
Numbers are measured, never projected._

## 1. Why not just use ChatGPT or another LLM for everything?

Because an LLM can hallucinate a wage figure or a scheme that
doesn't exist — and our user cannot verify it. Our answers are
verbatim quotes from cited sources, or a refusal. The LLM is
used only where a wrong answer is cheap (profile extraction,
with a human confirm step), and even there the deterministic
path is the default because the local LLM takes 35.9 seconds
per profile on CPU and makes semantic errors.

## 2. Faithfulness is 0.948 — what about the 6 failures?

The 6 unfaithful cases (kv-r015, kv-r033, kv-r056, kv-r059,
kv-r086, kv-r089) are ranking near-misses: the right source is
in the top 5, but a wrong chunk is cited first. The answers are
still verbatim and verified — grounding is not relevance. The
fix is ranking work, not a verifier fix, and the cases stay in
the gold set so the gap stays measured.

## 3. Your gold set is hand-written. How do you know it works on real users?

We don't — yet. The gold set (189 cases) measures the builders'
idea of realistic questions. Real-user measurement is the
pilot's job, and the impact plan names the baseline and metrics.
Anyone claiming real-user accuracy without users is guessing;
we're not.

## 4. Answers are in English — doesn't that defeat the purpose for Tamil users?

It's the biggest honest gap (L16). Retrieval works in Tamil and
Hindi at English parity (recall@5 1.000 in all variants), but
the quoted answer is English. The user can ask in Tamil and get
matched work in Tamil — but the RAG answer text is English.
Answer-language translation is the next build, and we name it
before judges find it.

## 5. Recall@5 is 1.000 everywhere — is the test too easy?

Possibly — recall@5 only asks whether the expected source is in
the top 5, and 1,048 chunks is a small corpus. That's why we
also report MRR (0.970 — rank matters) and faithfulness (0.948
— the cited source must be an expected one). The ablation shows
the ranking differences clearly: BM25-only and TF-IDF-only both
keep recall@5 1.000 while losing 7–9 faithfulness cases.

## 6. What happens when speech recognition mangles a Tamil dialect?

The gold set includes noisy English and code-mixed cases, and
the extractor reads through obvious mishearings ("electrition"
→ electrician). But browser STT accuracy on Tamil dialects is
unmeasured (R4) — the typed fallback is always available, and
the confirm step lets the user correct the profile before
anything is matched. If STT fails badly for a dialect, the
pilot will show it in the correction rate.

## 7. How do you verify employers are real?

Three layers: registration + phone verification (OTP, Firebase
phone auth — enablement is an owner step), a listing review
queue (admin/coordinator approves before a listing goes public),
and the 10-rule scam checker on every listing. No auto-verify
exists. At pilot scale a human reviews every employer; at
larger scale this needs more humans, and we say so (R5).

## 8. What stops a scammer from gaming your 10-rule checker?

Nothing absolute — it's 10 deterministic rules, and a careful
scammer can write a clean-looking listing. That's why the
checker is advisory (FLAG/WARN), not a verdict: the review
queue, worker reporting (one tap, 10/min rate-limited), and the
pilot console's report review are the real defences. The checker
catches the lazy, common scams (fee demands, absurd pay,
WhatsApp-only); the humans catch the rest.

## 9. Why SQLite and not Postgres in production?

Honest answer: the Postgres path is verified (migrations 1–14
apply cleanly on 16.2) but 16 legacy stores still open SQLite
directly — a split-brain boundary (L54). Pointing production at
Postgres today would split reads and writes across two
databases. The store-by-store port is the precondition, and the
deploy checklist names it. For the pilot, SQLite on one instance
is fine; the free-tier wipe-on-deploy risk (R1) is why pilot
data must move to Postgres (Supabase/Neon free tier) before
real users arrive.

## 10. Your load test shows /matches at 2.5 s — isn't that too slow?

Under 20 simultaneous users on one free-tier worker, yes, it's
slow — p50 2.51 s vs ~380 ms single-user. The cause is
structural: CPU-bound scoring serialised behind the GIL. The
pilot won't see 20 simultaneous match calls (a human-paced
voice flow), and the fix direction is per-profile-signature
score caching. We published the slow number rather than testing
with one user and claiming speed.

## 11. What does it cost to run?

Zero, on free tiers: Render free (backend), Vercel Hobby
(frontend), Firebase Spark (auth). No API keys, no hosted
model, no paid service. The constraint this creates is real:
one worker, 512 MB RAM, sleep after 15 minutes idle, ephemeral
filesystem. The deploy checklist names the paid-tier decision
points (more workers, persistent Postgres) as owner decisions,
not hidden costs.

## 12. How is this different from NCS, myScheme, or other government portals?

Those are destinations the user must find, read (in English),
and navigate. Kaam-Vaani is a conversation: the user speaks,
the system extracts, matches, and answers — and it cites NCS
and myScheme as sources rather than competing with them. The
NCS helpline (1514) is one of our two escalation numbers. We
are a front door to those services, not a replacement.

## 13. Are you DPDP compliant?

We do NOT claim compliance. COMPLIANCE.md records the DPDP
items (consent, purpose limitation, deletion, breach
notification) and flags each for legal review. What IS built:
revocable time-boxed consent, real deletion, minimal data
collection, audit logging, no user data in training. A lawyer
needs to review it before real users — the checklist says so.

## 14. How do you handle a user who can't read at all?

Voice input + spoken answers is the design goal, but today the
answers are displayed as text (and in English — see Q4). Full
voice output (TTS) exists only behind an OpenAI key the
deployment doesn't have. A non-reading user can speak and hear
matches read by a helper, but independent use needs TTS — that
is a gap, and the pilot will measure how much it matters.

## 15. What's your moat? Can't anyone build this?

Honestly: the code is not the moat. The moat would be verified
local employer relationships, real wage data, and trust with
school-leavers — none of which exists yet. What we have is a
working system with honest evaluation, built to be deployed.
The defensibility comes from the pilot, not the prototype.

## 16. Why did dense embeddings fail?

Multilingual-e5 with RRF fusion dropped faithfulness to 0.728
and refusal to 0.600 (Step 7A). Our read: dense similarity
retrieves topically related but wrong chunks (e.g. a wage-law
chunk for a wage-figure question), and the cosine gates tuned
for TF-IDF don't transfer. Dense stays opt-in and uncalibrated
(L52). We'd revisit it with calibrated thresholds and a larger
gold set — not by assuming embeddings are better.

## 17. The local LLM takes 36 seconds — why keep it at all?

Because it proves the architecture: the provider interface
exists, the prompt is versioned, and the extraction was
executed end-to-end on CPU with measured numbers. It's not the
default, and we don't pretend it is. If a faster path appears
(hosted key, better hardware), the integration point is ready.
Keeping a measured-but-slow option is better than claiming a
fast one we never ran.

## 18. How do you keep wage data current?

The VDA order revises twice a year (1 Apr, 1 Oct). The refresh
procedure is documented (SOURCES.md §5.5): re-fetch the order,
OCR, verify all sums, bump the snapshot version, re-run the
eval, commit together. The ingester fails loudly on bad
arithmetic. What is NOT built: an automated refresh — it's a
manual step, twice a year, owned by whoever runs the pilot.

## 19. What if an employer fakes hire outcomes?

Hire outcomes are employer-reported with worker follow-up, and
both sides are recorded. A fake outcome inflates the pilot's
retention metrics — which is why outcomes are reported with
their source, and the impact plan treats "employer-reported
hire" and "worker-confirmed hire" as different metrics. We
don't claim fraud-proofing we don't have.

## 20. How do you measure impact without claiming outcomes you haven't achieved?

The impact plan (docs/pitch/impact-measurement-plan.md) names
baselines (how school-leavers find work today), leading metrics
(profiles completed, matches viewed, consents granted), and
lagging metrics (interviews, worker-confirmed hires) — with
targets to be set FROM the baseline, not invented now. No
outcome is claimed until a pilot user achieves it.

## 21. What's the business model?

There isn't one yet, and inventing one for the pitch would be
dishonest. The honest options: institute subscriptions (the
pilot console is built for institutes), government partnership
(it fronts NCS/myScheme), or grant funding. The system costs
nothing to run at pilot scale, so there's no pressure to
monetise users — and charging the worker is explicitly out
(the scam checker flags fee demands, including ours would be
absurd).

## 22. Why only 1,048 chunks — isn't that a tiny knowledge base?

Yes, and deliberately so: every chunk traces to a fetched,
allowed source. The alternative — scraping thousands of pages
we can't verify — would make answers less trustworthy, not
more. The gaps (e-Shram, TN wages, NSQF syllabi) are documented
in SOURCES.md §5.3 with the reason each source couldn't be
ingested. A bigger KB is a sourcing task, not a code task.

## 23. What happens when Render sleeps or wipes the DB on deploy?

Render free sleeps after 15 min idle (first request is slow —
~4.3 s retriever build plus cold start) and its filesystem is
ephemeral (a deploy wipes SQLite). For the demo, warm the URL
first. For the pilot, data must move to Postgres (Supabase/Neon
free tier) before real users arrive — the deploy checklist
makes this a blocking item, not a footnote (R1).

## 24. How is users' data isolated?

Server-side role scoping on every route: workers see only their
own profile/consents, employers see only candidates who
consented to them, coordinators see their pilot's data, admins
see the audit log. Tests pin the 401/403 boundaries per
endpoint, and the consent tests prove an employer search only
returns candidates who consented to that employer. The legacy
(non-KV) app's scoping was not re-audited in this build — the
claim here covers the KV surface only.

## 25. What about users without smartphones or internet?

They can't use it — this is a web app, and there's no offline
voice shell or SMS/USSD path (L64 flags SMS/WhatsApp share as
needing the owner's phone pairing). The pilot targets
school-leavers with cheap Android phones and intermittent data.
Reaching the fully offline user needs a different product (IVR,
community kiosk), and we don't claim to be it.

## 26. You refuse 1 in 19 questions — isn't that bad UX?

A refusal is better than a wrong answer for this user. The one
refusal miss (kv-x007) is a case the full system answers that
it should refuse — BM25-only refuses it correctly, at the cost
of 7 faithfulness cases (see the ablation). We chose the trade
deliberately and recorded it. In the pilot, the refusal rate on
REAL questions is a metric to watch, not a number to hide.

## 27. How did you choose the 0.5/0.5 blend?

Tuned on the Stage 2 gold set (see EVAL_REPORT.md tuning
history) — four measured runs, not a guess. The ablation
confirms it: the blend beats either single signal by 6–8
faithfulness points. It's a choice for THIS corpus and THIS
gold set; a bigger KB would need re-tuning, and the harness
makes that a one-command job.

## 28. The audit log grows forever — what breaks?

One row per returned candidate per employer search, no
automated prune (L49). At pilot scale (tens of employers,
hundreds of searches) it's negligible; at national scale it's
the unbounded grower. The 365-day retention policy is recorded
but no prune is built — the log is append-only by design, and
pruning is a deliberate future ops decision, not something to
automate silently. The deploy checklist carries it.

## 29. Can a worker really delete their data?

Yes: `DELETE /api/v1/kv/me/data` erases the profile, consents,
shortlists, and contact requests, and anonymises hire outcomes
(one-way tombstone — the row stays for aggregate retention
stats, the link to the worker is gone). The audit trail is
kept as consent evidence (that's its purpose). Account
self-delete runs the same erasure first. Pinned by tests,
including idempotency (deleting twice is safe).

## 30. What would you build next with four more weeks?

In order: (1) answer-language translation — Tamil/Hindi answers,
the biggest UX gap; (2) the Postgres cutover so pilot data
survives deploys; (3) a minimal offline shell for the voice
flow; (4) TTS so a non-reading user can use it independently.
All four are named gaps with owners, not new ideas — the
roadmap is the limitations list, worked in priority order.
