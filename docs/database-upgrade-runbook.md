# Database upgrade runbook (review P2 — migrations)

One migration in this repo is **destructive by design** and needs a
backup + data decision before it touches any database that already holds
customer data.

## The destructive migration

`supabase/migrations/20260922120000_mvp_spec_alignment.sql` drops the
legacy compliance/Academy-era tables with `CASCADE` before aligning the
MVP schema:

- `threat_ticker`, `copilot_knowledge`, `academy_meta`, `academy_courses`
- `detection_layers`, `alerts`, `policy_drafts`, `remediations`
- `controls`, `frameworks`, `postures`, `scores`
- `profiles` (legacy shape — a new `profiles` table is created by later migrations)
- `tenants`
- plus legacy functions (`DROP FUNCTION ... CASCADE`)

Fresh databases are unaffected: there is no legacy data to lose. Any
database created from the pre-alignment schema (or with rows in those
tables) permanently loses that data when this migration applies.

## Pre-flight: does this database have legacy data?

```sql
SELECT 'threat_ticker' AS t, count(*) FROM threat_ticker
UNION ALL SELECT 'academy_courses', count(*) FROM academy_courses
UNION ALL SELECT 'frameworks', count(*) FROM frameworks
UNION ALL SELECT 'controls', count(*) FROM controls
UNION ALL SELECT 'tenants', count(*) FROM tenants;
```

If every count is 0 (or the tables don't exist), skip to "Apply".
Otherwise make the export-or-transform decision below first.

## 1. Take a restorable backup

- Supabase dashboard → Database → Backups: confirm a recent automatic
  backup exists and note its timestamp, **or**
- Logical dump (works through the pooler; custom roles need the
  `<role>.<project-ref>` username form):

```bash
pg_dump "postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres" \
  -Fc -f cyphward-pre-upgrade.dump
```

Verify the dump restores (into a scratch project, never over production):

```bash
pg_restore -d "<scratch-connection-string>" cyphward-pre-upgrade.dump
```

Do not proceed until the restore succeeds.

## 2. Decide: export or transform legacy data

| Data | Suggested handling |
|---|---|
| Academy courses/content (`academy_courses`, `academy_meta`) | `COPY (SELECT ...) TO 'academy_courses.csv' CSV HEADER` — keep for the future Academy track |
| Frameworks/controls/policy drafts (`frameworks`, `controls`, `policy_drafts`, `postures`) | Export CSV; map to the future compliance workspace when it ships (line 35) |
| Scores, alerts, remediations, tickers, copilot knowledge | Export if any customer ever saw them, otherwise drop |
| Legacy `profiles` / `tenants` | These predate the own-auth identity model and are superseded — export, then drop |

Record the decision (what was kept, where the export lives) in the
release notes for the upgrade.

## 3. Apply (in order, as in README)

```bash
supabase db push
# or apply supabase/migrations/*.sql manually in filename order
```

## 4. Verify

- `organizations`, `organization_members`, `domains`, `scans`,
  `findings`, `assets`, `reports` row counts match pre-upgrade.
- Application health: `GET /health` → `database: connected`; log in,
  list members and scans.
- The destructive tables are gone: the pre-flight query errors with
  "relation does not exist" (expected).

## Scan-admission migration pre-flight

Migration `20261013090000_scan_admission.sql` adds retry mappings and a unique
guard for active scans. Before applying it to an existing database, inspect
active duplicates:

```sql
SELECT org_id, domain_id, array_agg(id ORDER BY created_at, id) AS scan_ids,
       count(*) AS active_count
FROM scans
WHERE status IN ('queued', 'running') AND domain_id IS NOT NULL
GROUP BY org_id, domain_id
HAVING count(*) > 1;
```

The migration intentionally stops if any rows are returned. Review each row
against worker ownership and customer history, then decide whether to let a job
finish, safely cancel a duplicate, or repair a stale status. Record the chosen
scan IDs and reason before applying any data change. Do not bulk-delete scans
or observations to make the unique index succeed. Re-run the query and confirm
it returns no rows before retrying the additive migration. Apply first in a
disposable database, then follow the normal backup and release process.

For an existing, current installation, apply this **new additive migration only**
in a transaction; do not replay the historical destructive migrations or seeds.
Set bounded lock and statement timeouts, and abort if the migration preflight
raises. Verify the index is valid, the retry table has RLS and application-role
grants, and existing application row counts are unchanged. Record the version in
`supabase_migrations.schema_migrations` when using the manual SQL path. Deploy
the API before requiring the new frontend retry behavior. For an application
rollback, retain the additive schema and request mappings; rolling back the code
does not require deleting customer retry/history records.
