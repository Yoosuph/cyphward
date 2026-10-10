-- Deploy before the v2 API/worker. Preserve legacy history; do not rewrite
-- old measurements or compare them against the new model.
BEGIN;
ALTER TABLE scans ALTER COLUMN score TYPE numeric(5,1) USING score::numeric(5,1);
ALTER TABLE score_snapshots ALTER COLUMN score TYPE numeric(5,1) USING score::numeric(5,1);
ALTER TABLE score_snapshots
    ADD COLUMN IF NOT EXISTS model text NOT NULL DEFAULT 'cyphward-risk-v1',
    ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'domain',
    ADD COLUMN IF NOT EXISTS risk_points integer;
CREATE INDEX IF NOT EXISTS idx_score_snapshots_model_scope
    ON score_snapshots (org_id, model, scope, created_at DESC, id DESC);
COMMIT;
