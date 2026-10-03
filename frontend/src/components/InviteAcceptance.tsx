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
 */
export default function InviteAcceptance() {
  const location = useLocation();
  const nav = useNavigate();
  const toast = useToast();
  const { user } = useAuth();
  const attemptedKeyRef = useRef<string | null>(null);

  const token = new URLSearchParams(location.search).get('invite');

  const dropInviteParam = () => {
    const qs = new URLSearchParams(location.search);
    qs.delete('invite');
    nav({ search: qs.toString() ? `?${qs.toString()}` : '' }, { replace: true });
  };

  useEffect(() => {
    if (!token || !user) return;
    // One attempt per (token, account, verification state) — the key changes
    // after OTP verification so the retry fires without a page reload.
    const key = `${token}:${user.id}:${user.email_verified_at || 'unverified'}`;
    if (attemptedKeyRef.current === key) return;
    attemptedKeyRef.current = key;

    (async () => {
      try {
        const res = await acceptInvite(token);
        dropInviteParam();
        toast(res?.message || 'Invitation accepted — welcome to the team.');
      } catch (err) {
        const status = (err as { status?: number })?.status;
        const msg = err instanceof Error ? err.message : 'This invitation link is not valid.';
        if (status === 403) {
          // Keep the param: after OTP verification the new attempt key fires.
          toast('Verify your email address to join this workspace.');
          return;
        }
        // Invalid / expired / mismatched / already used — the link is dead.
        dropInviteParam();
        toast(msg);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user]);

  return null;
}
