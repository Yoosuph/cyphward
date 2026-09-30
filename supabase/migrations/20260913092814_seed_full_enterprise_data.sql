-- ============================================================================
-- Cyphward — Full Enterprise Multi-Framework Catalog & Real Data Migration
-- ============================================================================

DO $$
DECLARE
  v_tenant_id uuid := '00000000-0000-0000-0000-000000000001'::uuid;
BEGIN
  -- 1. Sync Frameworks with exact UI keys & control counts
  INSERT INTO frameworks (key, name, description, controls_count, passing_count) VALUES
    ('NDPA 2023', 'Nigeria Data Protection Act 2023', 'Statutory data protection framework enforced by the NDPC', 18, 14),
    ('CBN Framework', 'CBN Risk-Based Cybersecurity Framework', 'Mandatory security governance for financial institutions and PSPs', 6, 4),
    ('NITDA', 'NITDA Information Technology Guidelines', 'National Information Technology Development Agency baseline standards', 7, 5),
    ('ISO 27001', 'ISO/IEC 27001:2022', 'Information security management system international standard', 8, 6)
  ON CONFLICT (key) DO UPDATE SET
    controls_count = EXCLUDED.controls_count,
    passing_count = EXCLUDED.passing_count,
    name = EXCLUDED.name,
    description = EXCLUDED.description;

  -- 2. NDPA 2023 Controls
  INSERT INTO controls (id, tenant_id, framework_key, name, status, last_reviewed, owner, evidence) VALUES
    ('NDPA-2(1)', v_tenant_id, 'NDPA 2023', 'Lawful basis for processing', 'PASS', '2025-06-02', 'Legal', 'RoPA v3 — lawful basis documented for all 41 datasets.'),
    ('NDPA-2(3)', v_tenant_id, 'NDPA 2023', 'Consent records retained', 'PASS', '2025-06-02', 'Legal', 'Consent ledger export — 12,840 timestamped entries.'),
    ('NDPA-24(1)', v_tenant_id, 'NDPA 2023', 'Breach notification SLA', 'FAIL', '2025-06-28', 'DPO Office', 'No automated path to the NDPC; manual workflow measured at 9 days in tabletop test.'),
    ('NDPA-24(2)', v_tenant_id, 'NDPA 2023', 'Breach register maintained', 'PASS', '2025-06-02', 'DPO Office', 'Register holds 2 historic entries, both closed.'),
    ('NDPA-23(1)', v_tenant_id, 'NDPA 2023', 'DPO appointment', 'FAIL', '2025-06-28', 'Executive', 'No DPO registered with the Commission; responsibility unassigned.'),
    ('NDPA-23(2)', v_tenant_id, 'NDPA 2023', 'DPO contact published', 'PENDING', '2025-05-15', 'Compliance', 'Placeholder contact page staged, awaiting appointment.'),
    ('NDPA-28', v_tenant_id, 'NDPA 2023', 'Data subject request workflow', 'PASS', '2025-06-10', 'Compliance', 'DSR portal live; median fulfilment 3.1 days.'),
    ('NDPA-33', v_tenant_id, 'NDPA 2023', 'Privacy notice (EN / HA)', 'PASS', '2025-04-20', 'Legal', 'Notices published in English and Hausa.'),
    ('NDPA-39', v_tenant_id, 'NDPA 2023', 'Cross-border transfer safeguards', 'PASS', '2025-06-02', 'Legal', 'Standard contractual clauses executed with 2 processors.'),
    ('NDPA-42', v_tenant_id, 'NDPA 2023', 'Data retention schedule', 'PASS', '2025-05-30', 'Compliance', 'Retention matrix applied across 41 datasets.'),
    ('NDPA-19', v_tenant_id, 'NDPA 2023', 'Security of processing', 'PASS', '2025-06-15', 'Engineering', 'Encryption at rest and in transit verified across the estate.'),
    ('NDPA-20', v_tenant_id, 'NDPA 2023', 'Processor contracts', 'PASS', '2025-05-22', 'Legal', 'All 6 processors under NDPA-compliant clauses.'),
    ('NDPA-26', v_tenant_id, 'NDPA 2023', 'DPIA for new products', 'PASS', '2025-06-19', 'Product', 'DPIA completed for the payments feature.'),
    ('NDPA-35(1)', v_tenant_id, 'NDPA 2023', 'Incident escalation path', 'PENDING', '2025-05-15', 'Ops', 'Escalation chart drafted; on-call rota not yet mapped.'),
    ('NDPA-35(2)', v_tenant_id, 'NDPA 2023', 'Quarterly incident exercise', 'PASS', '2025-06-30', 'Ops', 'Tabletop executed 2025-06-28 — findings logged.'),
    ('NDPA-41', v_tenant_id, 'NDPA 2023', 'Records of processing', 'PASS', '2025-06-02', 'Compliance', 'RoPA v3 current as of June.'),
    ('NDPA-43', v_tenant_id, 'NDPA 2023', 'Audit trail integrity', 'PASS', '2025-06-15', 'Engineering', 'Append-only logs with hash chaining.'),
    ('NDPA-48', v_tenant_id, 'NDPA 2023', 'Regulatory reporting channel', 'PASS', '2025-04-20', 'Compliance', 'NDPC portal credentials secured in vault.')
  ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    framework_key = EXCLUDED.framework_key,
    status = EXCLUDED.status,
    last_reviewed = EXCLUDED.last_reviewed,
    owner = EXCLUDED.owner,
    evidence = EXCLUDED.evidence;

  -- 3. CBN Framework Controls
  INSERT INTO controls (id, tenant_id, framework_key, name, status, last_reviewed, owner, evidence) VALUES
    ('CBN-SEC-2(1)', v_tenant_id, 'CBN Framework', 'Customer data encrypted at rest', 'PASS', '2025-06-11', 'Engineering', 'AES-256 verified on all customer stores.'),
    ('CBN-SEC-3(2)', v_tenant_id, 'CBN Framework', 'Channel transaction monitoring', 'PASS', '2025-06-11', 'Engineering', 'Realtime monitoring live on all channels.'),
    ('CBN-SEC-5(1)', v_tenant_id, 'CBN Framework', 'Incident reporting to CBN', 'PASS', '2025-05-08', 'Ops', 'Reporting template aligned to circular.'),
    ('CBN-SEC-6(4)', v_tenant_id, 'CBN Framework', 'Third-party connectivity review', 'PENDING', '2025-04-30', 'Ops', 'Two vendor links awaiting annual review.'),
    ('CBN-SEC-7(2)', v_tenant_id, 'CBN Framework', 'SIM-binding controls for USSD', 'FAIL', '2025-06-28', 'Engineering', 'SIM-change re-binding not enforced within 24h.'),
    ('CBN-SEC-9(1)', v_tenant_id, 'CBN Framework', 'Annual penetration test', 'PASS', '2025-03-15', 'Engineering', 'External pentest 2025-02 — 3 findings, all closed.')
  ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    framework_key = EXCLUDED.framework_key,
    status = EXCLUDED.status,
    last_reviewed = EXCLUDED.last_reviewed,
    owner = EXCLUDED.owner,
    evidence = EXCLUDED.evidence;

  -- 4. NITDA Guidelines Controls
  INSERT INTO controls (id, tenant_id, framework_key, name, status, last_reviewed, owner, evidence) VALUES
    ('NITDA-G-1.3', v_tenant_id, 'NITDA', 'Data inventory maintained', 'PASS', '2025-06-02', 'Compliance', 'Inventory synced from CMDB weekly.'),
    ('NITDA-G-2.1', v_tenant_id, 'NITDA', 'ISMS scope documented', 'PASS', '2025-05-12', 'Compliance', 'Scope statement v2 covers Kano estate.'),
    ('NITDA-G-3.4', v_tenant_id, 'NITDA', 'Quarterly access review', 'PENDING', '2025-05-15', 'Ops', 'Q2 review scheduled for July.'),
    ('NITDA-G-4.2', v_tenant_id, 'NITDA', 'Backup and restore drill', 'PASS', '2025-06-06', 'Ops', 'Restore drill passed — RTO 41 minutes.'),
    ('NITDA-G-5.1', v_tenant_id, 'NITDA', 'Vulnerability scan cadence', 'PASS', '2025-06-15', 'Engineering', 'Weekly scans, SLA 14 days.'),
    ('NITDA-G-6.3', v_tenant_id, 'NITDA', 'Security awareness program', 'PASS', '2025-06-30', 'Compliance', 'Academy enrolment at 92%.'),
    ('NITDA-G-7.2', v_tenant_id, 'NITDA', 'Vendor risk register', 'FAIL', '2025-06-28', 'Legal', 'Register exists; 3 vendors unscored.')
  ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    framework_key = EXCLUDED.framework_key,
    status = EXCLUDED.status,
    last_reviewed = EXCLUDED.last_reviewed,
    owner = EXCLUDED.owner,
    evidence = EXCLUDED.evidence;

  -- 5. ISO 27001 Controls
  INSERT INTO controls (id, tenant_id, framework_key, name, status, last_reviewed, owner, evidence) VALUES
    ('ISO-A.5.1', v_tenant_id, 'ISO 27001', 'Information security policy', 'PASS', '2025-05-02', 'Compliance', 'Policy v4 approved by the board.'),
    ('ISO-A.5.9', v_tenant_id, 'ISO 27001', 'Asset inventory', 'PASS', '2025-06-02', 'Engineering', 'CMDB coverage 97%.'),
    ('ISO-A.6.3', v_tenant_id, 'ISO 27001', 'Security awareness training', 'PASS', '2025-06-30', 'Compliance', 'Tracked via Academy — 92% complete.'),
    ('ISO-A.8.16', v_tenant_id, 'ISO 27001', 'Incident management', 'PASS', '2025-06-15', 'Ops', 'IR playbook v3 in force.'),
    ('ISO-A.8.24', v_tenant_id, 'ISO 27001', 'Cryptographic controls', 'PASS', '2025-06-15', 'Engineering', 'Key rotation cadence enforced.'),
    ('ISO-A.5.19', v_tenant_id, 'ISO 27001', 'Supplier relationships', 'PENDING', '2025-05-15', 'Legal', 'Supplier controls clause rollout 60%.'),
    ('ISO-A.5.31', v_tenant_id, 'ISO 27001', 'Legal, statutory requirements', 'PASS', '2025-04-20', 'Legal', 'NDPA and CBN obligations mapped.'),
    ('ISO-A.5.36', v_tenant_id, 'ISO 27001', 'Independent compliance audit', 'FAIL', '2025-06-28', 'Executive', 'Last independent audit 19 months ago.')
  ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    framework_key = EXCLUDED.framework_key,
    status = EXCLUDED.status,
    last_reviewed = EXCLUDED.last_reviewed,
    owner = EXCLUDED.owner,
    evidence = EXCLUDED.evidence;

  -- 6. Remediations
  INSERT INTO remediations (id, tenant_id, title, severity, control_id, owner, due, status) VALUES
    ('rem_01', v_tenant_id, 'Automate NDPC breach notification (72h SLA)', 'CRITICAL', 'NDPA-24(1)', 'A. Bello — DPO Office', '2025-07-18', 'OPEN'),
    ('rem_02', v_tenant_id, 'Appoint and register a Data Protection Officer', 'HIGH', 'NDPA-23(1)', 'M. Okafor — Legal', '2025-07-25', 'OPEN'),
    ('rem_03', v_tenant_id, 'Publish DPO contact on the public register', 'MEDIUM', 'NDPA-23(2)', 'T. Adeyemi — Compliance', '2025-08-04', 'OPEN'),
    ('rem_04', v_tenant_id, 'Re-run quarterly incident tabletop exercise', 'LOW', 'NDPA-35(1)', 'K. Danjuma — Ops', '2025-08-15', 'OPEN')
  ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title,
    severity = EXCLUDED.severity,
    control_id = EXCLUDED.control_id,
    owner = EXCLUDED.owner,
    due = EXCLUDED.due,
    status = EXCLUDED.status;

  -- 7. Complete Detection Alerts & Rich Details
  INSERT INTO alerts (id, tenant_id, title, category, technique, severity, time, status, entity, confidence, summary, actions, timeline, evidence, related) VALUES
    (
      'alt_01',
      v_tenant_id,
      'Phishing — Hausa-language lure over SMS and email',
      'PHISHING',
      'T1566',
      'CRITICAL',
      '09:41:07',
      'OPEN',
      'kano-03 / 3 mailboxes',
      0.94,
      'Hausa-language credential lure delivered to three finance mailboxes via SMS and email. L4 AfroNLP classified the payload intent as credential theft; L5 LLM triage escalated with high confidence. One handset (kano-03) followed the link.',
      '[
        {"label":"Quarantine","toast":"Quarantine issued — kano-03 isolated from the estate"},
        {"label":"Block sender","toast":"Sender blocked at gateway — 3 addresses on the deny list"},
        {"label":"Notify user","toast":"Users notified — 3 advisories sent in Hausa and English"}
      ]'::jsonb,
      '[
        {"t":"09:38:12","label":"SMS lure delivered to 3 handsets"},
        {"t":"09:40:11","label":"kano-03 followed the link to the credential form"},
        {"t":"09:40:58","label":"L4 AfroNLP — Hausa payload, intent = credential theft"},
        {"t":"09:41:07","label":"L5 LLM triage — confidence 0.94, escalate"},
        {"t":"09:41:09","label":"Alert opened; kano-03 held pending action"}
      ]'::jsonb,
      '[
        "09:38:12 sms src=MTN-GW dst=finance×3 body_sha=9f3a…c1e lang=ha",
        "09:40:11 http kano-03 → hxxp://nnpc-careers[.]ng cred_form",
        "09:40:58 afro-nlp intent=\"credential_theft\" lang=ha conf=0.91",
        "09:41:07 llm_triage verdict=\"escalate\" conf=0.94"
      ]'::jsonb,
      '[{"id":"alt_05","label":"Beaconing from the same host — kano-03"}]'::jsonb
    ),
    (
      'alt_02',
      v_tenant_id,
      'SIM-swap attempt on CFO line',
      'SIM-SWAP',
      'SIM-swap',
      'HIGH',
      '09:12:44',
      'TRIAGED',
      'MTN +234…8011',
      0.88,
      'Repeated re-activation attempts against the CFO line, consistent with SIM-swap rehearsal. Carrier pattern flagged by L2; the line is frozen pending callback verification.',
      '[
        {"label":"Freeze line","toast":"Line frozen — re-activation blocked at carrier"},
        {"label":"Verify callback","toast":"Callback verification task created for the DPO office"},
        {"label":"Notify carrier","toast":"Carrier abuse desk notified — case reference logged"}
      ]'::jsonb,
      '[
        {"t":"09:09:02","label":"Failed re-activation attempt #1"},
        {"t":"09:11:36","label":"Failed re-activation attempt #2 — velocity flag"},
        {"t":"09:12:44","label":"L2 anomaly — SIM-swap pattern, escalate"}
      ]'::jsonb,
      '[
        "09:09:02 ussd act=reactivate msisdn=+234…8011 result=fail",
        "09:11:36 ussd act=reactivate msisdn=+234…8011 result=fail",
        "09:12:44 ml_anomaly label=\"sim_swap\" conf=0.88"
      ]'::jsonb,
      '[{"id":"alt_03","label":"USSD anomaly on the same gateway window"}]'::jsonb
    ),
    (
      'alt_03',
      v_tenant_id,
      'USSD transaction anomaly — velocity spike',
      'USSD ANOMALY',
      '—',
      'MEDIUM',
      '08:57:19',
      'OPEN',
      'ussd-gw-2',
      0.71,
      'Transaction velocity on ussd-gw-2 exceeded baseline by 6.4σ for a six-minute window. No fraud pattern matched yet; anomaly persists under watch.',
      '[
        {"label":"Throttle gateway","toast":"ussd-gw-2 throttled to baseline velocity"},
        {"label":"Challenge transfers","toast":"Step-up challenge applied to high-value transfers"}
      ]'::jsonb,
      '[
        {"t":"08:51:14","label":"Velocity crossed 4σ — watch mode"},
        {"t":"08:57:19","label":"Velocity crossed 6.4σ — anomaly opened"}
      ]'::jsonb,
      '[
        "08:51:14 velocity ussd-gw-2 sigma=4.1 tx/min=212",
        "08:57:19 velocity ussd-gw-2 sigma=6.4 tx/min=318"
      ]'::jsonb,
      '[]'::jsonb
    ),
    (
      'alt_04',
      v_tenant_id,
      'Malware dropped via invoice attachment',
      'MALWARE',
      'T1204',
      'MEDIUM',
      '08:44:02',
      'CONTAINED',
      'kano-01',
      0.96,
      'Macro payload delivered in a fake supplier invoice was blocked at execution by the endpoint agent. Hash matches known commodity stealer.',
      '[
        {"label":"Purge file","toast":"File purged from disk across all endpoints"},
        {"label":"Scan fleet","toast":"Full-fleet scan scheduled — 48 hosts queued"}
      ]'::jsonb,
      '[
        {"t":"08:43:51","label":"Attachment saved to disk by user"},
        {"t":"08:44:02","label":"Execution blocked — heuristic signature match"}
      ]'::jsonb,
      '[
        "08:43:51 file /Users/…/Downloads/invoice_NG_6421.xlsm sha=e4c2…",
        "08:44:02 endpoint block_action=terminate proc=excel.exe"
      ]'::jsonb,
      '[]'::jsonb
    ),
    (
      'alt_05',
      v_tenant_id,
      'Periodic beaconing to unclassified host',
      'BEACONING',
      'T1071',
      'HIGH',
      '08:30:55',
      'OPEN',
      'kano-03 → 185.220.x.x',
      0.82,
      'Regular 120-second outbound beacon observed from kano-03 to a non-reputable external address. Host was previously flagged under alt_01.',
      '[
        {"label":"Null-route IP","toast":"IP null-routed at edge — 185.220.x.x dropped"},
        {"label":"Capture traffic","toast":"PCAP capture active on kano-03 egress (10m window)"}
      ]'::jsonb,
      '[
        {"t":"08:12:00","label":"First outbound SYN to 185.220.x.x:443"},
        {"t":"08:30:55","label":"Periodicity confirmed (jitter < 3%) — alert opened"}
      ]'::jsonb,
      '[
        "08:12:00 net dst=185.220.x.x:443 proto=tcp state=established",
        "08:30:55 beacon_det period=120s jitter=2.1% conf=0.82"
      ]'::jsonb,
      '[{"id":"alt_01","label":"Phishing alert on the same host — kano-03"}]'::jsonb
    )
  ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title,
    category = EXCLUDED.category,
    technique = EXCLUDED.technique,
    severity = EXCLUDED.severity,
    time = EXCLUDED.time,
    status = EXCLUDED.status,
    entity = EXCLUDED.entity,
    confidence = EXCLUDED.confidence,
    summary = EXCLUDED.summary,
    actions = EXCLUDED.actions,
    timeline = EXCLUDED.timeline,
    evidence = EXCLUDED.evidence,
    related = EXCLUDED.related;

END;
$$;
