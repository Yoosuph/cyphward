-- Tenant-scoped composite foreign keys (review P1 — tenant relationships).
--
-- domain-referencing rows stored only `domain_id`; a plain (id) FK accepts
-- ANY domain row, including one owned by a different organization, and
-- joins like the report list could then surface another tenant's domain
-- name. Composite (org_id, domain_id) keys make a cross-tenant reference
-- impossible at the database level. ON DELETE actions are preserved from
-- the original constraints (CASCADE for scans; SET NULL elsewhere).
--
-- domains needs an explicit UNIQUE (org_id, id): an FK must reference the
-- exact column list (id alone being the PK is not enough).
-- domain_id stays nullable; MATCH SIMPLE keeps NULL domain_id rows valid.
--
-- DROP IF EXISTS + ADD keeps this re-runnable.

ALTER TABLE domains DROP CONSTRAINT IF EXISTS domains_org_id_id_key;
ALTER TABLE domains ADD CONSTRAINT domains_org_id_id_key UNIQUE (org_id, id);

ALTER TABLE scans DROP CONSTRAINT IF EXISTS scans_domain_id_fkey;
ALTER TABLE scans ADD CONSTRAINT scans_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE CASCADE;

ALTER TABLE assets DROP CONSTRAINT IF EXISTS assets_domain_id_fkey;
ALTER TABLE assets ADD CONSTRAINT assets_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL;

ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_domain_id_fkey;
ALTER TABLE reports ADD CONSTRAINT reports_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL;

ALTER TABLE score_snapshots DROP CONSTRAINT IF EXISTS score_snapshots_domain_id_fkey;
ALTER TABLE score_snapshots ADD CONSTRAINT score_snapshots_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL;
