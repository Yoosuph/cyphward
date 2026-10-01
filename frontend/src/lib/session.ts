/**
 * Cyphward session store — our own auth (no Supabase Auth).
 *
 * The backend issues {access_token, refresh_token}; we persist them in
 * localStorage and attach the access token to every API call. The token
 * rotates proactively before expiry and reactively on 401 (single retry).
 */

export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  email_verified_at?: string | null;
  provider?: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in?: number;
  user: SessionUser;
  /** client-side: epoch ms when the access token stops being valid */
  _expires_at?: number;
}

const SESSION_KEY = 'cyphward-session';
const API_BASE = '/api/v1';
const EXPIRY_SLACK_MS = 30_000;

export function loadSession(): AuthTokens | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthTokens;
    if (!parsed?.access_token || !parsed?.refresh_token || !parsed?.user?.id) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveSession(tokens: AuthTokens): void {
  try {
    const enriched: AuthTokens = {
      ...tokens,
      _expires_at: tokens.expires_in ? Date.now() + tokens.expires_in * 1000 : undefined,
    };
    localStorage.setItem(SESSION_KEY, JSON.stringify(enriched));
    clearLegacySupabaseKeys();
  } catch {
    /* storage unavailable — session stays in memory only */
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
    clearLegacySupabaseKeys();
  } catch {
    /* ignore */
  }
}

/** Drop pre-migration `sb-*-auth-token` keys so GoTrue state can't linger. */
function clearLegacySupabaseKeys(): void {
  try {
    const doomed: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('sb-') && key.endsWith('-auth-token')) doomed.push(key);
    }
    doomed.forEach((k) => localStorage.removeItem(k));
  } catch {
    /* ignore */
  }
}

export function getAccessTokenSync(): string | null {
  return loadSession()?.access_token ?? null;
}

/** Rotate the refresh token into a fresh pair. Null on any failure. */
export async function refreshSession(): Promise<AuthTokens | null> {
  const stored = loadSession();
  if (!stored) return null;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: stored.refresh_token }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as AuthTokens;
    if (!data?.access_token) return null;
    saveSession(data);
    return data;
  } catch {
    return null;
  }
}

/**
 * Return a valid access token, rotating first when close to expiry.
 * Returns null when there is no session at all.
 */
export async function ensureFreshAccessToken(): Promise<string | null> {
  const stored = loadSession();
  if (!stored) return null;
  if (stored._expires_at && Date.now() >= stored._expires_at - EXPIRY_SLACK_MS) {
    const rotated = await refreshSession();
    return rotated?.access_token ?? null;
  }
  return stored.access_token;
}
