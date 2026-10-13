-- Scan admission coordination and retry identity. This migration intentionally
-- refuses ambiguous active duplicates; operators must resolve them using the
-- database-upgrade runbook before retrying the migration.
DO $$
DECLARE duplicate_count bigint;
BEGIN
  SELECT count(*) INTO duplicate_count
  FROM (
    SELECT org_id, domain_id
    FROM scans
    WHERE status IN ('queued', 'running') AND domain_id IS NOT NULL
    GROUP BY org_id, domain_id
    HAVING count(*) > 1
  ) duplicates;
  IF duplicate_count > 0 THEN
    RAISE EXCEPTION 'Cannot create scan admission index: % organisation/domain pairs have multiple active scans. Review and resolve these rows before retrying this migration.', duplicate_count;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS scans_one_active_per_org_domain
  ON scans (org_id, domain_id)
  WHERE status IN ('queued', 'running') AND domain_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS scan_launch_requests (
  org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  request_scope text NOT NULL,
  request_key text NOT NULL CHECK (length(request_key) BETWEEN 1 AND 128),
  requested_domain_id uuid,
  domain_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  scan_id uuid NOT NULL UNIQUE REFERENCES scans(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (org_id, request_scope, request_key)
);

CREATE INDEX IF NOT EXISTS scan_launch_requests_expiry
  ON scan_launch_requests (org_id, expires_at);

ALTER TABLE scan_launch_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON scan_launch_requests;
CREATE POLICY cyphward_app_all ON scan_launch_requests FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON scan_launch_requests TO cyphward_app;
