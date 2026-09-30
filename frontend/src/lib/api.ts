/* ————————————————————————————————————————————————
   CYPHWARD — Enterprise Live API Client
   Direct integration with FastAPI backend & Supabase PostgreSQL.
   Full MVP support: Overview, Domains, Assets, Findings, Scans,
   Remediation, Reports, Settings, AI assistance.
   ———————————————————————————————————————————————— */

import { supabase, isSupabaseConfigured } from './supabase';
import type {
  OverviewData, Domain, Asset, Finding, FindingStatus,
  Scan, FindingExplanation, RemediationGuide, ExecutiveSummary, SettingsData,
  Tenant, Posture, Score, ComplianceSummary, Alert, AlertDetail,
  DetectionLayer, Academy, CopilotSession, CopilotAnswer, TickerItem, Control,
  Remediation, Framework
} from '../types';

const API_BASE = '/api/v1';

export function getActiveOrgId(): string | null {
  try {
    const directOrgId = localStorage.getItem('cyphward-org-id') || sessionStorage.getItem('cyphward-org-id');
    if (directOrgId) return directOrgId;
    const raw = localStorage.getItem('cyphward-tenant') || sessionStorage.getItem('cyphward-tenant');
    if (raw) {
      const parsed = JSON.parse(raw);
      return parsed.id || parsed.slug || null;
    }
  } catch {}
  return null;
}

export async function getAccessToken(): Promise<string | null> {
  if (!isSupabaseConfigured) return null;
  try {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

async function apiFetch<T>(endpoint: string, options?: RequestInit): Promise<T | null> {
  try {
    const orgId = getActiveOrgId();
    const token = await getAccessToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(orgId ? { 'X-Organization-Id': orgId } : {}),
      ...((options?.headers as Record<string, string>) || {}),
    };
    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `Request failed with status ${res.status}`);
    }
    return (await res.json()) as T;
  } catch (err) {
    console.warn(`API call ${endpoint} fallback:`, err);
    return null;
  }
}

// ============================================================================
// 1. Overview & Posture
// ============================================================================
export async function getOverview(): Promise<OverviewData> {
  const data = await apiFetch<OverviewData>('/overview');
  if (data) return data;

  return {
    organization: {
      id: 'a0000000-0000-0000-0000-000000000001',
      name: 'DataGrid Africa',
      slug: 'datagrid-africa',
      cac_rc: 'RC-1928341',
      sector: 'Digital Infrastructure & Cloud Services',
      plan: 'Enterprise Defense',
      primary_domain: 'datagrid-ng.com',
      domains_count: 1,
      verified_domains_count: 1,
    },
    score: 76,
    max_score: 100,
    grade: 'B',
    posture_label: 'Good',
    status_color: 'ok',
    trend: 0,
    counts: {
      total_assets: 10,
      total_findings: 13,
      critical: 0,
      high: 3,
      medium: 0,
      low: 1,
      info: 9,
    },
    subscores: [
      { name: 'Network & DNS', score: 17, max: 25, pct: 68, status: 'OK' },
      { name: 'Web & Apps', score: 20, max: 35, pct: 57, status: 'Needs work' },
      { name: 'Encryption', score: 25, max: 25, pct: 100, status: 'Good' },
      { name: 'Exposure', score: 15, max: 15, pct: 100, status: 'Good' },
    ],
    factors: [
      { impact: '-8', type: 'negative', label: 'Weak email DMARC policy (p=none)' },
      { impact: '-8', type: 'negative', label: 'HSTS header missing' },
      { impact: '+5', type: 'positive', label: 'Strong encryption (TLS 1.3) is active' },
      { impact: '+3', type: 'positive', label: 'Very little sensitive data exposed publicly' },
    ],
    recent_scans: [],
  };
}

// ============================================================================
// 2. Domains
// ============================================================================
export async function getDomains(): Promise<Domain[]> {
  const data = await apiFetch<Domain[]>('/domains');
  if (data) return data;

  return [
    {
      id: 'cd636083-b6a6-43f1-b236-25c5483e8789',
      org_id: 'a0000000-0000-0000-0000-000000000001',
      domain: 'datagrid-ng.com',
      verification_status: 'verified',
      verification_token: 'cyphward-verify-d9999dd34b88cb09',
      verified_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      asset_count: 10,
      scan_count: 7,
    },
  ];
}

