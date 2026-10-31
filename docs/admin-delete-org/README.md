# Delete an organisation from the owner console

Deleting is done in two separate owner actions. A third action undoes the first.

1. **Delete (soft delete).** The organisation is marked `deleted`. Nothing is removed, and it can be restored for 30 days.
2. **Restore.** This undoes a soft delete inside the 30-day window.
3. **Purge.** This is only possible after the window. It permanently removes the organisation's data. It is refused while any compliance record is still inside its retention period, or while any breach incident was opened in the last 6 years.

There is no automatic purge job. Every purge is an explicit owner action, run by following the runbook below.

Code:
- `backend/app/api/owner_actions.py`: the actions.
- `backend/app/core/org_guard.py`: the guardrails.
- `backend/app/core/suspension.py` and `backend/app/core/auth.py`: what customers see.
- `supabase/migrations/20261101100000_org_delete.sql`: the schema.
- `frontend/src/owner/actions.tsx` and `frontend/src/owner/peopleViews.tsx`: the console.

## States

The status lives in `organization_suspensions`, the same side table as the suspension. It is a side table, not a column on `organizations`, because several customer endpoints return the whole organisation row.

| status | customers | scans | owner console |
| --- | --- | --- | --- |
| `active` (or no row) | normal | normal | normal |
| `suspended` | sign in and read; writes refused with 403 `organization_suspended` | new, scheduled and queued scans paused | all actions |
| `deleted` | the organisation is gone for them (see below) | queued scans cancelled at the delete; a running scan finishes, emails nobody, and is never reclaimed; scheduled scans skip it | hidden from the lists unless the Deleted filter asks; its page opens; only restore or purge |

What a deleted organisation means for customers:

- **Sign-in.** It is left out of every membership query (`core/auth.py`), so the bootstrap and the organisation list no longer show it and it cannot be selected.
- **Its routes.** Every route that resolves it answers **404 "Organization not found."**, whether it is named by id or slug, or is the person's only organisation. This covers reads and writes: the 404 comes before the suspension gate.
- **Invitations.** Accepting an invitation to it also answers 404 (`suspension.ensure_active`).
- **Reviewers.** Outside reviewers lose access (`compliance/reviewer.ACTIVE_SQL`).
- **Reminders.** Compliance reminders and the six-monthly DPO reminder skip it.
- **New organisations.** Its owners cannot create a new organisation. The refusal is a 403 with its own plain message, not the suspension code, so the suspension banner is never shown for it.

## Routes (all new write routes)

| route | gate | typed confirmation | refusals (409 unless noted, each audited as `rejected`) |
| --- | --- | --- | --- |
| `POST /api/v1/owner/organizations/{org_id}/delete` | `require_owner_mutation` (owner console cookie session + exact console Origin; a bearer token is refused) | `confirm_name` = the exact name | wrong name; already deleted; protected organisation; active paid subscription |
| `POST /api/v1/owner/organizations/{org_id}/restore` | `require_owner_mutation` | `confirm_name` | wrong name; not deleted; restore window passed |
| `POST /api/v1/owner/organizations/{org_id}/purge` | `require_owner_mutation` | `confirm_name` and `confirm_word` = `DELETE` (exact, capitals) | wrong name; wrong word; not deleted; protected organisation; window not passed; records retained or a breach incident opened in the last 6 years (`detail.code = retention_hold` with counts only) |

All three also need a written `reason` (5 to 500 characters), which is kept in the owner log only.

All three routes are on the reviewed owner list in `backend/tests/test_suspension_gate.py` (`_OWNER`). `backend/tests/test_owner_phase1.py` checks that every owner action route depends on `require_owner_mutation`, and `backend/tests/test_admin_delete_org.py` checks the three new routes specifically.

Every other organisation action refuses a deleted organisation until it is restored: plan, trial, suspend, unsuspend, remove member and restore member. They answer "This organization has been deleted. Restore it before making any other change."

## Audit

Every step writes an `owner_audit` row. Outcomes are `success` or `rejected` (refusals too, with the reviewed reason). A success row is written in the same transaction as the change.

| action | metadata |
| --- | --- |
| `owner.action.delete_org` | `from` (the status before), `to`, `deleted_at`, `restore_until`, the ids of the cancelled queued scans, the subscription status and its `cancel_at_period_end`, `protected_override` |
| `owner.action.restore_org` | `from`, `to`, `deleted_at`, whether the earlier status was read from the delete row |
| `owner.action.purge_org` | the name, `deleted_at`, counts of what was removed (members, domains, scans, findings, evidence files), whether files were queued, the retention months, `protected_override` |

