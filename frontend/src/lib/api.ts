/* ————————————————————————————————————————————————
   CYPHWARD — Enterprise Live API Client
   Direct integration with FastAPI backend & Supabase PostgreSQL.
   Full MVP support: Overview, Domains, Assets, Findings, Scans,
   Remediation, Reports, Settings, AI assistance.
   ———————————————————————————————————————————————— */

import {
  ensureFreshAccessToken,
  getAccessTokenSync,
  refreshSession,
  type AuthTokens,
  type SessionUser,
} from './session';
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
  return ensureFreshAccessToken();
}

async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit,
  throwOnError = false,
): Promise<T | null> {
  const attempt = async (token: string | null): Promise<Response> => {
    const orgId = getActiveOrgId();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(orgId ? { 'X-Organization-Id': orgId } : {}),
      ...((options?.headers as Record<string, string>) || {}),
    };
    return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  };

  try {
    let token = await ensureFreshAccessToken();
    let res = await attempt(token);

    // One-shot recovery: rotate the refresh token and replay the request.
    if (res.status === 401 && getAccessTokenSync()) {
      const rotated = await refreshSession();
      if (rotated) {
        token = rotated.access_token;
        res = await attempt(token);
      }
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const error: any = new Error(err.detail || `Request failed with status ${res.status}`);
      // Carry the HTTP status so callers can branch (403 vs 409 vs 400).
      error.status = res.status;
      throw error;
    }
    return (await res.json()) as T;
  } catch (err) {
    // Callers that must surface the exact server detail (OTP invalid/attempts,
    // resend cooldowns) opt in via throwOnError; everything else degrades to null.
    if (throwOnError) throw err;
    console.warn(`API call ${endpoint} fallback:`, err);
    return null;
  }
}

// ============================================================================
// 1. Overview & Posture
// ============================================================================
export async function getOverview(): Promise<OverviewData | null> {
  // No mock fallback: a failed/forbidden call must surface as null so the UI
  // shows an honest loading/empty state instead of fabricated tenant data.
  return await apiFetch<OverviewData>('/overview');
}

// ============================================================================
// 2. Domains
// ============================================================================
export async function getDomains(): Promise<Domain[]> {
  // Empty list on failure — never invent domains for the tenant.
  const data = await apiFetch<Domain[]>('/domains');
  return data ?? [];
}

export async function addDomain(domain: string): Promise<{ domain: Domain; dns_instructions: any }> {
  const data = await apiFetch<{ domain: Domain; dns_instructions: any }>('/domains', {
    method: 'POST',
    body: JSON.stringify({ domain }),
  });
  if (!data) throw new Error('Failed to add domain. Ensure you are signed in.');
  return data;
}

export async function verifyDomain(domainId: string): Promise<{ status: string; message: string; details: any }> {
  const data = await apiFetch<{ status: string; message: string; details: any }>(`/domains/${domainId}/verify`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
  if (!data) throw new Error('Domain verification request failed. Please try again.');
  return data;
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
    sovereign_advisory: 'Roll the recommended change out in a test environment first, then apply it in production.',
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

export async function getExecutiveSummary(): Promise<ExecutiveSummary | null> {
  // No fabricated summary when the API fails — caller shows an honest error.
  return await apiFetch<ExecutiveSummary>('/ai/executive-summary', {
    method: 'POST',
    body: JSON.stringify({}),
  });
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
  plan?: string;
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
  }, true);
}

