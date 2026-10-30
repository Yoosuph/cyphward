# Owner console phase 2 (2026-10-31)

Follows `docs/admin-2026-10-29/AUDIT.md`. Four items: suspension enforced for customers, indexes for the owner
analytics and lists, plain scan-failure wording, and restoring a removed member from the audit record.

## 1. Suspension, enforced (`backend/app/core/suspension.py`)

- A suspended organisation can sign in and read everything it could before: dashboards, scans, findings, reports,
  compliance views. Read endpoints are unchanged apart from a `suspended` flag on `GET /organizations/current` and
  on each membership in `GET /auth/bootstrap`.
- Every customer write route takes `require_active_org`, or a role gate built on it (`require_active_admin`,
  `require_active_owner`, `require_active_reviewer`). A refused write is HTTP 403 with
  `{"detail": {"code": "organization_suspended", "message": "<reviewed sentence>"}}`. The message names only the
  existing contact (info@cyphward.com, the contact page).
- `backend/tests/test_suspension_gate.py` walks every POST/PUT/PATCH/DELETE route under `/api/v1`. Each one must
  be gated or on a short allow-list of `(method, path)` pairs, each with its reason. It fails on an ungated route,
  on a gated route that is still allow-listed, and on a stale allow-list entry.
- Scans: `admit_scan` (manual launch and the daily sweep) refuses a suspended organisation under the organisation
  row lock that the owner's suspend also takes. The sweep's due-domain query leaves suspended organisations out.
  The worker and local claim (`claim_recon`) does not claim their queued scans, so those wait and run after the
  suspension is lifted. Scans already running finish; the owner can cancel them. Domains and monitored hosts are
  not touched. A same-day unsuspend resumes at the next daily sweep.
- Customer app: a banner on every page (what is paused, what still works, who to contact). The main write buttons
  are disabled with a tooltip. Compliance becomes view only. A suspension that starts mid-session shows the banner
  on the first refused write.
- Owner actions are never blocked. Restoring a member is refused while suspended.

### Write routes and how each is gated

