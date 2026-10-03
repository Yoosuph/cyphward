import { FormEvent, useState, useEffect } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowRight, ShieldCheck, KeyRound, Lock,
  Eye, EyeOff, Sun, Moon, Check, Globe, Server, CheckCircle2,
  Radio, ShieldAlert, AlertCircle
} from 'lucide-react';
import { useAuth, IDLE_REASON_KEY } from '../lib/auth';
import { startGoogleOneTap } from '../lib/googleOneTap';
import { getTheme, toggleTheme } from '../lib/theme';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import CyphwardLogo from '../components/CyphwardLogo';

export default function Login() {
  const { tenant, signInWithCredentials, completeExternalLogin, onboardingStep } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [remember, setRemember] = useState(true);
  const [theme, setTheme] = useState(getTheme());

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

  // Google One Tap — the small side prompt, verified by our own backend.
  useEffect(() => {
    if (tenant) return;
    let cancelled = false;
    let stop: (() => void) | null = null;
    startGoogleOneTap({
      onSuccess: async tokens => {
        try {
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

  if (tenant) {
    if (onboardingStep !== 'none' && onboardingStep !== 'complete') {
      return <Navigate to={`/onboarding${inviteParam}`} replace />;
    }
    return <Navigate to={`/overview${inviteParam}`} replace />;
  }

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

    const first = (result.name || email.split('@')[0] || '').split(' ')[0];
    toast(`Welcome back${first ? `, ${first}` : ''}!`);

    // Navigate from the server-resolved onboarding step (no stale state).
    if (result.onboarding && result.onboarding !== 'complete' && result.onboarding !== 'none') {
      nav(`/onboarding${inviteParam}`, { replace: true });
    } else {
      nav(`/overview${inviteParam}`, { replace: true });
    }
  };

  const signInWithGoogle = () => {
    // Full-page redirect to our own backend OAuth flow; the callback lands
    // on /auth/callback with a one-time code.
    window.location.href = '/api/v1/auth/google';
  };

  return (
    <div className="login-wrap">
      {/* Precision ambient strata dot instrument */}
      <StrataField variant="auth" />

      <div className="relative z-10 w-full max-w-6xl mx-auto my-auto py-6">
        {/* Top Utility Bar */}
        <div className="flex items-center justify-between pb-6 mb-6 border-b border-line">
          <div className="flex items-center gap-3">
            <Link to="/" className="flex items-center text-ink hover:opacity-85 transition-opacity">
              <CyphwardLogo variant="compact" size={20} />
            </Link>
            <span className="text-line select-none">/</span>
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
              className="stat-link text-xs flex items-center gap-1.5 py-1 px-2.5 rounded border border-line hover:border-ink transition-all"
            >
              <Globe size={13} className="text-accent" />
              <span>VIEW WEBSITE ↗</span>
            </Link>
          </div>
        </div>

        {/* Main Split Grid on Desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-14 items-center">
          {/* Left Column: Brand Manifesto & Live Enclave Showcase */}
          <div className="lg:col-span-7 flex flex-col gap-6 order-2 lg:order-1">
            <div>
              <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded border border-line bg-inset font-mono text-[10.5px] tracking-wider text-soft mb-3">
                <Radio size={12} className="text-accent animate-pulse" />
                <span>PRIMARY REGION: LAGOS // KANO // NAIROBI</span>
              </div>

              <h1 className="display-h">
                African cyber defense, <em>layer by layer.</em>
              </h1>

              <p className="login-sub">
                Track NDPA and CBN compliance, watch for USSD and SIM-swap fraud, and see the
                security of everything you run online in one clear dashboard.
              </p>
            </div>

            {/* Live Telemetry Showcase Box */}
            <div className="login-telemetry-panel">
              <div className="flex items-center justify-between pb-3 mb-4 border-b border-line">
                <div className="flex items-center gap-2">
                  <span className="live-dot" />
                  <span className="eyebrow text-[10px] tracking-widest">LIVE ACTIVITY</span>
                </div>
                <span className="mono text-[10px] text-soft">LATENCY: 24ms · HEALTH: 100%</span>
              </div>

              <div className="flex flex-col gap-2.5">
                <div className="login-feed-item">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Server size={14} className="text-accent flex-none" />
                    <div>
                      <span className="font-semibold text-ink">USSD payments</span>
                      <span className="text-soft ml-1.5 hidden sm:inline">(Kano region)</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <span className="text-soft text-[10px]">1,420 / min</span>
                    <span className="tag text-[9px] text-ok border-ok/30 bg-ok/10">NORMAL</span>
                  </div>
                </div>

                <div className="login-feed-item">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <ShieldAlert size={14} className="text-accent flex-none" />
                    <div>
                      <span className="font-semibold text-ink">SIM-swap attempts</span>
                      <span className="text-soft ml-1.5 hidden sm:inline">(Lagos network)</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <span className="text-soft text-[10px]">3 blocked</span>
                    <span className="tag text-[9px] text-accent border-accent/30 bg-accent/10">BLOCKED</span>
                  </div>
                </div>

                <div className="login-feed-item">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <ShieldCheck size={14} className="text-ok flex-none" />
                    <div>
                      <span className="font-semibold text-ink">NDPA 2023 checks</span>
                      <span className="text-soft ml-1.5 hidden sm:inline">(always on)</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <span className="text-soft text-[10px]">14/18 controls</span>
                    <span className="tag text-[9px] text-ok border-ok/30 bg-ok/10">PASS</span>
                  </div>
                </div>
              </div>

              {/* Metrics Row */}
              <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-line text-center">
                <div>
                  <div className="mono text-xs font-semibold text-ink">99.98%</div>
                  <div className="mono text-[9px] text-soft tracking-wider mt-0.5">UPTIME</div>
                </div>
                <div>
                  <div className="mono text-xs font-semibold text-ink">&lt; 42ms</div>
                  <div className="mono text-[9px] text-soft tracking-wider mt-0.5">AVG. RESPONSE</div>
                </div>
                <div>
                  <div className="mono text-xs font-semibold text-ink">3 REGIONS</div>
                  <div className="mono text-[9px] text-soft tracking-wider mt-0.5">WEST & EAST AFRICA</div>
                </div>
              </div>

              {/* Compliance Badges */}
              <div className="auth-trust-strip mt-4">
                <span className="auth-trust-item">
                  <ShieldCheck size={12} className="text-accent" /> NDPA 2023 COMPLIANT
                </span>
                <span className="auth-trust-item">
                  <Lock size={12} className="text-accent" /> BUILT FOR CBN RULES
                </span>
                <span className="auth-trust-item">
                  <CheckCircle2 size={12} className="text-accent" /> SECURE SIGN-IN
                </span>
              </div>
            </div>

            {/* Testimonial Quote */}
            <div className="p-3.5 rounded border border-line bg-inset/60 text-xs text-soft leading-relaxed flex items-start gap-3">
              <span className="font-serif text-2xl text-accent leading-none select-none">“</span>
              <p>
                <strong className="text-ink">CYPHWARD</strong> gives our board a clear view of our security and compliance — no more guesswork.
                <span className="block mt-1 text-[10.5px] mono text-soft">— Folake Adeyemi, Lead DPO, Lagos Core Switch</span>
              </p>
            </div>
          </div>

          {/* Right Column: Authentication Terminal */}
          <div className="lg:col-span-5 order-1 lg:order-2">
            <div className="login-terminal-card">
              <div className="auth-tabs">
                <button type="button" className="auth-tab active">
                  <KeyRound size={13} className="inline mr-1.5" /> SIGN IN
                </button>
              </div>

              <form onSubmit={submit}>
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
                      <Link to="/forgot-password" className="text-[10px] mono text-soft hover:text-accent transition-colors">
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

                  {/* Trust Enclave Checkbox */}
                  <div className="flex items-center justify-between mt-4">
                    <label className="flex items-center gap-2 cursor-pointer text-xs mono text-soft select-none hover:text-ink transition-colors">
                      <input
                        type="checkbox"
                        checked={remember}
                        onChange={e => setRemember(e.target.checked)}
                        className="accent-accent"
                      />
                      <span>KEEP ME SIGNED IN ON THIS DEVICE</span>
                    </label>
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
                        <Link to={`/signup${inviteParam}`} className="text-accent underline font-medium ml-1">
                        Create Account
                      </Link>
                    </span>
                  </div>
              </form>

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
            <div><dt>COMPLIANCE</dt><dd>NDPA 2023 · CBN</dd></div>
            <div><dt>DATA LOCATION</dt><dd>LAGOS · NAIROBI</dd></div>
            <div><dt>ACCOUNT STATUS</dt><dd className="text-ok font-medium">SECURE &amp; ACTIVE</dd></div>
          </dl>
        </div>
      </div>
    </div>
  );
}
