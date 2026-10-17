-- Deleting a domain must not fail when it has assets, reports or score snapshots.
--
-- These composite foreign keys used ON DELETE SET NULL on (org_id, domain_id).
-- Postgres then tries to set org_id to NULL too, which violates the NOT NULL
-- on org_id, so the domain delete fails. The API reported "removed" anyway,
-- because the frontend did not surface the error.
--
-- PostgreSQL 15+ can limit the SET NULL to the nullable column only.

ALTER TABLE assets DROP CONSTRAINT IF EXISTS assets_domain_id_fkey;
ALTER TABLE assets ADD CONSTRAINT assets_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL (domain_id);

ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_domain_id_fkey;
ALTER TABLE reports ADD CONSTRAINT reports_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL (domain_id);

ALTER TABLE score_snapshots DROP CONSTRAINT IF EXISTS score_snapshots_domain_id_fkey;
ALTER TABLE score_snapshots ADD CONSTRAINT score_snapshots_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL (domain_id);
