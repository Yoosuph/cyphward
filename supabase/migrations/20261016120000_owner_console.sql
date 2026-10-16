-- Owner console (admin.cyphward.com): the platform owner's see-everything
-- access, separate from customer accounts. See backend/app/core/owner.py.
--
--   platform_owners  who is an owner. The app role can only READ it (plus
--                    update last_totp_step for replay protection): owners are
--                    added/removed only by an operator with database access.
--   owner_sessions   console sessions (SHA-256 of the cookie token only).
--   owner_audit      append-only record of owner sign-ins and actions. No
--                    foreign keys, so deleting a customer cannot erase it.
--
-- Additive. Apply before the API that uses it; until then owner endpoints
-- fail closed (500/503) and nothing else changes.
BEGIN;

CREATE TABLE IF NOT EXISTS platform_owners (
  user_id        uuid PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  note           text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_totp_step bigint
);

CREATE TABLE IF NOT EXISTS owner_sessions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  token_hash   text NOT NULL UNIQUE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  user_agent   text,
  ip           text
);
CREATE INDEX IF NOT EXISTS idx_owner_sessions_user ON owner_sessions (user_id);

CREATE TABLE IF NOT EXISTS owner_audit (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id uuid,
  actor_email   text,
  session_id    uuid,
  action        text NOT NULL,
  outcome       text NOT NULL,
  target_type   text,
  target_id     text,
  ip            text,
  user_agent    text,
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_owner_audit_created ON owner_audit (created_at DESC);

-- RLS on with only the app role's policy (anon/authenticated denied).
ALTER TABLE platform_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner_sessions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner_audit     ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON platform_owners;
CREATE POLICY cyphward_app_all ON platform_owners FOR ALL TO cyphward_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS cyphward_app_all ON owner_sessions;
CREATE POLICY cyphward_app_all ON owner_sessions FOR ALL TO cyphward_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS cyphward_app_all ON owner_audit;
CREATE POLICY cyphward_app_all ON owner_audit FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Default privileges give the app role full DML on new tables; narrow them.
REVOKE ALL ON platform_owners FROM cyphward_app;
GRANT SELECT ON platform_owners TO cyphward_app;
GRANT UPDATE (last_totp_step) ON platform_owners TO cyphward_app;

REVOKE ALL ON owner_sessions FROM cyphward_app;
GRANT SELECT, INSERT, UPDATE ON owner_sessions TO cyphward_app;

REVOKE ALL ON owner_audit FROM cyphward_app;
GRANT SELECT, INSERT ON owner_audit TO cyphward_app;

COMMIT;
