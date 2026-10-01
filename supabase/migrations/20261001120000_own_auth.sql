-- Own authentication (Supabase Auth removed): credentials + sessions live here.
ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS password_hash text,
  ADD COLUMN IF NOT EXISTS provider text NOT NULL DEFAULT 'email';

-- Refresh tokens (rotating) + one-time Google exchange codes. Hashes only.
CREATE TABLE IF NOT EXISTS auth_sessions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  refresh_token_hash text NOT NULL,
  otc_hash           text,
  otc_expires_at     timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL,
  revoked_at         timestamptz,
  last_used_at       timestamptz
);
CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS auth_sessions_refresh_idx ON auth_sessions (refresh_token_hash);

-- Single-use, short-lived password reset links (Brevo-delivered).
CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  token_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  used_at    timestamptz
);
CREATE INDEX IF NOT EXISTS password_reset_tokens_user_idx ON password_reset_tokens (user_id);
