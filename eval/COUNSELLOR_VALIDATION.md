# Counsellor validation — human agreement sampling protocol

_Status: protocol + tooling ready (Phase 5). **No results exist yet.**
Nothing in this document is an accuracy claim, and no number produced by
this process may be quoted in marketing copy as "accuracy". Results are
only valid once the protocol below has been run on real, consented
samples by a real counsellor, and the filled CSV + this protocol version
are kept together._

## What this measures (and what it does not)

The golden-set eval (`python -m eval.run`) checks the matcher against
hand-written profiles. This protocol checks something different and
weaker: **how often a practising counsellor, shown the same inputs,
agrees with the system's top recommendations for real users.** Agreement
is evidence the guidance is plausible to a professional — it is not
proof that a recommendation was "correct" for that person, and it says
nothing about employment outcomes.

## Sampling

1. Pick a sampling window (e.g. one month) and a target **N ≥ 30** runs.
2. Sample *systematically*: sort the window's signed-in recommendation
   runs by id and take every k-th run so k ≈ total/N. Do not hand-pick.
3. **Consent gate:** include only runs whose account holder agreed to
   take part (or whose institute's agreement covers review, confirmed by
   the owner with counsel — see docs/COMPLIANCE.md). Under-18 runs need
   the guardian consent recorded in the app (`consent_records`). If
   consent cannot be confirmed for a sampled run, skip it and take the
   next one; record how many were skipped.
4. The reviewer sees only the run's input profile (skills, interests,
   goals, education, experience) — **not** the person's name, e-mail,
   school or any other identity field. The CSV below carries run ids
   only.

## Scoring (per run, before seeing the system's output if possible)

The counsellor records, from the input profile alone:

- `counsellor_top_pick` — the single career they would recommend first.
- `rating` — after then seeing the system's top 5:
  `agree` (system's top pick is one they would lead with),
  `partial` (their pick is in the top 5, or the top pick is defensible),
  `disagree` (they would not recommend the system's top pick).

Then, from the system's stored run:

- `system_top_pick` — title of recommendation #1.
- `system_top5` — the five titles, `|` separated.

## CSV columns (exact)

| Column | Filled by | Content |
| --- | --- | --- |
| `run_id` | sampler | Run id (number, or `SAMPLE-*` in the demo file) |
| `counsellor_top_pick` | counsellor | One career title |
| `system_top_pick` | sampler | Recommendation #1 title for that run |
| `system_top5` | sampler | Five titles separated by `\|` |
| `rating` | counsellor | `agree` \| `partial` \| `disagree` |
| `notes` | counsellor | Free text (optional; no personal data) |

## Running the stats

```
python -m eval.counsellor_validation path/to/filled.csv
```

Prints runs reviewed, **top-1 agreement %**, **top-5 inclusion %**, and
the rating distribution. Title matching is case/whitespace-insensitive
exact match — near-miss titles count as disagreement, which is
deliberately conservative.

`eval/counsellor_sample.csv` contains five clearly-labelled **SAMPLE**
rows with fake data so the script can be tried end-to-end; its output
proves the tooling works and nothing else.

## Reporting results (when real ones exist)

Report: the sampling window, N sampled / N skipped for consent, the
counsellor's background (role, years), the three stats above, and this
file's version. Never round agreement up into an "accuracy" headline.
