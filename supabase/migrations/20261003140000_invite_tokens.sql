-- Tokenized, single-use invitations (review P0-2).
--
-- The previous flow created a profile AND granted organization_members at
-- invite time; /auth/register then adopted the row by matching the unverified
-- email, so anyone who knew the address could claim an outstanding invite.
-- Now: invite stores a time-limited, single-use token (hash only). The
-- membership row is created exclusively by POST /members/invites/accept,
-- which requires an authenticated account with the same email and a
-- verified email address.
CREATE TABLE IF NOT EXISTS organization_invites (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  email            text NOT NULL,
  full_name        text,
  role             text NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  token_hash       text NOT NULL,
  invited_by       uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  accepted_at      timestamptz,
  accepted_user_id uuid REFERENCES profiles(id) ON DELETE SET NULL,
  revoked_at       timestamptz
);

-- One live invitation per (org, email); accepted/revoked rows stay for audit.
CREATE UNIQUE INDEX IF NOT EXISTS organization_invites_pending_uniq
  ON organization_invites (org_id, lower(email))
  WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS organization_invites_token_hash_idx
  ON organization_invites (token_hash);

-- Same no-policy RLS posture as the tenant tables: the Data API roles get no
-- direct access; only the server path (service role) touches these rows.
ALTER TABLE organization_invites ENABLE ROW LEVEL SECURITY;
