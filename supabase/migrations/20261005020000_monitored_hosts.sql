-- Manually monitored hosts (scan-scope registration).
--
-- Passive discovery misses real hosts (no CT footprint yet, wildcard
-- certs, fresh DNS). Owners/admins can register hostnames under a
-- VERIFIED domain; every scan then probes them regardless of passive
-- discovery. Scope is enforced in the API (hostname must be the domain
-- itself or its subdomain) and re-checked by the worker's scope filter.
-- Composite (org_id, domain_id) FK keeps the tenant relationship exact.

CREATE TABLE IF NOT EXISTS monitored_hosts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id   uuid NOT NULL,
  hostname    text NOT NULL,
  added_by    uuid REFERENCES profiles(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, hostname),
  CONSTRAINT monitored_hosts_domain_fk
    FOREIGN KEY (org_id, domain_id)
    REFERENCES domains (org_id, id) ON DELETE CASCADE
);

ALTER TABLE monitored_hosts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cyphward_app_all ON monitored_hosts;
CREATE POLICY cyphward_app_all ON monitored_hosts FOR ALL TO cyphward_app
  USING (true) WITH CHECK (true);
