// Google One Tap — the small side prompt from Google Identity Services.
// We verify the ID token on OUR backend (/auth/google/one-tap), so no
// Supabase and no client-secret ever touch the browser.
import { getGoogleClientId, oneTapLogin } from './api';
import type { AuthTokens } from './session';

let scriptPromise: Promise<void> | null = null;

function loadGisScript(): Promise<void> {
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const g = (window as unknown as { google?: { accounts?: { id?: unknown } } }).google;
    if (g?.accounts?.id) {
      resolve();
      return;
    }
    const s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => {
      scriptPromise = null;
      reject(new Error('Google sign-in failed to load.'));
    };
    document.head.appendChild(s);
  });
  return scriptPromise;
}

export interface OneTapOptions {
  /** Called once the backend accepts the verified Google credential. */
  onSuccess: (tokens: AuthTokens) => void;
  /** Called when the backend rejects the credential (silent — no alert). */
  onError?: (message: string) => void;
}

type GisWindow = {
  google?: {
    accounts?: {
      id?: {
        initialize: (opts: Record<string, unknown>) => void;
        prompt: (cb?: (notif: Record<string, unknown>) => void) => void;
        disableAutoSelect?: () => void;
      };
    };
  };
};

/**
 * Show the One Tap side prompt when Google decides to (it may stay hidden
 * after a dismissal or an unverified session). Resolves to a cleanup
 * function, or null when Google sign-in isn't configured / unavailable —
 * the explicit "CONTINUE WITH GOOGLE" button remains the reliable path.
 */
export async function startGoogleOneTap(
  options: OneTapOptions,
): Promise<(() => void) | null> {
  try {
    const { client_id } = await getGoogleClientId();
    if (!client_id) return null;
    await loadGisScript();
    const gis = (window as unknown as GisWindow).google?.accounts?.id;
    if (!gis) return null;

    gis.initialize({
      client_id,
      callback: async (resp: { credential?: string }) => {
        if (!resp.credential) return;
        try {
          const tokens = await oneTapLogin(resp.credential);
          options.onSuccess(tokens);
        } catch (err) {
          options.onError?.(
            (err as Error).message || 'Google sign-in failed. Please try again.',
          );
        }
      },
    });
    gis.prompt();
    return () => {
      try {
        gis.disableAutoSelect?.();
      } catch {
        /* ignore — Google owns this state */
      }
    };
  } catch {
    return null;
  }
}
