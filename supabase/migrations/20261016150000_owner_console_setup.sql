-- Owner console: dedicated admin logins and first-sign-in setup.
--
--   platform_owners.console_only  the login exists only for the owner console:
--                                 it cannot sign in to the customer app and
--                                 "forgot password" never emails it.
--   owner_setups                  a time-boxed first sign-in: the operator-set
--                                 password works once, only to choose a new
--                                 password and enrol an authenticator.
--   owner_sessions.purpose        'setup' sessions can only finish setup.
--
-- Additive. Rows are created only by an operator (see docs/owner-console.md).
BEGIN;

ALTER TABLE platform_owners ADD COLUMN IF NOT EXISTS console_only boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS owner_setups (
  user_id      uuid PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  completed_at timestamptz
);
ALTER TABLE owner_setups ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON owner_setups;
CREATE POLICY cyphward_app_all ON owner_setups FOR ALL TO cyphward_app USING (true) WITH CHECK (true);
REVOKE ALL ON owner_setups FROM cyphward_app;
GRANT SELECT ON owner_setups TO cyphward_app;
GRANT UPDATE (completed_at) ON owner_setups TO cyphward_app;

ALTER TABLE owner_sessions ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'console';
ALTER TABLE owner_sessions DROP CONSTRAINT IF EXISTS owner_sessions_purpose_check;
ALTER TABLE owner_sessions ADD CONSTRAINT owner_sessions_purpose_check CHECK (purpose IN ('console', 'setup'));

COMMIT;
