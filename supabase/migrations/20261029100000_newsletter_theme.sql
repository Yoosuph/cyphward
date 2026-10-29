-- Newsletter: the email style (light or dark) the admin chose when sending an issue.
--
--   newsletter_issues.send_theme  'light' (the default, and every issue sent before this) or 'dark'. Written by
--                                 the send claim's single conditional UPDATE (core/newsletter.py claim_issue),
--                                 so it is set once, together with send_claimed_at, and a second request
--                                 matches no row and cannot change it.
--
-- Additive and idempotent: a new column with a default, nothing dropped or rewritten. RLS is unchanged.
-- The app role's UPDATE on newsletter_issues is granted per column (20261026100000_newsletter.sql), so the
-- claim needs UPDATE on this one column as well; nothing else changes.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE newsletter_issues
  ADD COLUMN IF NOT EXISTS send_theme text NOT NULL DEFAULT 'light' CHECK (send_theme IN ('light', 'dark'));

GRANT UPDATE (send_theme) ON newsletter_issues TO cyphward_app;

COMMIT;
