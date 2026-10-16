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

async function ownerFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/v1/owner${path}`, {
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

export type OwnerMe = { email: string; expires_at: string; idle_minutes: number };

export const ownerMe = () => ownerFetch<OwnerMe>('/me');

export const ownerSignIn = (email: string, password: string, code: string) =>
  ownerFetch<{ ok: true; email: string; expires_at: string; idle_minutes: number }>('/session', {
    method: 'POST',
    body: JSON.stringify({ email, password, code }),
  });

export const ownerSignOut = () => ownerFetch<{ signed_out: boolean }>('/logout', { method: 'POST' });
