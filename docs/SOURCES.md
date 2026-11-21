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

## 5. Kaam-Vaani RAG knowledge base (Stage 2 + Step 7B, snapshot v2, 21 Nov 2026)

Snapshot `data/kv_rag_snapshot_v2.jsonl`: **1,048 chunks** — 974
O*NET occupation chunks + 19 web + 47 Wikipedia + 8
central-sphere minimum-wage chunks (Step 7B). By topic:
occupation 974, courses 3, skilling 13, employment 2, schemes 2,
rights 27, scam 19, wages 8. All chunks are English. Every chunk
stores source URL, title, date, licence and language; answers cite
them (see `EVAL_REPORT.md` for retrieval quality). Snapshot v1
(1,040 chunks, 20 Nov 2026) is kept in the repo for reference; the
only non-wage difference between v1 and v2 is the ILO India home
page, re-fetched 21 Nov (a union list reordered, one news headline
changed — same page, no gold case depends on it).

### 5.1 Ingested sources

| Source | ID | Licence | Chunks | Notes |
| --- | --- | --- | --- | --- |
| O*NET Database (U.S. Dept. of Labor, ETA) | `onet:*` | CC BY 4.0 | 974 | From the in-app catalogue `data/catalog/occupations.json` (no network). One chunk per occupation in the common case; documents say "Preparation level: N", not "Job Zone" (the O*NET label injected "job" into all 974 chunks — see `EVAL_REPORT.md`). |
| SWAYAM | `web:swayam` | Official site | 1 | Home page text only (51 KB HTML, 472 words visible). |
| NPTEL | `web:nptel` | Official site | 2 | Home page text only (629 words visible). |
| NSDC | `web:nsdc` | Official site | 3 | Home page text only (1,001 words visible). |
| DGT (Directorate General of Training) | `web:dgt` | Official site | 2 | English home page `dgt.gov.in/en` (915 words visible). |
| National Qualification Register | `web:nqr` | Official site | 4 | Home page text only (1,419 words visible). |
| National Career Service | `web:ncs` | Official site | 2 | Home page text only (781 words visible). Carries the NCS Toll Free Helpline 1514, cyber fraud 1930, "NCS services are free of cost", support.ncs@gov.in. |
| myScheme | `web:myscheme` | Official site | 2 | Home page text only (511 words visible). Scheme pages are JS shells (see §5.3). |
| Tamil Nadu Labour Department | `web:tnlabour` | Official site | 1 | Home page text only (419 words visible). Mentions minimum-wage G.O.s by link label only — no figures. |
| ILO India | `web:ilo-india` | Official site | 2 | Home page text only (585 words visible). |
| Wikipedia: EPFO | `wiki:epfo` | CC BY-SA 4.0 | 6 | Fallback — the official EPFO site returns HTTP 403 (see §5.3). Full article extract (2,605 words). **Carries two different EPF wage-ceiling figures** (₹15,000 historical, ₹25,000 current per the article) — see §5.4. |
| Wikipedia: ESIC | `wiki:esic` | CC BY-SA 4.0 | 4 | Fallback — the official ESIC site is unreachable (see §5.3). Full article extract (1,462 words). Carries the ₹21,000/month ESI ceiling. |
| Wikipedia: PMKVY | `wiki:pmkvy` | CC BY-SA 4.0 | 2 | Fallback — the official PMKVY site is unreachable. Full article extract (535 words). Contains the only Naan Mudhalvan sentence in the base ("Tamil Nadu's Naan Mudhalvan scheme trains youth in Chennai…"). |
| Wikipedia: Advance-fee scam | `wiki:advance-fee-scam` | CC BY-SA 4.0 | 19 | Fallback — official advisories (CERT-In, cybercrime portal, RBI) are JS shells or unreachable (see §5.3). Full article extract (7,838 words). |
| Wikipedia: Code on Wages, 2019 | `wiki:code-on-wages` | CC BY-SA 4.0 | 2 | Fallback — India Code returns HTTP 403. Full article extract (606 words). Framework description, no wage figures. |
| Wikipedia: Skill India | `wiki:skill-india` | CC BY-SA 4.0 | 2 | Fallback — Skill India Digital is a JS shell. Full article extract (745 words). |
| Wikipedia: Unorganised Workers' Social Security Act, 2008 | `wiki:unorganised-workers-act` | CC BY-SA 4.0 | 1 | Full article extract (171 words). |
| Wikipedia: Social security in India | `wiki:social-security-india` | CC BY-SA 4.0 | 11 | Full article extract (4,377 words). |
| Labour Bureau VDA order, File No. 6/1/2026-VDA (30 Sep 2026, rates from 1 Oct 2026) | `web:labourbureau-vda-*` | Public information (Government of India) | 8 | **Step 7B.** Central-sphere minimum wages for 7 scheduled employments (construction, agriculture, sweeping/cleaning, loading/unloading, watch & ward, mines, stone mines piece rates) + 1 scope/areas chunk. The order is a scanned PDF with no text layer — numbers read by OCR (RapidOCR, 150 DPI) and verified two ways: all 52 printed `basic+VDA=total` sums re-added (0 mismatches) and all totals cross-checked against three independent readings of the same order. Structured data: `data/kv_wage_tables_2026-10.json` (provenance block); ingester `scripts/ingest/wages.py` (fails loudly on bad arithmetic); OCR evidence utility `scripts/ingest/ocr_vda_order.py`. Monthly figures are daily × 26 working days (shown as arithmetic in the chunk, not printed in the order). **Central sphere only** — TN state rates are NOT in the KB (see §5.3). |