`owner_audit` has no foreign keys, so the purge record outlives the organisation.

Restore returns the organisation to the status recorded in its delete row, so a suspended organisation comes back suspended. If that row cannot be read, it comes back suspended, and the owner can then lift the suspension deliberately.

## Guardrails (`backend/app/core/org_guard.py`)

### Protected organisations

These are refused for both soft delete and purge:

- the sample-data demo organisation, `DEMO_ORG_ID`;
- the public demo workspace, `DEMO_LOGIN_ORG_ID` (in production this is the InnovaTech workspace);
- the INNOVATECH organisation, **`5e3fe575-caea-4ea9-acab-353e72487d36`**, built in (`INNOVATECH_ORG_ID_BUILTIN`), plus any id in `INNOVATECH_ORG_ID`, which can add an id but cannot remove the built-in one;
- any organisation whose name contains "innovatech" (letters only, any case, so "Innova-Tech" counts too).

The override is **`OWNER_ALLOW_PROTECTED_ORG_DELETE=true`**. It is off by default, read on every request, and any other value means off. The audit row records that the override was used.

The built-in id was supplied with the founder's decisions of 2026-10-31. This PR did not read production, so it has not been compared with the production row here. Because the id is built in, no environment change is needed for the protection.

### Paid subscription

Soft delete is refused while all of these hold:

- the subscription is `active`;
- its current period has not ended;
- it is not set to cancel at the period end.

The customer's owner cancels it from Settings, which is allowed while suspended (founder rule, phase 2). The soft delete is then allowed. A trial, a lapsed period, or a cancelled or past-due subscription does not block. The console has no subscription-cancel action of its own.

### Window

Restore is allowed while `deleted_at + 30 days > now()`. Purge is allowed once `deleted_at + 30 days <= now()`. Both use the database clock, and the organisation page shows the same dates.

### Retention

The purge is refused while any of these is still inside the organisation's retention period (`organizations.evidence_retention_months`, 12 to 120, default 36):

