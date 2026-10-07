// "Continue with Google" in a popup instead of a full-page redirect.
//
// Opens /api/v1/auth/google?mode=popup; Google runs inside the popup, our
// backend answers with a postMessage page (otc / mfa_token / error), the
// popup closes itself, and the opener continues without ever leaving.
// Falls back to the classic full-page redirect when popups are blocked.
export interface GooglePopupResult {
  otc?: string;
  mfa_token?: string;
  email_hint?: string;
  error?: string;
}

const POPUP_TIMEOUT_MS = 180000;

export function signInWithGooglePopup(): Promise<GooglePopupResult> {
  return new Promise(resolve => {
    let settled = false;
    let closedWatch: number | undefined;
    const done = (result: GooglePopupResult) => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      clearTimeout(timer);
      if (closedWatch !== undefined) clearInterval(closedWatch);
      resolve(result);
    };

    const onMessage = (event: MessageEvent) => {
      // Same-origin only: the popup serves our own backend callback page.
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.type !== 'cyphward-google-auth') return;
      if (data.otc || data.mfa_token) {
        done({ otc: data.otc, mfa_token: data.mfa_token, email_hint: data.email_hint });
      } else {
        done({ error: data.error || 'oauth_failed' });
      }
    };
    window.addEventListener('message', onMessage);

    const timer = window.setTimeout(() => {
      try {
        popup?.close();
      } catch {
        /* ignore */
      }
      done({ error: 'timeout' });
    }, POPUP_TIMEOUT_MS);

    const popup = window.open(
      '/api/v1/auth/google?mode=popup',
      'cyphward-google-signin',
      'width=520,height=640,menubar=no,toolbar=no',
    );
    if (!popup) {
      // Blocked — caller falls back to the full-page redirect.
      done({ error: 'popup_blocked' });
      return;
    }

    closedWatch = window.setInterval(() => {
      if (popup.closed) {
        clearInterval(closedWatch);
        done({ error: 'closed' });
      }
    }, 500);
  });
}
