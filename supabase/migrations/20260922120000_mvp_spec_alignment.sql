-- ============================================================================
-- Cyphward MVP Spec Alignment Migration
-- - Removes out-of-scope legacy schema (compliance/academy/detect/copilot/ticker)
-- - Aligns core tables with the MVP spec (profiles, organization_members)
-- - Adds remediation, evidence, reports, notifications, audit, scan_targets
-- - Extends findings with confidence/status lifecycle required by the spec
-- - Adds RBAC role constraints (owner/admin/member)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. Drop out-of-scope legacy SQL functions
-- ----------------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT oid::regprocedure AS sig
    FROM pg_proc
    WHERE proname IN ('draft_policy', 'triage_alert', 'update_control_status', 'recalculate_tenant_score')
  LOOP
    EXECUTE 'DROP FUNCTION IF EXISTS ' || r.sig || ' CASCADE';
  END LOOP;
END $$;

-- ----------------------------------------------------------------------------
-- 2. Drop out-of-scope legacy tables
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS threat_ticker CASCADE;
DROP TABLE IF EXISTS copilot_knowledge CASCADE;
DROP TABLE IF EXISTS academy_meta CASCADE;
DROP TABLE IF EXISTS academy_courses CASCADE;
DROP TABLE IF EXISTS detection_layers CASCADE;
DROP TABLE IF EXISTS alerts CASCADE;
DROP TABLE IF EXISTS policy_drafts CASCADE;
DROP TABLE IF EXISTS remediations CASCADE;
DROP TABLE IF EXISTS controls CASCADE;
DROP TABLE IF EXISTS frameworks CASCADE;
DROP TABLE IF EXISTS postures CASCADE;
DROP TABLE IF EXISTS scores CASCADE;
DROP TABLE IF EXISTS profiles CASCADE; -- legacy profiles from init migration
DROP TABLE IF EXISTS tenants CASCADE;

-- ----------------------------------------------------------------------------
-- 3. Align identity tables with the spec
--    profiles(id) carries the Supabase auth user UUID.
--    organization_members links profiles -> organizations with RBAC roles.
-- ----------------------------------------------------------------------------
ALTER TABLE IF EXISTS users RENAME TO profiles;
ALTER TABLE IF EXISTS memberships RENAME TO organization_members;

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- Normalize historical free-text "roles" (job titles) into MVP roles
UPDATE organization_members
SET role = CASE
  WHEN lower(role) IN ('owner', 'admin', 'member') THEN lower(role)
  ELSE 'member'
END;

ALTER TABLE organization_members DROP CONSTRAINT IF EXISTS role_mvp_check;
ALTER TABLE organization_members ADD CONSTRAINT role_mvp_check
  CHECK (role IN ('owner', 'admin', 'member'));

ALTER TABLE organization_members ALTER COLUMN role SET DEFAULT 'member';

-- API keys are not part of MVP auth (Supabase Auth only)
ALTER TABLE organizations DROP COLUMN IF EXISTS api_key;

-- ----------------------------------------------------------------------------
-- 4. Domains: full verification lifecycle (pending/verified/expired/revoked)
-- ----------------------------------------------------------------------------
UPDATE domains SET verification_status = 'pending' WHERE verification_status = 'failed';
ALTER TABLE domains DROP CONSTRAINT IF EXISTS domains_verification_status_check;
ALTER TABLE domains ADD CONSTRAINT domains_verification_status_check
  CHECK (verification_status IN ('pending', 'verified', 'expired', 'revoked'));
ALTER TABLE domains ADD COLUMN IF NOT EXISTS revoked_at timestamptz;

-- ----------------------------------------------------------------------------
-- 5. Scans: scan_type per spec
-- ----------------------------------------------------------------------------
ALTER TABLE scans ADD COLUMN IF NOT EXISTS scan_type text NOT NULL DEFAULT 'EXTERNAL_ASSESSMENT';

-- ----------------------------------------------------------------------------
-- 6. Assets: port/service observation
-- ----------------------------------------------------------------------------
ALTER TABLE assets ADD COLUMN IF NOT EXISTS port int;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS protocol text;

-- ----------------------------------------------------------------------------
-- 7. Findings: spec-compliant lifecycle + evidence support
-- ----------------------------------------------------------------------------
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS confidence text NOT NULL DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS impact text,
  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'scanner',
  ADD COLUMN IF NOT EXISTS first_seen_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS resolved_at timestamptz,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

