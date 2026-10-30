-- Admin phase 2: a stored failure code per failed scan (docs/admin-phase2-2026-10-31/README.md, core/scan_failures.py).
--
--   scans.failure_code   one of a fixed set of codes (unreachable, blocked, timeout, out_of_scope, domain_unverified,
--                        interrupted, internal), written by the backend when it marks a scan failed. Customers see
--                        the reviewed sentence for the code; the raw worker text stays in error_message for the
--                        owner console only. NULL for scans that have not failed and for scans failed before this
--                        column existed (their stored text is classified when read).
--
-- The release must apply this file BEFORE the code that writes the column is deployed: fail_claim sets it.
--
-- ADD COLUMN with no default is a catalogue change (no table rewrite). The format check is added NOT VALID, so
-- existing rows are not scanned; new and updated rows are checked. Both take a brief ACCESS EXCLUSIVE lock on scans,
-- bounded by lock_timeout. Additive and idempotent. Table-level grants already cover the new column.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE scans ADD COLUMN IF NOT EXISTS failure_code text;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'scans_failure_code_format'
                 AND conrelid = 'public.scans'::regclass) THEN
    ALTER TABLE scans ADD CONSTRAINT scans_failure_code_format
      CHECK (failure_code IS NULL OR failure_code ~ '^[a-z_]{1,40}$') NOT VALID;
  END IF;
END $$;

COMMIT;
