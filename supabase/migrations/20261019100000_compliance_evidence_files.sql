-- Evidence file uploads for questionnaire answers (packet C6). See backend/app/compliance/evidence_file_store.py.
--
--   compliance_evidence_files  one row per uploaded file. The bytes are NOT in the database: they are in the
--                              private Supabase Storage bucket 'evidence-files' at org/<org_id>/<id>. The row
--                              says which organisation owns the file, what it is (display name, validated type,
--                              size, sha256) and who added or removed it. Removal is a soft delete: removed_at and
--                              removed_by are set, then the object is deleted from storage.
--   storage.buckets            the private bucket row, created only where the Supabase storage schema exists
--                              (the plain local test database has none). No policy is created on storage.objects:
--                              anon and authenticated roles get nothing; only the backend's service role touches it.
--
-- Additive. The app role gets SELECT, INSERT and UPDATE (removed_at, removed_by) only: no DELETE. A guard trigger
-- lets nothing else change (the only other change is a deleted profile clearing uploaded_by or removed_by).
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS compliance_evidence_files (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  question_key    text NOT NULL CHECK (char_length(question_key) BETWEEN 1 AND 80),
  attestation_id  uuid,
  display_name    text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 120),
  content_type    text NOT NULL CHECK (content_type IN (
                    'application/pdf', 'image/png', 'image/jpeg',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
  size_bytes      bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 10485760),
  sha256          text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  storage_path    text NOT NULL,
  uploaded_by     uuid REFERENCES profiles(id) ON DELETE SET NULL,
  uploaded_at     timestamptz NOT NULL DEFAULT now(),
  removed_at      timestamptz,
  removed_by      uuid REFERENCES profiles(id) ON DELETE SET NULL,
  CONSTRAINT compliance_evidence_files_org_id_key UNIQUE (org_id, id),
  -- The object path is derived from the organisation and file ids, never from the user's file name.
  CONSTRAINT compliance_evidence_files_path_check CHECK (storage_path = 'org/' || org_id::text || '/' || id::text),
  CONSTRAINT compliance_evidence_files_removed_check CHECK (removed_by IS NULL OR removed_at IS NOT NULL),
  -- Same-tenant link to the answer that was current when the file was added (NULL = no answer yet).
  CONSTRAINT compliance_evidence_files_attestation_fk FOREIGN KEY (org_id, attestation_id)
    REFERENCES compliance_attestations (org_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_compliance_evidence_files_path ON compliance_evidence_files (storage_path);
CREATE INDEX IF NOT EXISTS idx_compliance_evidence_files_question
  ON compliance_evidence_files (org_id, question_key, uploaded_at DESC) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_compliance_evidence_files_org_uploaded
  ON compliance_evidence_files (org_id, uploaded_at DESC);

-- A row can be marked removed once; nothing else changes. Deleting a profile may clear uploaded_by or removed_by
-- (ON DELETE SET NULL). Deletes are refused by grants; organisation deletion still cascades.
CREATE OR REPLACE FUNCTION compliance_evidence_files_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.removed_at IS DISTINCT FROM OLD.removed_at AND (OLD.removed_at IS NOT NULL OR NEW.removed_at IS NULL) THEN
    RAISE EXCEPTION 'compliance_evidence_files: a file can be marked removed once, and not unmarked';
  END IF;
  IF (NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by AND NEW.uploaded_by IS NOT NULL)
     OR (NEW.removed_by IS DISTINCT FROM OLD.removed_by
         AND (NEW.removed_by IS NOT NULL AND OLD.removed_by IS NOT NULL))
     OR (NEW.removed_by IS NOT NULL AND OLD.removed_by IS NULL AND OLD.removed_at IS NOT NULL)
     OR NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.question_key IS DISTINCT FROM OLD.question_key
     OR NEW.attestation_id IS DISTINCT FROM OLD.attestation_id
     OR NEW.display_name IS DISTINCT FROM OLD.display_name
     OR NEW.content_type IS DISTINCT FROM OLD.content_type
     OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
     OR NEW.sha256 IS DISTINCT FROM OLD.sha256
     OR NEW.storage_path IS DISTINCT FROM OLD.storage_path
     OR NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at THEN
    RAISE EXCEPTION 'compliance_evidence_files is append-only apart from marking a file removed';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS compliance_evidence_files_guard ON compliance_evidence_files;
CREATE TRIGGER compliance_evidence_files_guard BEFORE UPDATE ON compliance_evidence_files
  FOR EACH ROW EXECUTE FUNCTION compliance_evidence_files_guard();

ALTER TABLE compliance_evidence_files ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON compliance_evidence_files;
CREATE POLICY cyphward_app_all ON compliance_evidence_files FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them.
REVOKE ALL ON compliance_evidence_files FROM cyphward_app;
GRANT SELECT, INSERT ON compliance_evidence_files TO cyphward_app;
GRANT UPDATE (removed_at, removed_by) ON compliance_evidence_files TO cyphward_app;

-- The private bucket, where the Supabase storage schema exists. Re-running re-asserts that it is private.
DO $$
BEGIN
  IF to_regclass('storage.buckets') IS NOT NULL THEN
    EXECUTE $sql$
      INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
      VALUES ('evidence-files', 'evidence-files', false, 10485760, ARRAY[
        'application/pdf', 'image/png', 'image/jpeg',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
      ON CONFLICT (id) DO UPDATE SET
        public = false,
        file_size_limit = EXCLUDED.file_size_limit,
        allowed_mime_types = EXCLUDED.allowed_mime_types
    $sql$;
  END IF;
END $$;

COMMIT;
