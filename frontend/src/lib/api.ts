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
import { clearPageCache } from './pageCache';
import { reportArtifactSchema, type ReportArtifact, type ArtifactContext } from './reportArtifacts';
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
      const rotated = await refreshSession(true);
      if (rotated) {
        token = rotated.access_token;
        res = await attempt(token);
      }
    }

    // Any write may change what a cached list page shows; drop it all.
    // /ai/* POSTs only read (explain, remediate, summaries, chat).
    if ((options?.method || 'GET').toUpperCase() !== 'GET' && !endpoint.startsWith('/ai/')) clearPageCache();

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = typeof err.detail === 'string' ? err.detail : (err.detail?.message || err.message);
      const error: any = new Error(detail || `Request failed with status ${res.status}`);
      // Carry the HTTP status so callers can branch (403 vs 409 vs 400).
      error.status = res.status;
      error.code = err.code || err.detail?.code;
      error.scanId = err.scan_id || err.detail?.scan_id;
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
  return await apiFetch<OverviewData>('/overview', { cache: 'no-store' });
}

// ============================================================================
// 2. Domains
// ============================================================================
export async function getDomains(): Promise<Domain[]> {
  // Empty list on failure — never invent domains for the tenant.
  const data = await apiFetch<Domain[]>('/domains');
  return data ?? [];
}

/** Like getDomains, but a failed request throws so a page can show an error state instead of "no domains". */
export async function getDomainsStrict(): Promise<Domain[]> {
  return (await apiFetch<Domain[]>('/domains', undefined, true)) ?? [];
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
  // Throw on failure so the caller can show the server's reason instead of "removed".
  const data = await apiFetch<any>(`/domains/${domainId}`, { method: 'DELETE' }, true);
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
}, strict = false): Promise<{ findings: Finding[]; total: number; categories: Record<string, number> }> {
  const query = new URLSearchParams();
  if (params?.severity) query.append('severity', params.severity);
  if (params?.category) query.append('category', params.category);
  if (params?.status) query.append('status', params.status);
  if (params?.asset_id) query.append('asset_id', params.asset_id);
  if (params?.search) query.append('search', params.search);

  const data = await apiFetch<{ findings: Finding[]; total: number; categories: Record<string, number> }>(`/findings?${query.toString()}`, undefined, strict);
  if (data) return data;

  return {
    findings: [],
    total: 0,
    categories: {},
  };
}

/** Like getFindings, but a failed request throws so the page can show an error state instead of "no issues". */
export const getFindingsStrict = (params?: Parameters<typeof getFindings>[0]) => getFindings(params, true);

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

export async function launchScan(domainId?: string): Promise<{ message: string; scan: Scan; domain: string; dispatch: string; replayed?: boolean }> {
  const orgId = getActiveOrgId() || 'unknown-workspace';
  const selector = domainId || 'default-domain';
  const storageKey = `cyphward-scan-intent:${orgId}:${selector}`;
  let intentKey = sessionStorage.getItem(storageKey);
  if (!intentKey) {
    intentKey = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(storageKey, intentKey);
  }
  try {
    const data = await apiFetch<{ message: string; scan: Scan; domain: string; dispatch: string; replayed?: boolean }>('/scans/launch', {
      method: 'POST',
      headers: { 'Idempotency-Key': intentKey },
      body: JSON.stringify({ domain_id: domainId }),
    }, true);
    if (data) {
      sessionStorage.removeItem(storageKey);
      return data;
    }
    throw new Error('Failed to launch scan');
  } catch (error: any) {
    // Preserve transport failures and 5xx responses because commit outcome may
    // be uncertain. A definitive client error completes this intent.
    if (error?.status >= 400 && error?.status < 500) sessionStorage.removeItem(storageKey);
    throw error;
  }
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

  throw new Error('The finding explanation could not be loaded.');
}

