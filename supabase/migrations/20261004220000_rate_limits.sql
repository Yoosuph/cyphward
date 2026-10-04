-- Shared rate limiting + MFA OTP purpose (review P2 — throttling).
--
-- Login, password-reset and welcome cooldowns lived in Python-process
-- memory: invisible across replicas, lost on restart, unbounded growth.
-- `rate_limits` is the shared fixed-window store: one atomic
-- check-and-increment per bucket (see backend/app/core/rate_limit.py),
-- with stale buckets reaped probabilistically so state stays bounded.
-- `email_otps.purpose` separates email verification ('verify') from the
-- admin login step-up ('mfa') so consuming one never completes the other.

CREATE TABLE IF NOT EXISTS rate_limits (
  bucket_key   text PRIMARY KEY,
  window_start timestamptz NOT NULL DEFAULT now(),
  count        integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rate_limits_window
  ON rate_limits (window_start);

ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON rate_limits;
CREATE POLICY cyphward_app_all ON rate_limits FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);

ALTER TABLE email_otps
  ADD COLUMN IF NOT EXISTS purpose text NOT NULL DEFAULT 'verify';