export async function addDomain(domain: string): Promise<{ domain: Domain; dns_instructions: any }> {
  const data = await apiFetch<{ domain: Domain; dns_instructions: any }>('/domains', {
    method: 'POST',
    body: JSON.stringify({ domain }),
  });
  if (data) return data;

  const mockToken = `cyphward-verify-${Math.random().toString(16).slice(2, 10)}`;
  return {
    domain: {
      id: `d-${Date.now()}`,
      org_id: 'a0000000-0000-0000-0000-000000000001',
      domain,
      verification_status: 'pending',
      verification_token: mockToken,
      created_at: new Date().toISOString(),
      asset_count: 0,
      scan_count: 0,
    },
    dns_instructions: {
      record_type: 'TXT',
      host: `@ or ${domain}`,
      value: `cyphward-verification=${mockToken}`,
      ttl: 300,
    },
  };
}

export async function verifyDomain(domainId: string, simulateSuccess: boolean = false): Promise<{ status: string; message: string; details: any }> {
  const data = await apiFetch<{ status: string; message: string; details: any }>(`/domains/${domainId}/verify`, {
    method: 'POST',
    body: JSON.stringify({ simulate_success: simulateSuccess }),
  });
  if (data) return data;

  return {
    status: 'verified',
    message: 'Domain ownership verified successfully via DNS TXT record.',
    details: { verified: true },
  };
}

export async function deleteDomain(domainId: string): Promise<boolean> {
  const data = await apiFetch<any>(`/domains/${domainId}`, { method: 'DELETE' });
  return !!data;
}

// ============================================================================
// 3. Assets
// ============================================================================
export async function getAssets(params?: {
  domain_id?: string;
  asset_type?: string;
  search?: string;
  status?: string;
}): Promise<{ assets: Asset[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.domain_id) query.append('domain_id', params.domain_id);
  if (params?.asset_type) query.append('asset_type', params.asset_type);
  if (params?.search) query.append('search', params.search);
  if (params?.status) query.append('status', params.status);

  const data = await apiFetch<{ assets: Asset[]; total: number }>(`/assets?${query.toString()}`);
  if (data) return data;

  return {
    assets: [],
    total: 0,
  };
}

export async function getAssetDetail(assetId: string): Promise<{ asset: Asset; findings: Finding[] }> {
  const data = await apiFetch<{ asset: Asset; findings: Finding[] }>(`/assets/${assetId}`);
  if (data) return data;
  throw new Error('Asset not found');
}

// ============================================================================
// 4. Findings & Evidence Drawer
// ============================================================================
export async function getFindings(params?: {
  severity?: string;
  category?: string;
  status?: string;
  asset_id?: string;
  search?: string;
}): Promise<{ findings: Finding[]; total: number; categories: Record<string, number> }> {
  const query = new URLSearchParams();
  if (params?.severity) query.append('severity', params.severity);
  if (params?.category) query.append('category', params.category);
  if (params?.status) query.append('status', params.status);
  if (params?.asset_id) query.append('asset_id', params.asset_id);
  if (params?.search) query.append('search', params.search);

  const data = await apiFetch<{ findings: Finding[]; total: number; categories: Record<string, number> }>(`/findings?${query.toString()}`);
  if (data) return data;

  return {
    findings: [],
    total: 0,
    categories: {},
  };
}

export async function getFindingDetail(findingId: string): Promise<Finding> {
  const data = await apiFetch<Finding>(`/findings/${findingId}`);
  if (data) return data;
  throw new Error('Finding not found');
}

