-- Cookie-consent browser observation jobs (packet C2b). See backend/app/core/browser_jobs.py.
--
--   privacy_browser_jobs  the queue the separate browser worker claims over outbound HTTPS. It is a
--                         different table from `scans` on purpose: the scanner worker's claim query
--                         reads `scans` only, so it can never receive one of these jobs, and the
--                         browser worker's claim reads this table only.
--
-- Additive and idempotent. Apply before the API that uses it. The feature flag (BROWSER_CONSENT_ENABLED)
-- defaults to off, so applying this changes nothing for customers until it is switched on.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS privacy_browser_jobs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id        uuid NOT NULL,
  scan_id          uuid UNIQUE REFERENCES scans(id) ON DELETE SET NULL,
  job_type         text NOT NULL DEFAULT 'cookie_consent_observation' CHECK (job_type = 'cookie_consent_observation'),
  status           text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'failed')),
  attempts         integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 10),
  claimed_by       text CHECK (claimed_by IS NULL OR char_length(claimed_by) BETWEEN 1 AND 64),
  claim_generation integer NOT NULL DEFAULT 0 CHECK (claim_generation >= 0),
  claim_token      text CHECK (claim_token IS NULL OR claim_token ~ '^[A-Za-z0-9_-]{32,128}$'),
  lease_expires_at timestamptz,
  requested_at     timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  completed_at     timestamptz,
  error_message    text CHECK (error_message IS NULL OR char_length(error_message) <= 600),
  result           jsonb CHECK (result IS NULL OR (jsonb_typeof(result) = 'object' AND pg_column_size(result) <= 65536)),
  -- A job can never point at another organisation's domain.
  FOREIGN KEY (org_id, domain_id) REFERENCES domains (org_id, id) ON DELETE CASCADE,
  -- A running job always carries its lease and token.
  CHECK (status <> 'running' OR (claimed_by IS NOT NULL AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL))
);

-- One queued or running job per domain.
CREATE UNIQUE INDEX IF NOT EXISTS privacy_browser_jobs_one_active_per_domain
  ON privacy_browser_jobs (org_id, domain_id) WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_privacy_browser_jobs_queue
  ON privacy_browser_jobs (requested_at, id) WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_privacy_browser_jobs_domain_recent
  ON privacy_browser_jobs (org_id, domain_id, requested_at DESC);

ALTER TABLE privacy_browser_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON privacy_browser_jobs;
CREATE POLICY cyphward_app_all ON privacy_browser_jobs FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Convention: REVOKE ALL, then only what is needed. Supabase's default privileges give PUBLIC-like API roles
-- (anon, authenticated) ALL on new tables, TRUNCATE included, which row-level security does not stop.
-- service_role is left alone on purpose (Supabase's admin credential, never given to the API; same on every table).
REVOKE ALL ON privacy_browser_jobs FROM PUBLIC;

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON privacy_browser_jobs FROM %I', r);
    END IF;
  END LOOP;
END $$;

-- The app role never deletes: rows leave only with their organisation or domain (cascade).
REVOKE ALL ON privacy_browser_jobs FROM cyphward_app;
GRANT SELECT, INSERT, UPDATE ON privacy_browser_jobs TO cyphward_app;

COMMIT;
