/* ————————————————————————————————————————————————
   CYPHWARD — all mock data in one module.
   Every number and label on every page comes from here.
   ———————————————————————————————————————————————— */

export interface Tenant { name: string; plan: string; region: string; email?: string }

export interface Posture {
  tenant: string; plan: string;
  score: number; maxScore: number; trend: number;
  compliance: { passing: number; total: number; framework: string };
  trainingCompletion: number;
  openAlerts: number; criticalAlerts: number; criticalLabel: string;
  openRemediations: number;
  signalsToday: number;
}

export interface SubScore { key: string; label: string; value: number; max: number; delta: number }
export interface ScoreFactor { label: string; delta: number }
export interface Score { tenant: string; score: number; max: number; trend: number; subscores: SubScore[]; factors: ScoreFactor[] }

export type ControlStatus = 'PASS' | 'FAIL' | 'PENDING';
export interface Control {
  id: string; name: string; framework: string; status: ControlStatus;
  lastReviewed: string; owner: string; evidence: string;
}
export interface Framework { key: string; controls: number; passing: number }
export interface Remediation {
  id: string; title: string; severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  control: string; owner: string; due: string;
}
export interface ComplianceSummary {
  frameworks: Framework[]; controls: Control[]; passing: number; total: number;
  remediations: Remediation[];
}

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type AlertStatus = 'OPEN' | 'TRIAGED' | 'CONTAINED';
export interface Alert {
  id: string; title: string; category: string; technique: string;
  severity: Severity; time: string; status: AlertStatus; entity: string;
}
export interface AlertAction { label: string; toast: string }
export interface AlertDetail {
  id: string; confidence: number; summary: string;
  actions: AlertAction[];
  timeline: { t: string; label: string }[];
  evidence: string[];
  related: { id: string; label: string }[];
}
export interface DetectionLayer { id: string; name: string; detail: string; hits: number; state: 'ACTIVE' | 'IDLE' }

export interface Course { id: string; title: string; lang: 'EN' | 'HA' | 'PCM'; progress: number; minutes: number }
export interface SimCampaign { name: string; clicked: number; reported: number; sent: number; window: string }
export interface LeaderRow { rank: number; name: string; dept: string; points: number }
export interface Academy {
  courses: Course[]; sim: SimCampaign; leaderboard: LeaderRow[];
  heatmap: { depts: string[]; months: string[]; cells: number[][] };
}

export interface Source { id: string; label: string }
export interface CopilotAction { label: string; kind: 'solid' | 'ghost'; toast: string }
export interface CopilotAnswer { q: string; a: string; sources: Source[]; actions?: CopilotAction[] }
export interface CopilotSession { sources: Source[]; pairs: CopilotAnswer[]; fallback: CopilotAnswer }

export interface TickerItem { id: string; time: string; label: string }

/* ---------- tenant / defaults ---------- */
export const tenant: Tenant = { name: 'Acme Traders Ltd (Kano)', plan: 'Growth', region: 'ng-kano' };
export const DEFAULT_FRAMEWORK = 'NDPA 2023';
export const FIRST_ALERT_ID = 'alt_01';

/* ---------- posture & score ---------- */
export const posture: Posture = {
  tenant: tenant.name,
  plan: tenant.plan,
  score: 742, maxScore: 1000, trend: 12,
  compliance: { passing: 14, total: 18, framework: 'NDPA 2023' },
  trainingCompletion: 92,
  openAlerts: 5, criticalAlerts: 1, criticalLabel: 'PHISHING — T1566',
  openRemediations: 4,
  signalsToday: 12480,
};

export const score: Score = {
  tenant: tenant.name,
  score: 742, max: 1000, trend: 12,
  subscores: [
    { key: 'external', label: 'EXTERNAL', value: 810, max: 1000, delta: 9 },
    { key: 'compliance', label: 'COMPLIANCE', value: 780, max: 1000, delta: -24 },
    { key: 'threat', label: 'THREAT EXPOSURE', value: 690, max: 1000, delta: -6 },
    { key: 'training', label: 'TRAINING', value: 720, max: 1000, delta: 6 },
    { key: 'darkweb', label: 'DARKWEB', value: 850, max: 1000, delta: 15 },
  ],
  factors: [
    { label: 'DarkWeb exposure cleared — 40 credential mentions actioned with the takedown workflow', delta: 18 },
    { label: 'Two controls failed at quarterly review (NDPA-24(1), NDPA-23(1))', delta: -48 },
    { label: 'Academy training completion up 6 points across all departments', delta: 21 },
    { label: 'Phishing simulation — reporting rate reached 88%', delta: 14 },
    { label: 'One critical alert open beyond 24 hours (phishing, T1566)', delta: -7 },
  ],
};

