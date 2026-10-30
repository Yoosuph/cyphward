-- Admin phase 2: indexes for the owner console analytics and lists (docs/admin-phase2-2026-10-31/README.md).
--
-- Each index serves a query that filters or sorts on these columns today:
--   organizations (created_at)                    analytics summary (new in range), organizations list default sort
--   profiles (created_at)                         overview and analytics user counts, users list default sort
--   organization_members (org_id, role)           every per-organisation member lookup and count: the lists'
--                                                 member counts and owner email, organization detail, customer
--                                                 members page (only (user_id, org_id) existed)
--   owner_audit (target_type, target_id, created_at DESC)
--                                                 "owner actions on this organization", removed members and the
--                                                 restore-member lookup
--   auth_sessions (user_id, created_at DESC)      users list last sign-in, user detail sessions
--   findings (created_at)                         analytics new findings per day
--   audit_log (created_at DESC)                   owner logs and overview recent activity (all organisations)
--   audit_log (user_id, created_at DESC)          user detail activity
--   scans (created_at DESC)                       owner scans list, overview scans in 24 h
--   scans (org_id, created_at DESC)               last scan per organisation (organizations list), organization
--                                                 detail recent scans, the customer's scans list
--
-- Plain CREATE INDEX, not CONCURRENTLY: every migration runs inside a transaction (the test bootstrap and the
-- release tool both execute the file as one transaction), and CREATE INDEX CONCURRENTLY cannot run inside one.
-- A plain build takes a SHARE lock: reads continue, writes to that table wait until COMMIT. The locks are held to
-- the end of the file, so the busiest tables (findings, audit_log, scans) come last. lock_timeout stops the file
-- from queueing behind a long transaction; statement_timeout bounds each build; either one rolls the whole file
-- back with nothing changed. Check table sizes and the build time on a copy before release.
--
-- Additive and idempotent (IF NOT EXISTS). No table, column, grant or policy changes.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE INDEX IF NOT EXISTS idx_organizations_created ON organizations (created_at);
CREATE INDEX IF NOT EXISTS idx_profiles_created ON profiles (created_at);
CREATE INDEX IF NOT EXISTS idx_organization_members_org ON organization_members (org_id, role);
CREATE INDEX IF NOT EXISTS idx_owner_audit_target ON owner_audit (target_type, target_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_created ON auth_sessions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_created ON findings (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_created ON audit_log (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scans_created ON scans (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scans_org_created ON scans (org_id, created_at DESC);

COMMIT;
