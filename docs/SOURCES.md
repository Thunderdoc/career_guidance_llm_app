# Sources — every number shown to a user traces back to an entry here

_Rule (Master Build Prompt, Rule 1): no statistic, salary, demand figure or
claim is displayed anywhere in the product unless it has an entry in this
file with a source and an as-of date — or it is explicitly labelled an
estimate in the UI. Phase 1 seeds this file with only what is verifiable
from the repository itself today._

## 1. Occupational catalogue — 974 occupations

- **Claim used in the product:** "974 occupations" / "Top-5 careers from
  974 real occupations".
- **Source:** O*NET database, U.S. Department of Labor, Employment and
  Training Administration (USDOL/ETA), as compiled into this repository's
  catalogue at `data/catalog/occupations.json` (count verified against the
  file in the repo; the running API also reports it at
  `GET /api/v1/health` → `occupations`).
- **Licence / attribution:** O*NET® Database content is used under the
  Creative Commons Attribution 4.0 International licence (CC BY 4.0), as
  published by the U.S. Department of Labor. O*NET® is a trademark of the
  U.S. Department of Labor, Employment and Training Administration.
- **As of:** catalogue as shipped in this repository (verified 2026-11-06).

## 2. Match quality — internal evaluation (not a market statistic)

- **Claim used in the product:** none on the public landing. (Kept here so
  nobody promotes it to a headline without context.)
- **Source:** the repository's own golden-set evaluation —
  `python -m eval.run`: skills Hit@5 = 1.0, MRR 0.827; interests
  Hit@5 = 1.0, on 50 hand-written golden profiles + interest profiles in
  `eval/`.
- **As of:** 2026-11-06 (re-run with Phase 1).
- **Caveat:** this is a self-evaluation on hand-written profiles, not an
  independent accuracy study. Do not quote it as "98%/100% accurate" in
  marketing copy.

## 3. Salary & demand figures inside reports

- **Source:** curated seed data in `data/market_seed.yaml`, each entry
  labelled in the UI with its source string and shown as an estimate where
  it is one; live Adzuna data replaces seed values only when Adzuna keys
  are configured by the operator.
- **As of:** per-entry `source` strings in the seed file / API payload.
- **Status:** India-specific licensed market data is an open owner input
  (see docs/UPGRADE_PLAN.md §3, item 6). Until then, no salary or demand
  figure is presented as official.

## Not yet sourced — do not display

- Any headline statistic about graduate unemployment, skills shortages,
  hiring growth or AI job impact for the landing hero. The Phase 1 hero
  therefore uses the verifiable promise from entry #1 instead of a
  numeric statistic. Add an entry here (publisher, report title, year,
  URL, licence) before any such number appears in the UI.
