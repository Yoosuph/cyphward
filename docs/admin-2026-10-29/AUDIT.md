# Owner console audit and phase 1 (2026-10-29)

Scope: the platform owner console at admin.cyphward.com (`/admin` on localhost). Sources read: `frontend/src/owner/*`,
`backend/app/api/owner.py`, `owner_views.py`, `owner_actions.py`, `backend/app/core/owner.py`, the newsletter owner
routes in `backend/app/api/newsletter.py`, and the tests `test_owner_console.py`, `test_owner_setup.py`,
`test_owner_views_postgres.py`, `test_owner_actions_postgres.py` and `frontend/scripts/check-admin-newsletter.mjs`.

## 1. What existed before phase 1

### Access model (unchanged, still sound)

- To sign in you need an email, a password and a fresh authenticator (TOTP) code. Each TOTP step works only once, so a
  code cannot be replayed. Google sign-in, emailed codes and remembered browsers never open the console.
- The session is an opaque `__Host-` cookie: httpOnly and SameSite=Strict. It ends after 30 minutes idle or 8 hours
  in total, and both limits are checked by the server.
- Every owner endpoint refuses a request that carries an `Authorization` header. A customer token or a platform-staff
  token is therefore refused whatever scopes it holds.
- Changes also need the exact console `Origin`, as a CSRF guard.
- Each read writes its `owner_audit` row before it reads. If that row cannot be written, the request returns 503 and no
  data. Each change commits in the same transaction as its audit row.

### Screens

| Screen | Route | What it does |
|---|---|---|
| Sign-in | `/admin` (signed out) | email + password + authenticator code; one generic failure message |
| First sign-in setup | `/admin` (setup session) | new password + authenticator enrolment for an operator-created admin login |
| Overview | `/` | counts (users, orgs, domains, scans 24 h, queue), 14-day sign-ups, invoices, recent customer activity |
| Organizations | `/organizations` | search by name/slug/domain/member email, 50 per page, newest first |
| Organization | `/organizations/:id` | members, domains, plan and billing (change plan, extend trial), open findings by severity, recent scans, activity |
| Users | `/users` | search by email/name, 50 per page |
| User | `/users/:id` | account, memberships, sessions, activity; sign out everywhere |
| Subscriptions | `/subscriptions` | status chips, up to 200 subscriptions and 100 invoices, no paging |
| Scans | `/scans`, `/scans/:id` | search, state chips, paging; detail with stages and hosts; cancel a queued or running scan |
| Newsletter | `/newsletter`, `/newsletter/:id` | subscriber counts, drafts, typed-subject send |
| Logs | `/logs` | customer audit log or owner audit log, search, paging |
| System | `/system` | database, background jobs, deploy, scanner, scheduled runs, integrations |

### Endpoints (all under `/api/v1/owner` unless noted)

| Method and path | Purpose | Gate |
|---|---|---|
| `POST /session`, `GET /me`, `POST /logout` | sign in, session, sign out | console Origin on sign-in |
| `POST /setup/authenticator`, `POST /setup/complete` | first sign-in setup | setup session + Origin |
| `GET /overview` | platform counts | owner, audited |
| `GET /organizations`, `GET /organizations/{id}` | list, detail | owner, audited |
| `GET /users`, `GET /users/{id}` | list, detail | owner, audited |
| `GET /subscriptions` | subscriptions and invoices | owner, audited |
| `GET /scans`, `GET /scans/{id}` | list, detail | owner, audited |
| `GET /logs`, `GET /system` | logs, health | owner, audited |
| `POST /organizations/{id}/plan`, `/trial` | change plan, extend trial | owner + Origin + reason, audited in-transaction |
| `POST /scans/{id}/cancel`, `POST /users/{id}/sign-out` | cancel scan, sign out everywhere | owner + Origin + reason |
| `GET /api/v1/newsletter/stats` | subscriber counts | owner cookie only, audited |
| `GET /api/v1/newsletter/drafts`, `POST .../drafts/{id}/send` | drafts, send | owner cookie or staff with `platform:newsletter` |

`/api/v1/compliance/reviewer-grants` is named "owner" but it belongs to the customer's organization owner. It is not
part of the platform console.

### What was missing for analytics and management

- **Analytics:** there was no time-range view. Missing were scans per day, success and failure rates, findings by
  severity over time, paid/trialing/free counts, and suspension counts. The overview showed only 24 h and 14-day
  figures.
