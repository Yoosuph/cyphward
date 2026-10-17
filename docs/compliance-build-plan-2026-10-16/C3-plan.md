# C3 plan — attestations, owners and expiry, breach log

**Branch:** `codex/compliance-c3`. One PR. API + frontend + one additive migration. **No worker change.**
**Governing rule:** README section 0.
- A customer answer is evidence labelled `customer_attested`; it is never shown as tool or externally observed.
- Nothing here is a legal verdict. The breach checklist is a plain operational checklist, "not legal advice".
- File uploads stay deferred (D2): **links only**.

**Status:** plan for founder review. No code yet.

## 1. What C3 adds

1. **Guided questionnaire** (20 questions, section 2), grouped like the register.
   - Applicability questions come first, so requirements that don't apply leave the denominator **with a recorded reason**.
   - Each answer has an **owner** (a member), the date answered, an **expiry** (default 12 months), an optional **evidence link** (https only, never fetched by Cyphward) and optional notes.
2. **Expiry reminders** 30 and 7 days before an answer expires: in-app notification plus email to the answer's owner and the organisation's owners/admins. Sent once per answer per threshold, from a daily job under the existing cron claim.
3. **Breach incident log**:
   - title, detected at, became aware at, severity, status, when the Commission and the affected people were notified, notes;
   - the **72-hour deadline** is `became_aware_at + 72 h`, shown as a countdown and an **overdue** badge;
   - a short plain checklist ("not legal advice").
4. **Roles:** owners and admins edit; members view. **Every change is audited** in `audit_log`.

## 2. Questionnaire v1 (versioned data file, like the register)

`backend/app/compliance/questionnaires/ndpa_gaid_v1.json`, validated at startup. Every question names the register requirement(s) it evidences. Answer types: `yes_no`, `choice`, `date`, `text` (short).

