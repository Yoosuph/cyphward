/**
 * Owner console API client. Deliberately separate from lib/api.ts: no bearer
 * token, no organization header, no refresh logic. The httpOnly owner cookie
 * is sent by the browser (same origin) and is never readable from script.
 */

export class OwnerApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function ownerFetch<T>(path: string, init?: RequestInit, base = '/api/v1/owner'): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, {
      ...init,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
  } catch {
    throw new OwnerApiError('Network error — check your connection and retry.', 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body?.detail === 'string' ? body.detail : `Request failed (${res.status})`;
    throw new OwnerApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

/** GET a console view; empty params are dropped. */
export function ownerGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  const query = qs.toString();
  return ownerFetch<T>(query ? `${path}?${query}` : path);
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
  sendable: boolean;
  sections: NewsletterSection[];
  preview_html: string | null;
  preview_text: string | null;
};
export type NewsletterDrafts = { issues: NewsletterIssue[]; confirmed_subscribers: number };
export type NewsletterStats = { confirmed: number; unsubscribed: number; pending: number };
export type NewsletterSent = { id: string; status: 'sent'; sent_at: string | null; recipients: number };

export const newsletterDrafts = () => ownerFetch<NewsletterDrafts>('/drafts', undefined, NEWSLETTER);
export const newsletterStats = () => ownerFetch<NewsletterStats>('/stats', undefined, NEWSLETTER);

/** The one send: explicit approval plus the subject typed exactly. The server checks both again. */
export const newsletterSend = (id: string, subject: string) =>
  ownerFetch<NewsletterSent>(`/drafts/${encodeURIComponent(id)}/send`, {
    method: 'POST',
    body: JSON.stringify({ approve: true, subject }),
  }, NEWSLETTER);
