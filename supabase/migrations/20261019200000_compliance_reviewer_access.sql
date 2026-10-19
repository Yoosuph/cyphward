-- DPCO reviewer access (packet C6). See backend/app/compliance/reviewer.py.
--
--   compliance_reviewer_grants        an organisation owner's time-limited, revocable grant of read-only
--                                     review access to one person, named by email address. NOT an
--                                     organisation membership and not platform staff. Rows are never deleted
--                                     (only the organisation's deletion cascades) and never edited except
--                                     to record the revocation, once.
--   compliance_practitioner_reviews   append-only: "this practitioner reviewed this requirement". It never
--                                     changes any status and says nothing about the organisation's duties.
--   compliance_clause_verifications   append-only per-organisation overlay on the register's clause_verified
--                                     flag. The newest row per (organisation, requirement) wins. The register
--                                     file itself is code and is not changed by this.
--
-- Additive. Apply before the API that uses it. The app role gets SELECT and INSERT on the two record tables
-- (no UPDATE, no DELETE) and SELECT, INSERT and UPDATE (revoked_at, revoked_by) on grants.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS compliance_reviewer_grants (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  -- Matched against the signed-in account's own verified profile email on every request (never an email
  -- claim from a token). Stored lower-case.
  reviewer_email  text NOT NULL CHECK (reviewer_email = lower(reviewer_email)
                                       AND char_length(reviewer_email) BETWEEN 3 AND 254
                                       AND reviewer_email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  purpose         text NOT NULL CHECK (char_length(purpose) BETWEEN 1 AND 200),
  granted_by      uuid REFERENCES profiles(id) ON DELETE SET NULL,
  granted_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL,
  revoked_at      timestamptz,
  revoked_by      uuid REFERENCES profiles(id) ON DELETE SET NULL,
  -- At least one day and at most 90 days, both measured from the grant time on the database clock.
  CONSTRAINT reviewer_grant_expiry_window CHECK (expires_at >= granted_at + interval '1 day'
                                                 AND expires_at <= granted_at + interval '90 days'),
  CONSTRAINT reviewer_grant_revocation_after_grant CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
  UNIQUE (id, org_id)
);

-- One live (not revoked) grant per organisation and reviewer. An expired grant is still "not revoked", so a
-- replacement revokes it in the same transaction (the API does that under an advisory lock).
CREATE UNIQUE INDEX IF NOT EXISTS uq_reviewer_grants_live
  ON compliance_reviewer_grants (org_id, reviewer_email) WHERE revoked_at IS NULL;
-- "Which organisations may this email review right now?"
CREATE INDEX IF NOT EXISTS idx_reviewer_grants_email
  ON compliance_reviewer_grants (reviewer_email, expires_at) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_reviewer_grants_org
  ON compliance_reviewer_grants (org_id, granted_at DESC);

CREATE TABLE IF NOT EXISTS compliance_practitioner_reviews (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  requirement_key   text NOT NULL CHECK (char_length(requirement_key) BETWEEN 1 AND 120),
  grant_id          uuid NOT NULL,
  reviewer_user_id  uuid REFERENCES profiles(id) ON DELETE SET NULL,
  reviewer_name     text NOT NULL CHECK (char_length(reviewer_name) BETWEEN 1 AND 200),
  reviewed_at       timestamptz NOT NULL DEFAULT now(),
  outcome           text NOT NULL CHECK (outcome IN ('reviewed', 'reviewed_with_comments')),
  comment           text CHECK (comment IS NULL OR char_length(comment) BETWEEN 1 AND 500),
  FOREIGN KEY (grant_id, org_id) REFERENCES compliance_reviewer_grants (id, org_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_practitioner_reviews_req
  ON compliance_practitioner_reviews (org_id, requirement_key, reviewed_at DESC);

CREATE TABLE IF NOT EXISTS compliance_clause_verifications (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  requirement_key   text NOT NULL CHECK (char_length(requirement_key) BETWEEN 1 AND 120),
  verified          boolean NOT NULL,
  grant_id          uuid NOT NULL,
  reviewer_user_id  uuid REFERENCES profiles(id) ON DELETE SET NULL,
  reviewer_name     text NOT NULL CHECK (char_length(reviewer_name) BETWEEN 1 AND 200),
  verified_at       timestamptz NOT NULL DEFAULT now(),
  note              text CHECK (note IS NULL OR char_length(note) BETWEEN 1 AND 500),
  FOREIGN KEY (grant_id, org_id) REFERENCES compliance_reviewer_grants (id, org_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_clause_verifications_req
  ON compliance_clause_verifications (org_id, requirement_key, verified_at DESC);

-- ── Guard triggers ────────────────────────────────────────────────────────

-- Grants: only the revocation may change, once, and never be cleared. Referential actions (a deleted
-- profile nulling granted_by / revoked_by) change those two columns only and are let through.
CREATE OR REPLACE FUNCTION compliance_reviewer_grants_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.revoked_at IS NOT NULL OR NEW.revoked_by IS NOT NULL THEN
      RAISE EXCEPTION 'a reviewer grant starts unrevoked' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.granted_by IS NULL OR NOT EXISTS (
         SELECT 1 FROM organization_members m
         WHERE m.org_id = NEW.org_id AND m.user_id = NEW.granted_by AND m.role = 'owner') THEN
      RAISE EXCEPTION 'only an owner of the organisation can grant reviewer access' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.reviewer_email IS DISTINCT FROM OLD.reviewer_email OR NEW.purpose IS DISTINCT FROM OLD.purpose
     OR NEW.granted_at IS DISTINCT FROM OLD.granted_at OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
    RAISE EXCEPTION 'a reviewer grant cannot be edited, only revoked' USING ERRCODE = 'check_violation';
  END IF;
  -- granted_by may be nulled by the profile's deletion; anything else must not move.
  IF NEW.granted_by IS DISTINCT FROM OLD.granted_by AND NEW.granted_by IS NOT NULL THEN
    RAISE EXCEPTION 'a reviewer grant cannot be edited, only revoked' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'a revocation cannot be changed or cleared' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.revoked_at IS NULL AND NEW.revoked_by IS NOT NULL AND NEW.revoked_at IS NULL THEN
    RAISE EXCEPTION 'revoked_by needs revoked_at' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_compliance_reviewer_grants_guard ON compliance_reviewer_grants;
CREATE TRIGGER trg_compliance_reviewer_grants_guard
  BEFORE INSERT OR UPDATE ON compliance_reviewer_grants
  FOR EACH ROW EXECUTE FUNCTION compliance_reviewer_grants_guard();

-- Reviews and verifications: the write itself re-checks the grant, so a request that passed the API check
-- moments before a revocation or expiry still cannot write. The reviewer must be the person the grant names
-- (verified profile email), and not a member of the organisation.
CREATE OR REPLACE FUNCTION compliance_reviewer_write_guard() RETURNS trigger AS $$
DECLARE
  g compliance_reviewer_grants%ROWTYPE;
BEGIN
  SELECT * INTO g FROM compliance_reviewer_grants WHERE id = NEW.grant_id AND org_id = NEW.org_id;
  IF NOT FOUND OR g.revoked_at IS NOT NULL OR g.expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'the reviewer grant is not active' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.reviewer_user_id IS NULL OR NOT EXISTS (
       SELECT 1 FROM profiles p
       WHERE p.id = NEW.reviewer_user_id AND lower(p.email) = g.reviewer_email AND p.email_verified_at IS NOT NULL) THEN
    RAISE EXCEPTION 'the writer is not the verified reviewer of this grant' USING ERRCODE = 'check_violation';
  END IF;
  IF EXISTS (SELECT 1 FROM organization_members m WHERE m.org_id = NEW.org_id AND m.user_id = NEW.reviewer_user_id) THEN
    RAISE EXCEPTION 'a member of the organisation cannot act as its reviewer' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_practitioner_reviews_guard ON compliance_practitioner_reviews;
CREATE TRIGGER trg_practitioner_reviews_guard BEFORE INSERT ON compliance_practitioner_reviews
  FOR EACH ROW EXECUTE FUNCTION compliance_reviewer_write_guard();
DROP TRIGGER IF EXISTS trg_clause_verifications_guard ON compliance_clause_verifications;
CREATE TRIGGER trg_clause_verifications_guard BEFORE INSERT ON compliance_clause_verifications
  FOR EACH ROW EXECUTE FUNCTION compliance_reviewer_write_guard();

-- ── Row level security and grants ─────────────────────────────────────────

ALTER TABLE compliance_reviewer_grants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_reviewer_grants;
CREATE POLICY cyphward_app_all ON compliance_reviewer_grants FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

ALTER TABLE compliance_practitioner_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_practitioner_reviews;
CREATE POLICY cyphward_app_all ON compliance_practitioner_reviews FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

ALTER TABLE compliance_clause_verifications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_clause_verifications;
CREATE POLICY cyphward_app_all ON compliance_clause_verifications FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them.
REVOKE ALL ON compliance_reviewer_grants FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_reviewer_grants TO cyphward_app;
GRANT UPDATE (revoked_at, revoked_by) ON compliance_reviewer_grants TO cyphward_app;

REVOKE ALL ON compliance_practitioner_reviews FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_practitioner_reviews TO cyphward_app;

REVOKE ALL ON compliance_clause_verifications FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_clause_verifications TO cyphward_app;

COMMIT;
