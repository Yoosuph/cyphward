import { FormEvent, useState, useEffect, useRef } from 'react';
import AuthSidePanel from '../components/AuthSidePanel';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, KeyRound, Lock, Eye, EyeOff, Sun, Moon, Globe, AlertCircle } from 'lucide-react';
import { useAuth, IDLE_REASON_KEY } from '../lib/auth';
import { startGoogleOneTap } from '../lib/googleOneTap';
import { signInWithGooglePopup } from '../lib/googlePopup';
import { demoLoginStatus, exchangeOtp, mfaStart } from '../lib/api';
import type { MfaChallenge } from '../lib/api';
import { takeMfaChallenge } from '../lib/session';
import type { AuthTokens } from '../lib/session';
import { getTheme, toggleTheme } from '../lib/theme';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import CyphwardLogo from '../components/CyphwardLogo';

export default function Login() {
  const { tenant, signInWithCredentials, signInAsDemo, completeMfaSignIn, resendMfaCode, completeExternalLogin, onboardingStep } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [error, setError] = useState('');
  const [demoEnabled, setDemoEnabled] = useState(false);
  const [theme, setTheme] = useState(getTheme());
  // Admin step-up: password accepted, 6-digit email code pending.
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaHint, setMfaHint] = useState('');
  const [mfaDigits, setMfaDigits] = useState<string[]>(['', '', '', '', '', '']);
  const [mfaBusy, setMfaBusy] = useState(false);
  const [resendNote, setResendNote] = useState('');
  const [rememberBrowser, setRememberBrowser] = useState(true);
  const digitRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    const onThemeChange = () => setTheme(getTheme());
    window.addEventListener('cyphward:theme', onThemeChange);
    return () => window.removeEventListener('cyphward:theme', onThemeChange);
  }, []);

  // Errors bounced back from the backend OAuth flow (/login?error=…).
  const [searchParams] = useSearchParams();
  // Team-invitation links arrive as ?invite= — carry it through every
  // in-app navigation so InviteAcceptance can consume it after sign-in.
  const inviteParam = (() => {
    const t = searchParams.get('invite');
    return t ? `?invite=${encodeURIComponent(t)}` : '';
  })();
  useEffect(() => {
    const code = searchParams.get('error');
    if (!code) return;
    const messages: Record<string, string> = {
      oauth_failed: 'Google sign-in failed. Please try again, or use your email and password.',
      google_not_configured:
        "Google sign-in isn't set up on this deployment yet. Use your email and password instead.",
    };
    setError(messages[code] || 'Sign-in failed. Please try again.');
    window.history.replaceState({}, '', '/login');
  }, [searchParams]);

  // Explain an idle logout: the auth layer set this flag right before
  // ending a session after 10 minutes with no activity. When the logout was
  // followed by a cross-origin hop to this host, the flag arrives as a query
  // param instead (localStorage doesn't cross origins).
  useEffect(() => {
    try {
      const fromQuery = searchParams.get('notice') === 'idle';
      if (fromQuery || localStorage.getItem(IDLE_REASON_KEY) === '1') {
        localStorage.removeItem(IDLE_REASON_KEY);
        toast('Signed out after 10 minutes of inactivity');
        if (fromQuery) window.history.replaceState({}, '', '/login');
      }
    } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After a Google sign-in that needs the step-up, ask the server (on this
  // origin, where the remembered-browser cookie lives) to either sign this
  // browser straight in or email the code; then show the code screen.
  const enterGoogleStepUp = async (token: string, hint: string) => {
    try {
      const started = await mfaStart(token);
      if ('access_token' in started) {
        const step = await completeExternalLogin(started as AuthTokens);
        if (step && step !== 'complete' && step !== 'none') {
          nav(`/onboarding${inviteParam}`, { replace: true });
        } else if (step === 'none') {
          setError('Your session could not be restored. Please sign in again.');
        } else {
          nav(`/overview${inviteParam}`, { replace: true });
        }
        return;
      }
      setMfaHint(started.email_hint || hint);
      toast('Extra check — enter the code we emailed you.');
    } catch (e) {
      setMfaHint(hint);
      setError((e as Error).message || 'Could not send the sign-in code. Use RESEND CODE to try again.');
    }
    setMfaToken(token);
    setMfaDigits(['', '', '', '', '', '']);
    setResendNote('');
  };

  // A parked step-up challenge (Google on another page) continues here.
  useEffect(() => {
    const stashed = takeMfaChallenge();
    if (stashed) void enterGoogleStepUp(stashed.token, stashed.hint);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Google One Tap — the small side prompt, verified by our own backend.
  useEffect(() => {
    if (tenant) return;
    let cancelled = false;
    let stop: (() => void) | null = null;
    startGoogleOneTap({
      onSuccess: async tokens => {
        try {
          if ((tokens as MfaChallenge).mfa_required) {
            if (cancelled) return;
            const c = tokens as MfaChallenge;
            await enterGoogleStepUp(c.mfa_token, c.email_hint || '');
            return;
          }
          const step = await completeExternalLogin(tokens as AuthTokens);
          if (step && step !== 'complete' && step !== 'none') {
            nav(`/onboarding${inviteParam}`, { replace: true });
          } else if (step === 'none') {
            setError('Your session could not be restored. Please sign in again.');
          } else {
            nav(`/overview${inviteParam}`, { replace: true });
          }
        } catch {
          setError('Google sign-in failed. Please try again.');
        }
      },
      onError: msg => {
        if (!cancelled) setError(msg);
      },
    }).then(cleanup => {
      if (cancelled) cleanup?.();
      else stop = cleanup;
    });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [tenant]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    demoLoginStatus().then((status) => setDemoEnabled(status.enabled)).catch(() => setDemoEnabled(false));
  }, []);

  if (tenant) {
    if (onboardingStep !== 'none' && onboardingStep !== 'complete') {
      return <Navigate to={`/onboarding${inviteParam}`} replace />;
    }
    return <Navigate to={`/overview${inviteParam}`} replace />;
  }

  const tryDemo = async () => {
    if (busy) return;
    setBusy(true);
    setDemoBusy(true);
    setError('');
    const result = await signInAsDemo();
    if (!result.ok) {
      setBusy(false);
      setDemoBusy(false);
      setError(result.error || 'The demo is not available right now.');
      return;
    }
    finishLogin(result.name || 'Sample Owner', result.onboarding);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');

    const result = await signInWithCredentials(email, pw);

    if (!result.ok) {
      setBusy(false);
      setError(result.error || 'Wrong email or password. Please try again.');
      return;
    }

    if (result.mfa_required) {
      setBusy(false);
      setMfaToken(result.mfa_token || null);
      setMfaHint(result.email_hint || '');
      setMfaDigits(['', '', '', '', '', '']);
      setResendNote('');
      return;
    }

    finishLogin(result.name || email.split('@')[0] || '', result.onboarding);
  };

  const finishLogin = (name: string, onboarding: string | undefined) => {
    const first = (name || '').split(' ')[0];
    toast(`Welcome back${first ? `, ${first}` : ''}!`);

    // Navigate from the server-resolved onboarding step (no stale state).
    if (onboarding && onboarding !== 'complete' && onboarding !== 'none') {
      nav(`/onboarding${inviteParam}`, { replace: true });
    } else {
      nav(`/overview${inviteParam}`, { replace: true });
    }
  };

  const clearMfa = () => {
    setMfaToken(null);
    setMfaDigits(['', '', '', '', '', '']);
    setError('');
  };

  const submitMfaCode = async (code: string) => {
    if (mfaBusy || !mfaToken || code.length !== 6) return;
    setMfaBusy(true);
    setError('');

    const result = await completeMfaSignIn(mfaToken, code, rememberBrowser);
    setMfaBusy(false);
    if (!result.ok) {
      setError(result.error || 'Invalid code. Please try again.');
      setMfaDigits(['', '', '', '', '', '']);
      digitRefs.current[0]?.focus();
      return;
    }
    setMfaToken(null);
    finishLogin(result.name || '', result.onboarding);
  };

  const submitMfa = async (e: FormEvent) => {
    e.preventDefault();
    await submitMfaCode(mfaDigits.join(''));
  };

  const handleDigit = (i: number, raw: string) => {
    const d = raw.replace(/\D/g, '').slice(-1);
    setMfaDigits(prev => {
      const next = [...prev];
      next[i] = d;
      if (d && i < 5) {
        requestAnimationFrame(() => digitRefs.current[i + 1]?.focus());
      }
      if (d && next.every(x => x !== '')) {
        // Auto-send the moment the sixth box fills.
        requestAnimationFrame(() => submitMfaCode(next.join('')));
      }
      return next;
    });
  };

  const handleDigitKey = (i: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !mfaDigits[i] && i > 0) {
      const prev = [...mfaDigits];
      prev[i - 1] = '';
      setMfaDigits(prev);
      digitRefs.current[i - 1]?.focus();
    }
  };

  const handleDigitPaste = (e: React.ClipboardEvent) => {
    const text = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
    if (!text) return;
    e.preventDefault();
    const next = Array.from({ length: 6 }, (_, i) => text[i] || '');
    setMfaDigits(next);
    if (text.length === 6) {
      requestAnimationFrame(() => submitMfaCode(text));
    } else {
      requestAnimationFrame(() => digitRefs.current[text.length]?.focus());
    }
  };

  const resendCode = async () => {
    if (!mfaToken) return;
    setResendNote('');
    const result = await resendMfaCode(mfaToken);
    setResendNote(result.ok ? 'A fresh code is on its way.' : (result.error || 'Could not resend the code.'));
  };

  const signInWithGoogle = async () => {
    // Popup first (stays on this page); full-page redirect if blocked.
    try {
      const result = await signInWithGooglePopup();
      if (result.error === 'popup_blocked') {
        window.location.href = '/api/v1/auth/google';
        return;
      }
      if (result.error) {
        if (result.error !== 'closed') {
          setError('Google sign-in failed. Please try again, or use your email and password.');
        }
        return;
      }
      if (result.mfa_token) {
        await enterGoogleStepUp(result.mfa_token, result.email_hint || '');
        return;
      }
      if (result.otc) {
        try {
          const tokens = await exchangeOtp(result.otc);
          const step = await completeExternalLogin(tokens);
          if (step && step !== 'complete' && step !== 'none') {
            nav(`/onboarding${inviteParam}`, { replace: true });
          } else if (step === 'none') {
            setError('Your session could not be restored. Please sign in again.');
          } else {
            nav(`/overview${inviteParam}`, { replace: true });
          }
        } catch {
          setError('Google sign-in failed. Please try again.');
        }
        return;
      }
      setError('Google sign-in failed. Please try again.');
    } catch {
      setError('Google sign-in failed. Please try again.');
    }
  };

  return (
    <div className="login-wrap">
      {/* Precision ambient strata dot instrument */}
      <StrataField variant="auth" />

      <div className="relative z-10 w-full max-w-6xl mx-auto my-auto py-6">
        {/* Top Utility Bar */}
        <div className="flex items-center justify-between pb-6 mb-6 border-b border-line">
          <div className="flex items-center gap-3">
            <Link to="/" className="topbar-brand flex items-center text-ink hover:opacity-85 transition-opacity" aria-label="Cyphward home">
              <CyphwardLogo variant="compact" size={20} />
            </Link>
            <span className="text-line select-none" aria-hidden="true">/</span>
            <div className="eyebrow flex items-center gap-1.5 text-[10px] hidden sm:flex">
              <span className="live-dot" /> CYPHWARD · SECURE WORKSPACE
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              className="icon-btn hover-lift"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            </button>

            <Link
              to="/"
              className="stat-link tap-row text-xs flex items-center gap-1.5 py-1 px-2.5 rounded border border-line hover:border-ink transition-all"
            >
              <Globe size={13} className="text-accent" />
              <span>VIEW WEBSITE ↗</span>
            </Link>
          </div>
        </div>

        {/* Main Split Grid on Desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-14 items-center">
          {/* Left Column: what happens next / what we check (true statements only) */}
          <div className="lg:col-span-7 order-2 lg:order-1">
            <AuthSidePanel mode="login" />
          </div>

          {/* Right Column: Authentication Terminal */}
          <div className="lg:col-span-5 order-1 lg:order-2">
            <div className="login-terminal-card">
              <div className="auth-tabs">
                <button type="button" className="auth-tab active">
                  <KeyRound size={13} className="inline mr-1.5" /> SIGN IN
                </button>
              </div>

              {mfaToken ? (
              <form onSubmit={submitMfa} key="mfa" className="content-fade-in">
                  {/* Admin step-up: 6-digit code emailed after password check */}
                  <div className="p-3 mb-4 bg-accent/10 border border-accent/30 rounded text-xs mono text-ink">
                    Extra check for workspace admins — enter the 6-digit code we sent
                    {mfaHint ? ` to ${mfaHint}` : ''}.
                  </div>
                  <div className="field">
                    <label>SIGN-IN CODE</label>
                    <div className="flex items-center justify-between gap-2" onPaste={handleDigitPaste}>
                      {[0, 1, 2, 3, 4, 5].map(i => (
                        <input
                          key={i}
                          ref={el => { digitRefs.current[i] = el; }}
                          type="text"
                          inputMode="numeric"
                          autoFocus={i === 0}
                          autoComplete={i === 0 ? 'one-time-code' : 'off'}
                          aria-label={`Digit ${i + 1}`}
                          value={mfaDigits[i]}
                          onChange={e => handleDigit(i, e.target.value)}
                          onKeyDown={e => handleDigitKey(i, e)}
                          disabled={mfaBusy}
                          className="w-11 h-12 text-center text-lg mono font-semibold bg-inset border border-line rounded text-ink focus:outline-none focus:border-accent transition-colors disabled:opacity-50"
                        />
                      ))}
                    </div>
                  </div>

                  <label className="flex items-center gap-2 mb-4 text-xs mono text-soft cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={rememberBrowser}
                      onChange={e => setRememberBrowser(e.target.checked)}
                      className="accent-[var(--accent)] w-4 h-4"
                    />
                    Remember this browser for 30 days
                  </label>

                  {error && (
                    <div className="p-3 mb-4 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
                      <AlertCircle size={14} className="flex-none mt-0.5" />
                      <span>{error}</span>
                    </div>
                  )}

                  <div className="mt-4 pt-3.5 border-t border-line text-center">
                    {mfaBusy && <p className="text-xs mono text-soft mb-2">VERIFYING…</p>}
                    {resendNote && <p className="text-xs mono text-soft mb-2">{resendNote}</p>}
                    <button type="button" onClick={resendCode} className="text-xs mono text-soft hover:text-accent transition-colors">
                      RESEND CODE
                    </button>
                    <span className="text-xs mono text-soft mx-2">·</span>
                    <button type="button" onClick={() => { clearMfa(); }} className="text-xs mono text-soft hover:text-accent transition-colors">
                      BACK
                    </button>
                  </div>
              </form>
              ) : (
              <form onSubmit={submit} key="login" className="content-fade-in">
                  {/* Email Field */}
                  <div className="field">
                    <label htmlFor="email">WORK EMAIL</label>
                    <input
                      id="email"
                      type="email"
                      placeholder="ciso@acmetraders.ng"
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                      autoComplete="username"
                      required
                    />
                  </div>

                  {/* Password Field with Eye Toggle */}
                  <div className="field">
                    <div className="flex items-center justify-between mb-2">
                      <label htmlFor="pw" className="mb-0">PASSWORD</label>
                      <Link to="/forgot-password" className="tap-inline text-[10px] mono text-soft hover:text-accent transition-colors">
                        FORGOT PASSWORD?
                      </Link>
                    </div>

                    <div className="pw-input-wrap">
                      <input
                        id="pw"
                        type={showPw ? 'text' : 'password'}
                        placeholder="••••••••••••••"
                        value={pw}
                        onChange={e => setPw(e.target.value)}
                        autoComplete="current-password"
                        required
                      />
                      <button
                        type="button"
                        className="pw-toggle-btn"
                        onClick={() => setShowPw(!showPw)}
                        title={showPw ? 'Hide password' : 'Show password'}
                        aria-label={showPw ? 'Hide password' : 'Show password'}
                      >
                        {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </div>

                  {/* Error Display */}
                  {error && (
                    <div className="p-3 mb-4 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
                      <AlertCircle size={14} className="flex-none mt-0.5" />
                      <span>{error}</span>
                    </div>
                  )}

                  {/* Submit Button */}
                  <button className="btn btn-solid w-full justify-center mt-5" type="submit" disabled={busy}>
                    {busy ? (
                      <>SIGNING YOU IN…</>
                    ) : (
                      <>
                        SIGN IN <ArrowRight size={14} className="ml-1" />
                      </>
                    )}
                  </button>

                  {/* Alternative: sign in with Google via our own OAuth flow */}
                  <div className="flex items-center gap-3 my-4">
                    <span className="h-px flex-1 bg-line" />
                    <span className="text-[9.5px] mono text-soft tracking-widest">OR</span>
                    <span className="h-px flex-1 bg-line" />
                  </div>
                  <button
                    type="button"
                    className="btn btn-ghost w-full justify-center"
                    onClick={signInWithGoogle}
                    disabled={busy}
                  >
                    <svg width="14" height="14" viewBox="0 0 48 48" aria-hidden="true" className="mr-2">
                      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.2 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.2-.1-2.4-.4-3.5z"/>
                      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.2 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
                      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.3 0-9.7-3.4-11.3-8.1l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
                      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C36.9 39.7 44 34.5 44 24c0-1.2-.1-2.4-.4-3.5z"/>
                    </svg>
                    CONTINUE WITH GOOGLE
                  </button>

                  {/* Dedicated Registration Link */}
                  <div className="mt-4 pt-3.5 border-t border-line text-center">
                    <span className="text-xs mono text-soft">
                      Don't have an account?{' '}
                        <Link to={`/signup${inviteParam}`} className="tap-inline text-accent underline font-medium ml-1">
                        Create Account
                      </Link>
                    </span>
                  </div>
              {demoEnabled && (
                <div className="mt-4 text-center">
                  <button
                    type="button"
                    onClick={tryDemo}
                    disabled={busy}
                    aria-busy={demoBusy}
                    className="w-full h-11 border border-line rounded-md text-sm font-medium text-ink hover:bg-surface disabled:opacity-60"
                  >
                    {demoBusy ? (
                      <span className="inline-flex items-center gap-1 animate-pulse">
                        Signing you into the demo
                        <span aria-hidden="true">...</span>
                      </span>
                    ) : (
                      'Try the demo'
                    )}
                  </button>
                  <p className="text-xs mono text-soft mt-2">
                    Explore the shared demo workspace. No password or verification code needed.
                  </p>
                </div>
              )}
              </form>
              )}

              {/* Hardware attestation footer */}
              <div className="mt-5 pt-3 border-t border-line/60 flex items-center justify-between text-[9.5px] mono text-soft">
                <span className="flex items-center gap-1.5">
                  <Lock size={11} className="text-accent" /> PROTECTED CONNECTION
                </span>
                <span>DATA ENCRYPTED</span>
              </div>
            </div>
          </div>
        </div>

        {/* Global Metadata Footer */}
        <div className="mt-10 pt-6 border-t border-line">
          <dl className="meta-row">
            <div><dt>WORKSPACES</dt><dd>ONE PRIVATE WORKSPACE PER COMPANY</dd></div>
            <div><dt>SCANS</dt><dd>ONLY DOMAINS YOU VERIFY</dd></div>
          </dl>
        </div>
      </div>
    </div>
  );
}
