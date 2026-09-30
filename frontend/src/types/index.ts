/* ————————————————————————————————————————————————
   CYPHWARD — Enterprise Domain Types & Contracts
   Canonical TypeScript types for the Cyphward Platform.
   Aligned with MVP Architecture (FastAPI + Inngest + PostgreSQL)
   ———————————————————————————————————————————————— */

export interface Organization {
  id: string;
  name: string;
  slug: string;
  cac_rc?: string;
  sector?: string;
  plan?: string;
  primary_domain?: string;
  email?: string;
  domains_count?: number;
  verified_domains_count?: number;
}

export interface Domain {
  id: string;
  org_id: string;
  domain: string;
  verification_status: 'pending' | 'verified' | 'expired' | 'revoked' | 'failed';
  verification_token: string;
  verified_at?: string;
  created_at: string;
  updated_at?: string;
  asset_count?: number;
  scan_count?: number;
}

export interface AssetTechnology {
  name: string;
  version?: string;
  category?: string;
}

export interface AssetTlsInfo {
  valid?: boolean;
  issuer?: string;
  subject?: string;
  valid_to?: string;
  days_remaining?: number;
  protocol?: string;
  cipher?: string;
}

export interface Asset {
  id: string;
  org_id: string;
  domain_id?: string;
  hostname: string;
  ip_address?: string;
  asset_type: string;
  status: 'active' | 'unresponsive' | 'archived';
  first_seen: string;
  last_seen: string;
  http_status?: number;
  technologies?: AssetTechnology[];
  tls_info?: AssetTlsInfo;
  dns_records?: Record<string, any>;
  parent_domain?: string;
  findings_count?: number;
  critical_findings_count?: number;
}

export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';
export type FindingStatus = 'open' | 'acknowledged' | 'in_progress' | 'resolved';

export interface Finding {
  id: string;
  scan_id?: string;
  asset_id?: string;
  org_id: string;
  title: string;
  description: string;
  severity: FindingSeverity;
  category: string;
  evidence: Record<string, any>;
  remediation: string;
  status: FindingStatus;
  created_at: string;
  first_seen_at?: string;
  last_seen_at?: string;
  resolved_at?: string | null;
  confidence?: string;
  hostname?: string;
  ip_address?: string;
  asset_type?: string;
}

export interface StageInfo {
  status: 'queued' | 'pending' | 'running' | 'completed' | 'failed';
  items?: number;
  duration_ms?: number;
  score?: number | null;
}

export interface ScanStageProgress {
  discovery: StageInfo;
  dns: StageInfo;
  http: StageInfo;
  security_checks: StageInfo;
  normalization: StageInfo;
  scoring: StageInfo;
}

export interface Scan {
  id: string;
  org_id: string;
  domain_id: string;
  domain?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  score?: number;
  stage_progress: ScanStageProgress;
  current_stage?: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  created_at: string;
  findings_discovered?: number;
}

export interface ScorePillar {
  name: string;
  score: number;
  max: number;
  pct: number;
  status: string;
}

export interface ScoreFactorItem {
  impact: string;
  type: 'positive' | 'negative';
  label: string;
}

