import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertCircle } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { exchangeOtp } from '../lib/api';
import StrataField from '../components/StrataField';

/**
 * Landing point after the Google OAuth redirect. The backend hands us a
 * single-use code (?otc=…) — we exchange it for a real session here.
 */
export default function AuthCallback() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { completeExternalLogin } = useAuth();
  const [error, setError] = useState('');
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const otc = (params.get('otc') || '').trim();
    if (!otc) {
      setError('Sign-in link is missing its code. Please try again.');
      return;
    }

    (async () => {
      try {
        const tokens = await exchangeOtp(otc);
        const step = await completeExternalLogin(tokens);
        if (step && step !== 'complete' && step !== 'none') {
          nav('/onboarding', { replace: true });
        } else if (step === 'none') {
          setError('Your session could not be restored. Please sign in again.');
        } else {
          nav('/', { replace: true });
        }
      } catch (e: any) {
        setError(e?.message || 'Sign-in failed. Please try again.');
      }
    })();
  }, [params, completeExternalLogin, nav]);

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
