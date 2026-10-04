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