export interface OverviewData {
  organization: Organization;
  score: number;
  max_score: number;
  grade: string;
  posture_label: string;
  status_color: string;
  trend: number;
  counts: {
    total_assets: number;
    total_findings: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
  subscores: ScorePillar[];
  factors: ScoreFactorItem[];
  recent_scans: Scan[];
}

export interface FindingExplanation {
  title: string;
  severity: string;
  category: string;
  what_is_this: string;
  why_it_matters: string;
  evidence_analysis: string;
  what_happens_if_ignored: string;
  sovereign_advisory?: string;
}

export interface RemediationGuide {
  finding_id?: string;
  title: string;
  target_stack: string;
  summary: string;
  prerequisites: string[];
  steps: string[];
  code_snippet: string;
  verification_command: string;
  estimated_time_minutes: number;
}

export interface ExecutiveSummary {
  org_name: string;
  score: number;
  grade: string;
  posture_label: string;
  executive_headline: string;
  board_summary: string;
  key_strengths: string[];
  critical_action_items: {
    priority: string;
    title: string;
    impact: string;
    owner: string;
  }[];
  compliance_verdict: string;
  generated_at: string;
}

export interface SettingsData {
  organization: Organization;
  membership?: {
    role: string;
    user_id?: string;
  };
  members: {
    id: string;
    email: string;
    full_name: string;
    role: string;
    job_title?: string;
    created_at: string;
  }[];
}

// Compatibility types
export interface Tenant {
  id?: string;
  slug?: string;
  name: string;
  plan: string;
  region: string;
  email?: string;
}

export interface Posture {
  tenant: string;
  plan: string;
  score: number;
  maxScore: number;
  trend: number;
  compliance: {
    passing: number;
    total: number;
    framework: string;
  };
  trainingCompletion: number;
  openAlerts: number;
  criticalAlerts: number;
  criticalLabel: string;
  openRemediations: number;
  signalsToday: number;
}

export interface SubScore {
  key: string;
  label: string;
  value: number;
  max: number;
  delta: number;
}

export interface ScoreFactor {
  label: string;
  delta: number;
}

export interface Score {
  tenant: string;
  score: number;
  max: number;
  trend: number;
  subscores: SubScore[];
  factors: ScoreFactor[];
}

export type ControlStatus = 'PASS' | 'FAIL' | 'PENDING';

export interface Control {
  id: string;
  name: string;
  framework: string;
  status: ControlStatus;
  lastReviewed: string;
  owner: string;
  evidence: string;
}

export interface Framework {
  key: string;
  controls: number;
  passing: number;
}

export interface Remediation {
  id: string;
  title: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  control: string;
  owner: string;
  due: string;
}

export interface ComplianceSummary {
  frameworks: Framework[];
  controls: Control[];
  passing: number;
  total: number;
  remediations: Remediation[];
}

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type AlertStatus = 'OPEN' | 'TRIAGED' | 'CONTAINED';

export interface Alert {
  id: string;
  title: string;
  category: string;
  technique: string;
  severity: Severity;
  time: string;
  status: AlertStatus;
  entity: string;
}

export interface AlertAction {
  label: string;
  toast: string;
}

export interface AlertDetail {
  id: string;
  confidence: number;
  summary: string;
  actions: AlertAction[];
  timeline: { t: string; label: string }[];
  evidence: string[];
  related: { id: string; label: string }[];
}

export interface DetectionLayer {
  id: string;
  name: string;
  detail: string;
  hits: number;
  state: 'ACTIVE' | 'IDLE';
}

export interface Course {
  id: string;
  title: string;
  lang: 'EN' | 'HA' | 'PCM';
  progress: number;
  minutes: number;
}

export interface SimCampaign {
  name: string;
  clicked: number;
  reported: number;
  sent: number;
  window: string;
}

export interface LeaderRow {
  rank: number;
  name: string;
  dept: string;
  points: number;
}

export interface Academy {
  courses: Course[];
  sim: SimCampaign;
  leaderboard: LeaderRow[];
  heatmap: {
    depts: string[];
    months: string[];
    cells: number[][];
  };
}

export interface Source {
  id: string;
  label: string;
}

export interface CopilotAction {
  label: string;
  kind: 'solid' | 'ghost';
  toast: string;
}

export interface CopilotAnswer {
  q: string;
  a: string;
  sources: Source[];
  actions?: CopilotAction[];
}

export interface CopilotSession {
  sources: Source[];
  pairs: CopilotAnswer[];
  fallback: CopilotAnswer;
}

export interface TickerItem {
  id: string;
  time: string;
  label: string;
}

export const DEFAULT_FRAMEWORK = 'NDPA 2023';
export const FIRST_ALERT_ID = 'alt_01';