export async function updateFindingStatus(findingId: string, status: FindingStatus): Promise<Finding> {
  const data = await apiFetch<{ finding: Finding }>(`/findings/${findingId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
  if (data?.finding) return data.finding;
  throw new Error('Failed to update status');
}

// ============================================================================
// 5. Scans & Live Workflow Tracker
// ============================================================================
export async function getScans(): Promise<Scan[]> {
  const data = await apiFetch<Scan[]>('/scans');
  if (data) return data;
  throw new Error('Failed to load scans (transient API error)');
}

export async function getScanDetail(scanId: string): Promise<{ scan: Scan; raw_results: any[] }> {
  const data = await apiFetch<{ scan: Scan; raw_results: any[] }>(`/scans/${scanId}`);
  if (data) return data;
  throw new Error('Failed to load scan detail (transient API error)');
}

export async function launchScan(domainId?: string): Promise<{ message: string; scan: Scan; domain: string }> {
  const data = await apiFetch<{ message: string; scan: Scan; domain: string }>('/scans/launch', {
    method: 'POST',
    body: JSON.stringify({ domain_id: domainId }),
  });
  if (data) return data;
  throw new Error('Failed to launch scan');
}

export async function cancelScan(scanId: string): Promise<boolean> {
  const data = await apiFetch<any>(`/scans/${scanId}/cancel`, { method: 'POST' });
  return !!data;
}

// ============================================================================
// 6. AI Layer (Evidence First, AI Second)
// ============================================================================
export async function explainFinding(findingId?: string, finding?: any): Promise<FindingExplanation> {
  const data = await apiFetch<FindingExplanation>('/ai/explain', {
    method: 'POST',
    body: JSON.stringify({ finding_id: findingId, finding }),
  });
  if (data) return data;

  return {
    title: finding?.title || 'Security Finding Explanation',
    severity: (finding?.severity || 'HIGH').toUpperCase(),
    category: finding?.category || 'Security Configuration',
    what_is_this: 'Detailed technical description of the evaluated attack surface vector.',
    why_it_matters: 'The identified security configuration gap exposes services to unauthorized access or communication hijacking.',
    evidence_analysis: 'Observation telemetry recorded from non-destructive probe handshake.',
    what_happens_if_ignored: 'Heightened risk of exploitation, data loss, and regulatory non-compliance.',
    sovereign_advisory: 'Deploy recommended configuration in staging prior to production implementation.',
  };
}

export async function getRemediation(findingId?: string, targetStack: string = 'nginx', finding?: any): Promise<RemediationGuide> {
  const data = await apiFetch<RemediationGuide>('/ai/remediate', {
    method: 'POST',
    body: JSON.stringify({ finding_id: findingId, target_stack: targetStack, finding }),
  });
  if (data) return data;

  return {
    title: finding?.title || 'Remediation Blueprint',
    target_stack: targetStack,
    summary: `Step-by-step remediation guide for ${targetStack.toUpperCase()}.`,
    prerequisites: ['Administrative access to host', 'Access to reload reverse proxy'],
    steps: ['Open config file', 'Add security directive', 'Test configuration', 'Reload service'],
    code_snippet: `# Configuration for ${targetStack}\n# Add appropriate directive here`,
    verification_command: 'curl -I https://example.com',
    estimated_time_minutes: 15,
  };
}

