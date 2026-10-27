-- Newsletter: double opt-in subscribers and send-once issues (docs/newsletter/README.md).
--
--   newsletter_subscribers  one row per normalised address: the consent record (time, wording version,
--                           source page) and salted hashes of the confirm and unsubscribe tokens. No
--                           raw token, no name, nothing else about the person.
--   newsletter_issues       drafts written by GrokBot and the one send of each. A claim column
--                           (send_claimed_at) makes the send once-only; a trigger keeps it that way.
--   audit                   sends and drafts are written to the existing append-only audit_log
--                           (resource_type 'newsletter_issue'); no new audit table.
--
-- Additive and idempotent. Apply before the API that uses it. NEWSLETTER_ENABLED defaults to off, so
-- applying this changes nothing for anyone until the flag is switched on.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email_normalised         text NOT NULL UNIQUE
                           CHECK (email_normalised = lower(btrim(email_normalised))
                                  AND char_length(email_normalised) BETWEEN 3 AND 254
                                  AND position('@' IN email_normalised) > 1),
  status                   text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'unsubscribed')),
  consent_at               timestamptz NOT NULL,
  consent_wording_version  text NOT NULL CHECK (char_length(consent_wording_version) BETWEEN 1 AND 40),
  source                   text NOT NULL CHECK (source ~ '^[a-z_]{1,40}$'),
  token_generation         integer NOT NULL DEFAULT 1 CHECK (token_generation >= 1),
  confirm_token_hash       text CHECK (confirm_token_hash IS NULL OR confirm_token_hash ~ '^s1\$[0-9a-f]{32}\$[0-9a-f]{64}$'),
  confirm_expires_at       timestamptz,
  unsubscribe_token_hash   text CHECK (unsubscribe_token_hash IS NULL OR unsubscribe_token_hash ~ '^s1\$[0-9a-f]{32}\$[0-9a-f]{64}$'),
  confirmed_at             timestamptz,
  unsubscribed_at          timestamptz,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'pending' OR (confirm_token_hash IS NOT NULL AND confirm_expires_at IS NOT NULL)),
  CHECK (status <> 'confirmed' OR confirmed_at IS NOT NULL),
  CHECK (status <> 'unsubscribed' OR unsubscribed_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_confirmed
  ON newsletter_subscribers (confirmed_at, id) WHERE status = 'confirmed';

CREATE TABLE IF NOT EXISTS newsletter_issues (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status             text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent')),
  subject            text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 120),
  preview            text NOT NULL CHECK (char_length(preview) BETWEEN 1 AND 160),
  body_json          jsonb NOT NULL CHECK (jsonb_typeof(body_json) = 'object' AND pg_column_size(body_json) <= 65536),
  created_by         text NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 40),
  created_at         timestamptz NOT NULL DEFAULT now(),
  sent_at            timestamptz,
  brevo_campaign_id  text CHECK (brevo_campaign_id IS NULL OR brevo_campaign_id ~ '^[0-9A-Za-z_-]{1,40}$'),
  approved_by        uuid,
  approved_at        timestamptz,
  send_claimed_at    timestamptz,
  send_error         text CHECK (send_error IS NULL OR char_length(send_error) <= 600),
  CHECK (status <> 'sent' OR (sent_at IS NOT NULL AND send_claimed_at IS NOT NULL AND brevo_campaign_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_newsletter_issues_created ON newsletter_issues (created_at DESC);

-- Send once, at the database too: a claim cannot be cleared or moved, a campaign id cannot change once
-- recorded, a sent issue stays sent, and a draft's content never changes after it is written.
CREATE OR REPLACE FUNCTION newsletter_issues_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.send_claimed_at IS NOT NULL AND NEW.send_claimed_at IS DISTINCT FROM OLD.send_claimed_at THEN
    RAISE EXCEPTION 'newsletter issue % send claim is final', OLD.id;
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

DROP TRIGGER IF EXISTS newsletter_issues_guard ON newsletter_issues;
CREATE TRIGGER newsletter_issues_guard BEFORE UPDATE ON newsletter_issues
  FOR EACH ROW EXECUTE FUNCTION newsletter_issues_guard();

ALTER TABLE newsletter_subscribers ENABLE ROW LEVEL SECURITY;
ALTER TABLE newsletter_issues ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON newsletter_subscribers;
CREATE POLICY cyphward_app_all ON newsletter_subscribers FOR ALL TO cyphward_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS cyphward_app_all ON newsletter_issues;
CREATE POLICY cyphward_app_all ON newsletter_issues FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

-- Convention: REVOKE ALL, then only what is needed. Supabase's default privileges give anon and
-- authenticated ALL on new tables (TRUNCATE included), which row-level security does not stop.
-- service_role is left alone on purpose (Supabase's admin credential, never given to the API).
REVOKE ALL ON newsletter_subscribers FROM PUBLIC;
REVOKE ALL ON newsletter_issues FROM PUBLIC;
REVOKE ALL ON FUNCTION newsletter_issues_guard() FROM PUBLIC;

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON newsletter_subscribers FROM %I', r);
      EXECUTE format('REVOKE ALL ON newsletter_issues FROM %I', r);
      EXECUTE format('REVOKE ALL ON FUNCTION newsletter_issues_guard() FROM %I', r);
    END IF;
  END LOOP;
END $$;

-- The app role never deletes. Subscribers: read, add, change status. Issues: read, add, and update only
-- the send columns (content is fixed once written; the trigger enforces it as well).
REVOKE ALL ON newsletter_subscribers FROM cyphward_app;
GRANT SELECT, INSERT, UPDATE ON newsletter_subscribers TO cyphward_app;
REVOKE ALL ON newsletter_issues FROM cyphward_app;
GRANT SELECT, INSERT ON newsletter_issues TO cyphward_app;
GRANT UPDATE (status, sent_at, brevo_campaign_id, approved_by, approved_at, send_claimed_at, send_error)
  ON newsletter_issues TO cyphward_app;

COMMIT;