| record | measured from |
| --- | --- |
| reviewer grant | the latest of granted, revoked (or the expiry if never revoked), and the grant's latest practitioner review or clause verification |
| evidence pack | `issued_at` (the "retain until" packs already show) |
| assessment snapshot | `created_at` (the "retain until" snapshots already show) |
| compliance document | the latest of `generated_at` and the document's latest approval |
| evidence file | the latest of `uploaded_at` and `removed_at`; files already removed count too |
| breach incident | a fixed **6 years** (not the organisation's setting) from when it was opened: the latest of `detected_at`, `became_aware_at` and `created_at` |

Attestations (questionnaire answers) are not held back. They are removed with the organisation.

A record is retained while its date plus the period is after `now()`. This uses the same calendar month arithmetic as `snapshots.store.add_months`, and the purge sets the session time zone to UTC first. `test_the_retention_period_in_sql_matches_add_months` checks the month-end cases.

**Founder decisions (2026-10-31):**
- Snapshots and packs keep their existing rule.
- Reviewer grants, compliance documents and evidence files are measured from the record's last event date, as listed above.
- Breach incidents hold the purge for 6 years from when they were opened.
- Attestations are removed with the organisation.
- The `GRANT UPDATE (deleted_at, deleted_by)` added by the migration is approved.

The rules live in `RETENTION_SQL` in `org_guard.py`.

The refusal returns counts only (`reviewer_grants`, `packs`, `snapshots`, `documents`, `evidence_files`, `incidents`, plus `retention_months` and `incident_retention_years`), never record contents. The console words them itself.

## Purge: what it does

One transaction, run with `SET LOCAL lock_timeout = '5s'`, `statement_timeout = '60s'` and `TimeZone = 'UTC'`:

1. Lock the organisation, its subscription and its status rows. This is the same lock order as the other owner actions.
2. Check the name, the word, the status, the protection, the window, the retention and the 6-year incident period.
3. Count what will go, for the audit row.
4. Queue the organisation in `compliance_evidence_purge_queue`, using the same statement as the customer's own closing (`evidence_file_store.QUEUE_PURGE_SQL`), on the same transaction. The queue entry therefore commits only together with the deletion.
5. `DELETE FROM organizations WHERE id = ...`. Members, domains, assets, scans, findings, reports, invitations, activity, subscriptions, invoices and every compliance table cascade. People keep their own accounts.
6. Write the owner audit row and commit.

Any failure, including a timeout, rolls everything back: nothing is removed and nothing is queued.

**Stored evidence files are not deleted inline.** They stay in storage until the reconcile script processes the queue. It deletes the `org/<org_id>/` prefix only for organisations that no longer exist.

## Runbook: purging an organisation

The purge is irreversible. Follow `release-procedure` practice: one step at a time, with a backup first, and stop and ask the founder if anything differs from this runbook.

1. **Confirm the request.** Have it in writing from the founder: which organisation, and why. Check that the 30-day window has passed. The organisation page shows "The restore window ended ..." in its danger zone.
2. **Check the subscription and invoices.** On the organisation page, the subscription should be cancelled or lapsed, with no unpaid invoice that still has to be collected. Invoices are removed with the organisation; export them first (owner console, Subscriptions, CSV) if they are needed for the books.
3. **Back up the database.** Take an encrypted `pg_dump -Fc` as for a release migration, verify its sha256, and record where it is stored. The purge cannot be undone from the console; this backup is the only way back.
4. **Run the purge from the console.** Organisation page, Danger zone, Purge data. Write the reason, type the exact name, and type `DELETE`.
   - **If it is refused because records are retained:** stop. The counts show what is held and for how long the period runs. Do not lower the organisation's retention setting to get past this without the founder's written decision, because the retained records may have legal relevance. Try again once the period has passed.
   - **If it is refused for another reason:** fix that reason first (for example, the window has not passed). Do not use the override flag unless the founder has asked for that specific organisation in writing.
5. **Delete the stored files.** First run the read-only report, then the delete run with the API service's storage credentials:
   ```
   python backend/scripts/reconcile_evidence_files.py
   python backend/scripts/reconcile_evidence_files.py --delete --yes-delete
   ```
   In the output, the `purge_queue` counts should show `purged` of at least 1 and `failed` of 0. A failed entry stays queued; run the command again later.
6. **Verify.**
   - The organisation no longer opens in the console; it answers "That record was not found".
   - `owner_audit` has an `owner.action.purge_org` success row with the removed counts.
   - The purge queue has no entry for the organisation.
7. **Record it.** Note the backup location, the audit row id and the reconcile output in the release notes for the day.

**Rollback.** Before step 4 nothing has changed. After step 4 the only way back is to restore from the step 3 backup, which is a database-wide operation that needs the founder's decision. After step 5 the stored files are also gone; they are not in the database backup.

## Migration `20261101100000_org_delete.sql`

sha256 `78e81efb82cc6336b44efdee184b5d901d5ae25b7d129567c38011ad869867ac`

What it does:

- Adds `deleted_at timestamptz` and `deleted_by uuid` to `organization_suspensions`. Both are nullable with no default, so this is a catalogue change only and does not rewrite the table.
- Replaces the status CHECK with `status IN ('suspended', 'active', 'deleted')`. The old CHECK is found by its definition, not by its name.
- Adds a consistency CHECK: a `deleted` row has `deleted_at`; any other status has neither `deleted_at` nor `deleted_by`.
- Adds the partial index `idx_organization_suspensions_deleted (deleted_at) WHERE status = 'deleted'`.
- Runs inside BEGIN and COMMIT with `lock_timeout = '5s'` and `statement_timeout = '60s'`. It is idempotent: applied twice, the result is the same.

**RLS, policies and table-level grants are unchanged.** One addition: the app role already had UPDATE on `(status, changed_at, changed_by)` only, and now also gets **UPDATE on `(deleted_at, deleted_by)`**. Soft delete has to set these columns and restore has to clear them, and a new column is not covered by the existing column grants. There is still no DELETE grant: the row goes only through the organisation's ON DELETE CASCADE at purge. `test_migration_adds_columns_check_index_and_only_the_two_column_grants` applies the suspension migration and this one twice on a Supabase-style database, where new tables grant everything to PUBLIC, anon and authenticated, and asserts exactly these grants.

Apply it before merging, with the usual migration tool (lock and statement timeouts as above). The table has one row per organisation that has ever been suspended, so the CHECK validation and the index build are immediate.

## Not in this PR

- There is no automatic purge job.
- There is no console action to cancel a customer's subscription.
- Queued privacy-browser jobs of a deleted organisation are not cancelled. Like a suspended organisation's, they are skipped by the browser-worker claim, and they go with the organisation at purge.
- Soft-deleting an organisation that was never suspended creates its status row. That row's `first_suspended_at` is then the delete time, because the column is NOT NULL with a default.
- A person who is the sole owner of a deleted organisation is still asked to "transfer ownership or close" it before deleting their own account. Their account stays until the organisation is purged, or until it is restored and closed.
- The owner overview counts, analytics and logs still include deleted organisations. They are counts and audit records, not lists of organisations.