export async function updateMemberRole(userId: string, role: string): Promise<any> {
  return apiFetch(`/members/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  }, true);
}

/** Consume a single-use invite token; joins the workspace on success. */
export async function acceptInvite(token: string): Promise<{ message: string; member: any }> {
  const res = await apiFetch<{ message: string; member: any }>(
    '/members/invites/accept',
    { method: 'POST', body: JSON.stringify({ token }) },
    true,
  );
  if (!res) throw new Error('Could not accept the invitation. Please try again.');
  return res;
}

export async function listInvites(): Promise<any[] | null> {
  return apiFetch('/members/invites');
}

export async function revokeInvite(inviteId: string): Promise<any> {
  return apiFetch(`/members/invites/${inviteId}`, { method: 'DELETE' }, true);
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
    const naturalFallback = `Public sites should use HTTPS (TLS 1.3) and strict email authentication (DMARC p=reject).\n\nYou can see your open issues and security score in the **Findings** section. Would you like me to walk you through fixing your top issues?`;
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


// ============================================================================
// Auth lifecycle (welcome mail after signup / first login)
// ============================================================================
// throwOnError: network/server failures must reject so callers can retry on
// the next login, while a 200 "sent: false" (server declined) resolves.
export async function sendWelcomeEmail(): Promise<boolean> {
  const res = await apiFetch<{ sent: boolean }>('/auth/welcome', { method: 'POST' }, true);
  return !!res?.sent;
}

// ============================================================================
// Email verification (Brevo OTP)
// ============================================================================
export interface VerificationStatus {
  email: string;
  verified: boolean;
}

export interface OtpSendResult {
  sent: boolean;
  reason?: string;
  expires_in?: number;
  resend_after?: number;
}

export async function getVerificationStatus(): Promise<VerificationStatus | null> {
  return await apiFetch<VerificationStatus>('/auth/verification');
}

export async function sendVerificationOtp(): Promise<OtpSendResult> {
  // Throws (429 detail) on resend cooldown so the UI can show the window.
  const res = await apiFetch<OtpSendResult>('/auth/otp/send', { method: 'POST' }, true);
  if (!res) throw new Error('Could not send the code. Please try again.');
  return res;
}

export async function verifyEmailOtp(code: string): Promise<{ verified: boolean }> {
  // Throws with server detail (invalid code, attempts left, expired) so the
  // page can display the exact reason.
  const res = await apiFetch<{ verified: boolean }>(
    '/auth/otp/verify',
    { method: 'POST', body: JSON.stringify({ code }) },
    true,
  );
  if (!res) throw new Error('Verification failed. Please try again.');
  return res;
}

// ============================================================================
// Auth (our own backend — register/login/sessions, all emails via Brevo)
// ============================================================================
export interface BootstrapMembership {
  org: { id: string; name: string; slug: string; plan?: string; created_at?: string; [k: string]: unknown };
  role: string;
  domains: Domain[];
}

export interface BootstrapData {
  user: SessionUser;
  email_verified: boolean;
  memberships: BootstrapMembership[];
}

async function authPost<T>(endpoint: string, payload: unknown): Promise<T> {
  const res = await apiFetch<T>(endpoint, { method: 'POST', body: JSON.stringify(payload) }, true);
  if (!res) throw new Error('Authentication failed. Please try again.');
  return res;
}

export async function loginRequest(email: string, password: string): Promise<AuthTokens | MfaChallenge> {
  return authPost<AuthTokens | MfaChallenge>('/auth/login', { email, password });
}

export interface MfaChallenge {
  mfa_required: true;
  mfa_token: string;
  email_hint: string;
}

export async function mfaVerify(mfaToken: string, code: string): Promise<AuthTokens> {
  return authPost<AuthTokens>('/auth/mfa/verify', { mfa_token: mfaToken, code });
}

export async function mfaResend(mfaToken: string): Promise<{ sent: boolean }> {
  return authPost<{ sent: boolean }>('/auth/mfa/send', { mfa_token: mfaToken, code: '' });
}

export interface MfaStatus {
  enrolled: boolean;
  admin_required: boolean;
  email_verified: boolean;
}

export async function mfaStatus(): Promise<MfaStatus | null> {
  return apiFetch<MfaStatus>('/auth/mfa/status', {}, true);
}

export async function mfaEnroll(): Promise<{ enrolled: boolean } | null> {
  return apiFetch<{ enrolled: boolean }>('/auth/mfa/enroll', { method: 'POST' }, true);
}

export async function mfaDisableRequest(): Promise<{ sent: boolean } | null> {
  return apiFetch<{ sent: boolean }>('/auth/mfa/disable/request', { method: 'POST' }, true);
}

export async function mfaDisableConfirm(code: string): Promise<{ disabled: boolean } | null> {
  return apiFetch<{ disabled: boolean }>('/auth/mfa/disable/confirm', {
    method: 'POST',
    body: JSON.stringify({ code }),
  }, true);
}

export async function exportOrganization(): Promise<Blob | null> {
  const token = await ensureFreshAccessToken();
  const orgId = getActiveOrgId();
  const res = await fetch(`${API_BASE}/organizations/export`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(orgId ? { 'X-Organization-Id': orgId } : {}),
    },
  });
  if (!res.ok) throw new Error('Export failed. Only workspace owners can export.');
  return res.blob();
}

export async function closeOrganization(slug: string): Promise<{ closed: boolean; org_id: string } | null> {
  return apiFetch<{ closed: boolean; org_id: string }>('/organizations/close', {
    method: 'POST',
    body: JSON.stringify({ slug }),
  }, true);
}

export interface SubscriptionInfo {
  subscription: any | null;
  effective_status: string | null;
  entitlements: any;
  provider: string;
}

export async function getSubscription(): Promise<SubscriptionInfo | null> {
  return apiFetch<SubscriptionInfo>('/billing/subscription', {}, true);
}

export async function setSubscriptionPlan(plan: string): Promise<{ subscription: any; invoice: any } | null> {
  return apiFetch('/billing/subscription', {
    method: 'POST',
    body: JSON.stringify({ plan }),
  }, true);
}

export async function renewSubscription(): Promise<{ subscription: any; invoice: any } | null> {
  return apiFetch('/billing/subscription/renew', { method: 'POST' }, true);
}

export async function cancelSubscription(): Promise<{ subscription: any } | null> {
  return apiFetch('/billing/subscription/cancel', { method: 'POST' }, true);
}

export async function listInvoices(): Promise<{ invoices: any[] } | null> {
  return apiFetch<{ invoices: any[] }>('/billing/invoices', {}, true);
}

export interface MonitoredHost {
  id: string;
  hostname: string;
  created_at: string;
}

export async function listMonitoredHosts(domainId: string): Promise<{ hosts: MonitoredHost[] } | null> {
  return apiFetch<{ hosts: MonitoredHost[] }>(`/domains/${domainId}/hosts`, {}, true);
}

export async function addMonitoredHost(domainId: string, hostname: string): Promise<{ host: MonitoredHost } | null> {
  return apiFetch<{ host: MonitoredHost }>(`/domains/${domainId}/hosts`, {
    method: 'POST',
    body: JSON.stringify({ hostname }),
  }, true);
}

export async function removeMonitoredHost(domainId: string, hostId: string): Promise<{ removed: boolean } | null> {
  return apiFetch<{ removed: boolean }>(`/domains/${domainId}/hosts/${hostId}`, {
    method: 'DELETE',
  }, true);
}

export interface PlatformHealth {
  database: { connected: boolean; roundtrip_ms: number };
  daily_scans_last_completed: string | null;
  scans_active: number;
}

export async function platformHealth(): Promise<PlatformHealth> {
  const res = await apiFetch<PlatformHealth>('/platform/health', {}, true);
  if (!res) throw new Error('Platform access required.');
  return res;
}

export interface PlatformTenant {
  id: string;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
  member_count: number;
  domain_count: number;
  active_scan_count: number;
}

export async function platformTenantLookup(orgId: string, reason: string): Promise<PlatformTenant> {
  const res = await apiFetch<PlatformTenant>(
    `/platform/tenants/${encodeURIComponent(orgId)}?reason=${encodeURIComponent(reason)}`, {}, true);
  if (!res) throw new Error('Lookup failed.');
  return res;
}

export interface PlatformOverdueScan {
  id: string;
  org_id: string;
  org_name: string;
  status: string;
  created_at: string;
  lease_expires_at: string | null;
}

export async function platformOverdueScans(reason: string, limit = 50): Promise<{ count: number; scans: PlatformOverdueScan[] }> {
  const res = await apiFetch<{ count: number; scans: PlatformOverdueScan[] }>(
    `/platform/scans/overdue?reason=${encodeURIComponent(reason)}&limit=${limit}`, {}, true);
  if (!res) throw new Error('Lookup failed.');
  return res;
}

export async function registerRequest(
  email: string,
  password: string,
  fullName: string,
): Promise<AuthTokens> {
  return authPost<AuthTokens>('/auth/register', { email, password, full_name: fullName });
}

export async function exchangeOtp(otc: string): Promise<AuthTokens> {
  return authPost<AuthTokens>('/auth/exchange', { otc });
}

export async function logoutRequest(refreshToken: string): Promise<void> {
  try {
    await apiFetch('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }) });
  } catch {
    /* best-effort — the local session is cleared regardless */
  }
}

export async function forgotPasswordRequest(email: string): Promise<{ ok: boolean }> {
  return authPost<{ ok: boolean }>('/auth/forgot-password', { email });
}

export async function resetPasswordRequest(token: string, password: string): Promise<{ ok: boolean }> {
  return authPost<{ ok: boolean }>('/auth/reset-password', { token, password });
}

export async function getBootstrap(): Promise<BootstrapData> {
  const data = await apiFetch<BootstrapData>('/auth/bootstrap', {}, true);
  if (!data) throw new Error('Could not load your account.');
  return data;
}

export async function getGoogleClientId(): Promise<{ client_id: string | null }> {
  const res = await apiFetch<{ client_id: string | null }>('/auth/google/client-id', {}, true);
  if (!res) throw new Error('Could not reach Google sign-in.');
  return res;
}

export async function oneTapLogin(credential: string): Promise<AuthTokens> {
  return authPost<AuthTokens>('/auth/google/one-tap', { credential });
}
