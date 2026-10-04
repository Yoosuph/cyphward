-- Subscription + invoice model (billing follow-up; provider NOT wired).
--
-- Plans were enforced from `organizations.plan` text with no subscription
-- state. This adds the server-side commercial record: one subscription
-- row per org (plan, status, billing period, provider) plus an invoices
-- ledger. `provider` stays 'manual' until a real provider (Paystack /
-- Flutterwave) is integrated behind backend/app/billing/provider.py —
-- no code path calls any payment network today.

CREATE TABLE IF NOT EXISTS subscriptions (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id                uuid NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  plan                  text NOT NULL DEFAULT 'scale'
                        CONSTRAINT subscriptions_plan_check
                        CHECK (plan IN ('growth', 'scale', 'sovereign')),
  status                text NOT NULL DEFAULT 'trialing'
                        CONSTRAINT subscriptions_status_check
                        CHECK (status IN ('trialing', 'active', 'past_due', 'canceled')),
  provider              text NOT NULL DEFAULT 'manual',
  provider_ref          text,
  current_period_start  timestamptz NOT NULL DEFAULT now(),
  current_period_end    timestamptz NOT NULL DEFAULT now() + interval '30 days',
  trial_ends_at         timestamptz,
  cancel_at_period_end  boolean NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_org ON subscriptions (org_id);

CREATE TABLE IF NOT EXISTS invoices (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  number        text NOT NULL UNIQUE DEFAULT ('INV-' || to_char(now(), 'YYYYMMDD') || '-' || substr(md5(random()::text), 1, 6)),
  plan          text NOT NULL,
  amount_kobo   integer NOT NULL CHECK (amount_kobo >= 0),
  currency      text NOT NULL DEFAULT 'NGN',
  status        text NOT NULL DEFAULT 'open'
                CONSTRAINT invoices_status_check
                CHECK (status IN ('open', 'paid', 'void')),
  provider_ref  text,
  period_start  timestamptz NOT NULL DEFAULT now(),
  period_end    timestamptz NOT NULL DEFAULT now() + interval '30 days',
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices (org_id, created_at DESC);

ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON subscriptions;
CREATE POLICY cyphward_app_all ON subscriptions FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON invoices;
CREATE POLICY cyphward_app_all ON invoices FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);
