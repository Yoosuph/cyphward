-- Compliance attestations (packet C3a). See backend/app/compliance/.
--
--   compliance_attestations  append-only customer answers. One current answer
--                            per (organization, question); a new answer
--                            supersedes the old one in the same transaction.
--                            Customer answers are evidence labelled
--                            customer_attested, never tool or externally observed.
--   organizations.display_timezone  display zone for the organization (decision
--                            D11). Stored times stay UTC; the default is Africa/Lagos.
--
-- Additive. Apply before the API that writes it.
BEGIN;

ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS display_timezone text NOT NULL DEFAULT 'Africa/Lagos'
    CHECK (char_length(display_timezone) BETWEEN 1 AND 64);

CREATE TABLE IF NOT EXISTS compliance_attestations (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id                uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  question_key          text NOT NULL CHECK (char_length(question_key) BETWEEN 1 AND 80),
  questionnaire_version text NOT NULL CHECK (char_length(questionnaire_version) BETWEEN 1 AND 80),
  answer                jsonb NOT NULL CHECK (jsonb_typeof(answer) = 'object'),
  owner_user_id         uuid REFERENCES profiles(id) ON DELETE SET NULL,
  attested_by           uuid REFERENCES profiles(id) ON DELETE SET NULL,
  attested_at           timestamptz NOT NULL DEFAULT now(),
  expires_at            timestamptz NOT NULL,
  evidence_link         text CHECK (evidence_link IS NULL
                                    OR (evidence_link ~ '^https://' AND char_length(evidence_link) <= 500)),
  notes                 text CHECK (notes IS NULL OR char_length(notes) <= 1000),
  superseded_by         uuid,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT compliance_attestations_org_id_key UNIQUE (org_id, id),
  -- Same-tenant supersession. Deferred so the old row can point at the new row
  -- inside the superseding transaction (the new row is inserted after the UPDATE).
  CONSTRAINT compliance_attestations_superseded_fk FOREIGN KEY (org_id, superseded_by)
    REFERENCES compliance_attestations(org_id, id) DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT compliance_attestations_not_self CHECK (superseded_by IS NULL OR superseded_by <> id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_attestations_question
  ON compliance_attestations (org_id, question_key, attested_at DESC);
-- Exactly one current answer per (organization, question).
CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_attestations_current
  ON compliance_attestations (org_id, question_key) WHERE superseded_by IS NULL;

-- A current answer can be superseded once, and nothing else about a row changes.
-- The only other change allowed is the profile-deletion action (ON DELETE SET
-- NULL) clearing owner_user_id or attested_by. Deletes are refused by grants
-- (the app role has no DELETE); organisation deletion still cascades.
CREATE OR REPLACE FUNCTION compliance_attestations_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.superseded_by IS DISTINCT FROM OLD.superseded_by
     AND (OLD.superseded_by IS NOT NULL OR NEW.superseded_by IS NULL) THEN
    RAISE EXCEPTION 'compliance_attestations: only a current answer can be superseded, once';
  END IF;
  IF (NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id AND NEW.owner_user_id IS NOT NULL)
     OR (NEW.attested_by IS DISTINCT FROM OLD.attested_by AND NEW.attested_by IS NOT NULL)
     OR NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.question_key IS DISTINCT FROM OLD.question_key
     OR NEW.questionnaire_version IS DISTINCT FROM OLD.questionnaire_version
     OR NEW.answer IS DISTINCT FROM OLD.answer
     OR NEW.attested_at IS DISTINCT FROM OLD.attested_at
     OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
     OR NEW.evidence_link IS DISTINCT FROM OLD.evidence_link
     OR NEW.notes IS DISTINCT FROM OLD.notes
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'compliance_attestations is append-only';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS compliance_attestations_guard ON compliance_attestations;
CREATE TRIGGER compliance_attestations_guard BEFORE UPDATE ON compliance_attestations
  FOR EACH ROW EXECUTE FUNCTION compliance_attestations_guard();

ALTER TABLE compliance_attestations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_attestations;
CREATE POLICY cyphward_app_all ON compliance_attestations FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; append-only.
REVOKE ALL ON compliance_attestations FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_attestations TO cyphward_app;
GRANT UPDATE (superseded_by) ON compliance_attestations TO cyphward_app;

COMMIT;