- **Lists:** search was the only filter. There was no sort, and no filter by plan, billing state, suspension, MFA or
  email verification. Subscriptions had no paging (a fixed `LIMIT 200`).
- **Export:** none of the lists could be exported.
- **Management:** there was no way to suspend an organization or to remove a member. The organization page did not show
  which owner actions had been taken on it.

### Security and UX issues found

| # | Issue | Where | Status |
|---|---|---|---|
| 1 | Raw server text on screen. `ActionDialog`, the "console unavailable" screen and setup errors showed `detail` verbatim. A 422 validation array became "Request failed (422)", and a 500 body would show as is. | `ownerApi.ts`, `actions.tsx`, `OwnerApp.tsx` | **Fixed.** `ownerFetch` replaces any server text that is not on a reviewed list with wording chosen by status (`ownerErrorText`). The browser check covers 500, 422 and 503 bodies. |
| 2 | Plan and trial changes had no typed confirmation. A reason was enough. | `actions.tsx`, `owner_actions.py` | **Fixed.** Every organization action now needs the exact organization name. The server checks it under the row lock and records a mismatch as `rejected`. |
| 3 | The Subscriptions filter offered `cancelled` and `expired`. The database stores `canceled`, and `expired` is not a status. Both filters always returned nothing. | `opsViews.tsx` | **Fixed.** The filter now uses the stored statuses plus `lapsed` (the billing code's effective past due). |
| 4 | Subscriptions had no paging and a fixed cap of 200 rows. | `owner_views.py` | **Fixed.** It now pages, with a cap of 100 per page. |
| 5 | A page size above 100 was refused with 422 rather than capped. | list endpoints | **Fixed.** Sizes above 100 are now capped. A size below 1, a negative offset, an unknown sort or filter, or search text over 100 characters returns 422. |
| 6 | No list could be exported, so the owner had to copy from the screen. | — | **Fixed.** Server-side CSV, capped at 10,000 rows, audited, `no-store`, with formula-safe cells. |
| 7 | Sorting happened only in the client, or not at all. | lists | **Fixed.** Sorting is server-side, from a closed set of fixed SQL expressions, with the id as tiebreaker. |
| 8 | Reads had no statement timeout, so a slow list query could hold a pooled connection. | `owner_views.py` | **Fixed** for the lists, analytics and exports. Each runs under `SET LOCAL statement_timeout = '5s'` in one read-only transaction, and a cancellation returns 503 with reviewed wording. The overview, detail, scans, logs and system views still use the old path (phase 2). |
| 9 | `btn-mini` pager and filter controls were under 44 px on phones. | `ui.tsx` | **Fixed** for the new list pieces (global `.page button` rule plus `.owner-select`). The audit runs at 390 and 320. |
| 10 | The scan detail shows `scans.error_message` and stage errors as stored. This is scan data, not an API error, but it can contain worker internals. | `opsViews.tsx` | Open: phase 2 (map to reviewed scan-failure wording). |
| 11 | The owner audit log view prints `metadata` as raw JSON. It is owner-only, but hard to read. | `opsViews.tsx` LogsView | Open: phase 2. |
| 12 | The overview's "recent customer activity" and the logs show customer emails. That is acceptable (owner console only) and is noted for completeness. | — | No change. |
| 13 | `owner_audit` has no index on `(target_type, target_id)`. The new "owner actions on this organization" panel walks `idx_owner_audit_created`. | migration | Open: phase 2 (`CREATE INDEX CONCURRENTLY`). |

## 2. Phase 1: what was added

### A. Analytics (read-only, aggregates only)

- `GET /api/v1/owner/analytics/summary?range=7|30|90` returns:
  - organizations: total, new in the range, suspended;
  - billing states: paid, trialing, free;
  - subscription status counts, including `lapsed`;
  - scans in the range by status, with the success and failure rates;
  - users: total and new in the range.

  The response defines each state.
- `GET /api/v1/owner/analytics/timeseries?range=7|30|90` returns scans per day by status and new findings per day by
  severity. Every day in the range is present, including days with zero.
- Newsletter counts come from the existing `GET /api/v1/newsletter/stats`. If the newsletter is switched off, the
  console says so.
- The range is a closed enum, so any other value returns 422. Each query is capped at 1,000 rows. Each read writes an
  `owner.view.analytics_*` audit row with `range_days`.
- The responses carry counts, days, statuses and severities only. They never carry an address, a title, an identifier
  or other customer content. Two tests check this:
  - The PostgreSQL test seeds a recognisable finding title, a domain and emails, then searches every response for them.
  - The unit test makes the queries return leaky columns and checks they never reach the response.
- The demo organization is excluded, as on the overview.

**Definitions:**

| State | Meaning |
|---|---|
| paid | Subscription is `active` and its current period has not ended. |
| trialing | Subscription is `trialing` and its current period has not ended. |
| free | Anything else: no subscription, past due, canceled, or past its period end. |
| lapsed | Subscription is `active` or `trialing` but its current period has ended. |

### B. Management lists

These existing endpoints were extended in place: `GET /organizations`, `GET /users` and `GET /subscriptions`. All
filtering and sorting is server-side (`core/owner_lists.py`).

- **Organizations**
  - Filters: search (name, slug, domain or member email), billing state, plan, suspension.
  - Sorts: name, plan, members, domains, last scan, created.
  - Rows show: name, owner email, plan, billing, status, members, domains, last scan, created.
- **Users**
  - Filters: search, second step (authenticator, email code or none), email verified.
  - Sorts: email, last sign-in, created.
  - Rows show: email, name, roles in each organization, second step, last sign-in (newest session), active sessions,
    joined.
- **Subscriptions**
  - Filters: search, effective status, plan.
  - Sorts: organization, plan, status, period end, created.
  - The 50 most recent invoices are shown under the list.
- **Paging (all three lists)**
  - Offset paging; the total comes from the same transaction.
  - Page size 25, 50 or 100 in the UI. The server caps any request above 100.
- **Exports (all three lists)**
  - `GET /api/v1/owner/exports/{organizations,users,subscriptions}.csv` uses the same filters and sort as the list.
  - Capped at 10,000 rows. One extra row is read to detect truncation, which is reported in `X-Export-Truncated`.
  - The `owner.export.<list>` audit row (filters, row count, truncated) is written before the file is returned. If that
    write fails, no file is returned.
  - Cells starting with `= + - @`, tab or CR are prefixed with `'`.
  - Email addresses appear only in the console and in these exports.

### C. Changes on the owner side

Every action below needs:

- an owner session, the console Origin, and a reason of 5 to 500 characters;
- `confirm_name`, the organization's name exactly as stored (case and spaces count).

Each action runs in one transaction with its `owner_audit` row. A refusal (wrong name, wrong state, unknown target) is
audited as `rejected`. Each action returns the new state.

| Action | Endpoint | Notes |
|---|---|---|
| Change plan | `POST /organizations/{id}/plan` | Existing action; `confirm_name` now required. |
| Extend trial | `POST /organizations/{id}/trial` | Existing action; `confirm_name` now required. |
| Suspend | `POST /organizations/{id}/suspend` | Reversible: the row is kept with `status='active'` when lifted. A second suspend returns 409. |
| Unsuspend | `POST /organizations/{id}/unsuspend` | Returns 409 if the organization is not suspended. |
| Remove member | `POST /organizations/{id}/members/{user_id}/remove` | Deletes only the membership link. The person's account and the organization's data stay. Never removes the last owner: it uses the same locked owner-row guard as the customer's own role change. Scoped by organization, so a member of another organization returns 404. The owner audit row keeps the email, role and join date so the membership can be restored. Writes `member.removed` (by "cyphward") to the customer's activity log. |

Cancel scan and sign out everywhere are not organization actions. Their dialogs use the same typed gate on the domain or the email address, checked in the console only; the server still needs a reason. No
customer data is hard-deleted.

**The suspension rule (phase 1), stated in code, migration, UI and tests:**

- Suspension is a marker that the owner sets and lifts in the console.
- It does not change what the customer's own API does. Sign-in, reads, writes, scans and billing work exactly as
  before.
- It is not written to the customer's activity log.
- Customer responses do not change. The flag lives in a side table that no customer endpoint reads.

`test_customer_api_is_unchanged_while_suspended` checks that `GET /organizations/current`, `/members`, `/domains` and
`/settings` return byte-identical JSON before and during a suspension, and that a write
(`PATCH /organizations/current`) still succeeds. Enforcement is phase 2 work.

### D. Design

- **Shared list pieces** (`frontend/src/owner/table.tsx`):
  - `OwnerTable`: the ledger table with a sticky header on screens 641 px and wider (the body scrolls inside it).
    Sortable headers are real buttons with `aria-sort` and a caption that states the sort. Below 640 px each row
    becomes a card.
  - `FilterBar`, `SelectFilter`, and `SortSelect` (the way to sort on phones, where the header is hidden).
  - `PagerBar`, `ExportButton`, `KpiStrip` (the existing `Stat` tile) and `RangeSelector` (buttons with
    `aria-pressed`).
  - `ListState`: loading, empty and error from the shared `StatePanels`.
- **Typed-name gate:** added to the shared `components/ConfirmDialog.tsx`. It is a `typedName` option on
  `useConfirm()`, and is also exported as `TypedNameGate` / `typedNameMatches`.
  - The owner `ActionDialog` collects a reason (and a plan or a number of days), so it uses the shared `Dialog` with the
    shared `TypedNameGate` rather than `useConfirm()`.
  - The confirm button stays disabled until the reason is written and the name matches exactly.
  - Existing customer callers of `useConfirm()` are unaffected; the option is additive.
- **New screen:** Analytics (`/analytics`, in the sidebar and the phone menu).
- **Organization page:**
  - a suspension note;
  - Suspend / Unsuspend buttons;
  - a Remove button on each member (not shown for the last owner);
  - an "Owner actions on this organization" panel.
- **Brand:** no new visual language. The new screens use the existing tokens, ledger, `btn-mini`, `Stat`, `Pill`,
  StatePanels and Dialog.

## 3. Query plans (local PostgreSQL 18, synthetic volume)

The synthetic volume was 500 organizations, 50,000 scans and 50,000 findings. It was analysed, measured, then removed.

| Query | Plan | Time |
|---|---|---|
| scans per day (30 d) | Bitmap Index Scan on `idx_scans_status_created`, condition on status list and `created_at` | 13.6 ms |
| findings per day (30 d) | Bitmap Index Scan on `idx_findings_severity`, then a `created_at` filter (35,500 rows removed) | 19.4 ms |
| organizations sorted by members, 100 rows | Seq Scan on organizations, per-row counts through `idx_*_org` indexes | 22.4 ms |

There is no `findings(created_at)` or `organizations(created_at)` index, so those queries read more rows than they
return. The 5 s statement timeout bounds them. The phase 1 migration is limited to suspension, so the indexes are listed
for phase 2 (to be built `CONCURRENTLY`).

## 4. Migration

`supabase/migrations/20261030100000_organization_suspension.sql`

- Starts with `BEGIN; SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '60s';`.
- Creates `organization_suspensions (org_id PK → organizations ON DELETE CASCADE, status 'suspended'|'active',
  changed_at, changed_by, first_suspended_at)` and a partial index on suspended rows.
- RLS is on with the app role's policy only.
- Grants: `SELECT, INSERT` plus `UPDATE (status, changed_at, changed_by)` to `cyphward_app`. There is no DELETE, and
  `anon` and `authenticated` are revoked.
- Additive and idempotent. It was applied twice to the local test database without error. Existing tables, their RLS
  and their grants are unchanged.
- **Why a side table and not a column:** `api/settings.py` and `api/organizations.py` return `RETURNING *`, and
  `core/auth.py` selects `o.*`. A new column on `organizations` would appear in the customer's own API responses.
- sha256: `39e9c6f5bdb606af7df2c708288d04b359be80f0f917e4a4c368e1d296ab2c1e`

## 5. Phase 2

1. **Enforce suspension**, once the rule is agreed. For example: refuse new scans and writes with a reviewed message,
   pause scheduled scans, show a banner in the customer app, and add it to the customer activity log.
2. **Indexes, built `CONCURRENTLY`** in their own migration:
   - `findings(created_at)`
   - `organizations(created_at)`
   - `owner_audit(target_type, target_id, created_at)`
   - `auth_sessions(user_id, created_at)`
3. **Restore a removed member** from the owner audit row (role and join date). Also add role changes from the console.
4. **Move the remaining views onto the bounded-read helper:** overview, detail views, scans, logs and system (5 s
   timeout, read-only transaction). Give scans and logs the same table, sort and export.
5. **Reviewed wording for scan failures** in the scan detail, instead of the stored worker error. Readable owner audit
   metadata in Logs.
6. **Cursor (keyset) paging** for scans and logs, which grow fastest. An offset scan becomes slow past about 100k rows.
7. **Analytics:**
   - revenue from invoices, by month and currency (as records, not cash);
   - sign-up to first scan conversion;
   - scan duration percentiles;
   - CSV of each chart.
8. **Owner session hygiene:** list and revoke the owner's own console sessions, and alert on repeated owner sign-in
   failures.
