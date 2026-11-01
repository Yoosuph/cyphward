/**
 * Owner console API client. Deliberately separate from lib/api.ts: no bearer
 * token, no organization header, no refresh logic. The httpOnly owner cookie
 * is sent by the browser (same origin) and is never readable from script.
 */

import type { NotificationItem, NotificationSource } from '../lib/notifications';
/** The record counts that hold a purge back (backend core/org_guard.py). Integers only; the console words them. */
export type RetentionHold = {
  counts: { reviewer_grants: number; packs: number; snapshots: number; documents: number; evidence_files: number; incidents: number };
  retentionMonths: number | null;
  /** The fixed period for breach incidents, in years (6). */
  incidentYears: number | null;
};

export class OwnerApiError extends Error {
  /** `message` is always reviewed wording (ownerErrorText). `serverWording` is true when it is one of the server's
   *  reviewed sentences rather than the console's wording for the status. `hold` is set only for a purge refused
   *  because records are still retained. */
  constructor(message: string, readonly status: number, readonly serverWording = false, readonly hold?: RetentionHold) {
    super(message);
  }
}

/**
 * Server messages written for people, shown as they are. Anything else (a 500 body, a validation array, a
 * framework message, a stack) is replaced by the wording for its status below.
 */
const REVIEWED_DETAILS: (string | RegExp)[] = [
  // Organization and member actions (backend/app/api/owner_actions.py)
  'The name you typed does not match this organization. Nothing was changed.',
  'This organization is already suspended.',
  'This organization is not suspended.',
  'An organization must keep at least one owner.',
  'Member not found in this organization.',
  "This organization isn't on a trial.",
  "A trial can't end more than 90 days from today.",
  /^Already on the [A-Za-z ]{1,40} plan\.$/,
  'The organization changed; reload and try again.',
  'The subscription changed; reload and try again.',
  'The scan changed state; reload and try again.',
  /^Scan is already (completed|failed|cancelled)\.$/,
  "That's your own account — use Sign out instead.",
  'The change could not be saved. Nothing was changed.',
  'Organization not found.', 'User not found.', 'Scan not found.',
  // Restore a removed member (admin phase 2)
  'This organization is suspended. Lift the suspension before restoring a member. Nothing was changed.',
  'No member removal with that record was found for this organization.',
  'That record does not hold enough detail to restore the member. Nothing was changed.',
  'This removal has already been restored. Nothing was changed.',
  "That person's account no longer exists, so the membership cannot be restored.",
  "That account's email has changed since the removal. Nothing was changed.",
  'This person is already a member of this organization.',
  // Delete, restore and purge an organization (backend/app/api/owner_actions.py, docs/admin-delete-org)
  'This organization has been deleted. Restore it before making any other change. Nothing was changed.',
  'This organization is already deleted.',
  'This organization is not deleted. Nothing was changed.',
  'This organization is protected and cannot be deleted or purged from the console. Nothing was changed.',
  'This organization has an active paid subscription. It must be cancelled before the organization can be deleted. Nothing was changed.',
  'The 30-day restore window for this organization has passed, so it can no longer be restored. Nothing was changed.',
  'The 30-day restore window has not passed yet, so this organization cannot be purged. Nothing was changed.',
  'Type the word DELETE in capitals to confirm the purge. Nothing was changed.',
  'Some records of this organization are still inside their retention period, so it cannot be purged yet. Nothing was changed.',
  // Reads (backend/app/core/owner_reads.py)
  'This view took too long to load. Narrow the filters or try again in a moment.',
  // First sign-in setup (backend/app/api/owner.py)
  'Setup session expired — sign in again.',
  'Use 12–128 characters for the new password.',
  'Choose a new password, not the one you were given.',
  'Set up the authenticator app first.',
  'Set up the authenticator app again.',
  "That code didn't match — check the app and retry.",
  // Newsletter send (backend/app/api/newsletter.py)
  'This issue has already been sent or a send was already attempted.',
  "Type the draft's subject exactly to approve sending it.",
  'Nothing was sent: the mailing list could not be prepared. Ask for a new draft once the cause is fixed.',
  /^Brevo did not confirm the send of campaign [A-Za-z0-9-]{1,40}\. Check it in Brevo before doing anything else\.$/,
];