| # | Key | Question (plain English) | Type | Evidences / effect |
|---|---|---|---|---|
| A1 | `registration.major_importance` | Are you a data controller or processor of major importance? | yes_no / not sure | `gaid.registration.major_importance_status`. **No** → `gaid.registration.registered` not applicable |
| A2 | `registration.tier` | Which tier: UHL, EHL or OHL? (shown if A1 = yes) | choice | **OHL** → `gaid.registration.annual_car` not applicable |
| A3 | `dpia.high_risk_processing` | Do you carry out processing likely to pose a high risk to people (large-scale sensitive data, profiling, monitoring)? | yes_no | **No** → `gaid.dpia.high_risk_processing` not applicable |
| A4 | `transfers.outside_nigeria` | Is personal data stored or sent outside Nigeria (including cloud hosting)? | yes_no | **No** → `ndpa.part8.transfers_identified` not applicable |
| Q1 | `registration.registered` | Have you registered with the Commission? (+ registration date) | yes_no + date | `gaid.registration.registered` |
| Q2 | `registration.car_filed` | Was this year's audit return filed through a licensed DPCO? (+ date) | yes_no + date | `gaid.registration.annual_car` |
| Q3 | `dpo.designated` | Have you named a data protection officer? (+ name/role, never personal ID numbers) | yes_no + text | `gaid.dpo.designated` |
| Q4 | `dpo.contact_published` | Is the DPO's contact published (e.g. in your privacy policy)? | yes_no | `gaid.dpo.contact_published` (alongside C2a's observation) |
| Q5 | `dpo.reports_to_management` | Does the DPO report directly to senior management? | yes_no | `gaid.dpo.reports_to_management` |
| Q6 | `dpo.six_monthly_report` | Date of the DPO's latest six-monthly report | date | `gaid.dpo.six_monthly_report` (expires 183 days after that date) |
| Q7 | `breach.response_plan` | Do you have a written breach response plan? | yes_no | `ndpa.s40.breach_response_plan` |
| Q8 | `breach.notification_process` | Is there a process to notify the Commission within 72 hours? | yes_no | `ndpa.s40.notification_72h` |
| Q9 | `breach.incident_log` | Do you keep an incident log? (Cyphward's log counts if in use) | yes_no | `ndpa.s40.incident_log` |
| Q10 | `dpia.done` | Have you completed a DPIA for that processing? (if A3 = yes) | yes_no + date | `gaid.dpia.high_risk_processing` |
| Q11 | `lawful_basis.documented` | Is the lawful basis written down for each processing purpose? | yes_no | `ndpa.s25.lawful_basis_documented` |
| Q12 | `consent.records_kept` | Where you rely on consent, do you keep records of who agreed, to what and when? | yes_no / not applicable | `gaid.consent.records_kept` |
| Q13 | `rights.process` | Is there a process for access, correction, portability and erasure requests? | yes_no | `ndpa.part6.rights_process` |
| Q14 | `transfers.identified` | Are your transfers outside Nigeria listed with the basis relied on? (if A4 = yes) | yes_no | `ndpa.part8.transfers_identified` |
| Q15 | `training.in_place` | Do staff who handle personal data get privacy/security training at least yearly? | yes_no | `gaid.training.in_place` |
| Q16 | `training.last_session` | Date of the latest training session | date | `gaid.training.in_place` (expiry from that date) |

## 3. How answers become status (read side)

- **Yes** with a current answer → `present`, source `customer_attested`, with owner, date, expiry and link.
- **No** → `gap` ("You told us this isn't in place yet"), with the requirement's `remediation_hint` and "Create task".
- **Not sure / unanswered** → `awaiting_input`.
- **Expired** → `awaiting_input` with reason `answer_expired` ("renewal due"). An expired attestation is never present; it isn't "not assessed" either, since nothing could run.
- **Superseded** answers are history only; the newest answer wins.
- **Applicability:**
  - "No" to A1/A3/A4, or OHL for A2 → the dependent requirement becomes `not_applicable` with the answer as the **recorded reason**, and leaves the denominator;
  - unanswered applicability → the requirement stays applicable;
  - the page always shows what was excluded and why.
- **Mixed sources:**
  - **DPO contact:** present if either a current attestation or C2a's observation is present. A gap from either is shown; observed evidence is never overridden by an answer, and vice versa.
  - **Privacy policy / cookie / trackers:** stay externally observed only.
- **Never cross-labelled:** a customer answer never appears as tool or externally observed (tested).

## 4. Data model (one additive migration)

```sql
compliance_attestations (
  id uuid pk, org_id uuid not null fk organizations on delete cascade,
  question_key text not null, questionnaire_version text not null,
  answer jsonb not null,               -- {"value": "yes"|"no"|"not_sure"|..., "date": ..., "text": ...}
  owner_user_id uuid fk profiles on delete set null,
  attested_by uuid fk profiles on delete set null,
  attested_at timestamptz not null default now(),
  expires_at timestamptz not null,
  evidence_link text check (evidence_link is null or (evidence_link ~ '^https://' and length(evidence_link) <= 500)),
  notes text check (length(notes) <= 1000),
  superseded_by uuid fk compliance_attestations, created_at ...)
  -- index (org_id, question_key, attested_at desc); partial unique: one current (superseded_by is null) per (org, question)

compliance_incidents (
  id uuid pk, org_id uuid not null fk organizations on delete cascade,
  title text not null (<= 200), severity text check in ('low','medium','high','critical'),
  status text check in ('open','contained','closed'),
  detected_at timestamptz not null, became_aware_at timestamptz not null,
  notified_commission_at timestamptz, notified_subjects_at timestamptz,
  notes text (<= 4000), created_by uuid, created_at, updated_at,
  check (became_aware_at >= detected_at - interval '30 days'))   -- sanity, not a rule

compliance_reminders (attestation_id uuid fk on delete cascade, threshold_days int, sent_at timestamptz,
  primary key (attestation_id, threshold_days))   -- dedupe: one reminder per answer per threshold
```

**Grants for `cyphward_app`:**

| Table | Grants |
|---|---|
| attestations | SELECT, INSERT, UPDATE(`superseded_by`) only |
| incidents | SELECT, INSERT, UPDATE(status, notified_*, notes, severity, updated_at); no DELETE |
| reminders | SELECT, INSERT |

RLS policy on all three, the same as every app table. All times are stored in UTC.

## 5. API (tenant-scoped; members read, owners/admins write)

- `GET /api/v1/compliance/questionnaire`: questions plus the current answer, owner and expiry for each.
- `POST /api/v1/compliance/attestations`: owner/admin only.
  - Body: `question_key`, `answer`, `owner_user_id` (must be a member), optional `expires_at` (default 12 months; capped at 24), `evidence_link`, `notes`.
  - Supersedes the current answer in one transaction and writes `audit_log`.
- `GET /api/v1/compliance/attestations/{question_key}`: answer history.
- `GET/POST /api/v1/compliance/incidents` and `PATCH /api/v1/compliance/incidents/{id}`:
  - owner/admin write; members read; audited;
  - responses include `deadline_at`, `hours_remaining` and `overdue`, computed server-side from UTC.
- The overview gains `not_applicable` entries with their reasons, and the `customer_attested` source.

## 6. Reminders

- A daily job (cron name `compliance_reminders`) runs under the existing atomic cron claim, from the in-process scheduler and the Inngest cron, like the scan sweep.
- It finds current answers expiring within 30 or 7 days with no reminder row for that threshold. For each, it inserts the reminder row, then the notification and email, in that order, so a retry can't double-send.
- Email goes to the answer's owner and the organisation's owners/admins, through the existing mailer. The text names the requirement, the expiry date and a link; it contains no answer content.

## 7. Frontend

- Compliance page:
  - an **"Answer questions"** flow (applicability first; one group at a time; owner picker; expiry; link);
  - each attested requirement shows "You told us … on … (owner …, renews …)";
  - an **Excluded** section lists not-applicable requirements with their reasons.
- **Incidents** tab:
  - a list with severity and status;
  - a **72 h countdown** (hours and minutes) and a red **Overdue** badge when past the deadline without a Commission notification;
  - a create/edit form;
  - the checklist: contain, assess, record, notify the Commission within 72 h if required, notify affected people where required, review.
- Times show in the **viewer's organisation display time zone** (D11). The deadline maths stays UTC.
- Members see everything read-only. Desktop/390/320.

## 8. Tests

- **Questionnaire:** loader/validator (unknown requirement keys, bad types, applicability targets).
- **Truth table:** yes / no / not sure / unanswered / expired / superseded / not applicable with a reason excluded from the denominator / mixed DPO sources / answers never labelled tool or externally observed.
- **PostgreSQL:**
  - superseding is atomic, with one current answer;
  - append-only grants (attestations can't be edited in place; incidents can't be deleted);
  - cross-tenant IDs rejected (attestation owner from another org, incident of another org);
  - members can't write; every write audited.
- **Reminders:**
  - 30/7-day thresholds;
  - dedupe across retries;
  - a stale cron claim can't send;
  - emails stubbed;
  - expiry turns `present` into `awaiting_input`.
- **72-hour deadline:**
  - edges: exactly 72 h, 1 minute before or after, notified before the deadline (never overdue), notified after (shown "notified late");
  - time zones: `became_aware_at` entered near midnight in Lagos, and around DST in a non-Lagos zone; stored UTC, displayed in the organisation's zone.
- **Banned phrases** over the questionnaire, incident checklist, emails and the new page copy.
- **Browser suite:** questionnaire flow, incidents, countdown and overdue, read-only for members, at desktop/390/320.
- Full backend on a fresh bootstrap; `git diff --check`.

## 9. Decisions for the founder

| # | Question | Proposed default |
|---|---|---|
| D11 | Display time zone (organisations have no country field) | Add `organizations.display_timezone`, default **Africa/Lagos**, editable by owners in Settings. Store UTC everywhere. |
| D12 | Expired answer | Shows **Awaiting your input — renewal due**; never present; reminders at 30 and 7 days before. |
| D13 | "Not sure" answers | Treated as unanswered (`awaiting_input`), never a gap. |
| D14 | Who may be an answer's owner | Any member of the organisation; owners/admins assign. |
| D15 | Incident retention | Never deleted by the app; closed incidents stay as history (operator SQL only, audited). |

## 10. Release

1. Back up (encrypted).
2. Apply the migration as `postgres`; verify the tables, RLS, the narrow grants through `cyphward_app`, and that row counts are unchanged.
3. Merge → API (Render) and frontend (Vercel). **No scanner deploy.**
4. Verify:
   - `/health`;
   - the new endpoints return 401 without auth;
   - `/comply` shows the questionnaire.
5. The day after release, confirm the reminders job ran. Its `cron_runs` row isn't covered by your standing permission, so I'll ask before reading it.

No production writes beyond the migration. I won't fill in your answers for you.