/* ---------- compliance ---------- */
const ctl = (id: string, name: string, framework: string, status: ControlStatus,
             lastReviewed: string, owner: string, evidence: string): Control =>
  ({ id, name, framework, status, lastReviewed, owner, evidence });

const ndpaControls: Control[] = [
  ctl('NDPA-2(1)', 'Lawful basis for processing', 'NDPA 2023', 'PASS', '2025-06-02', 'Legal', 'RoPA v3 — lawful basis documented for all 41 datasets.'),
  ctl('NDPA-2(3)', 'Consent records retained', 'NDPA 2023', 'PASS', '2025-06-02', 'Legal', 'Consent ledger export — 12,840 timestamped entries.'),
  ctl('NDPA-24(1)', 'Breach notification SLA', 'NDPA 2023', 'FAIL', '2025-06-28', 'DPO Office', 'No automated path to the NDPC; manual workflow measured at 9 days in tabletop test.'),
  ctl('NDPA-24(2)', 'Breach register maintained', 'NDPA 2023', 'PASS', '2025-06-02', 'DPO Office', 'Register holds 2 historic entries, both closed.'),
  ctl('NDPA-23(1)', 'DPO appointment', 'NDPA 2023', 'FAIL', '2025-06-28', 'Executive', 'No DPO registered with the Commission; responsibility unassigned.'),
  ctl('NDPA-23(2)', 'DPO contact published', 'NDPA 2023', 'PENDING', '2025-05-15', 'Compliance', 'Placeholder contact page staged, awaiting appointment.'),
  ctl('NDPA-28', 'Data subject request workflow', 'NDPA 2023', 'PASS', '2025-06-10', 'Compliance', 'DSR portal live; median fulfilment 3.1 days.'),
  ctl('NDPA-33', 'Privacy notice (EN / HA)', 'NDPA 2023', 'PASS', '2025-04-20', 'Legal', 'Notices published in English and Hausa.'),
  ctl('NDPA-39', 'Cross-border transfer safeguards', 'NDPA 2023', 'PASS', '2025-06-02', 'Legal', 'Standard contractual clauses executed with 2 processors.'),
  ctl('NDPA-42', 'Data retention schedule', 'NDPA 2023', 'PASS', '2025-05-30', 'Compliance', 'Retention matrix applied across 41 datasets.'),
  ctl('NDPA-19', 'Security of processing', 'NDPA 2023', 'PASS', '2025-06-15', 'Engineering', 'Encryption at rest and in transit verified across the estate.'),
  ctl('NDPA-20', 'Processor contracts', 'NDPA 2023', 'PASS', '2025-05-22', 'Legal', 'All 6 processors under NDPA-compliant clauses.'),
  ctl('NDPA-26', 'DPIA for new products', 'NDPA 2023', 'PASS', '2025-06-19', 'Product', 'DPIA completed for the payments feature.'),
  ctl('NDPA-35(1)', 'Incident escalation path', 'NDPA 2023', 'PENDING', '2025-05-15', 'Ops', 'Escalation chart drafted; on-call rota not yet mapped.'),
  ctl('NDPA-35(2)', 'Quarterly incident exercise', 'NDPA 2023', 'PASS', '2025-06-30', 'Ops', 'Tabletop executed 2025-06-28 — findings logged.'),
  ctl('NDPA-41', 'Records of processing', 'NDPA 2023', 'PASS', '2025-06-02', 'Compliance', 'RoPA v3 current as of June.'),
  ctl('NDPA-43', 'Audit trail integrity', 'NDPA 2023', 'PASS', '2025-06-15', 'Engineering', 'Append-only logs with hash chaining.'),
  ctl('NDPA-48', 'Regulatory reporting channel', 'NDPA 2023', 'PASS', '2025-04-20', 'Compliance', 'NDPC portal credentials secured in vault.'),
];