const STATUS_TEXT: Record<number, string> = {
  0: 'We could not reach Cyphward. Check your connection and try again.',
  400: 'Some details were not accepted. Check them and try again.',
  401: 'Your owner session has ended. Sign in again.',
  403: 'This request must come from the owner console. Reload the page and try again.',
  404: 'That record was not found. It may have been removed. Reload and try again.',
  409: 'This changed since the page loaded. Reload and try again.',
  422: 'Some details were not accepted. Check them and try again.',
  429: 'Too many requests. Wait a moment and try again.',
};
const SERVER_TEXT = 'The console could not complete this. Try again in a moment.';

const HOLD_KINDS = ['reviewer_grants', 'packs', 'snapshots', 'documents', 'evidence_files', 'incidents'] as const;
const count = (v: unknown) => (typeof v === 'number' && Number.isInteger(v) && v >= 0 && v < 1e9 ? v : 0);

/** A purge refused with code `retention_hold`: whole numbers only, any other field ignored. */
function retentionHold(detail: unknown): RetentionHold | undefined {
  if (!detail || typeof detail !== 'object') return undefined;
  const d = detail as { code?: unknown; counts?: Record<string, unknown>; retention_months?: unknown; incident_retention_years?: unknown };
  if (d.code !== 'retention_hold' || !d.counts || typeof d.counts !== 'object') return undefined;
  const counts = Object.fromEntries(HOLD_KINDS.map(k => [k, count(d.counts?.[k])])) as RetentionHold['counts'];
  const months = count(d.retention_months);
  const years = count(d.incident_retention_years);
  return { counts, retentionMonths: months > 0 ? months : null, incidentYears: years > 0 ? years : null };
}

function isReviewed(detail: unknown): detail is string {
  return typeof detail === 'string' && REVIEWED_DETAILS.some(r => (typeof r === 'string' ? r === detail : r.test(detail)));
}

/** The only text an owner-console error may show: a reviewed server message, else the wording for its status. */
export function ownerErrorText(status: number, detail?: unknown): string {
  if (isReviewed(detail)) return detail;
  if (status >= 500) return SERVER_TEXT;
  return STATUS_TEXT[status] ?? SERVER_TEXT;
}

async function ownerFetch<T>(path: string, init?: RequestInit, base = '/api/v1/owner'): Promise<T> {
  const res = await ownerRequest(`${base}${path}`, init);
  return res.json() as Promise<T>;
}

async function ownerRequest(url: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
  } catch {
    throw new OwnerApiError(ownerErrorText(0), 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const hold = retentionHold(body?.detail);
    if (hold) {
      // The purge refusal carries its reviewed sentence and the counts; nothing else from the body is shown.
      const message = body.detail.message;
      throw new OwnerApiError(ownerErrorText(res.status, message), res.status, isReviewed(message), hold);
    }
    throw new OwnerApiError(ownerErrorText(res.status, body?.detail), res.status, isReviewed(body?.detail));
  }
  return res;
}

function queryString(params?: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const query = qs.toString();
  return query ? `?${query}` : '';
}

/** Download a server-side CSV export (the same filters as the list on screen). Returns the row count. */
export async function ownerDownload(path: string, params?: Record<string, string | number | undefined>) {
  const res = await ownerRequest(`/api/v1/owner${path}${queryString(params)}`, { headers: { Accept: 'text/csv' } });
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')?.[1] || 'cyphward-export.csv';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { rows: Number(res.headers.get('x-export-rows') || 0), truncated: res.headers.get('x-export-truncated') === 'true' };
}

/** GET a console view; empty params are dropped. */
export function ownerGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  return ownerFetch<T>(`${path}${queryString(params)}`);
}

/** POST a console action (reason required server-side); needs the console Origin, which same-origin fetch sends. */
export function ownerPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return ownerFetch<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

export type OwnerMe = { email: string; expires_at: string; idle_minutes: number };

export const ownerMe = () => ownerFetch<OwnerMe>('/me');

