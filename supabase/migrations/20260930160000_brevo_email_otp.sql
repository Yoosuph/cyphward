-- Cyphward email OTP verification — Brevo-delivered 6-digit codes.
-- Supabase auth stays silent (mailer_autoconfirm on); verification is ours.

-- Track verification per account (existing rows backfilled: they were created
-- under Supabase's own confirmation flow and must not be re-gated).
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS email_verified_at timestamptz;

UPDATE profiles SET email_verified_at = now() WHERE email_verified_at IS NULL;

-- One-time codes: hash only, never the plaintext code.
CREATE TABLE IF NOT EXISTS email_otps (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  code_hash  text NOT NULL,
  attempts   int NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_otps_user_created
  ON email_otps (user_id, created_at DESC);

-- Backend-only table: enable RLS with no policies => anon/authenticated denied.
ALTER TABLE email_otps ENABLE ROW LEVEL SECURITY;