### 5.2 Figure rules

1. **Minimum-wage figures: central sphere only (Step 7B).** The
   Labour Bureau VDA order (see §5.1) carries central-sphere rates
   for 7 scheduled employments, effective 1 Oct 2026, next revision
   due 1 Apr 2027. Tamil Nadu STATE rates are NOT in the KB — the
   TN Labour Department's minimum-wage G.O. PDFs all return 404
   (probed 21 Nov 2026, see §5.3) — so TN-specific wage questions
   (a tailor in Madurai, TN shop workers) are refusal cases, as
   are future rates and non-scheduled employments. The answerer
   refuses figure questions whose top chunk carries no currency
   figure (see `EVAL_REPORT.md`); a question about the wage LAW is
   a framework question, not a figure question, and is answered
   from the Code on Wages chunk.
2. **Statutory scheme thresholds Wikipedia does carry** (EPF/ESI
   ceilings) are ingested as-is, with source + fetch date cited on
   every answer. They can go stale; the citation shows the date so
   a coordinator can check.

### 5.3 Sources that could NOT be ingested (probed 20 Nov 2026)

Probed with a polite user agent, 20–30 s timeout, 1 s between
fetches; failures were retried once. Nothing was invented to fill
these gaps.

**JS shells (HTTP 200, no usable text without JS execution):**

- Skill India Digital (`skillindiadigital.gov.in`) — 13 words visible.
- e-Shram (`eshram.gov.in`) — 8 words visible; `/about` is HTTP 404.
  **e-Shram has zero coverage in v1** — no Wikipedia article exists
  either (the REST summary API returns 404), and the "Ministry of
  Labour and Employment (India)" article mentions it once in a
  poorly-written sentence with a wrong date, so it was NOT used.
  e-Shram questions are refusal cases (LIMITATIONS.md L15).
- myScheme scheme pages (`/schemes/e-shram`, `/pmkvy`, `/naps`,
  `/ncs`) — all return the identical 41,955-byte shell, 56 words.
- RBI (`rbi.org.in`) — 9 words visible.
- CERT-In (`cert-in.org.in`) — 6 words visible.

**Not fetchable (connection closed / timeout, both rounds):**

