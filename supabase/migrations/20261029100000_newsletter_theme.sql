-- Newsletter: the email style (light or dark) the admin chose when sending an issue.
--
--   newsletter_issues.send_theme  'light' (the default, and every issue sent before this) or 'dark'. Written by
--                                 the send claim's single conditional UPDATE (core/newsletter.py claim_issue),
--                                 so it is set once, together with send_claimed_at, and a second request
--                                 matches no row and cannot change it.
--   newsletter_issues_guard()     replaced with the same checks as 20261026100000_newsletter.sql plus one: once
--                                 an issue is claimed, send_theme is final. The claim itself (send_claimed_at
--                                 NULL before the UPDATE) still sets it. CREATE OR REPLACE keeps the function's
--                                 owner and privileges (no EXECUTE for anyone but the owner) and its trigger.
--
-- Additive and idempotent: a new column with a default and a stricter trigger function; nothing dropped. RLS is
-- unchanged. The app role's UPDATE on newsletter_issues is granted per column (20261026100000_newsletter.sql), so
-- the claim needs UPDATE on this one column as well.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE newsletter_issues
  ADD COLUMN IF NOT EXISTS send_theme text NOT NULL DEFAULT 'light' CHECK (send_theme IN ('light', 'dark'));

GRANT UPDATE (send_theme) ON newsletter_issues TO cyphward_app;

-- Send once, at the database too: a claim cannot be cleared or moved, a campaign id cannot change once
-- recorded, a sent issue stays sent, the email style is fixed by the claim, and a draft's content never
-- changes after it is written.
CREATE OR REPLACE FUNCTION newsletter_issues_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.send_claimed_at IS NOT NULL AND NEW.send_claimed_at IS DISTINCT FROM OLD.send_claimed_at THEN
    RAISE EXCEPTION 'newsletter issue % send claim is final', OLD.id;
  END IF;
  IF OLD.send_claimed_at IS NOT NULL AND NEW.send_theme IS DISTINCT FROM OLD.send_theme THEN
    RAISE EXCEPTION 'newsletter issue % email style is final', OLD.id;
  END IF;
  IF OLD.brevo_campaign_id IS NOT NULL AND NEW.brevo_campaign_id IS DISTINCT FROM OLD.brevo_campaign_id THEN
    RAISE EXCEPTION 'newsletter issue % campaign id is final', OLD.id;
  END IF;
  IF OLD.status = 'sent' AND NEW.status <> 'sent' THEN
    RAISE EXCEPTION 'newsletter issue % was sent', OLD.id;
  END IF;
  IF NEW.subject IS DISTINCT FROM OLD.subject OR NEW.preview IS DISTINCT FROM OLD.preview
     OR NEW.body_json IS DISTINCT FROM OLD.body_json OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
    RAISE EXCEPTION 'newsletter issue % content is final', OLD.id;
  END IF;
  RETURN NEW;
END;
$$;

COMMIT;