export async function getRemediation(findingId?: string, targetStack: string = 'nginx', finding?: any): Promise<RemediationGuide> {
  const data = await apiFetch<RemediationGuide>('/ai/remediate', {
    method: 'POST',
    body: JSON.stringify({ finding_id: findingId, target_stack: targetStack, finding }),
  });
  if (data) return data;

  throw new Error('The remediation guide could not be loaded.');
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
export async function acceptInvite(token: string): Promise<{ message: string; member: any; organization?: { id: string; slug?: string; name?: string } }> {
  const res = await apiFetch<{ message: string; member: any; organization?: { id: string; slug?: string; name?: string } }>(
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
  snapshot_id?: string | null;
  report_version?: string | null;
  integrity?: 'snapshot' | 'legacy';
  integrity_label?: string;
}

export async function listReports(): Promise<{ reports: ReportRow[]; total: number }> {
  const data = await apiFetch<{ reports: ReportRow[]; total: number }>('/reports');
  if (data) return data;
  return { reports: [], total: 0 };
}

/** Like listReports, but a failed request throws so a page can show an error state instead of "no reports". */
export async function listReportsStrict(): Promise<{ reports: ReportRow[]; total: number }> {
  return (await apiFetch<{ reports: ReportRow[]; total: number }>('/reports', undefined, true)) ?? { reports: [], total: 0 };
}

export async function createReport(payload?: { domain_id?: string; title?: string; request_key?: string }): Promise<{ report: ReportRow } | null> {
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
  artifact?: ReportArtifact;
  sources?: Array<{ id: string; label: string }>;
  actions?: Array<{ label: string; kind?: string; path?: string; toast?: string }>;
}

export type CyphBotActivityStep = 'request_sent' | 'reading_workspace' | 'reviewing_request' | 'building_report' | 'querying_period' | 'writing_answer' | 'retrying_provider';
const ACTIVITY_STEPS: CyphBotActivityStep[] = ['reading_workspace', 'reviewing_request', 'building_report', 'querying_period', 'writing_answer', 'retrying_provider'];

export interface CyphBotStreamCallbacks {
  onToken: (token: string) => void;
  onArtifact?: (artifact: ReportArtifact) => void;
  onArtifactStatus?: () => void;
  onActivity?: (step: CyphBotActivityStep) => void;
  onComplete: (meta: { sources?: Array<{ id: string; label: string }>; actions?: Array<{ label: string; kind?: string; path?: string; toast?: string }> }) => void;
  onError: (err: any) => void;
}

export async function streamCyphBot(
  message: string,
  history: CyphBotMessage[] = [],
  callbacks: CyphBotStreamCallbacks,
  options: { artifact_context?: ArtifactContext; signal?: AbortSignal } = {},
): Promise<void> {
  const token = await getAccessToken();
  const orgId = getActiveOrgId();

  try {
    const response = await fetch('/api/v1/ai/chat/stream', {
      method: 'POST',
      signal: options.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(orgId ? { 'X-Organization-Id': orgId } : {}),
      },
      body: JSON.stringify({
        message,
        artifact_context: options.artifact_context,
        history: history.map(h => ({
          role: h.role === 'assistant' ? 'model' : 'user',
          content: h.content,
        })),
      }),
    });

    if (!response.ok || !response.body) {
      const failure = await response.json().catch(() => null);
      if (typeof failure?.detail === 'string') throw new Error(failure.detail);
      throw new Error(`Stream request failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const consume = (line: string): boolean => {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) return false;
      const data = JSON.parse(trimmed.slice(5).trim());
      if (data.error) throw new Error(String(data.error));
      if (data.type === 'assistant-status' && ACTIVITY_STEPS.includes(data.step)) callbacks.onActivity?.(data.step);
      if (data.type === 'artifact-status') callbacks.onArtifactStatus?.();
      if (data.type === 'artifact') {
        const artifact = reportArtifactSchema.parse(data.artifact);
        if (artifact.org_id !== orgId) throw new Error('Report workspace mismatch');
        callbacks.onArtifact?.(artifact);
      }
      if (data.token) callbacks.onToken(data.token);
      if (data.done) {
        callbacks.onComplete({ sources: data.sources, actions: data.actions });
        return true;
      }
      return false;
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          if (buffer.trim() && consume(buffer)) return;
          throw new Error('CyphBot disconnected before finishing. Please retry.');
        }

        buffer += decoder.decode(value, { stream: true });
        if (buffer.length > 2_000_000) throw new Error('The response was too large to display. Try a smaller report.');
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (consume(line)) return;
        }
      }
    } finally {
      await reader.cancel().catch(() => {});
    }

  } catch (err) {
    callbacks.onError(err);
    throw err;
  }
}

export async function askCyphBot(
  message: string,
  history: CyphBotMessage[] = [],
  options: { artifact_context?: ArtifactContext; signal?: AbortSignal } = {},
): Promise<CyphBotResponse> {
  try {
    const data = await apiFetch<any>('/ai/chat', {
      method: 'POST',
      signal: options.signal,
      body: JSON.stringify({
        message,
        artifact_context: options.artifact_context,
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
      artifact: data.artifact ? reportArtifactSchema.parse(data.artifact) : undefined,
      sources: data.sources || [{ id: 's1', label: 'Cyphward Sovereign Defense Core' }],
      actions: data.actions || [{ label: 'View Findings', kind: 'solid', path: '/findings' }],
    };
  } catch (err) {
    if (options.signal?.aborted) throw err;
    const naturalFallback = `CyphBot could not load a response. Open the recorded finding and its guidance in **Findings**, or retry. No new assessment or configuration recommendation was produced.`;
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

/** Whether the server offers its configured demo sign-in. */
export async function demoLoginStatus(): Promise<{ enabled: boolean }> {
  const res = await apiFetch<{ enabled: boolean }>('/auth/demo-login', undefined, false);
  return { enabled: Boolean(res?.enabled) };
}

/** Demo sign-in. The browser sends no account credentials. */
export async function demoLoginRequest(): Promise<AuthTokens> {
  return authPost<AuthTokens>('/auth/demo-login', {});
}

export interface MfaChallenge {
  mfa_required: true;
  mfa_token: string;
  email_hint: string;
}

export async function mfaVerify(mfaToken: string, code: string, remember = false): Promise<AuthTokens> {
  return authPost<AuthTokens>('/auth/mfa/verify', { mfa_token: mfaToken, code, remember });
}

export type MfaStartResult = AuthTokens | { mfa_required: true; sent: boolean; email_hint: string };

/**
 * Second step of a Google sign-in. Runs on the sign-in page's own origin, so
 * the server can see a remembered-browser cookie: a remembered browser gets
 * its session straight away, any other gets the emailed code.
 */
export async function mfaStart(mfaToken: string): Promise<MfaStartResult> {
  return authPost<MfaStartResult>('/auth/mfa/start', { mfa_token: mfaToken, code: '' });
}

export async function forgetTrustedBrowsers(): Promise<{ forgotten: boolean } | null> {
  return apiFetch<{ forgotten: boolean }>('/auth/trusted-browsers/forget', { method: 'POST' }, true);
}

export async function mfaResend(mfaToken: string): Promise<{ sent: boolean }> {
  return authPost<{ sent: boolean }>('/auth/mfa/send', { mfa_token: mfaToken, code: '' });
}

export interface MfaStatus {
  enrolled: boolean;
  admin_required: boolean;
  email_verified: boolean;
  totp_enrolled: boolean;
  totp_pending: boolean;
  remembered_browsers?: number;
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

export async function totpEnrollStart(): Promise<{ secret: string; otpauth_url: string } | null> {
  return apiFetch('/auth/totp/enroll/start', { method: 'POST' }, true);
}

export async function totpEnrollConfirm(code: string): Promise<{ enrolled: boolean } | null> {
  return apiFetch('/auth/totp/enroll/confirm', {
    method: 'POST',
    body: JSON.stringify({ code }),
  }, true);
}

export async function totpDisable(code: string): Promise<{ disabled: boolean } | null> {
  return apiFetch('/auth/totp/disable', {
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

export async function deleteOwnAccount(email: string, password: string): Promise<{ deleted: boolean } | null> {
  return apiFetch<{ deleted: boolean }>('/auth/account/delete', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
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

export async function platformOverdueScans(reason: string, limit = 50): Promise<{ count: number; scans: PlatformOverdueScan[] }> {  const res = await apiFetch<{ count: number; scans: PlatformOverdueScan[] }>(
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

export async function oneTapLogin(credential: string): Promise<AuthTokens | MfaChallenge> {
  return authPost<AuthTokens | MfaChallenge>('/auth/google/one-tap', { credential });
}

// ============================================================================
// Compliance readiness (evidence only — never a legal verdict)
// ============================================================================
export type ComplianceStatus = 'present' | 'gap' | 'not_assessed' | 'not_applicable' | 'awaiting_input';

export interface ComplianceFindingRef {
  id: string;
  title: string;
  severity: string;
  status: string;
}

export interface ComplianceDomainEvidence {
  domain_id: string;
  domain: string;
  status: ComplianceStatus;
  status_label: string;
  reason: string;
  reason_text: string;
  source: string | null;
  source_label: string | null;
  observed_at: string | null;
  expires_at: string | null;
  scan_id: string | null;
  finding_ids: string[];
  details: {
    open_ports?: Record<string, number[]>;
    missing?: { hostname: string; check: string; reason: string }[];
    omitted?: { hostname: string; check: string; reason: string }[];
    complete_scans?: { scan_id: string; completed_at: string }[];
    not_counted?: { scan_id: string; completed_at: string; state: string }[];
    window_days?: number;
    [key: string]: unknown;
  };
}

export interface ComplianceRequirement {
  key: string;
  group: string;
  title: string;
  summary: string;
  clause: string;
  clause_verified: boolean;
  clause_label: string;
  evidence_type_labels: string[];
  checks_performed: string | null;
  not_checked: string | null;
  freshness_days: number;
  remediation_hint: string;
  status: ComplianceStatus;
  status_label: string;
  reason: string;
  reason_text: string;
  source: string | null;
  source_label: string | null;
  domains: ComplianceDomainEvidence[];
  findings: ComplianceFindingRef[];
  informational_findings: ComplianceFindingRef[];
  policy_mentions?: { domain: string; state: 'mentioned' | 'not_found'; url: string | null }[];
  sources?: { source: string; source_label: string; status: ComplianceStatus; status_label: string; reason: string; reason_text: string; headline?: boolean }[];
  answers?: { question_key: string; status: ComplianceStatus; reason: string; reason_text: string; answered: boolean;
              owner_name: string | null; expires_at: string | null; value?: string | null; date?: string | null }[];
  /** A practitioner's note that they reviewed this requirement (C6). Never changes the status. */
  /** Reviewers receive a count instead of finding details. */
  open_finding_count?: number;
  practitioner_review?: PractitionerReview | null;
  /** This organisation's practitioner overlay on the clause reference (C6). */
  clause_review?: ClauseReview | null;
}

export interface PractitionerReview {
  outcome: 'reviewed' | 'reviewed_with_comments';
  outcome_label: string;
  reviewer_name: string;
  reviewer_domain?: string | null;
  reviewed_at: string;
  comment: string | null;
  label: string;
}

export interface ClauseReview {
  verified: boolean;
  reviewer_name: string;
  at: string;
  note: string | null;
  label: string;
}

export interface ComplianceReadiness {
  with_evidence: number;
  present: number;
  gap: number;
  awaiting_input: number;
  not_assessed: number;
  applicable: number;
}

export interface ComplianceOverview {
  disclaimer: string;
  note: string;
  register: { version: string; title: string; references_pending_review: number };
  plan: string;
  readiness: ComplianceReadiness;
  domains: { id: string; domain: string }[];
  groups: {
    key: string;
    title: string;
    locked: boolean;
    counts: ComplianceReadiness;
    requirement_count: number;
    requirements: ComplianceRequirement[];
  }[];
}

export async function getComplianceOverview(): Promise<ComplianceOverview> {
  return (await apiFetch<ComplianceOverview>('/compliance/overview', undefined, true)) as ComplianceOverview;
}


// ---- Questionnaire and customer answers (C3a) ----
export interface QuestionnaireAnswer {
  id: string;
  value: string | null;
  date: string | null;
  text: string | null;
  owner_user_id: string | null;
  owner_name: string | null;
  attested_at: string;
  expires_at: string;
  expired: boolean;
  evidence_link: string | null;
  notes: string | null;
}

export interface QuestionnaireQuestion {
  key: string;
  group: string;
  group_title: string;
  prompt: string;
  type: 'yes_no' | 'choice' | 'date' | 'text';
  shown: boolean;
  options: string[];
  allow_not_applicable: boolean;
  allows_date: boolean;
  date_label: string | null;
  allows_text: boolean;
  text_label: string | null;
  text_max: number | null;
  expiry_days_from_date: number | null;
  show_if: { question: string; value: string } | null;
  evidences: { key: string; title: string }[];
  applicability: { requirement_key: string; when: string }[];
  answer_state: 'unanswered' | 'answered' | 'not_sure' | 'expired';
  current: QuestionnaireAnswer | null;
  status: ComplianceStatus | null;
  status_label: string | null;
  reason: string | null;
  reason_text: string | null;
}

export interface Questionnaire {
  disclaimer: string;
  version: string;
  display_timezone: string;
  answered: number;
  questions: QuestionnaireQuestion[];
}

export interface OrgMember {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
}

export interface AttestationInput {
  question_key: string;
  answer: { value: string; date?: string; text?: string };
  owner_user_id: string;
  expires_at?: string;
  evidence_link?: string;
  notes?: string;
}

export const getQuestionnaire = () =>
  apiFetch<Questionnaire>('/compliance/questionnaire', undefined, true) as Promise<Questionnaire>;

export const recordAttestation = (body: AttestationInput) =>
  apiFetch<QuestionnaireAnswer>('/compliance/attestations', { method: 'POST', body: JSON.stringify(body) }, true);

export const getAttestationHistory = (key: string) =>
  apiFetch<{ question_key: string; history: (QuestionnaireAnswer & { superseded: boolean })[] }>(
    `/compliance/attestations/${encodeURIComponent(key)}`, undefined, true);

export const listOrgMembers = () => apiFetch<OrgMember[]>('/members', undefined, true) as Promise<OrgMember[]>;

// ---- Breach incident log (C3b) ----
export type IncidentSeverity = 'low' | 'medium' | 'high' | 'critical';
export type IncidentStatus = 'open' | 'contained' | 'closed';

export interface Incident {
  id: string;
  title: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  notes: string | null;
  detected_at: string;
  became_aware_at: string;
  notified_commission_at: string | null;
  notified_subjects_at: string | null;
  deadline_at: string;
  hours_remaining: number | null;
  overdue: boolean;
  notified_late: boolean;
  commission_state: 'pending' | 'overdue' | 'notified_on_time' | 'notified_late';
  display_timezone: string;
  local: Record<'detected_at' | 'became_aware_at' | 'notified_commission_at' | 'notified_subjects_at' | 'deadline_at', string | null>;
}

export interface IncidentList {
  disclaimer: string;
  checklist: { key: string; title: string; text: string }[];
  deadline_hours: number;
  display_timezone: string;
  incidents: Incident[];
}

export interface IncidentCreate {
  title: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  detected_at: string;
  became_aware_at: string;
  notified_commission_at?: string | null;
  notified_subjects_at?: string | null;
  notes?: string | null;
}

export type IncidentChanges = Partial<Pick<Incident, 'status' | 'severity' | 'notified_commission_at' | 'notified_subjects_at' | 'notes'>>;

export const listIncidents = () => apiFetch<IncidentList>('/compliance/incidents', undefined, true) as Promise<IncidentList>;

export const createIncident = (body: IncidentCreate) =>
  apiFetch<Incident>('/compliance/incidents', { method: 'POST', body: JSON.stringify(body) }, true) as Promise<Incident>;

export const updateIncident = (id: string, changes: IncidentChanges) =>
  apiFetch<Incident>(`/compliance/incidents/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(changes) }, true) as Promise<Incident>;

// ============================================================================
// Evidence packs (packet C4). Growth plan; members read, owners and admins issue.
// ============================================================================
export type PackKind = 'readiness_pack' | 'dpo_section';

export interface EvidencePack {
  id: string;
  snapshot_id: string;
  kind: PackKind;
  pack_version: string;
  issued_at: string;
  issued_by: string | null;
  window_start: string | null;
  window_end: string | null;
  html_sha256: string;
  pdf_sha256: string;
  retain_until: string;
}

export interface PackList {
  packs: EvidencePack[];
  total: number;
  notice: string;
  retention_months: number;
  retention: string;
}

export const listPacks = () => apiFetch<PackList>('/packs', undefined, true) as Promise<PackList>;

export const issuePack = (body: { kind: PackKind; include_dpo?: boolean; request_key?: string }) =>
  apiFetch<{ pack: EvidencePack; created: boolean }>('/packs', { method: 'POST', body: JSON.stringify(body) }, true) as Promise<{ pack: EvidencePack; created: boolean }>;

/** The stored bytes of an issued pack. A plain link cannot send the session headers, so this fetches a Blob. */
export async function downloadPack(id: string, format: 'html' | 'pdf'): Promise<Blob> {
  const token = await ensureFreshAccessToken();
  const orgId = getActiveOrgId();
  const res = await fetch(`${API_BASE}/packs/${encodeURIComponent(id)}/${format}`, {
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(orgId ? { 'X-Organization-Id': orgId } : {}) },
  });
  if (!res.ok) throw new Error(res.status === 403 ? 'Evidence packs are part of the Growth plan.' : 'The download failed. Try again.');
  return res.blob();
}

// How long issued snapshots (and packs) are kept. Members read it; the owner sets it.
export interface EvidenceRetention { retention_months: number; retention: string }
export const getEvidenceRetention = () =>
  apiFetch<EvidenceRetention>('/snapshots/retention', undefined, true) as Promise<EvidenceRetention>;
export const setEvidenceRetention = (months: number) =>
  apiFetch<EvidenceRetention>('/snapshots/retention', { method: 'PUT', body: JSON.stringify({ months }) }, true) as Promise<EvidenceRetention>;

// ---- AI-drafted documents (C5) ----
export type DocumentKind = 'privacy_policy' | 'cookie_notice' | 'breach_response_plan' | 'retention_schedule';
export type DocumentStatus = 'not_generated' | 'draft' | 'approved';

export interface DocumentPlaceholder { key: string; text: string }
export interface DocumentApproval { approved_by: string | null; approved_at: string; source: 'customer_attested'; open_placeholders: number }

export interface DocumentVersion {
  id: string;
  version: number;
  generated_at: string;
  generated_by: string | null;
  generator: string;
  fallback_reason: string | null;
  placeholders: DocumentPlaceholder[];
  open_placeholders: number;
  approval: DocumentApproval | null;
  stale?: boolean;
}

export interface DocumentSummary {
  kind: DocumentKind;
  title: string;
  status: DocumentStatus;
  latest: DocumentVersion | null;
  history: DocumentVersion[];
}

export interface DocumentList { label: string; daily_cap: number; generated_today: number; documents: DocumentSummary[] }
export interface DocumentFull extends DocumentVersion { kind: DocumentKind; title: string; label: string; text: string; is_latest: boolean }

export const listDocuments = () => apiFetch<DocumentList>('/compliance/documents', undefined, true) as Promise<DocumentList>;
export const getDocument = (id: string) =>
  apiFetch<DocumentFull>(`/compliance/documents/${encodeURIComponent(id)}`, undefined, true) as Promise<DocumentFull>;
export const generateDocument = (kind: DocumentKind) =>
  apiFetch<{ id: string; version: number }>(`/compliance/documents/${kind}/generate`, { method: 'POST' }, true) as Promise<{ id: string; version: number }>;
export const approveDocument = (id: string) =>
  apiFetch<{ id: string; approved_at: string }>(`/compliance/documents/${encodeURIComponent(id)}/approve`, { method: 'POST' }, true) as Promise<{ id: string; approved_at: string }>;

// ---- Evidence files attached to questionnaire answers (C6) ----
export interface EvidenceFile {
  id: string;
  question_key: string;
  display_name: string;
  content_type: string;
  type_label: string;
  size_bytes: number;
  uploaded_at: string | null;
  uploaded_by: string | null;
}
export interface EvidenceFileList {
  files: EvidenceFile[];
  usage: { files: number; bytes: number };
  limits: { max_bytes: number; max_files: number; max_total_bytes: number; extensions: string[]; label: string };
  uploads_available: boolean;
}

export const listEvidenceFiles = () =>
  apiFetch<EvidenceFileList>('/compliance/evidence-files', undefined, true) as Promise<EvidenceFileList>;

export const getEvidenceFileLink = (id: string) =>
  apiFetch<{ url: string; expires_in: number; display_name: string }>(
    `/compliance/evidence-files/${encodeURIComponent(id)}/download`, { cache: 'no-store' }, true);

export const removeEvidenceFile = (id: string) =>
  apiFetch<{ id: string; removed: boolean }>(`/compliance/evidence-files/${encodeURIComponent(id)}`, { method: 'DELETE' }, true);

/** The file goes up as the raw request body (no multipart); XMLHttpRequest gives upload progress. */
export async function uploadEvidenceFile(
  questionKey: string, file: File, onProgress: (fraction: number) => void,
): Promise<EvidenceFile> {
  const token = await ensureFreshAccessToken();
  const orgId = getActiveOrgId();
  return new Promise<EvidenceFile>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/compliance/evidence-files?question_key=${encodeURIComponent(questionKey)}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-File-Name', encodeURIComponent(file.name));
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    if (orgId) xhr.setRequestHeader('X-Organization-Id', orgId);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onerror = () => reject(new Error('The upload could not be sent. Check your connection and try again.'));
    xhr.onload = () => {
      let body: any = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        clearPageCache();
        resolve(body as EvidenceFile);
        return;
      }
      const detail = typeof body?.detail === 'string' ? body.detail : `The upload failed (status ${xhr.status}).`;
      const error: any = new Error(detail);
      error.status = xhr.status;
      reject(error);
    };
    xhr.send(file);
  });
}