| Route | Gate |
|---|---|
| `POST /api/v1/ai/chat` | allow-list: read-only AI answer (core.auth.READ_ONLY_POSTS): writes no customer record |
| `POST /api/v1/ai/chat/stream` | allow-list: read-only AI answer (core.auth.READ_ONLY_POSTS): writes no customer record |
| `POST /api/v1/ai/executive-summary` | allow-list: read-only AI answer (core.auth.READ_ONLY_POSTS): writes no customer record |
| `POST /api/v1/ai/explain` | allow-list: read-only AI answer (core.auth.READ_ONLY_POSTS): writes no customer record |
| `POST /api/v1/ai/remediate` | allow-list: read-only AI answer (core.auth.READ_ONLY_POSTS): writes no customer record |
| `POST /api/v1/auth/account/delete` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/demo-login` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/exchange` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/forgot-password` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/google/one-tap` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/login` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/logout` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/mfa/disable/confirm` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/mfa/disable/request` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/mfa/enroll` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/mfa/send` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/mfa/start` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/mfa/verify` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/otp/send` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/otp/verify` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/refresh` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/register` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/reset-password` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/totp/disable` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/totp/enroll/confirm` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/totp/enroll/start` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/trusted-browsers/forget` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/auth/welcome` | allow-list: personal account and sign-in: acts on the person, not on an organisation |
| `POST /api/v1/billing/subscription` | require_active_owner (owner) |
| `POST /api/v1/billing/subscription/cancel` | require_active_owner (owner) |
| `POST /api/v1/billing/subscription/renew` | require_active_owner (owner) |
| `POST /api/v1/browser-worker/claim` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/browser-worker/jobs/{job_id}/fail` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/browser-worker/jobs/{job_id}/heartbeat` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/browser-worker/jobs/{job_id}/result` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/compliance/attestations` | require_active_admin (owner/admin) |
| `POST /api/v1/compliance/documents/{document_id}/approve` | require_active_admin (owner/admin) |
| `POST /api/v1/compliance/documents/{kind}/generate` | require_active_admin (owner/admin) |
| `POST /api/v1/compliance/evidence-files` | require_active_admin (owner/admin) |
| `DELETE /api/v1/compliance/evidence-files/{file_id}` | require_active_admin (owner/admin) |
| `POST /api/v1/compliance/incidents` | require_active_admin (owner/admin) |
| `PATCH /api/v1/compliance/incidents/{incident_id}` | require_active_admin (owner/admin) |
| `POST /api/v1/compliance/reviewer-grants` | require_active_owner (owner) |
| `POST /api/v1/compliance/reviewer-grants/{grant_id}/revoke` | require_active_owner (owner) |
| `POST /api/v1/compliance/reviewer/requirements/{key}/clause-reference` | require_active_reviewer (reviewer grant) |
| `POST /api/v1/compliance/reviewer/requirements/{key}/review` | require_active_reviewer (reviewer grant) |
| `POST /api/v1/contact` | allow-list: public form or newsletter flow: no organisation |
| `POST /api/v1/domains` | require_active_admin (owner/admin) |
| `DELETE /api/v1/domains/{domain_id}` | require_active_admin (owner/admin) |
| `POST /api/v1/domains/{domain_id}/consent-observation` | require_active_admin (owner/admin) |
| `POST /api/v1/domains/{domain_id}/hosts` | require_active_admin (owner/admin) |
| `DELETE /api/v1/domains/{domain_id}/hosts/{host_id}` | require_active_admin (owner/admin) |
| `POST /api/v1/domains/{domain_id}/verify` | require_active_admin (owner/admin) |
| `PATCH /api/v1/findings/{finding_id}/status` | require_active_admin (owner/admin) |
| `POST /api/v1/members/invite` | require_active_admin (owner/admin) |
| `POST /api/v1/members/invites/accept` | allow-list: the organisation comes from the invitation token, so the handler calls suspension.ensure_active on it (test_invite_accept_is_refused_for_a_suspended_organisation) |
| `DELETE /api/v1/members/invites/{invite_id}` | require_active_admin (owner/admin) |
| `PATCH /api/v1/members/{user_id}` | require_active_admin (owner/admin) |
| `POST /api/v1/newsletter/confirm` | allow-list: public form or newsletter flow: no organisation |
| `POST /api/v1/newsletter/drafts` | allow-list: newsletter draft upload with the drafts key; no organisation |
| `POST /api/v1/newsletter/drafts/{issue_id}/send` | allow-list: owner or newsletter staff send; no organisation |
| `POST /api/v1/newsletter/subscribe` | allow-list: public form or newsletter flow: no organisation |
| `POST /api/v1/newsletter/unsubscribe` | allow-list: public form or newsletter flow: no organisation |
| `POST /api/v1/notifications/read-all` | allow-list: the person's own read markers; no organisation record |
| `PATCH /api/v1/notifications/{notification_id}/read` | allow-list: the person's own read marker; no organisation record |
| `POST /api/v1/organizations` | allow-list: creates a new organisation for the person; no existing organisation changes |
| `POST /api/v1/organizations/close` | require_active_owner (owner) |
| `PATCH /api/v1/organizations/current` | require_active_admin (owner/admin) |
| `POST /api/v1/owner/logout` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/organizations/{org_id}/members/restore` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/organizations/{org_id}/members/{user_id}/remove` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/organizations/{org_id}/plan` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/organizations/{org_id}/suspend` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/organizations/{org_id}/trial` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/organizations/{org_id}/unsuspend` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/scans/{scan_id}/cancel` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/session` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/setup/authenticator` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/setup/complete` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/owner/users/{user_id}/sign-out` | allow-list: owner console: separate owner session; owner actions are never blocked by a suspension |
| `POST /api/v1/packs` | require_active_admin (owner/admin) |
| `POST /api/v1/remediation` | require_active_org (any member) |
| `PATCH /api/v1/remediation/{task_id}` | require_active_org (any member) |
| `POST /api/v1/remediation/{task_id}/verify` | require_active_admin (owner/admin) |
| `POST /api/v1/reports` | require_active_admin (owner/admin) |
| `POST /api/v1/reports/send-email` | require_active_admin (owner/admin) |
| `POST /api/v1/scanner/claim` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/scanner/jobs/{scan_id}/complete` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/scanner/jobs/{scan_id}/fail` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/scanner/jobs/{scan_id}/observations` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/scanner/jobs/{scan_id}/progress` | allow-list: scanner or browser worker protocol: machine credentials and a claimed job, no organisation session |
| `POST /api/v1/scans/launch` | require_active_admin (owner/admin) |
| `POST /api/v1/scans/{scan_id}/cancel` | require_active_admin (owner/admin) |
| `POST /api/v1/settings/company` | require_active_admin (owner/admin) |
| `POST /api/v1/snapshots` | require_active_admin (owner/admin) |
| `PUT /api/v1/snapshots/retention` | require_active_owner (owner) |

37 gated, 59 allow-listed. The `require_active_*` role gates all depend on `require_active_org`.

Judgement calls, for review:

- `POST /billing/subscription/cancel` is gated. The literal rule covers settings changes, so a suspended owner
  cannot schedule a cancellation.
- `POST /compliance/reviewer-grants/{id}/revoke` and `PATCH /members/{user_id}` are gated too, so a suspended
  organisation cannot remove outside access itself; the owner console can remove members.
- `POST /organizations/close` is gated, since closing would delete the organisation and its suspension row.
- `POST /organizations` (create a new organisation) is allow-listed. A suspended customer could create a new
  organisation and add the same domain there. Raise it if that should be refused.
- Notification read markers and the five AI answer routes are allow-listed: they write no organisation record
  (AI use is only rate-limited).

## 2. Indexes (`supabase/migrations/20261031100000_admin_indexes.sql`)

Ten indexes, each tied to a query in `owner_analytics.py`, `owner_lists.py` or `owner_views.py` (listed in the
file header). They are plain `CREATE INDEX IF NOT EXISTS` inside `BEGIN … COMMIT` with `lock_timeout = '5s'` and
`statement_timeout = '60s'`. `CONCURRENTLY` cannot run here, because both the test bootstrap and the release tool
apply each file as one transaction. Each build takes a SHARE lock on its table, so writes to that table wait until
the file commits. Reads continue. The busiest tables come last. **Check table sizes and the build time on a copy at
release.**

`backend/tests/test_admin_indexes_postgres.py` loads 50,000 scans, findings, customer audit rows and owner audit
rows (plus 2,000 organisations, 5,000 people and 20,000 sessions) in one transaction, runs ANALYZE, and checks with
EXPLAIN that the queries the code actually issues use an index. The queries checked are:

- the analytics timeseries and summary;
- the organizations and users lists;
- the owner and customer logs;
- the organization detail.

The fixture is rolled back afterwards.

## 3. Plain scan-failure wording (`backend/app/core/scan_failures.py`, `20261031100100_scan_failure_code.sql`)

- `scans.failure_code` is new: nullable text, with a `NOT VALID` format check. The column is written when a scan
  fails, from a fixed set: unreachable, blocked, timeout, out_of_scope, domain_unverified, interrupted, internal.
- Customers see the reviewed sentence for the code. An unknown or missing code gets the generic sentence. Scans
  that failed before the column existed are classified from their stored text when read.
- Customer scan list, detail and overview responses go through `customer_scan` / `customer_raw_results`, which
  remove `error_message` and the top-level progress error. They replace any stage note or per-host reason that is
  not reviewed backend wording.
- The owner console shows the sentence and the raw text.
- **Release order:** apply this migration before deploying the code, because `fail_claim` writes the column.

## 4. Restore a removed member

`POST /api/v1/owner/organizations/{org_id}/members/restore` with `reason`, `confirm_name` and `audit_id`.

- The person, role and join date come from the `owner.action.remove_member` success row for that organisation.
- Refused when:
  - the name is wrong;
  - the organisation is suspended;
  - the record is unknown or belongs to another organisation;
  - the removal was already restored (each audit row restores once);
  - the account is gone or its email changed;
  - the person is already a member.
- Every refusal is audited as `rejected`. A success writes the owner audit row (`restored_from`) and the customer's
  `member.restored` activity entry.
- The organization page lists members removed by owner actions, with a Restore button behind the typed-name gate.