UPDATE findings SET status = 'open' WHERE status = 'suppressed';
UPDATE findings SET resolved_at = now() WHERE status = 'resolved' AND resolved_at IS NULL;

ALTER TABLE findings DROP CONSTRAINT IF EXISTS findings_status_check;
ALTER TABLE findings ADD CONSTRAINT findings_status_check
  CHECK (status IN ('open', 'acknowledged', 'in_progress', 'resolved'));
ALTER TABLE findings DROP CONSTRAINT IF EXISTS findings_severity_check;
ALTER TABLE findings ADD CONSTRAINT findings_severity_check
  CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info'));
ALTER TABLE findings DROP CONSTRAINT IF EXISTS findings_confidence_check;
ALTER TABLE findings ADD CONSTRAINT findings_confidence_check
  CHECK (confidence IN ('high', 'medium', 'low'));

-- ----------------------------------------------------------------------------
-- 8. New core tables
-- ----------------------------------------------------------------------------

-- Evidence backing each finding (spec §24)
CREATE TABLE IF NOT EXISTS finding_evidence (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  finding_id  uuid NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  type        text NOT NULL, -- http_response | dns_record | tls_result | port_observation | scanner_output
  data        jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_finding_evidence_finding ON finding_evidence(finding_id);

-- Remediation tasks (spec §27)
CREATE TABLE IF NOT EXISTS remediation_tasks (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  finding_id  uuid REFERENCES findings(id) ON DELETE SET NULL,
  title       text NOT NULL,
  instructions text,
  assignee_id uuid REFERENCES profiles(id) ON DELETE SET NULL,
  priority    text NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','critical')),
  status      text NOT NULL DEFAULT 'open'
              CHECK (status IN ('open','in_progress','ready_for_verification','verified','reopened')),
  due_date    date,
  created_by  uuid REFERENCES profiles(id) ON DELETE SET NULL,
  verified_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_remediation_org ON remediation_tasks(org_id);
CREATE INDEX IF NOT EXISTS idx_remediation_finding ON remediation_tasks(finding_id);
CREATE INDEX IF NOT EXISTS idx_remediation_status ON remediation_tasks(status);

-- Generated assessment reports (spec §32)
CREATE TABLE IF NOT EXISTS reports (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id   uuid REFERENCES domains(id) ON DELETE SET NULL,
  scan_id     uuid REFERENCES scans(id) ON DELETE SET NULL,
  title       text NOT NULL,
  status      text NOT NULL DEFAULT 'ready' CHECK (status IN ('generating','ready','failed')),
  html        text,
  summary     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by  uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reports_org ON reports(org_id, created_at DESC);

-- In-app notifications + email fanout bookkeeping (spec §31)
CREATE TABLE IF NOT EXISTS notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  type        text NOT NULL, -- critical_finding | high_risk_exposure | new_asset | finding_reopened | finding_resolved | scan_completed
  title       text NOT NULL,
  body        text,
  severity    text NOT NULL DEFAULT 'info' CHECK (severity IN ('info','low','medium','high','critical')),
  link        text,
  read_at     timestamptz,
  email_sent  boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notifications_org ON notifications(org_id, created_at DESC);

-- Audit trail for security-sensitive actions (spec §39)
CREATE TABLE IF NOT EXISTS audit_log (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid REFERENCES organizations(id) ON DELETE CASCADE,
  user_id       uuid,
  action        text NOT NULL,
  resource_type text,
  resource_id   text,
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_log(org_id, created_at DESC);

-- Per-scan target inventory produced by discovery/probing
CREATE TABLE IF NOT EXISTS scan_targets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id     uuid NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  hostname    text NOT NULL,
  ip_address  text,
  status      text NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered','active','inactive')),
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now(),
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(scan_id, hostname)
);
CREATE INDEX IF NOT EXISTS idx_scan_targets_scan ON scan_targets(scan_id);

-- ----------------------------------------------------------------------------
-- 9. Tenant isolation hardening: enable RLS with no policies so Supabase
--    anon/authenticated API access is denied by default. The application
--    connects as the table owner (or service role) and enforces tenant
--    scoping in SQL (WHERE org_id = ...) on every query.
-- ----------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename IN (
        'organizations','profiles','organization_members','domains','assets','scans',
        'scan_results','scan_targets','findings','score_snapshots','finding_evidence',
        'remediation_tasks','reports','notifications','audit_log'
      )
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

COMMIT;
