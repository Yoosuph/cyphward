-- Least-privileged application role (review P1 — isolation boundary).
--
-- The application currently connects as `postgres`, which has BYPASSRLS —
-- every "no-policy" RLS posture on the tenant tables is bypassed for the
-- server path, so row-level protection is never exercised by the app's own
-- connection. This migration provisions `cyphward_app`: a normal LOGIN role
-- (no superuser, no bypassrls, no createrole) with permissive policies so
-- existing queries behave identically, while RLS now genuinely applies to
-- the application role — any future restrictive policy is enforced instead
-- of silently bypassed.
--
-- Cutover (no password lives in this repo — it is a secret):
--   1. ALTER ROLE cyphward_app WITH PASSWORD '<strong password>';   (DBA)
--   2. set DATABASE_URL to that role's connection string (Render env)
--   3. restart the service; verify with backend/tests/test_rls_integration.py
--      (CYPHWARD_RLS_INTEGRATION=1).
--
-- anon / authenticated keep their existing grants: the no-policy RLS on
-- each table still denies them every row (Data API path stays locked down).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cyphward_app') THEN
    CREATE ROLE cyphward_app LOGIN;
  END IF;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO cyphward_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cyphward_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cyphward_app;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cyphward_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO cyphward_app;

-- Permissive policies: identical behavior for the app, but RLS is no
-- longer bypassed — enforcement is real for this role from now on.
DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT c.relname FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS cyphward_app_all ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY cyphward_app_all ON %I FOR ALL TO cyphward_app '
      'USING (true) WITH CHECK (true)', tbl);
  END LOOP;
END $$;