const cbnControls: Control[] = [
  ctl('CBN-SEC-2(1)', 'Customer data encrypted at rest', 'CBN Framework', 'PASS', '2025-06-11', 'Engineering', 'AES-256 verified on all customer stores.'),
  ctl('CBN-SEC-3(2)', 'Channel transaction monitoring', 'CBN Framework', 'PASS', '2025-06-11', 'Engineering', 'Realtime monitoring live on all channels.'),
  ctl('CBN-SEC-5(1)', 'Incident reporting to CBN', 'CBN Framework', 'PASS', '2025-05-08', 'Ops', 'Reporting template aligned to circular.'),
  ctl('CBN-SEC-6(4)', 'Third-party connectivity review', 'CBN Framework', 'PENDING', '2025-04-30', 'Ops', 'Two vendor links awaiting annual review.'),
  ctl('CBN-SEC-7(2)', 'SIM-binding controls for USSD', 'CBN Framework', 'FAIL', '2025-06-28', 'Engineering', 'SIM-change re-binding not enforced within 24h.'),
  ctl('CBN-SEC-9(1)', 'Annual penetration test', 'CBN Framework', 'PASS', '2025-03-15', 'Engineering', 'External pentest 2025-02 — 3 findings, all closed.'),
];

const nitdaControls: Control[] = [
  ctl('NITDA-G-1.3', 'Data inventory maintained', 'NITDA', 'PASS', '2025-06-02', 'Compliance', 'Inventory synced from CMDB weekly.'),
  ctl('NITDA-G-2.1', 'ISMS scope documented', 'NITDA', 'PASS', '2025-05-12', 'Compliance', 'Scope statement v2 covers Kano estate.'),
  ctl('NITDA-G-3.4', 'Quarterly access review', 'NITDA', 'PENDING', '2025-05-15', 'Ops', 'Q2 review scheduled for July.'),
  ctl('NITDA-G-4.2', 'Backup and restore drill', 'NITDA', 'PASS', '2025-06-06', 'Ops', 'Restore drill passed — RTO 41 minutes.'),
  ctl('NITDA-G-5.1', 'Vulnerability scan cadence', 'NITDA', 'PASS', '2025-06-15', 'Engineering', 'Weekly scans, SLA 14 days.'),
  ctl('NITDA-G-6.3', 'Security awareness program', 'NITDA', 'PASS', '2025-06-30', 'Compliance', 'Academy enrolment at 92%.'),
  ctl('NITDA-G-7.2', 'Vendor risk register', 'NITDA', 'FAIL', '2025-06-28', 'Legal', 'Register exists; 3 vendors unscored.'),
];

const isoControls: Control[] = [
  ctl('ISO-A.5.1', 'Information security policy', 'ISO 27001', 'PASS', '2025-05-02', 'Compliance', 'Policy v4 approved by the board.'),
  ctl('ISO-A.5.9', 'Asset inventory', 'ISO 27001', 'PASS', '2025-06-02', 'Engineering', 'CMDB coverage 97%.'),
  ctl('ISO-A.6.3', 'Security awareness training', 'ISO 27001', 'PASS', '2025-06-30', 'Compliance', 'Tracked via Academy — 92% complete.'),
  ctl('ISO-A.8.16', 'Incident management', 'ISO 27001', 'PASS', '2025-06-15', 'Ops', 'IR playbook v3 in force.'),
  ctl('ISO-A.8.24', 'Cryptographic controls', 'ISO 27001', 'PASS', '2025-06-15', 'Engineering', 'Key rotation cadence enforced.'),
  ctl('ISO-A.5.19', 'Supplier relationships', 'ISO 27001', 'PENDING', '2025-05-15', 'Legal', 'Supplier controls clause rollout 60%.'),
  ctl('ISO-A.5.31', 'Legal, statutory requirements', 'ISO 27001', 'PASS', '2025-04-20', 'Legal', 'NDPA and CBN obligations mapped.'),
  ctl('ISO-A.5.36', 'Independent compliance audit', 'ISO 27001', 'FAIL', '2025-06-28', 'Executive', 'Last independent audit 19 months ago.'),
];

export const frameworks: Framework[] = [
  { key: 'NDPA 2023', controls: 18, passing: 14 },
  { key: 'CBN Framework', controls: 6, passing: 4 },
  { key: 'NITDA', controls: 7, passing: 5 },
  { key: 'ISO 27001', controls: 8, passing: 6 },
];

export const controlsByFramework: Record<string, Control[]> = {
  'NDPA 2023': ndpaControls,
  'CBN Framework': cbnControls,
  'NITDA': nitdaControls,
  'ISO 27001': isoControls,
};

