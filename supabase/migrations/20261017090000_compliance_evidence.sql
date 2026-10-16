-- Compliance readiness evidence (packet C1). See backend/app/compliance/.
--
--   compliance_evidence  append-only evidence rows per (organization,
--                        requirement, domain). Tool rows are written only in
--                        the fenced scan-completion transaction. The current
--                        state is the latest row; history is never edited.
--                        Status is derived on read and is evidence, never a
--                        legal verdict.
--
-- Additive. Apply before the API that writes it. Until then the completion
-- transaction's evidence savepoint fails and rolls back alone: scans still
-- complete, and the Compliance page reads every requirement as not assessed.
BEGIN;

CREATE TABLE IF NOT EXISTS compliance_evidence (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id        uuid REFERENCES domains(id) ON DELETE CASCADE,
  requirement_key  text NOT NULL,
  register_version text NOT NULL,
  source           text NOT NULL CHECK (source IN ('tool_observed', 'externally_observed',
                                                   'customer_attested', 'practitioner_reviewed')),
  status           text NOT NULL CHECK (status IN ('present', 'gap', 'not_assessed', 'not_applicable')),
  observed_at      timestamptz NOT NULL,
  expires_at       timestamptz,
  scan_id          uuid REFERENCES scans(id) ON DELETE SET NULL,
  finding_ids      uuid[] NOT NULL DEFAULT '{}',
  details          jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by       uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_evidence_latest
  ON compliance_evidence (org_id, requirement_key, domain_id, observed_at DESC);
-- One row per requirement per scan, so a replayed completion cannot duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_evidence_scan
  ON compliance_evidence (scan_id, requirement_key) WHERE scan_id IS NOT NULL;

ALTER TABLE compliance_evidence ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_evidence;
CREATE POLICY cyphward_app_all ON compliance_evidence FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; append-only.
REVOKE ALL ON compliance_evidence FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_evidence TO cyphward_app;

COMMIT;
