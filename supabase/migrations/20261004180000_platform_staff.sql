-- Platform staff scope (review P1 — workspace authorization, line 32).
--
-- Organization roles (owner/admin/member) never grant cross-tenant rights.
-- Internal support access is a SEPARATE grant in this table, checked by the
-- `require_platform_staff` gate with reason capture and immutable audit.
--
-- Scopes (text array, subset-checked): 'platform:read' (lookup/health).
-- Grants are time-boxed (expires_at) and revoked by setting revoked_at —
-- cyphward_app keeps only a column-scoped UPDATE (revoked_at) on this
-- table, so grants cannot be escalated or deleted through the app role.
-- audit_log becomes append-only for the app role (no UPDATE/DELETE):
-- every tenant-data read/action by staff is an immutable event.

CREATE TABLE IF NOT EXISTS platform_staff (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  scopes      text[] NOT NULL DEFAULT '{}',
  granted_by  uuid REFERENCES profiles(id) ON DELETE SET NULL,
  reason      text NOT NULL,
  expires_at  timestamptz,
  revoked_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_platform_staff_user
  ON platform_staff (user_id) WHERE revoked_at IS NULL;

ALTER TABLE platform_staff ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON platform_staff;
CREATE POLICY cyphward_app_all ON platform_staff FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);

-- Least-privilege tightening for the app role on the two staff/audit tables.
REVOKE UPDATE, DELETE ON platform_staff FROM cyphward_app;
GRANT UPDATE (revoked_at) ON platform_staff TO cyphward_app;
REVOKE UPDATE, DELETE ON audit_log FROM cyphward_app;
