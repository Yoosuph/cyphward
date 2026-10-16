-- Remembered browsers for the sign-in step-up code (owners/admins + opted-in
-- users). Only a SHA-256 of the cookie token is stored. Rows expire 30 days
-- after creation and are deleted on password reset, MFA/TOTP changes and
-- "forget remembered browsers". Apply before deploying the API that reads it;
-- until then the API fails closed (asks for the code as before).
BEGIN;

CREATE TABLE IF NOT EXISTS trusted_browsers (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  token_hash   text NOT NULL UNIQUE,
  user_agent   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_used_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_trusted_browsers_user ON trusted_browsers (user_id, expires_at);

-- Backend-only: RLS on, with only the app role's policy (anon/authenticated
-- denied). Explicit grant in case the migration runs as a role other than the
-- one whose default privileges cover cyphward_app.
GRANT SELECT, INSERT, UPDATE, DELETE ON trusted_browsers TO cyphward_app;
ALTER TABLE trusted_browsers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON trusted_browsers;
CREATE POLICY cyphward_app_all ON trusted_browsers FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);

COMMIT;
