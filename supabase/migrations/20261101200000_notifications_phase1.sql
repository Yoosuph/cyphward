-- Notifications phase 1 (docs/notifications-phase1/README.md, backend/app/services/notifications.py).
--
--   notifications              extended, not replaced. Existing rows (one per organisation, user_id NULL) are kept
--                              and still shown to every member of that organisation. New rows are one per
--                              recipient per event:
--     user_id                  the recipient. NULL only on rows written before this migration.
--     audience                 'customer' (the customer app) or 'owner' (the owner console). An owner row names the
--                              platform owner as user_id and the organisation the event is about as org_id.
--     category                 the mute bucket (scans, findings, billing, members, organisation, compliance).
--     dedupe_key               the event's key. The unique index below makes a second write of the same event
--                              for the same recipient impossible.
--     group_keys               the keys of later events folded into this row (repeats of one kind within
--                              15 minutes); they are checked as well, so a folded event is never written twice.
--     group_count              how many events the row stands for (1 unless grouped).
--     last_event_at            when the newest folded event happened (the 15-minute window is measured from here).
--     in_app                   false for a row kept only to carry a critical email to someone who muted the
--                              category in the app but not by email; the bell never lists it.
--     email_status             NULL (no email for this row), 'pending', 'sending', 'sent' or 'failed'. Only critical
--                              events whose category the recipient has not muted for email are 'pending'. Delivery
--                              claims a row by moving it to 'sending' first, so a row is emailed at most once.
--   notification_preferences   one row per (user, category) the person has changed. No row means the defaults:
--                              in-app on, email on (email is only ever sent for critical events in phase 1).
--
-- The severity check gains 'warning' (phase 1 writes info, warning and critical); the old values stay allowed so
-- existing rows remain valid. It is re-added NOT VALID, so existing rows are not scanned.
--
-- Additive and idempotent. Every ADD COLUMN has no default or a constant default (no table rewrite). Locks are
-- bounded by lock_timeout. Apply before the code that writes the new columns is deployed.
--
-- Grants, following the newsletter convention: REVOKE ALL first (Supabase's default privileges hand anon and
-- authenticated ALL, TRUNCATE included, which row-level security does not stop), then only what the app needs.
-- The app role never deletes notifications or preferences (an organisation or person being removed cascades).
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE notifications ADD COLUMN IF NOT EXISTS user_id uuid;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'customer';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS category text;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key text;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS group_keys text[] NOT NULL DEFAULT '{}';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS group_count integer NOT NULL DEFAULT 1;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS last_event_at timestamptz;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS in_app boolean NOT NULL DEFAULT true;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_status text;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_attempted_at timestamptz;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_user_id_fkey'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_audience_check'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_audience_check
      CHECK (audience IN ('customer', 'owner')) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_category_format'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_category_format
      CHECK (category IS NULL OR category ~ '^[a-z_]{1,40}$') NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_dedupe_key_length'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_dedupe_key_length
      CHECK (dedupe_key IS NULL OR char_length(dedupe_key) BETWEEN 1 AND 300) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_group_count_positive'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_group_count_positive
      CHECK (group_count >= 1) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_email_status_check'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_email_status_check
      CHECK (email_status IS NULL OR email_status IN ('pending', 'sending', 'sent', 'failed')) NOT VALID;
  END IF;
  -- New rows always name a recipient; rows written before this migration have none.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_keyed_rows_have_recipient'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications ADD CONSTRAINT notifications_keyed_rows_have_recipient
      CHECK (dedupe_key IS NULL OR user_id IS NOT NULL) NOT VALID;
  END IF;
  -- Widen the severity check to include 'warning'. Skipped when the widened check is already in place.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'notifications_severity_phase1'
                 AND conrelid = 'public.notifications'::regclass) THEN
    ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_severity_check;
    ALTER TABLE notifications ADD CONSTRAINT notifications_severity_phase1
      CHECK (severity IN ('info', 'warning', 'critical', 'low', 'medium', 'high')) NOT VALID;
  END IF;
END $$;

-- One row per recipient per event.
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_recipient_dedupe
  ON notifications (audience, user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
-- The bell: a person's rows in one organisation, newest first, and their unread count.
CREATE INDEX IF NOT EXISTS idx_notifications_recipient
  ON notifications (user_id, audience, org_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_recipient_unread
  ON notifications (user_id, audience, org_id) WHERE user_id IS NOT NULL AND read_at IS NULL AND in_app;
-- Folded keys are checked on every write for that recipient.
CREATE INDEX IF NOT EXISTS idx_notifications_group_keys
  ON notifications USING gin (group_keys) WHERE cardinality(group_keys) > 0;
-- The email outbox.
CREATE INDEX IF NOT EXISTS idx_notifications_email_pending
  ON notifications (created_at) WHERE email_status = 'pending';

CREATE TABLE IF NOT EXISTS notification_preferences (
  user_id       uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  category      text NOT NULL CHECK (category ~ '^[a-z_]{1,40}$'),
  in_app_muted  boolean NOT NULL DEFAULT false,
  email_muted   boolean NOT NULL DEFAULT false,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, category)
);

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON notifications;
CREATE POLICY cyphward_app_all ON notifications FOR ALL TO cyphward_app USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS cyphward_app_all ON notification_preferences;
CREATE POLICY cyphward_app_all ON notification_preferences FOR ALL TO cyphward_app USING (true) WITH CHECK (true);

REVOKE ALL ON notifications FROM PUBLIC;
REVOKE ALL ON notification_preferences FROM PUBLIC;

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON notifications FROM %I', r);
      EXECUTE format('REVOKE ALL ON notification_preferences FROM %I', r);
    END IF;
  END LOOP;
END $$;

-- Notifications: read, add, and update only the read, grouping and email columns. Content written by the
-- reviewed templates is replaced only when a later event is folded in (title, body).
REVOKE ALL ON notifications FROM cyphward_app;
GRANT SELECT, INSERT ON notifications TO cyphward_app;
GRANT UPDATE (read_at, title, body, group_keys, group_count, last_event_at, email_status, email_attempted_at,
              email_sent)
  ON notifications TO cyphward_app;
-- Preferences: read, add, change. Never delete.
REVOKE ALL ON notification_preferences FROM cyphward_app;
GRANT SELECT, INSERT ON notification_preferences TO cyphward_app;
GRANT UPDATE (in_app_muted, email_muted, updated_at) ON notification_preferences TO cyphward_app;

COMMIT;
