/**
 * Cyphward session store — our own auth (no Supabase Auth).
 *
 * The backend issues {access_token, refresh_token}; we persist them in
 * localStorage and attach the access token to every API call. The token
 * rotates proactively before expiry and reactively on 401 (single retry).
 */

export interface SessionUser {
  demo_session?: boolean;
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

/**
 * Sessions live on the app/auth origins. A leftover copy on the marketing
 * host (written before the subdomain split) drives an endless bounce:
 * / → HomeRoute sees the tenant → /overview → app host (no session there)
 * → auth login → logo → / … Clearing cookies with a short time range can
 * miss it, so drop it the moment we see it.
 */
function isMarketingHost(): boolean {
  const h = window.location.hostname;
  return h === 'cyphward.com' || h === 'www.cyphward.com';
}

export function loadSession(): AuthTokens | null {
  try {
    if (isMarketingHost()) {
      localStorage.removeItem(SESSION_KEY);
      return null;
    }
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
    const previous = loadSession();
    if (previous?.user.id !== tokens.user.id) {
      // Workspace and onboarding caches belong to the previous account.
      for (const key of ['cyphward-tenant', 'cyphward-org-id', 'cyphward-onboarding', 'cyphward-greeted']) {
        localStorage.removeItem(key);
        sessionStorage.removeItem(key);
      }
    }
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

/**
 * Cross-origin session handoff (auth.cyphward.com → app.cyphward.com).
 *
 * localStorage is per-origin, so after a login on the auth host the HostGate
 * hands the session to the app host inside the URL fragment (fragments are
 * never sent to servers or leaked via Referer). The receiving boot calls this
 * once — storing the session and stripping the fragment from history — and the
 * sending host clears its copy, so a snapshot can never be re-used after the
 * app host has rotated the tokens (that would cause a redirect loop).
 */
export function consumeHandoff(): void {
  try {
    const match = window.location.hash.match(/session=([^&]+)/);
    if (!match) return;
    try {
      const parsed = JSON.parse(decodeURIComponent(match[1])) as AuthTokens;
      if (parsed?.access_token && parsed?.refresh_token && parsed?.user?.id) {
        saveSession(parsed);
      }
    } catch {
      /* malformed handoff — drop it */
    }
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  } catch {
    /* ignore */
  }
}

/** Build the app-host handoff URL for a target path, consuming the local copy. */
export function buildAppHandoff(target: string): string | null {
  const stored = loadSession();
  if (!stored) return null;
  const url = new URL(target);
  url.hash = `session=${encodeURIComponent(JSON.stringify(stored))}`;
  clearSession();
  return url.toString();
}

export function getAccessTokenSync(): string | null {
  return loadSession()?.access_token ?? null;
}

let refreshInFlight: { token: string; promise: Promise<AuthTokens> } | null = null;

/** Rotate tokens; share one request so concurrent callers cannot consume the same token twice. */
export async function refreshSession(throwOnError = false): Promise<AuthTokens | null> {
  const stored = loadSession();
  if (!stored) return null;
  if (!refreshInFlight || refreshInFlight.token !== stored.refresh_token) {
    refreshInFlight = {
      token: stored.refresh_token,
      promise: (async () => {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: stored.refresh_token }),
        });
        if (!res.ok) throw Object.assign(new Error('Could not refresh your session.'), { status: res.status });
        const data = (await res.json()) as AuthTokens;
        if (!data?.access_token || !data.refresh_token || !data.user?.id) {
          throw Object.assign(new Error('Invalid session refresh response.'), { status: 502 });
        }
        // A late response from before sign-out/account switching cannot restore
        // that old account over the current session.
        const current = loadSession();
        if (current?.refresh_token !== stored.refresh_token || current.user.id !== stored.user.id) {
          throw Object.assign(new Error('The account session changed during refresh.'), { status: 409 });
        }
        saveSession(data);
        return data;
      })(),
    };
  }
  const request = refreshInFlight;
  try {
    return await request.promise;
  } catch (error) {
    if (throwOnError) throw error;
    return null;
  } finally {
    if (refreshInFlight === request) refreshInFlight = null;
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
    const rotated = await refreshSession(true);
    return rotated?.access_token ?? null;
  }
  return stored.access_token;
}

const MFA_CHALLENGE_KEY = 'cyphward-mfa-challenge';

export interface StashedMfaChallenge {
  token: string;
  hint: string;
}

/** Park a step-up challenge (e.g. from One Tap on the signup page) for the Login MFA screen. */
export function stashMfaChallenge(token: string, hint: string): void {
  try {
    sessionStorage.setItem(MFA_CHALLENGE_KEY, JSON.stringify({ token, hint }));
  } catch {
    /* storage unavailable */
  }
}

/** Take (and clear) a parked step-up challenge, if any. */
export function takeMfaChallenge(): StashedMfaChallenge | null {
  try {
    const raw = sessionStorage.getItem(MFA_CHALLENGE_KEY);
    sessionStorage.removeItem(MFA_CHALLENGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StashedMfaChallenge;
    return parsed?.token ? parsed : null;
  } catch {
    return null;
  }
}
