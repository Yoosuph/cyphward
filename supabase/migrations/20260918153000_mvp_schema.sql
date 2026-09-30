-- ============================================================================
-- Cyphward MVP Schema Migration
-- Next.js / React -> FastAPI -> PostgreSQL -> Inngest -> Risk Engine -> Dashboard
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Organizations
CREATE TABLE IF NOT EXISTS organizations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  slug        text UNIQUE NOT NULL,
  cac_rc      text,
  sector      text NOT NULL DEFAULT 'Fintech & Digital Commerce',
  plan        text NOT NULL DEFAULT 'Enterprise Defense',
  api_key     text UNIQUE DEFAULT ('cyph_' || encode(gen_random_bytes(20), 'hex')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 2. Users
CREATE TABLE IF NOT EXISTS users (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email       text UNIQUE NOT NULL,
  full_name   text NOT NULL,
  role        text NOT NULL DEFAULT 'Security Officer',
  avatar_url  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 3. Memberships
CREATE TABLE IF NOT EXISTS memberships (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  role        text NOT NULL DEFAULT 'owner',
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT unique_user_org UNIQUE(user_id, org_id)
);

-- 4. Domains (Verification via DNS TXT Record)
CREATE TABLE IF NOT EXISTS domains (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id              uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain              text NOT NULL,
  verification_status text NOT NULL DEFAULT 'pending', -- 'pending', 'verified', 'failed'
  verification_token  text NOT NULL,
  verified_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT unique_org_domain UNIQUE(org_id, domain)
);

-- 5. Discovered Assets
CREATE TABLE IF NOT EXISTS assets (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id     uuid REFERENCES domains(id) ON DELETE SET NULL,
  hostname      text NOT NULL,
  ip_address    text,
  asset_type    text NOT NULL DEFAULT 'Web Endpoint',
  status        text NOT NULL DEFAULT 'active',
  first_seen    timestamptz NOT NULL DEFAULT now(),
  last_seen     timestamptz NOT NULL DEFAULT now(),
  http_status   int,
  technologies  jsonb NOT NULL DEFAULT '[]'::jsonb,
  tls_info      jsonb NOT NULL DEFAULT '{}'::jsonb,
  dns_records   jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT unique_org_hostname UNIQUE(org_id, hostname)
);

-- 6. Scans (Multi-stage Inngest Pipeline)
CREATE TABLE IF NOT EXISTS scans (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id       uuid REFERENCES domains(id) ON DELETE CASCADE,
  status          text NOT NULL DEFAULT 'queued', -- 'queued', 'running', 'completed', 'failed', 'cancelled'
  score           int,
  stage_progress  jsonb NOT NULL DEFAULT '{
    "discovery": {"status": "pending", "items": 0, "duration_ms": 0},
    "dns": {"status": "pending", "items": 0, "duration_ms": 0},
    "http": {"status": "pending", "items": 0, "duration_ms": 0},
    "security_checks": {"status": "pending", "items": 0, "duration_ms": 0},
    "normalization": {"status": "pending", "items": 0, "duration_ms": 0},
    "scoring": {"status": "pending", "score": null, "duration_ms": 0}
  }'::jsonb,
  current_stage   text DEFAULT 'queued',
  started_at      timestamptz,
  completed_at    timestamptz,
  error_message   text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- 7. Scan Results (Raw Observations)
CREATE TABLE IF NOT EXISTS scan_results (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id     uuid NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  stage       text NOT NULL,
  raw_data    jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- 8. Findings (Categorized Vulnerabilities & Misconfigurations)
CREATE TABLE IF NOT EXISTS findings (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id      uuid REFERENCES scans(id) ON DELETE CASCADE,
  asset_id     uuid REFERENCES assets(id) ON DELETE SET NULL,
  org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  title        text NOT NULL,
  description  text NOT NULL,
  severity     text NOT NULL DEFAULT 'medium', -- 'critical', 'high', 'medium', 'low', 'info'
  category     text NOT NULL DEFAULT 'Security Configuration',
  evidence     jsonb NOT NULL DEFAULT '{}'::jsonb,
  remediation  text NOT NULL,
  status       text NOT NULL DEFAULT 'open', -- 'open', 'resolved', 'suppressed'
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- 9. Score Snapshots (Score History over Time)
CREATE TABLE IF NOT EXISTS score_snapshots (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  domain_id   uuid REFERENCES domains(id) ON DELETE SET NULL,
  score       int NOT NULL,
  subscores   jsonb NOT NULL DEFAULT '[]'::jsonb,
  factors     jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_domains_org ON domains(org_id);
CREATE INDEX IF NOT EXISTS idx_assets_org ON assets(org_id);
CREATE INDEX IF NOT EXISTS idx_assets_domain ON assets(domain_id);
CREATE INDEX IF NOT EXISTS idx_scans_org ON scans(org_id);
CREATE INDEX IF NOT EXISTS idx_scans_domain ON scans(domain_id);
CREATE INDEX IF NOT EXISTS idx_findings_org ON findings(org_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_score_snapshots_org ON score_snapshots(org_id, created_at DESC);
