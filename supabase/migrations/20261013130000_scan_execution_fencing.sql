-- Additive execution authority. Deploy with the coordinated protocol-v2
-- rollout in the Packet 02 runbook; legacy evidence is intentionally untouched.
ALTER TABLE scans
  ADD COLUMN IF NOT EXISTS claim_generation bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS claim_token text,
  ADD COLUMN IF NOT EXISTS observation_generation bigint,
  ADD COLUMN IF NOT EXISTS execution_phase text
    CHECK (execution_phase IN ('worker', 'local', 'core'));

ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS attempt_generation bigint;
CREATE UNIQUE INDEX IF NOT EXISTS scan_results_attempt_stage
  ON scan_results (scan_id, attempt_generation, stage)
  WHERE attempt_generation IS NOT NULL;

ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS scan_id uuid
  REFERENCES scans(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS score_snapshots_assessment
  ON score_snapshots (scan_id) WHERE scan_id IS NOT NULL;

ALTER TABLE cron_runs
  ADD COLUMN IF NOT EXISTS claim_generation bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS claim_token text,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
