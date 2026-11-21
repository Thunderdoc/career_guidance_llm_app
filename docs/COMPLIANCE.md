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

## 1a. Kaam-Vaani worker consent (Stage 6) — a separate consent domain

The parental-consent system above (migration v7, `consent_records`)
is NOT reused for worker–employer sharing: Stage 6 has its own
tables (migration v14: `kv_consents`, `kv_consent_audit`) and its
own rules, because the data principal, purpose and lifecycle differ.

- [x] Consent is per-employer, time-limited (7/30/90 days, default
  30), revocable at any time, and specific: the worker picks the
  exact fields shared from a fixed set (skills, education, city,
  income, goal, interests, contact). One active consent per
  (worker, employer); re-grant only after revoke/expire.
- [x] Purpose limitation is enforced server-side: an employer sees
  a worker's fields only under an active consent, only for
  matching/shortlist/contact about verified listings, and only the
  consented fields (`filter_profile` allow-list). No consent means
  no data — enforced in the API, not just the UI (negative tests).
- [x] The explanation is a deterministic template, never
  LLM-paraphrased, so it cannot misstate which fields are shared
  or for how long. It is also spoken aloud (Listen button).
- [x] Revocation is immediate and final; expiry is lazy but
  enforced on every read path (an overdue grant flips to expired
  with a `system` audit event before any data is returned).
- [x] The audit log (`kv_consent_audit`) is append-only: the only
  write is an INSERT; there is no update/delete path anywhere,
  and re-seeding sample data deliberately keeps old audit rows.
  Every grant, revoke, expiry and profile access is recorded,
  visible to the worker on `/sharing` and to the employer in
  their own audit view.
- [x] Contact sharing is minimal: `contact` shares the sign-in
  e-mail plus the verified phone only — an unverified phone is
  never shared.
- [ ] **Owner/lawyer:** confirm the DPDP notice text for worker
  sharing (what is shared, with whom, for how long, how to
  revoke), the retention policy for the audit log (today: kept
  forever, L49), and whether worker profiles need a
  deletion/erasure path beyond account deletion.

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

### 4a. Kaam-Vaani deletion (Step 9.4)

`DELETE /api/v1/kv/me/data` (signed-in) erases the caller's
Kaam-Vaani data; full account deletion (`DELETE /api/v1/me`,
and the admin user delete) runs the same erasure first, then
the base-app deletion above. Before Step 9.4, account deletion
left every KV row behind — the KV tables postdate
`delete_user`. One helper is the single entry point:
`delete_all_kv_data` (`career_guidance/kaamvaani/consent.py`).

- **Deleted:** worker profile, every consent naming the worker
  (all statuses), shortlists and contact requests naming the
  worker; the employer row and all its listings (when the
  account is an employer); consents/shortlists/contact requests
  naming the deleted employer.
- **Anonymised, not deleted:** hire outcomes about the worker —
  the row stays (aggregate retention stats must stay valid) but
  the worker link becomes a one-way tombstone
  `deleted-{sha256(user_id)[:12]}` (unique per worker, so the
  (listing, worker) dedup still holds; unlinkable once the
  account row is gone), the reporter link is cleared when the
  worker reported it, and the worker's note is cleared. The
  employer's reporter link/note on outcomes is cleared the same
  way when the employer deletes.
- **Retained:** listing reports (workers' safety records naming
  no employer PII — deleting them would destroy scam evidence)
  and the consent audit trail (`kv_consent_audit`), which is
  NEVER deleted: it is the append-only consent-evidence log
  (Stage 6 invariant, execution prompt 6.2). Its rows hold only
  user-id tokens (random, unlinkable after the account row is
  gone) plus the employer's e-mail as the `actor` on
  `accessed` events — the e-mail is the identifier the worker
  recognises, and it is the consent evidence itself.
- **Retention policy (Step 9.4, recorded, NOT automated):**
  audit rows are retained for **365 days**. No automated prune
  exists — the append-only invariant means pruning is a
  deliberate future ops decision (a migration + an explicit
  ops action), not a code path. At pilot scale the log is
  small; the prune decision is a deploy-checklist item.
- [ ] **Owner/lawyer:** confirm (a) the 365-day audit
  retention, (b) that retaining the employer's e-mail as the
  audit actor is acceptable as consent evidence, (c) the
  outcome-tombstone anonymisation, (d) the backup-retention
  period (deleted KV data persists in old backups until they
  rotate, same as §4).

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
