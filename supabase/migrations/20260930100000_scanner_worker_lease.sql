-- ============================================================================
-- Cyphward Scanner Worker — job lease columns (Phase 2b)
-- The scans table doubles as the scanner job queue: the Azure worker claims
-- queued (or lease-expired) rows atomically and holds a time-boxed lease.
-- ============================================================================

ALTER TABLE scans ADD COLUMN IF NOT EXISTS claimed_by text;
ALTER TABLE scans ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;

-- Queue polling index: claim queries filter on status + created_at.
CREATE INDEX IF NOT EXISTS idx_scans_status_created
  ON scans (status, created_at ASC);

-- Partial index for lease expiry checks on running scans.
CREATE INDEX IF NOT EXISTS idx_scans_lease
  ON scans (lease_expires_at)
  WHERE status = 'running';
