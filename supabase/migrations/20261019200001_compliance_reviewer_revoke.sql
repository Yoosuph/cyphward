-- Reviewer access (packet C6), follow-up to 20261019200000: take Supabase's default privileges for the API roles
-- (anon, authenticated) away from the three reviewer tables, and re-assert the app role's minimal grants.
-- RLS already denies those roles every row; the convention is REVOKE ALL, then only what is needed.
--
-- Additive and idempotent. 20261019200000 has been applied already and is not edited.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON compliance_reviewer_grants FROM %I', r);
      EXECUTE format('REVOKE ALL ON compliance_practitioner_reviews FROM %I', r);
      EXECUTE format('REVOKE ALL ON compliance_clause_verifications FROM %I', r);
    END IF;
  END LOOP;
END $$;

REVOKE ALL ON compliance_reviewer_grants FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_reviewer_grants TO cyphward_app;
GRANT UPDATE (revoked_at, revoked_by) ON compliance_reviewer_grants TO cyphward_app;

REVOKE ALL ON compliance_practitioner_reviews FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_practitioner_reviews TO cyphward_app;

REVOKE ALL ON compliance_clause_verifications FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_clause_verifications TO cyphward_app;

COMMIT;
