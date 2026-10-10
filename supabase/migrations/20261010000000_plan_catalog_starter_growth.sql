-- Canonical plan catalog: starter + growth (review: onboarding plans).
--
-- Marketing, onboarding, billing and quotas now share one catalog.
-- Retired tiers (scale/sovereign/Enterprise Defense) map to growth so
-- existing tenants keep working; no row is left outside the new allowlist.

UPDATE organizations
SET plan = CASE lower(plan)
             WHEN 'scale' THEN 'growth'
             WHEN 'sovereign' THEN 'growth'
             WHEN 'enterprise defense' THEN 'growth'
             ELSE plan
           END
WHERE lower(plan) NOT IN ('starter', 'growth');

UPDATE organizations
SET plan = 'growth'
WHERE plan NOT IN ('starter', 'growth');

UPDATE subscriptions
SET plan = 'growth', updated_at = now()
WHERE plan NOT IN ('starter', 'growth');

ALTER TABLE organizations ALTER COLUMN plan SET DEFAULT 'growth';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'organizations_plan_check') THEN
    ALTER TABLE organizations DROP CONSTRAINT organizations_plan_check;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'organizations_plan_check') THEN
    ALTER TABLE organizations
      ADD CONSTRAINT organizations_plan_check
      CHECK (plan IN ('starter', 'growth'));
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'subscriptions_plan_check') THEN
    ALTER TABLE subscriptions DROP CONSTRAINT subscriptions_plan_check;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'subscriptions_plan_check') THEN
    ALTER TABLE subscriptions
      ADD CONSTRAINT subscriptions_plan_check
      CHECK (plan IN ('starter', 'growth'));
  END IF;
END $$;
