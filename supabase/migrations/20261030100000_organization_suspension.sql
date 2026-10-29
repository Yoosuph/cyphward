-- Owner console phase 1: a reversible suspension status per organization (docs/admin-2026-10-29/AUDIT.md).
--
--   organization_suspensions   one row per organization the owner has ever suspended. status is 'suspended' or
--                              'active' (lifted); no row means active. Suspend and unsuspend only flip status and
--                              record when and by which owner. Nothing is deleted, and the history of who did what
--                              and why lives in owner_audit.
--
-- Why a side table and not a column on organizations: several customer endpoints return the whole organization
-- row (RETURNING * in api/settings.py and api/organizations.py, SELECT o.* in core/auth.py). A new column there
-- would appear in the customer's own API responses. This table is read only by the owner console.
--
-- The phase 1 rule: suspension is a marker the owner sets and lifts. It does not change what the customer's own
-- API does. Sign-in, reads, scans and billing work exactly as before. Enforcement is phase 2 work.
--
-- Additive and idempotent. Existing tables, their RLS and their grants are unchanged. The new table has RLS on with
-- the app role's policy only, and the app role gets SELECT, INSERT and UPDATE of the status columns (no DELETE).
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS organization_suspensions (
  org_id            uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
  status            text NOT NULL DEFAULT 'suspended' CHECK (status IN ('suspended', 'active')),
  changed_at        timestamptz NOT NULL DEFAULT now(),
  changed_by        uuid,
  first_suspended_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_organization_suspensions_suspended
  ON organization_suspensions (org_id) WHERE status = 'suspended';

ALTER TABLE organization_suspensions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON organization_suspensions;
CREATE POLICY cyphward_app_all ON organization_suspensions FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them to what the owner console needs.
REVOKE ALL ON organization_suspensions FROM PUBLIC;
REVOKE ALL ON organization_suspensions FROM cyphward_app;
GRANT SELECT, INSERT ON organization_suspensions TO cyphward_app;
GRANT UPDATE (status, changed_at, changed_by) ON organization_suspensions TO cyphward_app;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE 'REVOKE ALL ON organization_suspensions FROM anon';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    EXECUTE 'REVOKE ALL ON organization_suspensions FROM authenticated';
  END IF;
END $$;

COMMIT;
