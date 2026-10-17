-- Deleting a domain must not fail when it has assets, reports or score snapshots.
--
-- These composite foreign keys used ON DELETE SET NULL on (org_id, domain_id). Postgres then also tries
-- to set org_id to NULL, which violates its NOT NULL, so the domain delete failed. The API reported
-- "removed" anyway, because the frontend did not surface the error.
--
-- After this migration, deleting a domain:
--   assets           are deleted with it (an asset belongs to one domain's inventory);
--   reports          keep their row; only domain_id is cleared (PostgreSQL 15+ column list);
--   score_snapshots  keep their row; only domain_id is cleared.
-- Scans, monitored hosts and compliance evidence already cascade (earlier migrations).
--
-- One transaction. The timeouts stop it waiting behind a long-running query (lock_timeout) or running
-- away (statement_timeout); on either, nothing changes and it can be retried.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE assets DROP CONSTRAINT IF EXISTS assets_domain_id_fkey;
ALTER TABLE assets ADD CONSTRAINT assets_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE CASCADE;

ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_domain_id_fkey;
ALTER TABLE reports ADD CONSTRAINT reports_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL (domain_id);

ALTER TABLE score_snapshots DROP CONSTRAINT IF EXISTS score_snapshots_domain_id_fkey;
ALTER TABLE score_snapshots ADD CONSTRAINT score_snapshots_domain_id_fkey
  FOREIGN KEY (org_id, domain_id) REFERENCES domains(org_id, id) ON DELETE SET NULL (domain_id);

COMMIT;