- PMKVY (`pmkvyofficial.org`), TNSDC (`tnsdc.in`), Naan Mudhalvan
  (`naanmudhalvan.tnsdc.in`, `naanmudhalvan.tn.gov.in`), CLC
  (`clc.gov.in`), ESIC (`esic.gov.in`, `esic.nic.in`), Cybercrime
  (`cybercrime.gov.in`), I4C (`i4c.mha.gov.in`), NCVET
  (`ncvet.gov.in` — timeout, then connection closed), Infosec
  Awareness (`infosecawareness.in`).

**HTTP 403 (blocked):** Apprenticeship India
(`apprenticeshipindia.gov.in`), EPFO (`epfindia.gov.in`), India
Code (`indiacode.nic.in`), PIB (`pib.gov.in`), Ministry of Labour
(`labour.gov.in` — 200 once, then 403 on both retries).

**Dead links (probed 21 Nov 2026, Step 7B):** the Tamil Nadu Labour
Department's minimum-wage page (`labour.tn.gov.in/minimum-wages.php`,
HTTP 200) lists ~85 scheduled-employment G.O. PDFs, but every
tested download returns HTTP 404 — Agriculture
(`GO2D_3_23012015.pdf`), Tailoring (`GO2D_59_2014.pdf`), Shops &
Commercial (`GO2D_30_29052009.pdf`), Domestic Work
(`Domestic-Works.pdf`), Construction (`GO2D_27.pdf`) — including
with a full browser user agent + Referer. The page's links are
stale. The Commissioner's VDA statement (Order No. Z3/3459/2026,
dated 18.02.2026, effective 01.04.2026, cited by all aggregators)
was not found on the official site. `tn.gov.in/documents/dept/17`
is unreachable from the sandbox. Third-party aggregator figures
for TN (e.g. ₹8,500/mo vs ₹13,823/mo for the same category) were
NOT ingested — they conflict and are not official sources.

### 5.4 Known content issue: EPFO ceiling contradiction

The EPFO Wikipedia article carries two different EPF wage-ceiling
figures: ₹15,000/month (from 1 Sept 2014) and ₹25,000 (described
as the current ceiling). Whether ₹25,000 is in force or proposed
could not be verified from a fetchable official source, so both
figures are kept as-is with source + fetch date cited, and the
contradiction is recorded here rather than resolved by guessing.
No gold case asks for a specific ceiling figure.

### 5.6 Rights-assistant helplines (Step 9.1, 21 Nov 2026)

The rights/scam assistant (`data/kv_helplines.json`) escalates ONLY
to these two numbers. No other helpline number is verified — do NOT
add 112/181/1098 or any other number without a source entry here.

| Number | Service | Source | Verified |
| --- | --- | --- | --- |
| 1930 | National Cyber Crime Helpline (24×7, toll-free) | PIB release 06 Apr 2022 (https://www.pib.gov.in/PressReleasePage.aspx?PRID=1814120&reg=48&lang=2), corroborated by PIB PRID=2085609 | 21 Nov 2026 |
| 1514 | National Career Service (NCS) helpline | The NCS chunk itself (`web:ncs`, source https://www.ncs.gov.in/) | 21 Nov 2026 (from the KB chunk, not a fresh fetch) |

Note: `cybercrime.gov.in` could not be fetched on 21 Nov (network
error) — the 1930 number rests on the PIB releases above, not on
the portal. Escalation text is rendered only from the API
response, never hardcoded in the frontend.

### 5.5 Refresh procedure

Bump `--version` on `python -m scripts.ingest.run` (never overwrite
a snapshot in place), check the fetch log, update this section,
re-run the eval, update `EVAL_REPORT.md`, and commit the snapshot +
meta + docs together (see `scripts/ingest/README.md`).

## Not yet sourced — do not display

- Any headline statistic about graduate unemployment, skills shortages,
  hiring growth or AI job impact for the landing hero. The Phase 1 hero
  therefore uses the verifiable promise from entry #1 instead of a
  numeric statistic. Add an entry here (publisher, report title, year,
  URL, licence) before any such number appears in the UI.
