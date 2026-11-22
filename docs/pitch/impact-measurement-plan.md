# Impact Measurement Plan — Kaam-Vaani pilot (one page)

_Stage 11 requirement. No outcome is claimed as achieved: there
are no users yet. This plan names the baseline, the metrics, and
how targets will be set — targets come FROM the baseline, not
from this document._

## Pilot shape

One institute (ITI / polytechnic / school) and its final-year
school-leavers, 4 weeks, coordinator-led. The pilot console
(`/pilot`) reports every metric below; CSV export is built in.

## Baseline (week 0 — measure before the system arrives)

Survey the cohort (coordinator-administered, in Tamil):

- How do you currently look for work? (family/friends, walk-in,
  portal, agent, nothing yet)
- Have you ever been asked to pay a fee for a job? (yes/no,
  amount if yes)
- Can you name the minimum wage for your trade? (yes/no)
- Phone + data access: own smartphone? daily data?
- Current employment status + what "a good outcome" means to
  them (job, apprenticeship, further training).

**No baseline, no impact claim.** If week 0 is skipped, the
pilot measures activity, not impact — and the report must say so.

## Leading metrics (system activity — measured automatically)

| Metric | Source | Target-setting |
| --- | --- | --- |
| Profiles completed (voice flow finished) | Voice sessions | Set from cohort size (e.g. 60% of enrolled in week 1) |
| Matches viewed per profile | /matches calls | Baseline: first-week median, then hold or improve |
| Skill-gap plans opened | Gap-learning calls | Same |
| RAG questions asked, by topic | Trace log (hashed questions only) | Watch the mix: wages/rights/scam share shows real need |
| Refusal rate on real questions | Eval-style logging | Compare with gold-set 1/19; a much higher rate means the KB is too thin for real questions |
| Consent grants / revokes | Consent store | Grants show trust; revokes show the control works |
| Listings reported | Report queue | Reports are a GOOD sign (users trust the mechanism) |

## Lagging metrics (outcomes — measured by the coordinator, not the system)

| Metric | How measured | Honesty rule |
| --- | --- | --- |
| Employer contacts (worker-consented) | Contact requests | Count only consented contacts |
| Interviews attended | Coordinator follow-up (week 3–4 calls) | Worker-confirmed only |
| Hires / apprenticeships started | Worker-confirmed at week 4 + week 8 | Employer-reported hires are reported separately and never merged into the worker-confirmed count |
| Scam attempts avoided | Worker self-report + reports filed | Self-reported; label as such |
| Wage knowledge gain | Repeat the week-0 wage question at week 4 | Same question, same cohort, or the comparison is meaningless |

## What success looks like (to be set from the baseline)

- A majority of enrolled school-leavers complete a profile.
- At least one worker-confirmed interview per 10 active profiles
  (target to be set from the baseline's current interview rate —
  if the baseline is zero, any confirmed interview is signal).
- Zero fee-charging listings reach users (review queue catches
  them or workers report them first).
- Refusal rate on real questions stays near the gold-set rate —
  a spike means the KB needs the sources the pilot surfaces.

## What failure looks like (say it in advance)

- Profiles started but not completed (voice flow too hard, STT
  failing on dialect, answers in English).
- Matches viewed but no consents (users don't trust it, or the
  matches are wrong for them).
- High refusal rate on real questions (the KB doesn't cover
  what users actually ask).
- Coordinator overload (review queue unmanageable at pilot
  scale — the scale story fails early, which is useful to know).

## Reporting

Weekly one-page report from the pilot console CSV + coordinator
notes: baseline vs current, leading metrics, lagging metrics so
far, top 5 real questions asked, top 3 failures. The week-4
report is the go/no-go input for a wider pilot.
