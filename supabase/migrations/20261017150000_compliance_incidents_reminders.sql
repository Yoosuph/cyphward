-- Breach incident log and expiry reminders (packet C3b). See backend/app/compliance/.
--
--   compliance_incidents  one row per personal-data breach the organisation records.
--                         The 72-hour deadline is derived (became_aware_at + 72 h) and never stored.
--                         Never deleted by the app (decision D15): the app role has no DELETE, and
--                         only status, notified_*, notes, severity and updated_at can change.
--   compliance_reminders  one row per (current answer, threshold): written before the notification
--                         and the email, so a retried job cannot send twice.
--
-- Additive. Apply before the API and the reminders job that use it.
BEGIN;

CREATE TABLE IF NOT EXISTS compliance_incidents (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id                  uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  title                   text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
  severity                text NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  status                  text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'contained', 'closed')),
  detected_at             timestamptz NOT NULL,
  became_aware_at         timestamptz NOT NULL,
  notified_commission_at  timestamptz,
  notified_subjects_at    timestamptz,
  notes                   text CHECK (notes IS NULL OR char_length(notes) <= 4000),
  created_by              uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  -- Sanity, not a rule: catches a typo in the year, not a late discovery.
  CONSTRAINT compliance_incidents_aware_sane CHECK (became_aware_at >= detected_at - interval '30 days')
);

CREATE INDEX IF NOT EXISTS idx_compliance_incidents_org
  ON compliance_incidents (org_id, became_aware_at DESC);

CREATE TABLE IF NOT EXISTS compliance_reminders (
  attestation_id  uuid NOT NULL REFERENCES compliance_attestations(id) ON DELETE CASCADE,
  threshold_days  integer NOT NULL CHECK (threshold_days > 0),
  sent_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (attestation_id, threshold_days)
);

ALTER TABLE compliance_incidents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_incidents;
CREATE POLICY cyphward_app_all ON compliance_incidents FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

ALTER TABLE compliance_reminders ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_reminders;
CREATE POLICY cyphward_app_all ON compliance_reminders FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them.
REVOKE ALL ON compliance_incidents FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_incidents TO cyphward_app;
GRANT UPDATE (status, notified_commission_at, notified_subjects_at, notes, severity, updated_at)
  ON compliance_incidents TO cyphward_app;

REVOKE ALL ON compliance_reminders FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_reminders TO cyphward_app;

COMMIT;
