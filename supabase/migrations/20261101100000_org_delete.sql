-- Owner console: delete an organisation in two steps (docs/admin-delete-org/README.md).
--
-- Step one is a soft delete. The owner marks the organisation 'deleted' in organization_suspensions, the same side
-- table that holds the suspension status (see 20261030100000_organization_suspension.sql for why it is a side table
-- and not a column on organizations: several customer endpoints return the whole organizations row). A deleted
-- organisation is hidden from customers and from the owner lists by default, and it can be restored for 30 days.
-- Step two, the purge, is a separate owner action after that window; it deletes the organizations row (the tenant
-- subtree cascades, as the customer's own closing does). Nothing in this file deletes or rewrites data.
--
--   organization_suspensions.status       now 'active', 'suspended' or 'deleted'
--   organization_suspensions.deleted_at   when the organisation was soft deleted; NULL unless status is 'deleted'
--   organization_suspensions.deleted_by   the owner (platform_owners user id) who soft deleted it; no foreign key,
--                                         like changed_by, so the record survives a profile deletion
--
-- Additive and idempotent:
--   * the two columns are nullable with no default, so adding them changes only the catalogue (no table rewrite);
--   * the status CHECK is replaced by one that allows the existing values plus 'deleted'. It is found by its
--     definition rather than by its default name, so a differently named constraint is replaced too, and re-running
--     the file drops and re-adds the same two checks;
--   * one partial index serves the owner's "deleted" filter and the restore and purge window checks.
-- RLS and the table-level grants are unchanged. The app role already has UPDATE on (status, changed_at, changed_by)
-- only; it gets UPDATE on the two new columns as well, because soft delete sets them and restore clears them. No
-- DELETE grant: the row goes only through the organisation's own ON DELETE CASCADE at purge.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE organization_suspensions ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE organization_suspensions ADD COLUMN IF NOT EXISTS deleted_by uuid;

DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'organization_suspensions'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%status%'
  LOOP
    EXECUTE format('ALTER TABLE organization_suspensions DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE organization_suspensions
  ADD CONSTRAINT organization_suspensions_status_check CHECK (status IN ('suspended', 'active', 'deleted'));
-- A deleted row always says when; any other status never carries a deletion time or author.
ALTER TABLE organization_suspensions
  ADD CONSTRAINT organization_suspensions_deleted_check CHECK (
    (status = 'deleted' AND deleted_at IS NOT NULL) OR (status <> 'deleted' AND deleted_at IS NULL AND deleted_by IS NULL));

CREATE INDEX IF NOT EXISTS idx_organization_suspensions_deleted
  ON organization_suspensions (deleted_at) WHERE status = 'deleted';

GRANT UPDATE (deleted_at, deleted_by) ON organization_suspensions TO cyphward_app;

COMMIT;
