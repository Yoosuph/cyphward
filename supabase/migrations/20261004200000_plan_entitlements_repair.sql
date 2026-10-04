-- Plan entitlement repair (review P1 — plan enforcement, line 33).
--
-- The onboarding plan selector was sent as `sector`, so organizations that
-- picked Growth/Scale/Sovereign carry the plan NAME in sector with plan
-- stuck at the old database default. Repair those rows, map any other
-- leftover default to the continuity tier, then lock plan to the server
-- allowlist (backend/app/core/plans.py) with a CHECK constraint and a
-- matching column default. Idempotent: a second run matches zero rows.

UPDATE organizations
SET plan = CASE lower(sector)
             WHEN 'growth' THEN 'growth'
             WHEN 'scale' THEN 'scale'
             WHEN 'sovereign' THEN 'sovereign'
           END,
    sector = 'Technology'
WHERE lower(sector) IN ('growth', 'scale', 'sovereign')
  AND plan = 'Enterprise Defense';

UPDATE organizations
SET plan = 'scale'
WHERE plan NOT IN ('growth', 'scale', 'sovereign');

ALTER TABLE organizations ALTER COLUMN plan SET DEFAULT 'scale';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'organizations_plan_check'
  ) THEN
    ALTER TABLE organizations
      ADD CONSTRAINT organizations_plan_check
      CHECK (plan IN ('growth', 'scale', 'sovereign'));
  END IF;
END $$;