// ---------------------------------------------------------------------------
// Reviewer access (C6): an owner grants a DPCO practitioner time-limited, read-only review access
// ---------------------------------------------------------------------------

export type ReviewerGrantStatus = 'pending' | 'active' | 'expired' | 'revoked';

export interface ReviewerGrant {
  id: string;
  reviewer_email: string;
  purpose: string;
  status: ReviewerGrantStatus;
  granted_at: string;
  granted_by_name: string | null;
  expires_at: string;
  revoked_at: string | null;
}

export interface ReviewerActivity {
  kind: 'review' | 'clause';
  id: string;
  requirement_key: string;
  requirement_title: string;
  reviewer_name: string;
  at: string;
  outcome: string | null;
  outcome_label: string | null;
  verified: boolean | null;
  text: string | null;
}

export interface ReviewerGrantList {
  grants: ReviewerGrant[];
  activity: ReviewerActivity[];
  audit: { action: string; at: string; grant_id: string | null; by: string | null }[];
  note: string;
  limits: { min_days: number; default_days: number; max_days: number; purpose_max: number };
  can_grant: boolean;
}

export const listReviewerGrants = () =>
  apiFetch<ReviewerGrantList>('/compliance/reviewer-grants', undefined, true) as Promise<ReviewerGrantList>;