export const remediations: Remediation[] = [
  { id: 'rem_01', title: 'Automate NDPC breach notification (72h SLA)', severity: 'CRITICAL', control: 'NDPA-24(1)', owner: 'A. Bello — DPO Office', due: '2025-07-18' },
  { id: 'rem_02', title: 'Appoint and register a Data Protection Officer', severity: 'HIGH', control: 'NDPA-23(1)', owner: 'M. Okafor — Legal', due: '2025-07-25' },
  { id: 'rem_03', title: 'Publish DPO contact on the public register', severity: 'MEDIUM', control: 'NDPA-23(2)', owner: 'T. Adeyemi — Compliance', due: '2025-08-04' },
  { id: 'rem_04', title: 'Re-run quarterly incident tabletop exercise', severity: 'LOW', control: 'NDPA-35(1)', owner: 'K. Danjuma — Ops', due: '2025-08-15' },
];

/* ---------- detection ---------- */
export const alerts: Alert[] = [
  { id: 'alt_01', title: 'Phishing — Hausa-language lure over SMS and email', category: 'PHISHING', technique: 'T1566', severity: 'CRITICAL', time: '09:41:07', status: 'OPEN', entity: 'kano-03 / 3 mailboxes' },
  { id: 'alt_02', title: 'SIM-swap attempt on CFO line', category: 'SIM-SWAP', technique: 'SIM-swap', severity: 'HIGH', time: '09:12:44', status: 'TRIAGED', entity: 'MTN +234…8011' },
  { id: 'alt_03', title: 'USSD transaction anomaly — velocity spike', category: 'USSD ANOMALY', technique: '—', severity: 'MEDIUM', time: '08:57:19', status: 'OPEN', entity: 'ussd-gw-2' },
  { id: 'alt_04', title: 'Malware dropped via invoice attachment', category: 'MALWARE', technique: 'T1204', severity: 'MEDIUM', time: '08:44:02', status: 'CONTAINED', entity: 'kano-01' },
  { id: 'alt_05', title: 'Periodic beaconing to unclassified host', category: 'BEACONING', technique: 'T1071', severity: 'HIGH', time: '08:30:55', status: 'OPEN', entity: 'kano-03 → 185.220.x.x' },
];

