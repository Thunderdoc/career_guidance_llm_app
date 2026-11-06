# Compliance — engineering checklist (Phase 5)

> **Engineering checklist — not legal advice. Owner must review with a
> lawyer before launch.**
>
> This document records what the *software* does today, so a lawyer can
> review the product against India's Digital Personal Data Protection
> Act, 2023 (DPDP) and any other applicable law. The product copy says
> "designed to support DPDP" — it never claims "DPDP compliant".

## 1. Consent

- [x] Consent requests are recorded (`consent_records`, migration v7):
  user, guardian e-mail, notice version, status
  (`pending/granted/denied/revoked`), method, requested/decided
  timestamps.
- [x] Guardian flow is manual/e-mail: the guardian confirms or declines
  through a public, token-secured link (`GET /api/v1/consent/confirm/{token}`);
  no guardian account is needed. Tokens are stored **hashed**, expire in
  **72 hours** (`TOKEN_TTL_HOURS`), and are single-decision.
- [x] Notice versioning: `NOTICE_VERSION` in `career_guidance/consent.py`.
  Bumping it turns every stored grant into computed `needs_reconsent` —
  restrictions re-apply automatically until a guardian re-confirms.
- [x] Withdrawal: the user can revoke in Account → Privacy; a guardian
  can revoke via a fresh action-token link
  (`ConsentStore.issue_action_token`); deleting the account deletes the
  consent records with everything else.
- [x] Delivery honesty: SMTP when configured, otherwise the log-only
  notification provider — the UI never claims an e-mail was sent when
  the log channel was used; a dev link is surfaced **only outside
  production** (same rule as magic links).
- [ ] **Owner/lawyer:** confirm the notice text, the age threshold this
  product should use, and whether verifiable parental consent is
  required for the exact services offered (DPDP §9) before launch.

## 2. Minor protections (under-18 accounts)

Age is established by a **least-data declaration** — an `age_band`
(`adult`/`minor`) plus an optional birth **year**; a full date of birth
is never collected. A birth year implying under-18 overrides an "adult"
band (fail-safe). `users.is_minor` is derived from the declaration.

For a minor **without** granted parental consent
(`career_guidance.consent.restrictions_for`):

| Surface | Behaviour |
| --- | --- |
| Core guidance (recommend, plan, assessment, job fit) | Works — minimal processing needed to deliver what was asked |
| Public profile `/p/{handle}` | Blocked (all minors, granted or not — Phase 3 rule, kept) |
| Behavioural analytics (`tool_events`) | Not recorded |
| XP / streaks / badges | No awards; dashboard + activity streak surfaces return zeroed server-side; plan reminders suppressed (`minor_restricted`) |
| Institute cohort aggregates | Student still counted (membership is guardian/school-mediated) |
| Institute needs-attention individual lists | Student excluded (cohort, students list, CSV/PDF counts) |
| Plan-item completion markers | Kept — they are the storage for the user's own plan progress, not a nudge |

- [ ] **Owner/lawyer:** review the minimal-processing set above; decide
  whether consented minors should regain any surface (today only
  analytics/XP/attention-list return; public profiles stay off).

## 3. Data minimisation

- [x] No full date of birth anywhere; birth year only, optional.
- [x] Guardian e-mail stored in plain text **only** inside
  `consent_records` (access-controlled; never in any public payload;
  included only in the account holder's own status/export, since they
  supplied it).
- [x] Public profiles expose only display name, verified skills,
  projects and plan progress — never e-mail, age or school.
- [x] Cohort exports are aggregate-only (no names/e-mails).
- [x] Counsellor-validation sampling uses run ids only
  (`eval/COUNSELLOR_VALIDATION.md`).

## 4. Export & delete (verified end-to-end by tests)

- Export (`GET /api/v1/me/export`) returns the account record plus
  profile, runs, plans, 90-day plans, ratings, progress, assessments,
  interview sessions, XP/badges, feedback, skill verifications, quiz
  attempts, project evidence, payments and consent records (token
  hashes excluded — credentials, not data). Tests assert two users'
  exports contain only their own data.
- Delete (`DELETE /api/v1/me`, admin delete uses the same store method)
  removes **all** of: user row, runs, profiles, targets, plans, 90-day
  plans, ratings, saved/done resources, interview sessions, XP, badges,
  assessments, skill progress, verifications, quiz attempts, projects,
  tool events, payments, consent records, reviews (of and by the user),
  magic links and institute invites for the e-mail.
- Kept, anonymised: feedback rows (rating kept, `user_id` set to NULL)
  and audit-log rows (action kept, actor e-mail replaced with
  `deleted-user`). Both are product/operations data with no remaining
  link to the person.
- [ ] **Owner/lawyer:** confirm the anonymised-retention choices and set
  a backup-retention period; deleted data persists in old backups until
  they rotate.

## 5. Breach-response runbook (engineering steps)

1. **Detect & tell the owner immediately** (error logs, provider
   alerts, user reports). Do not investigate silently for days.
2. **Contain:** rotate `SESSION_SECRET` (invalidates all sessions),
   rotate SMTP/Razorpay/API keys that may be exposed, disable affected
   accounts (`users.disabled`), take the service offline if personal
   data is actively leaking.
3. **Assess:** which tables/accounts/date ranges were accessed
   (audit log, `tool_events`, host/provider logs); write down what is
   *known* vs *suspected* — do not speculate to users.
4. **Preserve evidence:** snapshot logs and the DB before cleanup;
   record a timeline.
5. **Notify:** owner + lawyer decide user and authority notifications
   and their timing under the law as it stands at that date — this
   runbook deliberately does not state deadlines; the lawyer confirms
   the current DPDP Board / CERT-In requirements.
6. **Remediate & record:** fix the root cause, add a regression test,
   note the incident and the fix in `CHANGELOG.md`.

## 6. Open owner decisions (not engineering)

- Legal review of the privacy notice + terms (this checklist §1).
- Business name, contact/grievance e-mail for the legal pages
  (placeholders today — UPGRADE_PLAN §3 item 3).
- SMTP provider for production mail (consent + magic links).
- Backup retention period (§4) and a named person responsible for the
  breach runbook (§5).
