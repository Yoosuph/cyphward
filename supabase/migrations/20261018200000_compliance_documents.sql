-- AI-drafted compliance documents (packet C5). See backend/app/compliance/documents.py.
--
--   compliance_documents           append-only draft versions: a new version never edits an old one.
--                                  The text begins with the "Draft - not legal advice" label.
--   compliance_document_approvals  append-only: an owner/admin's approval of one version, recorded as
--                                  customer_attested. It says who read and approved the draft, nothing more:
--                                  it is never evidence for a register requirement.
--   compliance_document_quota      generations used per organisation per UTC day, capped by a CHECK so
--                                  the database, not the app, bounds AI cost.
--
-- Additive. Apply before the API that uses it. The app role gets SELECT and INSERT only on the two
-- document tables (no UPDATE, no DELETE); rows leave only when the organisation is deleted (cascade).
BEGIN;

CREATE TABLE IF NOT EXISTS compliance_documents (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  kind             text NOT NULL CHECK (kind IN ('privacy_policy', 'cookie_notice', 'breach_response_plan', 'retention_schedule')),
  version          integer NOT NULL CHECK (version >= 1),
  generated_at     timestamptz NOT NULL DEFAULT now(),
  generated_by     uuid REFERENCES profiles(id) ON DELETE SET NULL,
  generator        text NOT NULL CHECK (char_length(generator) BETWEEN 1 AND 120),
  fallback_reason  text CHECK (fallback_reason IS NULL OR char_length(fallback_reason) <= 120),
  inputs_hash      text NOT NULL CHECK (inputs_hash ~ '^[0-9a-f]{64}$'),
  text_sha256      text NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
  text             text NOT NULL CHECK (char_length(text) BETWEEN 1 AND 60000
                                        AND text LIKE 'Draft — not legal advice%'),
  placeholders     jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(placeholders) = 'array'),
  questionnaire_version text NOT NULL,
  UNIQUE (org_id, kind, version),
  UNIQUE (id, org_id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_documents_org_kind
  ON compliance_documents (org_id, kind, version DESC);

CREATE TABLE IF NOT EXISTS compliance_document_approvals (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  document_id        uuid NOT NULL,
  approved_by        uuid REFERENCES profiles(id) ON DELETE SET NULL,
  approved_at        timestamptz NOT NULL DEFAULT now(),
  source             text NOT NULL DEFAULT 'customer_attested' CHECK (source = 'customer_attested'),
  text_sha256        text NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
  open_placeholders  integer NOT NULL CHECK (open_placeholders >= 0),
  -- A cross-tenant approval fails here as well as in the API.
  FOREIGN KEY (document_id, org_id) REFERENCES compliance_documents (id, org_id) ON DELETE CASCADE,
  UNIQUE (document_id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_document_approvals_org
  ON compliance_document_approvals (org_id, approved_at DESC);

CREATE TABLE IF NOT EXISTS compliance_document_quota (
  org_id  uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  day     date NOT NULL,
  n       integer NOT NULL CHECK (n >= 0 AND n <= 10),
  PRIMARY KEY (org_id, day)
);

ALTER TABLE compliance_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_documents;
CREATE POLICY cyphward_app_all ON compliance_documents FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

ALTER TABLE compliance_document_approvals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_document_approvals;
CREATE POLICY cyphward_app_all ON compliance_document_approvals FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

ALTER TABLE compliance_document_quota ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_document_quota;
CREATE POLICY cyphward_app_all ON compliance_document_quota FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them.
REVOKE ALL ON compliance_documents FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_documents TO cyphward_app;

REVOKE ALL ON compliance_document_approvals FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_document_approvals TO cyphward_app;

REVOKE ALL ON compliance_document_quota FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_document_quota TO cyphward_app;
GRANT UPDATE (n) ON compliance_document_quota TO cyphward_app;

COMMIT;