export const alertDetails: Record<string, AlertDetail> = {
  alt_01: {
    id: 'alt_01',
    confidence: 0.94,
    summary: 'Hausa-language credential lure delivered to three finance mailboxes via SMS and email. L4 AfroNLP classified the payload intent as credential theft; L5 LLM triage escalated with high confidence. One handset (kano-03) followed the link.',
    actions: [
      { label: 'Quarantine', toast: 'Quarantine issued — kano-03 isolated from the estate' },
      { label: 'Block sender', toast: 'Sender blocked at gateway — 3 addresses on the deny list' },
      { label: 'Notify user', toast: 'Users notified — 3 advisories sent in Hausa and English' },
    ],
    timeline: [
      { t: '09:38:12', label: 'SMS lure delivered to 3 handsets' },
      { t: '09:40:11', label: 'kano-03 followed the link to the credential form' },
      { t: '09:40:58', label: 'L4 AfroNLP — Hausa payload, intent = credential theft' },
      { t: '09:41:07', label: 'L5 LLM triage — confidence 0.94, escalate' },
      { t: '09:41:09', label: 'Alert opened; kano-03 held pending action' },
    ],
    evidence: [
      '09:38:12 sms src=MTN-GW dst=finance×3 body_sha=9f3a…c1e lang=ha',
      '09:40:11 http kano-03 → hxxp://nnpc-careers[.]ng cred_form',
      '09:40:58 afro-nlp intent="credential_theft" lang=ha conf=0.91',
      '09:41:07 llm_triage verdict="escalate" conf=0.94',
    ],
    related: [{ id: 'alt_05', label: 'Beaconing from the same host — kano-03' }],
  },
  alt_02: {
    id: 'alt_02',
    confidence: 0.88,
    summary: 'Repeated re-activation attempts against the CFO line, consistent with SIM-swap rehearsal. Carrier pattern flagged by L2; the line is frozen pending callback verification.',
    actions: [
      { label: 'Freeze line', toast: 'Line frozen — re-activation blocked at carrier' },
      { label: 'Verify callback', toast: 'Callback verification task created for the DPO office' },
      { label: 'Notify carrier', toast: 'Carrier abuse desk notified — case reference logged' },
    ],
    timeline: [
      { t: '09:09:02', label: 'Failed re-activation attempt #1' },
      { t: '09:11:36', label: 'Failed re-activation attempt #2 — velocity flag' },
      { t: '09:12:44', label: 'L2 anomaly — SIM-swap pattern, escalate' },
    ],
    evidence: [
      '09:09:02 ussd act=reactivate msisdn=+234…8011 result=fail',
      '09:11:36 ussd act=reactivate msisdn=+234…8011 result=fail',
      '09:12:44 ml_anomaly label="sim_swap" conf=0.88',
    ],
    related: [{ id: 'alt_03', label: 'USSD anomaly on the same gateway window' }],
  },
  alt_03: {
    id: 'alt_03',
    confidence: 0.71,
    summary: 'Transaction velocity on ussd-gw-2 exceeded baseline by 6.4σ for a six-minute window. No fraud pattern matched yet; anomaly persists under watch.',
    actions: [
      { label: 'Throttle gateway', toast: 'ussd-gw-2 throttled to baseline velocity' },
      { label: 'Challenge transfers', toast: 'Step-up challenge applied to high-value transfers' },
    ],
    timeline: [
      { t: '08:51:14', label: 'Velocity crossed 4σ — watch mode' },
      { t: '08:57:19', label: 'Velocity crossed 6.4σ — anomaly opened' },
    ],
    evidence: [
      '08:51:14 velocity ussd-gw-2 sigma=4.1 tx/min=212',
      '08:57:19 velocity ussd-gw-2 sigma=6.4 tx/min=318',
    ],
    related: [],
  },
  alt_04: {
    id: 'alt_04',
    confidence: 0.9,
    summary: 'Invoice-themed attachment executed a dropper on kano-01. Host was isolated within four minutes; sweep of the estate returned clean.',
    actions: [
      { label: 'Isolate host', toast: 'kano-01 isolated — network access revoked' },
      { label: 'Sweep estate', toast: 'Estate sweep queued — 34 endpoints' },
      { label: 'Notify user', toast: 'User advisory sent — invoice scam briefing' },
    ],
    timeline: [
      { t: '08:43:58', label: 'Attachment executed on kano-01' },
      { t: '08:44:02', label: 'L1 Sigma match — dropper signature' },
      { t: '08:47:30', label: 'Host isolated; containment confirmed' },
    ],
    evidence: [
      '08:43:58 proc parent=winword.exe sha=7b21…e04 flag=dropper',
      '08:44:02 sigma rule=T1204 match=invoice_dropper',
    ],
    related: [],
  },
  alt_05: {
    id: 'alt_05',
    confidence: 0.83,
    summary: 'kano-03 beacons to an unclassified external host on a fixed 60-second interval — classic C2 rhythm. Correlates with the host that followed the phishing link.',
    actions: [
      { label: 'Block at egress', toast: 'Egress block applied — 185.220.x.x denied' },
      { label: 'Hunt lateral', toast: 'Hunt query dispatched — graph layer, kano-03 pivot' },
      { label: 'Notify user', toast: 'User notified — kano-03 collected for imaging' },
    ],
    timeline: [
      { t: '08:24:31', label: 'First beacon observed — interval 60s' },
      { t: '08:30:55', label: 'L3 graph — pattern confirmed across 12 intervals' },
    ],
    evidence: [
      '08:24:31 dns kano-03 → cdn-metrics[.]top interval=60s',
      '08:30:55 graph link kano-03→ext(185.220.x.x) edges=12',
    ],
    related: [{ id: 'alt_01', label: 'Phishing lure — same host, kano-03' }],
  },
};

export const detectionLayers: DetectionLayer[] = [
  { id: 'L1', name: 'SIGMA', detail: 'RULE MATCHING', hits: 12, state: 'ACTIVE' },
  { id: 'L2', name: 'ML ANOMALY', detail: 'BASELINE DEVIATION', hits: 4, state: 'ACTIVE' },
  { id: 'L3', name: 'GRAPH', detail: 'LATERAL MOVEMENT', hits: 2, state: 'ACTIVE' },
  { id: 'L4', name: 'AFRONLP', detail: 'LOCAL-LANGUAGE INTENT', hits: 1, state: 'ACTIVE' },
  { id: 'L5', name: 'LLM TRIAGE', detail: 'CONFIDENT ESCALATION', hits: 5, state: 'ACTIVE' },
];