export const createReviewerGrant = (body: { email: string; days: number; purpose: string }) =>
  apiFetch<{ grant: ReviewerGrant }>('/compliance/reviewer-grants', { method: 'POST', body: JSON.stringify(body) }, true) as Promise<{ grant: ReviewerGrant }>;
export const revokeReviewerGrant = (id: string) =>
  apiFetch<{ revoked: boolean }>(`/compliance/reviewer-grants/${encodeURIComponent(id)}/revoke`, { method: 'POST' }, true) as Promise<{ revoked: boolean }>;

export interface MyReviewGrant { org_id: string; org_name: string; purpose: string; expires_at: string }

/** The organisations this account may review right now. Never throws: no grant simply means an empty list. */
export async function getMyReviewGrants(): Promise<MyReviewGrant[]> {
  try {
    const res = await apiFetch<{ grants: MyReviewGrant[] }>('/compliance/reviewer/grants', undefined, true);
    return res?.grants ?? [];
  } catch {
    return [];
  }
}

export interface ReviewerOverview extends ComplianceOverview {
  organisation: { id: string; name: string };
  grant: { id: string; purpose: string; expires_at: string };
  reviewer_note: string;
}

// The reviewed organisation is named per call; it overrides the header of the signed-in account's own workspace.
const forOrg = (orgId: string): RequestInit => ({ headers: { 'X-Organization-Id': orgId } });

export const getReviewerOverview = (orgId: string) =>
  apiFetch<ReviewerOverview>('/compliance/reviewer/overview', forOrg(orgId), true) as Promise<ReviewerOverview>;
export const recordPractitionerReview = (orgId: string, key: string, body: { outcome: string; comment: string | null }) =>
  apiFetch<{ practitioner_review: PractitionerReview }>(`/compliance/reviewer/requirements/${encodeURIComponent(key)}/review`,
    { ...forOrg(orgId), method: 'POST', body: JSON.stringify(body) }, true) as Promise<{ practitioner_review: PractitionerReview }>;
export const recordClauseReference = (orgId: string, key: string, body: { verified: boolean; note: string | null }) =>
  apiFetch<{ clause_review: ClauseReview }>(`/compliance/reviewer/requirements/${encodeURIComponent(key)}/clause-reference`,
    { ...forOrg(orgId), method: 'POST', body: JSON.stringify(body) }, true) as Promise<{ clause_review: ClauseReview }>;
