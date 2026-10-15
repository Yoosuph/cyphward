-- Apply before the v3 scoring API/Core. Additive: retain legacy measurements;
-- NULL means no defensible score, never substitute zero or 100.
BEGIN;
ALTER TABLE score_snapshots ALTER COLUMN score DROP NOT NULL;
ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS assessment_coverage jsonb;
COMMIT;