/* ---------- academy ---------- */
export const academy: Academy = {
  courses: [
    { id: 'c1', title: 'NDPA Compliance Basics', lang: 'EN', progress: 72, minutes: 24 },
    { id: 'c2', title: 'Recognizing Phishing', lang: 'HA', progress: 72, minutes: 24 },
    { id: 'c3', title: 'SIM-Swap Defense', lang: 'EN', progress: 72, minutes: 24 },
    { id: 'c4', title: 'Password Hygiene', lang: 'PCM', progress: 72, minutes: 24 },
  ],
  sim: { name: 'Q3 SIM-Swap Sim', clicked: 12, reported: 88, sent: 240, window: 'SEP 2025 · 6 DAYS' },
  leaderboard: [
    { rank: 1, name: 'Fatima Sani', dept: 'FINANCE', points: 9820 },
    { rank: 2, name: 'Emeka Obi', dept: 'ENGINEERING', points: 9410 },
    { rank: 3, name: 'Aisha Bello', dept: 'COMPLIANCE', points: 9005 },
  ],
  heatmap: {
    depts: ['Finance', 'Engineering', 'Compliance', 'HR'],
    months: ['APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP'],
    cells: [
      [22, 25, 31, 28, 34, 30],
      [30, 28, 26, 33, 29, 27],
      [12, 14, 15, 18, 16, 14],
      [48, 52, 61, 58, 55, 60],
    ],
  },
};

/* ---------- copilot ---------- */
export const copilotSession: CopilotSession = {
  sources: [
    { id: 's1', label: 'NDPA 2023, s.40' },
    { id: 's2', label: 'NDPA 2023, s.23–24' },
    { id: 's3', label: 'CBN Risk Framework' },
    { id: 's4', label: 'IR Playbook v3' },
    { id: 's5', label: 'NITDA Guidelines' },
  ],
  pairs: [
    {
      q: 'What are my NDPA breach notification obligations?',
      a: 'Under the Nigeria Data Protection Act 2023, section 40, you must notify the Nigeria Data Protection Commission (NDPC) within 72 hours of becoming aware of a personal data breach.\n\nThe notification should cover the nature of the breach, the categories and approximate number of affected data subjects, the likely consequences, and the measures taken or proposed. If full details are not available within 72 hours, you notify in phases and explain the delay.\n\nWhere the breach is likely to result in a high risk to the rights of data subjects, the affected individuals must also be informed without undue delay.',
      sources: [{ id: 's1', label: 'NDPA 2023, s.40' }],
    },
    {
      q: 'Show my top 3 gaps and draft fixes',
      a: '1. Breach notification SLA — NDPA-24(1), FAIL.\nNo automated path to the NDPC; the tabletop measured 9 days against a 72-hour duty.\nFix: wire alerting into a notification workflow with a 72-hour countdown clock and a named owner on shift.\n\n2. DPO appointment — NDPA-23(1), FAIL.\nNo Data Protection Officer registered with the Commission.\nFix: appoint and register a DPO, and route all subject requests and regulator contact through the office.\n\n3. DPO contact published — NDPA-23(2), PENDING.\nThe contact page is staged but blocked on the appointment.\nFix: publish the DPO name and channel, and link it from every privacy notice.',
      sources: [{ id: 's2', label: 'NDPA 2023, s.23–24' }, { id: 's5', label: 'NITDA Guidelines' }],
      actions: [
        { label: 'Draft Policy', kind: 'solid', toast: 'Policy draft queued — Breach Notification (NDPA-24(1))' },
        { label: 'Create Remediation', kind: 'ghost', toast: 'Remediation created — rem_05, assigned to the DPO office' },
      ],
    },
  ],
  fallback: {
    q: '',
    a: 'In this demo I answer from the connected compliance corpus — try one of the suggested questions, or ask about breach notification, DPO duties, or your open gaps.',
    sources: [{ id: 's5', label: 'NITDA Guidelines' }],
  },
};

/* ---------- ticker ---------- */
export const tickerItems: TickerItem[] = [
  { id: 't1', time: '09:12', label: 'SIM-swap blocked' },
  { id: 't2', time: '09:41', label: 'Hausa phishing lure quarantined' },
  { id: 't3', time: '08:57', label: 'USSD anomaly killed' },
  { id: 't4', time: '09:44', label: 'endpoint kano-03 baseline normal' },
];
