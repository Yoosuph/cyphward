-- TOTP authenticator-app support (MFA follow-up).
--
-- `totp_secret_enc` holds the Fernet-encrypted base32 seed (never
-- plaintext); a row with a secret but NULL `totp_enrolled_at` is a
-- pending enrollment awaiting its confirmation code. Table privileges
-- already cover the new columns via cyphward_app_all (no GRANT change).
ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS totp_secret_enc text,
  ADD COLUMN IF NOT EXISTS totp_enrolled_at timestamptz;
