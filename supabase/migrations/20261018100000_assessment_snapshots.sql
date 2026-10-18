-- Immutable assessment snapshots and report integrity (Packet 04). See backend/app/snapshots/.
--
--   assessment_snapshots  one frozen, organisation-scoped record of an assessment: scope, dates,
--                         coverage, findings, provenance, scoring model and the compliance state
--                         (register version, evidence rows, current attestations, readiness counts).
--                         `content` is canonical JSON; `content_sha256` is the hash of that
--                         canonical text. Append-only: the app role can SELECT and INSERT, never
--                         UPDATE or DELETE, and a guard trigger refuses any change except the
--                         profile-deletion action clearing created_by.
--   reports.snapshot_id   a report generated from a snapshot points at it. A report without one
--                         is a legacy report (built from live data); it is labelled, never backfilled.
--
-- Deletion: snapshots belong to the organisation. Deleting the organisation cascades to its
-- snapshots and reports (the app role has no DELETE, but the cascade runs as the table owner).
-- Deleting a domain keeps the snapshot: it holds domain names as text, not a foreign key.
--
-- Additive. Apply before the API that writes it.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- Retention period for issued snapshots and packs, in months (default 3 years). It is a recorded policy:
-- the app role cannot delete, so removal after the period is an operator-run step, never automatic.
ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS evidence_retention_months integer NOT NULL DEFAULT 36
    CHECK (evidence_retention_months BETWEEN 12 AND 120);

CREATE TABLE IF NOT EXISTS assessment_snapshots (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  seq             integer NOT NULL CHECK (seq >= 1),
  schema_version  integer NOT NULL CHECK (schema_version >= 1),
  scope           text NOT NULL DEFAULT 'organization' CHECK (scope = 'organization'),
  content         jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
  content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  request_key     text CHECK (request_key IS NULL OR char_length(request_key) BETWEEN 8 AND 80),
  created_by      uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT assessment_snapshots_org_id_key UNIQUE (org_id, id),
  CONSTRAINT assessment_snapshots_org_seq_key UNIQUE (org_id, seq)
);

-- One snapshot per request: a retried request with the same key finds the first one.
CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_snapshots_request
  ON assessment_snapshots (org_id, request_key) WHERE request_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_assessment_snapshots_org
  ON assessment_snapshots (org_id, created_at DESC);

-- Nothing about a snapshot changes. The one exception is the profile-deletion action
-- (ON DELETE SET NULL) clearing created_by.
CREATE OR REPLACE FUNCTION assessment_snapshots_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.created_by IS DISTINCT FROM OLD.created_by AND NEW.created_by IS NOT NULL)
     OR NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.seq IS DISTINCT FROM OLD.seq OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
     OR NEW.scope IS DISTINCT FROM OLD.scope OR NEW.content IS DISTINCT FROM OLD.content
     OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
     OR NEW.request_key IS DISTINCT FROM OLD.request_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'assessment_snapshots is append-only';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS assessment_snapshots_guard ON assessment_snapshots;
CREATE TRIGGER assessment_snapshots_guard BEFORE UPDATE ON assessment_snapshots
  FOR EACH ROW EXECUTE FUNCTION assessment_snapshots_guard();

ALTER TABLE assessment_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON assessment_snapshots;
CREATE POLICY cyphward_app_all ON assessment_snapshots FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; append-only.
REVOKE ALL ON assessment_snapshots FROM cyphward_app;
GRANT SELECT, INSERT ON assessment_snapshots TO cyphward_app;

-- Reports generated from a snapshot. Same-tenant by the composite key.
ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS snapshot_id uuid,
  ADD COLUMN IF NOT EXISTS report_version text CHECK (report_version IS NULL OR char_length(report_version) <= 80);
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_snapshot_fk;
ALTER TABLE reports ADD CONSTRAINT reports_snapshot_fk
  FOREIGN KEY (org_id, snapshot_id) REFERENCES assessment_snapshots(org_id, id);
CREATE INDEX IF NOT EXISTS idx_reports_snapshot ON reports (org_id, snapshot_id) WHERE snapshot_id IS NOT NULL;

-- A report issued from a snapshot keeps its content. Allowed: the SET NULL actions of a domain or
-- profile deletion (domain_id, created_by), and updated_at/status bookkeeping.
CREATE OR REPLACE FUNCTION reports_snapshot_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.snapshot_id IS NOT NULL AND (
       NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id OR NEW.org_id IS DISTINCT FROM OLD.org_id
       OR NEW.html IS DISTINCT FROM OLD.html OR NEW.summary IS DISTINCT FROM OLD.summary
       OR NEW.title IS DISTINCT FROM OLD.title OR NEW.report_version IS DISTINCT FROM OLD.report_version
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR (NEW.domain_id IS DISTINCT FROM OLD.domain_id AND NEW.domain_id IS NOT NULL)
       OR (NEW.created_by IS DISTINCT FROM OLD.created_by AND NEW.created_by IS NOT NULL)) THEN
    RAISE EXCEPTION 'a report issued from a snapshot cannot be changed';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS reports_snapshot_guard ON reports;
CREATE TRIGGER reports_snapshot_guard BEFORE UPDATE ON reports
  FOR EACH ROW EXECUTE FUNCTION reports_snapshot_guard();

COMMIT;
