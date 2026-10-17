-- NDPA readiness evidence packs and DPO six-monthly reminders (packet C4). See backend/app/packs/.
--
--   evidence_packs  one issued pack, generated from one assessment snapshot (Packet 04). The rendered
--                   HTML and PDF bytes and their sha256 are stored at issue and served as stored, so a
--                   re-download is byte-identical. Append-only: the app role has SELECT and INSERT only,
--                   and a guard trigger refuses any change except the profile-deletion action clearing
--                   issued_by. A second issue makes a new pack; it never edits one.
--   dpo_reminders   one row per (organisation, half-year) once the six-monthly reminder is recorded,
--                   written in the same transaction as the in-app notification so a retry cannot repeat it.
--
-- Deletion: organisation deletion cascades to packs and reminders (the cascade runs as the table owner).
-- Additive. Apply after 20261018100000_assessment_snapshots.sql and before the API that writes it.
BEGIN;

CREATE TABLE IF NOT EXISTS evidence_packs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  snapshot_id   uuid NOT NULL,
  kind          text NOT NULL CHECK (kind IN ('readiness_pack', 'dpo_section')),
  pack_version  text NOT NULL CHECK (char_length(pack_version) BETWEEN 1 AND 80),
  issued_at     timestamptz NOT NULL,
  issued_by     uuid REFERENCES profiles(id) ON DELETE SET NULL,
  window_start  timestamptz,
  window_end    timestamptz,
  dpo           jsonb CHECK (dpo IS NULL OR jsonb_typeof(dpo) = 'object'),
  html          text NOT NULL,
  html_sha256   text NOT NULL CHECK (html_sha256 ~ '^[0-9a-f]{64}$'),
  pdf           bytea NOT NULL,
  pdf_sha256    text NOT NULL CHECK (pdf_sha256 ~ '^[0-9a-f]{64}$'),
  request_key   text CHECK (request_key IS NULL OR char_length(request_key) BETWEEN 8 AND 80),
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evidence_packs_org_id_key UNIQUE (org_id, id),
  CONSTRAINT evidence_packs_snapshot_fk FOREIGN KEY (org_id, snapshot_id)
    REFERENCES assessment_snapshots(org_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_packs_request
  ON evidence_packs (org_id, request_key) WHERE request_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_evidence_packs_org ON evidence_packs (org_id, issued_at DESC);

CREATE OR REPLACE FUNCTION evidence_packs_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.issued_by IS DISTINCT FROM OLD.issued_by AND NEW.issued_by IS NOT NULL)
     OR NEW.id IS DISTINCT FROM OLD.id OR NEW.org_id IS DISTINCT FROM OLD.org_id
     OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id OR NEW.kind IS DISTINCT FROM OLD.kind
     OR NEW.pack_version IS DISTINCT FROM OLD.pack_version OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
     OR NEW.window_start IS DISTINCT FROM OLD.window_start OR NEW.window_end IS DISTINCT FROM OLD.window_end
     OR NEW.dpo IS DISTINCT FROM OLD.dpo OR NEW.html IS DISTINCT FROM OLD.html
     OR NEW.html_sha256 IS DISTINCT FROM OLD.html_sha256 OR NEW.pdf IS DISTINCT FROM OLD.pdf
     OR NEW.pdf_sha256 IS DISTINCT FROM OLD.pdf_sha256 OR NEW.request_key IS DISTINCT FROM OLD.request_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'evidence_packs is append-only';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS evidence_packs_guard ON evidence_packs;
CREATE TRIGGER evidence_packs_guard BEFORE UPDATE ON evidence_packs
  FOR EACH ROW EXECUTE FUNCTION evidence_packs_guard();

CREATE TABLE IF NOT EXISTS dpo_reminders (
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  period_key  text NOT NULL CHECK (period_key ~ '^[0-9]{4}-H[12]$'),
  sent_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, period_key)
);

ALTER TABLE evidence_packs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON evidence_packs;
CREATE POLICY cyphward_app_all ON evidence_packs FOR ALL TO cyphward_app USING (true) WITH CHECK (true);
ALTER TABLE dpo_reminders ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON dpo_reminders;
CREATE POLICY cyphward_app_all ON dpo_reminders FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them.
REVOKE ALL ON evidence_packs FROM cyphward_app;
GRANT SELECT, INSERT ON evidence_packs TO cyphward_app;
REVOKE ALL ON dpo_reminders FROM cyphward_app;
GRANT SELECT, INSERT ON dpo_reminders TO cyphward_app;

COMMIT;
