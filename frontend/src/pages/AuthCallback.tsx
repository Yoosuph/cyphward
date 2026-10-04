import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertCircle } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { exchangeOtp, mfaVerify } from '../lib/api';
import StrataField from '../components/StrataField';

/**
 * Landing point after the Google OAuth redirect. The backend hands us either
 * a single-use code (?otc=…) for an immediate session, or a step-up challenge
 * (?mfa=…) when the account must confirm a sign-in code first.
 */
export default function AuthCallback() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { completeExternalLogin } = useAuth();
  const [error, setError] = useState('');
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  const finishWithTokens = async (tokens: Parameters<typeof completeExternalLogin>[0]) => {
    const step = await completeExternalLogin(tokens);
    if (step && step !== 'complete' && step !== 'none') {
      nav('/onboarding', { replace: true });
    } else if (step === 'none') {
      setError('Your session could not be restored. Please sign in again.');
    } else {
      nav('/overview', { replace: true });
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const mfa = (params.get('mfa') || '').trim();
    if (mfa) {
      setMfaToken(mfa);
      window.history.replaceState({}, '', '/auth/callback');
      return;
    }

    const otc = (params.get('otc') || '').trim();
    if (!otc) {
      setError('Sign-in link is missing its code. Please try again.');
      return;
    }

    (async () => {
      try {
        await finishWithTokens(await exchangeOtp(otc));
      } catch (e: any) {
        setError(e?.message || 'Sign-in failed. Please try again.');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, completeExternalLogin, nav]);

  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !mfaToken) return;
    setBusy(true);
    setError('');
    try {
      await finishWithTokens(await mfaVerify(mfaToken, code.trim()));
    } catch (e: any) {
      setError(e?.message || 'Invalid code. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-md mx-auto my-auto px-4 text-center">
        <div className="auth-card panel mt-6 py-10">
          {error ? (
            <>
              <div className="inline-block p-4 rounded-full bg-red-500/10 text-red-500 border border-red-500/30 mb-4">
                <AlertCircle size={36} />
              </div>
              <h3 className="font-display text-2xl font-medium mb-2">Sign-in failed</h3>
              <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">{error}</p>
              <button
                className="btn btn-solid w-full justify-center"
                onClick={() => nav('/login', { replace: true })}
              >
                BACK TO SIGN IN
              </button>
            </>
          ) : mfaToken ? (
            <>
              <h3 className="font-display text-2xl font-medium mb-2">Check your email</h3>
              <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
                This account confirms every sign-in with a 6-digit code.
              </p>
              <form onSubmit={submitCode} className="flex items-center justify-center gap-2">
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="123456"
                  value={code}
                  onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  autoComplete="one-time-code"
                  className="w-36 bg-inset border border-line rounded px-3 py-2 text-ink mono text-center focus:outline-none focus:border-accent"
                />
                <button
                  type="submit"
                  disabled={busy || code.length !== 6}
                  className="btn btn-solid justify-center disabled:opacity-50"
                >
                  {busy ? 'VERIFYING…' : 'VERIFY'}
                </button>
              </form>
            </>
          ) : (
            <>
              <div className="inline-block w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin mb-4" />
              <p className="mono text-[11px] text-soft tracking-widest">
                COMPLETING SIGN-IN…
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
