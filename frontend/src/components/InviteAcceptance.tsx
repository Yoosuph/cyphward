import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';
import { acceptInvite } from '../lib/api';

/**
 * Consumes an ?invite=<token> query param (the emailed team-invitation link).
 *
 * Mounted once above the router so it runs on every host/path the invite can
 * land on (login, onboarding, overview). Membership is granted server-side by
 * POST /members/invites/accept, which requires a signed-in account whose
 * verified email matches the invitation — so this component waits for `user`
 * and re-attempts whenever the verification state changes (unverified → 403
 * “verify first” → OTP verified → retry succeeds).
 *
 * The param is dropped only for terminal outcomes (invalid/used/expired/
 * mismatched). Network errors, 5xx and 429 are retried a few times while
 * mounted — a temporary outage must never eat an invitation. On success the
 * workspace list refreshes and the newly joined organization is selected.
 */
const TERMINAL_STATUSES = new Set([400, 404, 409, 410, 422]);
const MAX_ATTEMPTS = 4;
const RETRY_MS = 2500;

export default function InviteAcceptance() {
  const location = useLocation();
  const nav = useNavigate();
  const toast = useToast();
  const { user, refreshAfterInviteAccept } = useAuth();
  const attemptedKeyRef = useRef<string | null>(null);

  const token = new URLSearchParams(location.search).get('invite');

  const dropInviteParam = () => {
    const qs = new URLSearchParams(location.search);
    qs.delete('invite');
    nav({ search: qs.toString() ? `?${qs.toString()}` : '' }, { replace: true });
  };

  useEffect(() => {
    if (!token || !user) return;
    // One attempt cycle per (token, account, verification state) — the key
    // changes after OTP verification so the retry fires without a reload.
    const key = `${token}:${user.id}:${user.email_verified_at || 'unverified'}`;
    if (attemptedKeyRef.current === key) return;
    attemptedKeyRef.current = key;

    let cancelled = false;
    (async () => {
      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        try {
          const res = await acceptInvite(token);
          if (cancelled) return;
          const orgId = res?.organization?.id;
          if (orgId) {
            await refreshAfterInviteAccept(orgId).catch(() => {});
          }
          dropInviteParam();
          toast(res?.message || 'Invitation accepted — welcome to the team.');
          return;
        } catch (err) {
          if (cancelled) return;
          const status = (err as { status?: number })?.status;
          const msg = err instanceof Error ? err.message : 'This invitation link is not valid.';
          if (status === 403) {
            // Keep the param: after OTP verification the new attempt key fires.
            toast('Verify your email address to join this workspace.');
            return;
          }
          if (status !== undefined && TERMINAL_STATUSES.has(status)) {
            // Invalid / expired / mismatched / already used — the link is dead.
            dropInviteParam();
            toast(msg);
            return;
          }
          if (attempt < MAX_ATTEMPTS) {
            await new Promise(r => setTimeout(r, RETRY_MS));
            continue;
          }
          // Out of retries: keep the param so the next navigation re-attempts.
          toast('Server trouble accepting the invitation — it is kept and will retry.');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user]);

  return null;
}
