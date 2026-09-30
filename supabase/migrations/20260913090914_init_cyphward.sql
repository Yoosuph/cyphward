-- ============================================================================
-- Cyphward — Supabase Core Migration
-- Aligned with CYPHWARD-PRD.md v1.0
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "citext";

-- ---------------------------------------------------------------------------
-- 1. Tenancy & Organization
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id         citext NOT NULL UNIQUE,
  legal_name        text NOT NULL,
  cac_rc            text,
  sector            text NOT NULL DEFAULT 'ecommerce',
  region            text NOT NULL DEFAULT 'ng-kano',
  plan              text NOT NULL DEFAULT 'Growth',
  primary_locale    text NOT NULL DEFAULT 'en',
  hitl_threshold    numeric(3,2) NOT NULL DEFAULT 0.75,
  staff_bucket      text NOT NULL DEFAULT '1-50',
  flags             jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS profiles (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE,
  email         text NOT NULL,
  full_name     text,
  role          text NOT NULL DEFAULT 'dpo',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 2. Posture & Live Scoring (Score Pillar)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS postures (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,
  score                 int NOT NULL DEFAULT 742,
  max_score             int NOT NULL DEFAULT 1000,
  trend                 int NOT NULL DEFAULT 12,
  framework             text NOT NULL DEFAULT 'NDPA 2023',
  passing_controls      int NOT NULL DEFAULT 14,
  total_controls        int NOT NULL DEFAULT 18,
  training_completion   int NOT NULL DEFAULT 92,
  open_alerts           int NOT NULL DEFAULT 5,
  critical_alerts       int NOT NULL DEFAULT 1,
  critical_label        text NOT NULL DEFAULT 'PHISHING — T1566',
  open_remediations     int NOT NULL DEFAULT 4,
  signals_today         int NOT NULL DEFAULT 12480,
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scores (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,
  score         int NOT NULL DEFAULT 742,
  max_score     int NOT NULL DEFAULT 1000,
  trend         int NOT NULL DEFAULT 12,
  subscores     jsonb NOT NULL DEFAULT '[]'::jsonb,
  factors       jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 3. Compliance & Governance (Comply Pillar)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS frameworks (
  key           text PRIMARY KEY,
  name          text NOT NULL,
  description   text,
  controls_count int NOT NULL DEFAULT 0,
  passing_count  int NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS controls (
  id            text PRIMARY KEY,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE,
  framework_key text REFERENCES frameworks(key) ON DELETE CASCADE,
  name          text NOT NULL,
  status        text NOT NULL DEFAULT 'PASS',
  last_reviewed text NOT NULL,
  owner         text NOT NULL,
  evidence      text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS remediations (
  id            text PRIMARY KEY,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE,
  title         text NOT NULL,
  severity      text NOT NULL,
  control_id    text,
  owner         text NOT NULL,
  due           text NOT NULL,
  status        text NOT NULL DEFAULT 'OPEN',
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS policy_drafts (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE,
  control_id    text NOT NULL,
  title         text NOT NULL,
  content       text NOT NULL,
  status        text NOT NULL DEFAULT 'draft',
  version       int NOT NULL DEFAULT 1,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4. Threat Detection & Response (Detect Pillar)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
  id            text PRIMARY KEY,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE,
  title         text NOT NULL,
  category      text NOT NULL,
  technique     text NOT NULL,
  severity      text NOT NULL,
  time          text NOT NULL,
  status        text NOT NULL DEFAULT 'OPEN',
  entity        text NOT NULL,
  confidence    numeric(3,2) NOT NULL DEFAULT 0.90,
  summary       text,
  actions       jsonb NOT NULL DEFAULT '[]'::jsonb,
  timeline      jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence      jsonb NOT NULL DEFAULT '[]'::jsonb,
  related       jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS detection_layers (
  id            text PRIMARY KEY,
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE,
  name          text NOT NULL,
  detail        text NOT NULL,
  hits          int NOT NULL DEFAULT 0,
  state         text NOT NULL DEFAULT 'ACTIVE',
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 5. Training & Phishing Simulation (Academy Pillar)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS academy_courses (
  id            text PRIMARY KEY,
  title         text NOT NULL,
  lang          text NOT NULL DEFAULT 'EN',
  progress      int NOT NULL DEFAULT 0,
  minutes       int NOT NULL DEFAULT 10,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS academy_meta (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,
  sim           jsonb NOT NULL DEFAULT '{}'::jsonb,
  leaderboard   jsonb NOT NULL DEFAULT '[]'::jsonb,
  heatmap       jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 6. AI Copilot Knowledge & Threat Ticker
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS copilot_knowledge (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question      text NOT NULL,
  answer        text NOT NULL,
  sources       jsonb NOT NULL DEFAULT '[]'::jsonb,
  actions       jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS threat_ticker (
  id            text PRIMARY KEY,
  time          text NOT NULL,
  label         text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 7. Row-Level Security Policies (Open read/write for MVP tenant isolation)
-- ---------------------------------------------------------------------------
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE postures ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE frameworks ENABLE ROW LEVEL SECURITY;
ALTER TABLE controls ENABLE ROW LEVEL SECURITY;
ALTER TABLE remediations ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE detection_layers ENABLE ROW LEVEL SECURITY;
ALTER TABLE academy_courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE academy_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE copilot_knowledge ENABLE ROW LEVEL SECURITY;
ALTER TABLE threat_ticker ENABLE ROW LEVEL SECURITY;

-- Allow anon and authenticated access for client interactions
CREATE POLICY "Public read tenants" ON tenants FOR SELECT USING (true);
CREATE POLICY "Public all profiles" ON profiles FOR ALL USING (true);
CREATE POLICY "Public all postures" ON postures FOR ALL USING (true);
CREATE POLICY "Public all scores" ON scores FOR ALL USING (true);
CREATE POLICY "Public read frameworks" ON frameworks FOR SELECT USING (true);
CREATE POLICY "Public all controls" ON controls FOR ALL USING (true);
CREATE POLICY "Public all remediations" ON remediations FOR ALL USING (true);
CREATE POLICY "Public all policy_drafts" ON policy_drafts FOR ALL USING (true);
CREATE POLICY "Public all alerts" ON alerts FOR ALL USING (true);
CREATE POLICY "Public all detection_layers" ON detection_layers FOR ALL USING (true);
CREATE POLICY "Public all academy_courses" ON academy_courses FOR ALL USING (true);
CREATE POLICY "Public all academy_meta" ON academy_meta FOR ALL USING (true);
CREATE POLICY "Public read copilot_knowledge" ON copilot_knowledge FOR SELECT USING (true);
CREATE POLICY "Public all threat_ticker" ON threat_ticker FOR ALL USING (true);

-- ---------------------------------------------------------------------------
-- 8. Stored Procedures / RPC Functions for Autonomous Operations
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION draft_policy(p_control_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_ctrl RECORD;
  v_draft_id uuid;
  v_title text;
  v_content text;
BEGIN
  SELECT * INTO v_ctrl FROM controls WHERE id = p_control_id LIMIT 1;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'Control not found');
  END IF;

  v_title := 'Automated Policy: ' || v_ctrl.name;
  v_content := 'This policy establishes mandatory operational safeguards under NDPA 2023 / ' 
               || v_ctrl.framework_key || ' for ' || v_ctrl.id || '. '
               || 'Automated enforcement, periodic audit trail logging, and continuous compliance telemetry are required.';

  INSERT INTO policy_drafts (tenant_id, control_id, title, content, status)
  VALUES (v_ctrl.tenant_id, p_control_id, v_title, v_content, 'draft')
  RETURNING id INTO v_draft_id;

  RETURN jsonb_build_object(
    'ok', true,
    'draft_id', v_draft_id,
    'control', p_control_id,
    'title', v_title
  );
END;
$$;

CREATE OR REPLACE FUNCTION triage_alert(p_alert_id text, p_new_status text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE alerts 
  SET status = p_new_status, updated_at = now()
  WHERE id = p_alert_id;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'Alert not found');
  END IF;

  RETURN jsonb_build_object('ok', true, 'id', p_alert_id, 'status', p_new_status);
END;
$$;

CREATE OR REPLACE FUNCTION update_control_status(p_control_id text, p_status text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_tenant_id uuid;
  v_fw text;
  v_passing int;
  v_total int;
BEGIN
  UPDATE controls
  SET status = p_status, last_reviewed = to_char(now(), 'YYYY-MM-DD'), updated_at = now()
  WHERE id = p_control_id
  RETURNING tenant_id, framework_key INTO v_tenant_id, v_fw;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'Control not found');
  END IF;

  -- Re-calculate counts for framework
  SELECT count(*), count(*) FILTER (WHERE status = 'PASS')
  INTO v_total, v_passing
  FROM controls
  WHERE framework_key = v_fw AND tenant_id = v_tenant_id;

  UPDATE frameworks
  SET controls_count = v_total, passing_count = v_passing
  WHERE key = v_fw;

  -- Update posture
  UPDATE postures
  SET passing_controls = v_passing, total_controls = v_total, updated_at = now()
  WHERE tenant_id = v_tenant_id;

  RETURN jsonb_build_object('ok', true, 'id', p_control_id, 'status', p_status, 'passing', v_passing, 'total', v_total);
END;
$$;

-- ---------------------------------------------------------------------------
-- 9. Seed Data (Acme Traders Ltd Kano & Complete PRD Catalogs)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  v_tenant_id uuid := '00000000-0000-0000-0000-000000000001'::uuid;
BEGIN
  -- 1. Tenant
  INSERT INTO tenants (id, public_id, legal_name, cac_rc, sector, region, plan, primary_locale)
  VALUES (v_tenant_id, 'acme-traders-kano', 'Acme Traders Ltd (Kano)', 'RC-1849204', 'ecommerce', 'ng-kano', 'Growth', 'ha')
  ON CONFLICT (id) DO NOTHING;

  -- 2. Posture
  INSERT INTO postures (tenant_id, score, max_score, trend, framework, passing_controls, total_controls, training_completion, open_alerts, critical_alerts, critical_label, open_remediations, signals_today)
  VALUES (v_tenant_id, 742, 1000, 12, 'NDPA 2023', 14, 18, 92, 5, 1, 'PHISHING — T1566', 4, 12480)
  ON CONFLICT (tenant_id) DO NOTHING;

  -- 3. Scores
  INSERT INTO scores (tenant_id, score, max_score, trend, subscores, factors)
  VALUES (
    v_tenant_id,
    742,
    1000,
    12,
    '[
      {"key":"external","label":"EXTERNAL","value":810,"max":1000,"delta":9},
      {"key":"compliance","label":"COMPLIANCE","value":780,"max":1000,"delta":-24},
      {"key":"threat","label":"THREAT EXPOSURE","value":690,"max":1000,"delta":-6},
      {"key":"training","label":"TRAINING","value":720,"max":1000,"delta":6},
      {"key":"darkweb","label":"DARKWEB","value":850,"max":1000,"delta":15}
    ]'::jsonb,
    '[
      {"label":"DarkWeb exposure cleared — 40 credential mentions actioned with the takedown workflow","delta":18},
      {"label":"Two controls failed at quarterly review (NDPA-24(1), NDPA-23(1))","delta":-48},
      {"label":"Academy training completion up 6 points across all departments","delta":21},
      {"label":"Phishing simulation — reporting rate reached 88%","delta":14},
      {"label":"One critical alert open beyond 24 hours (phishing, T1566)","delta":-7},
      {"label":"External TLS certificates renewed on all *.acmetraders.ng endpoints","delta":8}
    ]'::jsonb
  )
  ON CONFLICT (tenant_id) DO NOTHING;

  -- 4. Frameworks
  INSERT INTO frameworks (key, name, description, controls_count, passing_count) VALUES
    ('NDPA 2023', 'Nigeria Data Protection Act 2023', 'Statutory data protection framework enforced by the NDPC', 18, 14),
    ('NDPR', 'Nigeria Data Protection Regulation 2019', 'NITDA NDPR baseline compliance rules', 12, 10),
    ('CBN Cybersecurity Framework', 'CBN Risk-Based Cybersecurity Framework', 'Mandatory security governance for financial institutions and PSPs', 24, 19),
    ('CBN Open Banking', 'CBN Regulatory Framework for Open Banking in Nigeria', 'API authentication, consent management, and data sharing standards', 15, 11),
    ('ISO 27001', 'ISO/IEC 27001:2022', 'Information security management system international standard', 28, 22),
    ('PCI-DSS', 'Payment Card Industry Data Security Standard v4.0', 'Cardholder data environment protections', 16, 13)
  ON CONFLICT (key) DO NOTHING;

  -- 5. Controls (NDPA 2023)
  INSERT INTO controls (id, tenant_id, framework_key, name, status, last_reviewed, owner, evidence) VALUES
    ('NDPA-24(1)', v_tenant_id, 'NDPA 2023', 'Duty to respect data subject rights (access, erasure, portability)', 'FAIL', '2026-08-14', 'Legal / DPO', 'SAR log missing 2 request closures within the 30-day statutory window'),
    ('NDPA-24(2)', v_tenant_id, 'NDPA 2023', 'Transparent privacy notice in clear language (English + Hausa)', 'PASS', '2026-08-20', 'Marketing', 'Privacy notice v3.2 published and bilingual; reviewed by external counsel'),
    ('NDPA-25', v_tenant_id, 'NDPA 2023', 'Lawful basis for processing personal and special-category data', 'PASS', '2026-07-30', 'Compliance', 'RoPA updated with explicit consent logs for all customer onboarding channels'),
    ('NDPA-28', v_tenant_id, 'NDPA 2023', 'Data Protection Impact Assessment (DPIA) for high-risk processing', 'PASS', '2026-06-11', 'Security Lead', 'DPIA signed for AWS migration and mobile wallet integrations'),
    ('NDPA-32', v_tenant_id, 'NDPA 2023', 'Designation of a certified Data Protection Officer (DPO)', 'PASS', '2026-05-02', 'HR / Legal', 'DPO appointed, certified with NDPC registration number verified'),
    ('NDPA-39', v_tenant_id, 'NDPA 2023', 'Security of processing (encryption at rest + in transit, AES-256)', 'PASS', '2026-08-01', 'DevOps', 'TLS 1.3 enforced, RDS volume encryption enabled with KMS customer managed key'),
    ('NDPA-40', v_tenant_id, 'NDPA 2023', '72-hour mandatory breach notification to NDPC', 'PASS', '2026-07-15', 'Incident Team', 'Playbook tested in tabletop drill Q2 2026; template synced with NDPC portal'),
    ('NDPA-41', v_tenant_id, 'NDPA 2023', 'Data subject notification in case of high-risk security breach', 'PASS', '2026-07-15', 'Comms', 'Customer notification workflow active; bilingual SMS and email templates'),
    ('NDPA-43', v_tenant_id, 'NDPA 2023', 'Cross-border data transfer adequacy assessment', 'PASS', '2026-04-18', 'Legal', 'Standard contractual clauses verified for EU SaaS vendors'),
    ('NDPA-48', v_tenant_id, 'NDPA 2023', 'Record of Processing Activities (RoPA) maintenance', 'PASS', '2026-08-10', 'DPO', 'RoPA register current; reviewed quarterly by internal audit'),
    ('NDPA-52', v_tenant_id, 'NDPA 2023', 'Vendor and third-party data processor due diligence', 'PASS', '2026-06-25', 'Procurement', 'DPAs signed with 14 active vendors; 2 under renewal review'),
    ('NDPA-17', v_tenant_id, 'NDPA 2023', 'Child data processing consent verification', 'PASS', '2026-03-12', 'Compliance', 'Age verification gate implemented; parental consent workflow operational'),
    ('NDPA-23(1)', v_tenant_id, 'NDPA 2023', 'Technical and organizational measures against accidental loss', 'FAIL', '2026-08-12', 'Infrastructure', 'Disaster recovery failover test overdue by 45 days'),
    ('NDPA-23(2)', v_tenant_id, 'NDPA 2023', 'Regular testing, assessing and evaluating of security effectiveness', 'PASS', '2026-07-28', 'SecOps', 'Quarterly vulnerability scan and penetration test completed by CREST vendor'),
    ('NDPA-30', v_tenant_id, 'NDPA 2023', 'Data minimization and storage limitation policy', 'PASS', '2026-05-19', 'Engineering', 'Automated S3 lifecycle rule purges raw audit telemetry older than 365 days'),
    ('NDPA-31', v_tenant_id, 'NDPA 2023', 'Accuracy of personal data and rectification mechanism', 'PASS', '2026-06-03', 'Product', 'Self-service profile update portal operational in mobile app and web console'),
    ('NDPA-35', v_tenant_id, 'NDPA 2023', 'Employee cybersecurity and privacy awareness training', 'PASS', '2026-08-22', 'People Ops', 'Cyphward Academy completion at 92% across all departments'),
    ('NDPA-38', v_tenant_id, 'NDPA 2023', 'Physical access controls to processing facilities', 'PASS', '2026-02-14', 'Facilities', 'Biometric door locks and CCTV operational at Kano headquarters data room')
  ON CONFLICT (id) DO NOTHING;

  -- 6. Remediations
  INSERT INTO remediations (id, tenant_id, title, severity, control_id, owner, due, status) VALUES
    ('rem_01', v_tenant_id, 'Resolve 2 overdue Data Subject Access Requests (DSARs)', 'CRITICAL', 'NDPA-24(1)', 'Balarabe (Legal)', '2026-09-18', 'OPEN'),
    ('rem_02', v_tenant_id, 'Execute semi-annual Disaster Recovery drill and archive proof', 'HIGH', 'NDPA-23(1)', 'Aminu (DevOps)', '2026-09-25', 'OPEN'),
    ('rem_03', v_tenant_id, 'Rotate stale service account tokens for Paystack webhook ingest', 'MEDIUM', 'NDPA-39', 'Zainab (Backend)', '2026-10-02', 'OPEN'),
    ('rem_04', v_tenant_id, 'Re-screen 2 third-party delivery contractors on data handling', 'LOW', 'NDPA-52', 'Procurement Team', '2026-10-15', 'OPEN')
  ON CONFLICT (id) DO NOTHING;

  -- 7. Detection Layers
  INSERT INTO detection_layers (id, tenant_id, name, detail, hits, state) VALUES
    ('L1', v_tenant_id, 'ENDPOINT TELEMETRY', 'Fleet osquery daemon telemetry across 48 laptops and 6 staging instances', 184, 'ACTIVE'),
    ('L2', v_tenant_id, 'CLOUD & IDENTITY', 'AWS CloudTrail, IAM privilege escalation, and Google Workspace sign-in audit', 92, 'ACTIVE'),
    ('L3', v_tenant_id, 'NETWORK & REPUTATION', 'Real-time threat feed ingestion from ngCERT, AlienVault OTX, and abuse.ch', 340, 'ACTIVE'),
    ('L4', v_tenant_id, 'AFRO-THREAT ML', 'Multilingual NLP models detecting Hausa/Pidgin phishing and SIM-swap patterns', 67, 'ACTIVE'),
    ('L5', v_tenant_id, 'AUTONOMOUS PLAYBOOKS', 'Automated containment rules with Human-In-The-Loop (HITL) safeguard gates', 15, 'ACTIVE')
  ON CONFLICT (id) DO NOTHING;

  -- 8. Alerts
  INSERT INTO alerts (id, tenant_id, title, category, technique, severity, time, status, entity, confidence, summary, actions, timeline, evidence, related) VALUES
    (
      'alt_01',
      v_tenant_id,
      'Spear Phishing with Malicious Payroll Macro (Hausa & English)',
      'INITIAL_ACCESS',
      'T1566.001',
      'CRITICAL',
      '14 mins ago',
      'OPEN',
      'finance-laptop-04.kano.acmetraders.ng',
      0.96,
      'Incoming email impersonating Kano State Internal Revenue Service (KIRS) containing password-protected zip file with VBA payload executing rundll32.exe.',
      '[{"label":"Isolate Host","toast":"Command sent: host isolation issued via osquery daemon"},{"label":"Revoke OAuth Token","toast":"Google Workspace session revoked for user"}]'::jsonb,
      '[{"t":"10:12:04","label":"SMTP gateway flagged attachment payload hash (T1566)"},{"t":"10:13:22","label":"Endpoint osquery observed suspicious rundll32 spawn"},{"t":"10:14:01","label":"Cyphward L4 NLP flagged Hausa urgency phrasing score 0.98"}]'::jsonb,
      '["SHA256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","Subject: Gagaggawan Biya: KIRS Tax Clearance Certificate Confirmation","Source IP: 102.164.12.89 (Lagos, Nigeria — MTN AS37075)"]'::jsonb,
      '[{"id":"alt_04","label":"SIM-Swap alert on finance director phone"},{"id":"rem_01","label":"Audit item NDPA-39 encryption requirement"}]'::jsonb
    ),
    (
      'alt_02',
      v_tenant_id,
      'SIM-Swap Fraud Sequence on Verified Authorizer Phone',
      'CREDENTIAL_ACCESS',
      'T1111',
      'HIGH',
      '42 mins ago',
      'TRIAGED',
      'MSISDN: +234 803 291 0021',
      0.91,
      'Telco change notification received for company signatory line followed immediately by OTP request to online banking gateway.',
      '[{"label":"Freeze Approvals","toast":"Signatory authorization suspended across payment switches"},{"label":"Notify Bank","toast":"Automated incident notice dispatched to First Bank of Nigeria"}]'::jsonb,
      '[{"t":"09:44:10","label":"Carrier telemetry reported IMSI change in Kaduna"},{"t":"09:47:33","label":"Web portal OTP request submitted from unknown IP"},{"t":"09:48:00","label":"Cyphward rule SIM-SWAP-SEQ-01 triggered alert"}]'::jsonb,
      '["Carrier: MTN Nigeria","IMSI changed: 621300948291002 -> 621300948999124","Attempted login from: 105.112.44.12"]'::jsonb,
      '[{"id":"alt_01","label":"Spear phishing attempt targeting finance laptop"}]'::jsonb
    ),
    (
      'alt_03',
      v_tenant_id,
      'AWS S3 Bucket Policy Alteration (Unrestricted Public Read)',
      'DEFENSE_EVASION',
      'T1562.001',
      'HIGH',
      '2 hours ago',
      'CONTAINED',
      'arn:aws:s3:::acme-traders-backup-kano',
      0.99,
      'CloudTrail logged PutBucketPolicy API call removing Principal IP restrictions from database backup bucket. Remediated automatically by L5 playbook.',
      '[{"label":"Restore Baseline Policy","toast":"Baseline IAM policy re-applied successfully"}]'::jsonb,
      '[{"t":"08:15:20","label":"PutBucketPolicy executed by user aminud@acmetraders.ng"},{"t":"08:15:24","label":"Cyphward L2 policy auditor detected public read wildcard"},{"t":"08:15:26","label":"L5 auto-remediation restored locked-down bucket policy"}]'::jsonb,
      '["Bucket: acme-traders-backup-kano","Action: s3:PutBucketPolicy","Caller ARN: arn:aws:iam::849201948201:user/aminud"]'::jsonb,
      '[]'::jsonb
    ),
    (
      'alt_04',
      v_tenant_id,
      'High Volume USSD Session Requests Exceeding Rate Threshold',
      'DENIAL_OF_SERVICE',
      'T1499',
      'MEDIUM',
      '4 hours ago',
      'CONTAINED',
      'USSD Channel: *737*99#',
      0.88,
      'Over 2,400 balance inquiry sessions generated within 6 minutes from contiguous phone prefixes. Rate limiter throttled traffic.',
      '[]'::jsonb,
      '[{"t":"06:12:00","label":"USSD aggregator API traffic spike detected"},{"t":"06:14:15","label":"Anomaly score 8.4 triggered auto-throttle"}]'::jsonb,
      '["Channel: Aggregator Gateway Link 2","Requests/sec: 420 (Normal: 12)"]'::jsonb,
      '[]'::jsonb
    ),
    (
      'alt_05',
      v_tenant_id,
      'Credential Stuffing Attack Detected Against Web Customer Portal',
      'CREDENTIAL_ACCESS',
      'T1110.004',
      'LOW',
      '7 hours ago',
      'CONTAINED',
      'https://portal.acmetraders.ng/login',
      0.94,
      '1,200 failed sign-in attempts against 140 accounts from Tor exit node cluster. WAF IP block list triggered.',
      '[]'::jsonb,
      '[{"t":"03:00:12","label":"Failed login surge across 140 usernames"},{"t":"03:02:00","label":"Cloudflare WAF IP reputation challenge engaged"}]'::jsonb,
      '["Source: Distributed Tor network","Success rate: 0.0%"]'::jsonb,
      '[]'::jsonb
    )
  ON CONFLICT (id) DO NOTHING;

  -- 9. Academy Courses
  INSERT INTO academy_courses (id, title, lang, progress, minutes) VALUES
    ('crs_01', 'Recognizing Local Phishing (SMS, WhatsApp, Email) in English & Pidgin', 'PCM', 100, 15),
    ('crs_02', 'Tsaron Bayanai na Kasuwanci da Kiyaye Sauya SIM (Hausa)', 'HA', 95, 20),
    ('crs_03', 'NDPA 2023 Fundamentals for Frontline Staff', 'EN', 88, 25),
    ('crs_04', 'Secure Mobile Banking & USSD Hygiene for Agents', 'EN', 84, 15)
  ON CONFLICT (id) DO NOTHING;

  -- 10. Academy Meta
  INSERT INTO academy_meta (tenant_id, sim, leaderboard, heatmap)
  VALUES (
    v_tenant_id,
    '{"name":"Q3 2026 Spear-Phishing Drill","clicked":4,"reported":42,"sent":48,"window":"Active — Day 4 of 7"}'::jsonb,
    '[
      {"rank":1,"name":"Zainab Mustapha","dept":"Finance & Billing","points":980},
      {"rank":2,"name":"Aliyu Umar","dept":"Logistics (Kano Hub)","points":945},
      {"rank":3,"name":"Chiamaka Eze","dept":"Customer Operations","points":910},
      {"rank":4,"name":"Ibrahim Sani","dept":"Warehouse & Inventory","points":875}
    ]'::jsonb,
    '{
      "depts":["Finance","Operations","Customer Support","Engineering","Executive"],
      "months":["May","Jun","Jul","Aug","Sep"],
      "cells":[[78,82,85,91,96],[65,70,74,80,88],[70,75,81,86,92],[90,92,94,97,99],[60,65,72,78,85]]
    }'::jsonb
  )
  ON CONFLICT (tenant_id) DO NOTHING;

  -- 11. Copilot Knowledge Base
  INSERT INTO copilot_knowledge (question, answer, sources, actions) VALUES
    (
      'What are our statutory breach reporting requirements under NDPA 2023?',
      'Under **Section 40 of the Nigeria Data Protection Act 2023**, the data controller or processor must notify the **Nigeria Data Protection Commission (NDPC)** within **72 hours** of becoming aware of a personal data breach likely to cause risk to rights and freedoms. If high risk, affected individuals must also be notified without undue delay under **Section 41**.',
      '[{"id":"src_01","label":"NDPA 2023 Act, Part V, Section 40 & 41"},{"id":"src_02","label":"Cyphward Breach Playbook (NDPC-72H-V2)"}]'::jsonb,
      '[{"label":"Draft NDPC Notification","kind":"solid","toast":"NDPC 72-Hour template draft generated"},{"label":"Review High-Risk Assets","kind":"ghost","toast":"Redirecting to asset inventory"}]'::jsonb
    ),
    (
      'How does Cyphward calculate our 0-1000 cyber risk score?',
      'The Cyphward score is calculated using 5 weighted sub-dimensions: **External Attack Surface (25%)**, **Regulatory Compliance (25%)**, **Threat Exposure & Alert Velocity (25%)**, **Workforce Training & Simulation (15%)**, and **DarkWeb / Credential Exposure (10%)**. It updates continuously as new signals and control audits arrive.',
      '[{"id":"src_03","label":"Cyphward Scoring Engine Specification v1.0"},{"id":"src_04","label":"CBN Risk-Based Framework Guidance"}]'::jsonb,
      '[{"label":"View Score Breakdown","kind":"solid","toast":"Navigating to Score detail page"}]'::jsonb
    ),
    (
      'What automated action does Cyphward take when an L4 SIM-swap alert fires?',
      'When an L4 SIM-Swap sequence is detected, Cyphward automatically signals the **Human-In-The-Loop (HITL) queue**, temporarily locks high-value payment authorizer privileges via API switches, dispatches bilingual SMS verification to the out-of-band secondary contact, and logs the chain into the tamper-proof audit trail.',
      '[{"id":"src_05","label":"Playbook PB-SIMSWAP-01"},{"id":"src_06","label":"AfroSec-Bench Threat Model"}]'::jsonb,
      '[{"label":"Inspect Active SIM Alerts","kind":"solid","toast":"Filtering alerts by T1111"}]'::jsonb
    );

  -- 12. Threat Ticker
  INSERT INTO threat_ticker (id, time, label) VALUES
    ('tck_01', '10:14:02', 'L4 AfroSec Model: Spear-phishing email intercepted (Hausa text, payroll impersonation)'),
    ('tck_02', '10:02:44', 'ngCERT Advisory: Banking Trojan variant active across West African IP ranges'),
    ('tck_03', '09:48:19', 'L4 Telemetry: SIM-swap sequence flagged on +234 803 291 0021'),
    ('tck_04', '09:30:11', 'L1 Fleet: osquery check completed — 54 of 54 endpoints healthy'),
    ('tck_05', '08:15:26', 'L5 Playbook: S3 bucket public access policy automatically revoked'),
    ('tck_06', '07:44:00', 'Score Engine: Updated daily score to 742/1000 (+12 trend)')
  ON CONFLICT (id) DO NOTHING;

END;
$$;
