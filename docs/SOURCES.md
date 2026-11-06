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

## 4. India data layer (Phase 2, added 2026-11-06)

### 4.1 O*NET → NCO-2015 crosswalk — `data/crosswalk_onet_nco.yaml`
- **Method:** manual mapping by occupation concept from O*NET (SOC-based)
  titles to NCO-2015 family (4-digit) codes. NCO-2015 follows the ISCO-08
  unit-group structure for these professional/technical groups (pattern
  verified against the Directorate General of Employment, Government of
  India, NCO portal — e.g. family 2512 = Software Developers); each entry
  also carries the ISCO-08 unit group where solid.
- **Confidence:** `high` = same occupation concept in both systems;
  `medium` = closest unit group, occupation broader/narrower than the group;
  `low` = indicative only. Occupations with no defensible mapping return
  empty — nothing is guessed. 86 mappings ship in v1.
- **Attribution:** O*NET® Database content is used under CC BY 4.0
  (U.S. Department of Labor, Employment and Training Administration);
  O*NET® is a trademark of USDOL/ETA. NCO-2015 is published by the
  Directorate General of Employment, Ministry of Labour & Employment,
  Government of India.

### 4.2 India market estimates — `data/india_market.yaml`
- **Kind:** every entry is `kind: estimate`. **Source (verbatim in the UI):**
  "Derived from project market seed (curated estimates, not official
  statistics)". `source_url` is intentionally empty — there is no official
  publication behind these numbers and none is claimed. As of 2026-11-06.
- **Derivation** from each `data/market_seed.yaml` family band
  (p25/p50/p75): fresher = [0.6×p25, p25]; ~3 years = [0.8×p50, 1.1×p50];
  ~7 years = [0.9×p75, 1.3×p75]. Top cities/sectors are curated editorial
  estimates in the same file. Admins may override entries via
  `GET/PUT /api/v1/admin/india-market` (audit-logged); overrides are
  labelled admin overrides, not official data.

### 4.3 India Reality Score — `career_guidance/reality.py`
Deterministic 0–100, weighted average over **available** components only:
entry demand 0.30 (seed demand 1–5 + trend), AI exposure 0.20 (inverse of a
documented keyword heuristic over O*NET occupation text — routine/clerical
signals raise exposure, hands-on/care/judgement signals lower it; labelled
`heuristic_estimate`, not a measurement), salary ladder 0.20 (7-year vs
fresher growth from §4.2 estimates), barrier to entry 0.15 (inverse of
O*NET job zone), time to first job 0.15 (inverse of an estimate from demand
+ job zone, labelled estimate). Missing data → component excluded with
status `insufficient_data`, named in `missing_components`, and overall
`confidence` = sum of available weights (drops below 1.0).

## Not yet sourced — do not display

- Any headline statistic about graduate unemployment, skills shortages,
  hiring growth or AI job impact for the landing hero. The Phase 1 hero
  therefore uses the verifiable promise from entry #1 instead of a
  numeric statistic. Add an entry here (publisher, report title, year,
  URL, licence) before any such number appears in the UI.
