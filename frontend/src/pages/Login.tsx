import { FormEvent, useState, useEffect } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import {
  ArrowRight, ShieldCheck, KeyRound, Lock,
  Eye, EyeOff, Sun, Moon, Check, Globe, Server, CheckCircle2,
  Radio, ShieldAlert, AlertCircle
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import { supabase, isSupabaseConfigured } from '../lib/supabase';
import { getTheme, toggleTheme } from '../lib/theme';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import CyphwardLogo from '../components/CyphwardLogo';

export default function Login() {
  const { tenant, signInWithCredentials, onboardingStep } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [needsVerify, setNeedsVerify] = useState(false);
  const [resendBusy, setResendBusy] = useState(false);
  const [remember, setRemember] = useState(true);
  const [theme, setTheme] = useState(getTheme());

  useEffect(() => {
    const onThemeChange = () => setTheme(getTheme());
    window.addEventListener('cyphward:theme', onThemeChange);
    return () => window.removeEventListener('cyphward:theme', onThemeChange);
  }, []);

  if (tenant) {
    if (onboardingStep !== 'none' && onboardingStep !== 'complete') {
      return <Navigate to="/onboarding" replace />;
    }
    return <Navigate to="/" replace />;
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    setNeedsVerify(false);

    const result = await signInWithCredentials(email, pw);

    if (!result.ok) {
      setBusy(false);
      const msg = result.error || 'Wrong email or password. Please try again.';
      if (/not confirmed|confirm/i.test(msg)) {
        setNeedsVerify(true);
        setError('Please verify your email first — open the link we sent you, then sign in.');
      } else {
        setError(msg);
      }
      return;
    }

    const first = (result.name || email.split('@')[0] || '').split(' ')[0];
    toast(`Welcome back${first ? `, ${first}` : ''}!`);

    // Navigate from the server-resolved onboarding step (no stale state).
    if (result.onboarding && result.onboarding !== 'complete' && result.onboarding !== 'none') {
      nav('/onboarding', { replace: true });
    } else {
      nav('/', { replace: true });
    }
  };

  const resendVerification = async () => {
    if (resendBusy || !isSupabaseConfigured || !email) return;
    setResendBusy(true);
    try {
      const { error: resendError } = await supabase.auth.resend({ email, type: 'signup' });
      if (resendError) throw resendError;
      toast('Verification email sent.');
    } catch (err: any) {
      toast(err?.message || 'Could not send verification email.');
    } finally {
      setResendBusy(false);
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
            <Link to="/landing" className="flex items-center text-ink hover:opacity-85 transition-opacity">
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
              to="/landing"
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
                  {needsVerify && (
                    <button
                      type="button"
                      className="w-full mb-4 py-2 text-xs mono border border-line rounded text-soft hover:text-ink hover:border-line-strong transition-colors"
                      onClick={resendVerification}
                      disabled={resendBusy}
                    >
                      {resendBusy ? 'SENDING…' : 'RESEND VERIFICATION EMAIL'}
                    </button>
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

                  {/* Dedicated Registration Link */}
                  <div className="mt-4 pt-3.5 border-t border-line text-center">
                    <span className="text-xs mono text-soft">
                      Don't have an account?{' '}
                        <Link to="/signup" className="text-accent underline font-medium ml-1">
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