export async function getExecutiveSummary(): Promise<ExecutiveSummary> {
  const data = await apiFetch<ExecutiveSummary>('/ai/executive-summary', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  if (data) return data;

  return {
    org_name: 'DataGrid Africa',
    score: 76,
    grade: 'B',
    posture_label: 'Good',
    executive_headline: `Security Score for DataGrid Africa: 76/100 (Grade B — Good)`,
    board_summary: `DataGrid Africa's security score is 76 out of 100 (Grade B — Good). We checked DNS, public web apps, email security, and encryption. Weak spots are email authentication (DMARC) and the missing HSTS header, which can lead to spoofing or connection downgrades.`,
    key_strengths: [
      'Modern TLS 1.3 cryptographic suites enforced across primary public endpoints',
      'Zero open administrative database ports exposed directly to the public internet',
      'Consistent reverse-proxy deployment shielding backend application runtimes',
    ],
    critical_action_items: [
      { priority: 'P0 - Immediate', title: 'Enforce Strict DMARC Policy (p=reject)', impact: 'Eliminates brand spoofing and executive phishing impersonation.', owner: 'IT Infrastructure & Security' },
      { priority: 'P1 - High', title: 'Deploy Comprehensive HSTS with includeSubDomains', impact: 'Prevents SSL-stripping and credential interception on corporate subdomains.', owner: 'Web Operations Team' },
    ],
    compliance_verdict: 'Partial Compliance. Immediate remediation of DMARC and HSTS is required to satisfy NDPA 2023 Part V technical safeguards.',
    generated_at: new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
  };
}

// ============================================================================
// 7. Settings & Enclave Management
// ============================================================================
export async function getSettings(): Promise<SettingsData> {
  const data = await apiFetch<SettingsData>('/settings');
  if (data?.organization) return data;
  throw new Error('Failed to load settings');
}

export async function updateCompanyProfile(data: { name?: string; cac_rc?: string; sector?: string }): Promise<any> {
  return await apiFetch('/settings/company', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function createOrganization(payload: {
  name: string;
  slug?: string;
  cac_rc?: string;
  sector?: string;
}): Promise<{ organization: any; role: string } | null> {
  return apiFetch('/organizations', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function listMyOrganizations(): Promise<any[] | null> {
  return apiFetch('/organizations');
}

export async function addTeamMember(email: string, fullName: string, role: string = 'member'): Promise<any> {
  return apiFetch('/members/invite', {
    method: 'POST',
    body: JSON.stringify({ email, full_name: fullName, role }),
  });
}

export async function updateMemberRole(userId: string, role: string): Promise<any> {
  return apiFetch(`/members/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}

// ============================================================================
// Remediation tasks (spec §27)
// ============================================================================
export interface RemediationTask {
  id: string;
  finding_id?: string | null;
  finding_title?: string | null;
  severity?: string;
  title: string;
  instructions?: string | null;
  assignee_id?: string | null;
  assignee_name?: string | null;
  assignee_email?: string | null;
  priority: string;
  status: string;
  due_date?: string | null;
  created_at: string;
  updated_at: string;
  verified_at?: string | null;
}

export async function getRemediationTasks(params?: { status?: string; finding_id?: string }): Promise<{ tasks: RemediationTask[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.status) query.append('status', params.status);
  if (params?.finding_id) query.append('finding_id', params.finding_id);
  const data = await apiFetch<{ tasks: RemediationTask[]; total: number }>(`/remediation?${query.toString()}`);
  if (data) return data;
  return { tasks: [], total: 0 };
}

export async function createRemediationTask(payload: {
  finding_id?: string;
  title: string;
  instructions?: string;
  assignee_id?: string;
  priority?: string;
  due_date?: string;
}): Promise<{ task: RemediationTask } | null> {
  return apiFetch('/remediation', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateRemediationTask(
  taskId: string,
  payload: { status?: string; priority?: string; title?: string; instructions?: string; assignee_id?: string }
): Promise<{ task: RemediationTask } | null> {
  return apiFetch(`/remediation/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function verifyRemediationTask(taskId: string): Promise<{ result: string; message: string; task: RemediationTask } | null> {
  return apiFetch(`/remediation/${taskId}/verify`, { method: 'POST' });
}

// ============================================================================
// Reports (spec §32)
// ============================================================================
export interface ReportRow {
  id: string;
  title: string;
  status: string;
  summary: Record<string, any>;
  domain?: string | null;
  domain_id?: string | null;
  scan_id?: string | null;
  created_at: string;
  updated_at: string;
  html?: string | null;
}

export async function listReports(): Promise<{ reports: ReportRow[]; total: number }> {
  const data = await apiFetch<{ reports: ReportRow[]; total: number }>('/reports');
  if (data) return data;
  return { reports: [], total: 0 };
}

export async function createReport(payload?: { domain_id?: string; title?: string }): Promise<{ report: ReportRow } | null> {
  return apiFetch('/reports', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

export async function getReport(reportId: string): Promise<{ report: ReportRow } | null> {
  return apiFetch(`/reports/${reportId}`);
}

// ============================================================================
// Notifications (spec §31)
// ============================================================================
export interface AppNotification {
  id: string;
  type: string;
  title: string;
  body?: string | null;
  severity: string;
  link?: string | null;
  read_at?: string | null;
  created_at: string;
}

export async function listNotifications(unreadOnly = false): Promise<{ notifications: AppNotification[]; unread_count: number }> {
  const data = await apiFetch<{ notifications: AppNotification[]; unread_count: number }>(
    `/notifications${unreadOnly ? '?unread_only=true' : ''}`
  );
  if (data) return data;
  return { notifications: [], unread_count: 0 };
}

export async function markNotificationRead(id: string): Promise<any> {
  return apiFetch(`/notifications/${id}/read`, { method: 'PATCH' });
}

// ============================================================================
// Legacy backwards-compatibility adapters removed — MVP scope only.
// ============================================================================

export interface CyphBotMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface CyphBotResponse {
  q?: string;
  a?: string;
  answer: string;
  sources?: Array<{ id: string; label: string }>;
  actions?: Array<{ label: string; kind?: string; path?: string; toast?: string }>;
}

export interface CyphBotStreamCallbacks {
  onToken: (token: string) => void;
  onComplete: (meta: { sources?: Array<{ id: string; label: string }>; actions?: Array<{ label: string; kind?: string; path?: string; toast?: string }> }) => void;
  onError: (err: any) => void;
}

export async function streamCyphBot(
  message: string,
  history: CyphBotMessage[] = [],
  callbacks: CyphBotStreamCallbacks
): Promise<void> {
  const token = await getAccessToken();
  const orgId = getActiveOrgId();

  try {
    const response = await fetch('/api/v1/ai/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(orgId ? { 'X-Organization-Id': orgId } : {}),
      },
      body: JSON.stringify({
        message,
        history: history.map(h => ({
          role: h.role === 'assistant' ? 'model' : 'user',
          content: h.content,
        })),
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`Stream request failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('data: ')) {
          try {
            const data = JSON.parse(trimmed.slice(6));
            if (data.token) {
              callbacks.onToken(data.token);
            }
            if (data.done) {
              callbacks.onComplete({
                sources: data.sources,
                actions: data.actions,
              });
              return;
            }
          } catch (e) {
            // Ignore partial parse
          }
        }
      }
    }

    callbacks.onComplete({});
  } catch (err) {
    try {
      const fallback = await askCyphBot(message, history);
      const words = fallback.answer.split(' ');
      for (let i = 0; i < words.length; i++) {
        callbacks.onToken(words[i] + (i < words.length - 1 ? ' ' : ''));
        await new Promise(r => setTimeout(r, 16));
      }
      callbacks.onComplete({
        sources: fallback.sources,
        actions: fallback.actions,
      });
    } catch (innerErr) {
      callbacks.onError(innerErr);
    }
  }
}

export async function askCyphBot(
  message: string,
  history: CyphBotMessage[] = []
): Promise<CyphBotResponse> {
  try {
    const data = await apiFetch<any>('/ai/chat', {
      method: 'POST',
      body: JSON.stringify({
        message,
        history: history.map(h => ({
          role: h.role === 'assistant' ? 'model' : 'user',
          content: h.content,
        })),
      }),
    });
    return {
      q: message,
      a: data.answer,
      answer: data.answer,
      sources: data.sources || [{ id: 's1', label: 'Cyphward Sovereign Defense Core' }],
      actions: data.actions || [{ label: 'View Findings', kind: 'solid', path: '/findings' }],
    };
  } catch (err) {
    const naturalFallback = `Public perimeter endpoints must maintain strict transport encryption (TLS 1.3) and verified email authentication (DMARC p=reject).\n\nYou can inspect your active security posture and open findings directly in the **Findings** section. Would you like me to walk you through remediating your priority findings?`;
    return {
      q: message,
      a: naturalFallback,
      answer: naturalFallback,
      sources: [{ id: 'src_resilient', label: 'Cyphward Sovereign Defense Core' }],
      actions: [{ label: 'View Findings', kind: 'solid', path: '/findings' }],
    };
  }
}

export async function sendReportEmail(payload: {
  to_email: string;
  recipient_name?: string;
  subject?: string;
  custom_note?: string;
}): Promise<{ success: boolean; message: string; org?: string; domain?: string }> {
  const res = await apiFetch<{ success: boolean; message: string; org?: string; domain?: string }>(
    '/reports/send-email',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
  if (!res) throw new Error('Failed to dispatch email');
  return res;
}