export const ownerSignIn = (email: string, password: string, code: string) =>
  ownerFetch<{ ok: true; email: string; setup_required?: boolean; expires_at?: string; idle_minutes?: number }>('/session', {
    method: 'POST',
    body: JSON.stringify({ email, password, code }),
  });

/** First sign-in of a new admin login: issue the authenticator secret (shown once). */
export const ownerSetupAuthenticator = () =>
  ownerFetch<{ secret: string; otpauth_url: string }>('/setup/authenticator', { method: 'POST' });

export const ownerSetupComplete = (newPassword: string, code: string) =>
  ownerFetch<{ ok: true; email: string }>('/setup/complete', {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword, code }),
  });

export const ownerSignOut = () => ownerFetch<{ signed_out: boolean }>('/logout', { method: 'POST' });

/* ── Newsletter (the same owner cookie; routes live under /api/v1/newsletter) ── */
const NEWSLETTER = '/api/v1/newsletter';

/** The email's colours, chosen when sending: light (the default) or dark. */
export type NewsletterTheme = 'light' | 'dark';
export type NewsletterLink = { label: string; url: string };
export type NewsletterSource = { title: string; url: string };
export type NewsletterSection = {
  type: string; heading: string; body: string; links?: NewsletterLink[]; sources?: NewsletterSource[];
};
export type NewsletterIssue = {
  id: string;
  status: 'draft' | 'sent' | string;
  subject: string;
  preview: string;
  created_by: string | null;
  created_at: string | null;
  sent_at: string | null;
  approved_at: string | null;
  send_claimed_at: string | null;
  /** The email style recorded when the send was claimed; null until then. */
  send_theme?: NewsletterTheme | null;
  sendable: boolean;
  sections: NewsletterSection[];
  preview_html: string | null;
  preview_text: string | null;
};
export type NewsletterDrafts = { issues: NewsletterIssue[]; confirmed_subscribers: number };
export type NewsletterStats = { confirmed: number; unsubscribed: number; pending: number };
export type NewsletterSent = {
  id: string; status: 'sent'; sent_at: string | null; recipients: number; theme?: NewsletterTheme;
};

export const newsletterDrafts = () => ownerFetch<NewsletterDrafts>('/drafts', undefined, NEWSLETTER);
export const newsletterStats = () => ownerFetch<NewsletterStats>('/stats', undefined, NEWSLETTER);

/** The one send: explicit approval plus the subject typed exactly (the server checks both again), in the chosen
 *  email style. The server records the style with the send; it cannot be changed afterwards. */
export const newsletterSend = (id: string, subject: string, theme: NewsletterTheme = 'light') =>
  ownerFetch<NewsletterSent>(`/drafts/${encodeURIComponent(id)}/send`, {
    method: 'POST',
    body: JSON.stringify({ approve: true, subject, theme }),
  }, NEWSLETTER);

/* ── Notifications (owner-relevant events; backend/app/api/notifications.py owner_router) ── */
type OwnerNotificationPage = { notifications: NotificationItem[]; unread_count: number; has_more?: boolean };

/** The bell's source. Reads of the list are written to the owner audit; the 60-second poll asks for a count only. */
export const ownerNotifications: NotificationSource = {
  async list(limit, offset) {
    const page = await ownerGet<Partial<OwnerNotificationPage> & { items?: unknown }>('/notifications', offset ? { limit, offset } : { limit });
    return { notifications: Array.isArray(page?.notifications) ? page.notifications : [],
             unread_count: Number(page?.unread_count) || 0, has_more: Boolean(page?.has_more) };
  },
  async unreadCount() {
    const page = await ownerGet<{ unread_count?: number }>('/notifications/unread-count');
    return Number(page?.unread_count) || 0;
  },
  markRead: (id) => ownerPost(`/notifications/${encodeURIComponent(id)}/read`, {}),
  markAllRead: () => ownerPost('/notifications/read-all', {}),
};

/** Owner rows open the organisation in the console (customer paths mean nothing here). */
export const ownerNotificationLink = (item: NotificationItem): string | null =>
  item.org_id && /^[0-9a-f-]{36}$/i.test(item.org_id) ? `/organizations/${item.org_id}` : null;
