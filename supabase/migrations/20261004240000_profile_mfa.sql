-- Per-user MFA opt-in (settings control; review P2 follow-up).
--
-- Admins always step up at password login. Any other user may enroll
-- voluntarily: login then also requires the email step-up code.
-- Table privileges already cover the new column via the existing
-- cyphward_app_all table policy (no GRANT change needed).
ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS mfa_enrolled_at timestamptz;
