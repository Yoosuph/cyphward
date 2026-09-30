import { FormEvent, useState, useEffect } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import {
  ArrowRight, ShieldCheck, Lock,
  Eye, EyeOff, Sun, Moon, Check, Globe, Server, CheckCircle2,
  Radio, ShieldAlert, AlertCircle, User
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import { getTheme, toggleTheme } from '../lib/theme';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import CyphwardLogo from '../components/CyphwardLogo';

export default function Signup() {
  const { tenant, signUpWithCredentials, onboardingStep } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
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

    const result = await signUpWithCredentials(email, password, name);

    if (!result.ok) {
      setBusy(false);
      setError(result.error || 'Registration failed. Please try again.');
      return;
    }

    const first = (name || '').trim().split(' ')[0] || email.split('@')[0];
    toast(`Welcome to Cyphward${first ? `, ${first}` : ''}! Check your inbox for your welcome email.`);
    if (result.needsOnboarding) {
      nav('/onboarding', { replace: true });
    } else {
      nav('/', { replace: true });
    }
  };

  return (
    <div className="login-wrap">
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
              <span className="live-dot" /> SOVEREIGN CLOUD ENCLAVE · L00 ACCESS
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
              <span>PLATFORM OVERVIEW ↗</span>
            </Link>
          </div>
        </div>

        {/* Main Split Grid on Desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-14 items-center">
          {/* Left Column: Brand Manifesto & Live Telemetry */}
          <div className="lg:col-span-7 flex flex-col gap-6 order-2 lg:order-1">
            <div>
              <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded border border-line bg-inset font-mono text-[10.5px] tracking-wider text-soft mb-3">
                <Radio size={12} className="text-accent animate-pulse" />
                <span>PRIMARY REGION: LAGOS // KANO // NAIROBI</span>
              </div>

              <h1 className="display-h">
                Deploy sovereign <em>cyber defense.</em>
              </h1>

              <p className="login-sub">
                Create your enclave to secure your organization's digital perimeter with continuous NDPA 2023 compliance monitoring and localized African threat detection.
              </p>
            </div>

            {/* Live Telemetry Showcase Box */}
            <div className="login-telemetry-panel">
              <div className="flex items-center justify-between pb-3 mb-4 border-b border-line">
                <div className="flex items-center gap-2">
                  <span className="live-dot" />
                  <span className="eyebrow text-[10px] tracking-widest">LIVE ENCLAVE TELEMETRY</span>
                </div>
                <span className="mono text-[10px] text-soft">LATENCY: 24ms · HEALTH: 100%</span>
              </div>

              <div className="flex flex-col gap-2.5">
                <div className="login-feed-item">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Server size={14} className="text-accent flex-none" />
                    <div>
                      <span className="font-semibold text-ink">USSD GATEWAY</span>
                      <span className="text-soft ml-1.5 hidden sm:inline">(KANO EDGE CLUSTER)</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <span className="text-soft text-[10px]">1,420 TX/MIN</span>
                    <span className="tag text-[9px] text-ok border-ok/30 bg-ok/10">NORMAL</span>
                  </div>
                </div>

                <div className="login-feed-item">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <ShieldAlert size={14} className="text-accent flex-none" />
                    <div>
                      <span className="font-semibold text-ink">SIM-SWAP RADAR</span>
                      <span className="text-soft ml-1.5 hidden sm:inline">(LAGOS CORE SWITCH)</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <span className="text-soft text-[10px]">3 INTERCEPTS</span>
                    <span className="tag text-[9px] text-accent border-accent/30 bg-accent/10">BLOCKED</span>
                  </div>
                </div>

                <div className="login-feed-item">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <ShieldCheck size={14} className="text-ok flex-none" />
                    <div>
                      <span className="font-semibold text-ink">NDPA 2023 BASELINE</span>
                      <span className="text-soft ml-1.5 hidden sm:inline">(CONTINUOUS AUDIT)</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-none">
                    <span className="text-soft text-[10px]">14/18 CONTROLS</span>
                    <span className="tag text-[9px] text-ok border-ok/30 bg-ok/10">PASS</span>
                  </div>
                </div>
              </div>

              {/* Metrics Row */}
              <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-line text-center">
                <div>
                  <div className="mono text-xs font-semibold text-ink">99.98%</div>
                  <div className="mono text-[9px] text-soft tracking-wider mt-0.5">ENCLAVE UPTIME</div>
                </div>
                <div>
                  <div className="mono text-xs font-semibold text-ink">&lt; 42ms</div>
                  <div className="mono text-[9px] text-soft tracking-wider mt-0.5">TRIAGE LATENCY</div>
                </div>
                <div>
                  <div className="mono text-xs font-semibold text-ink">3 NODES</div>
                  <div className="mono text-[9px] text-soft tracking-wider mt-0.5">WEST & EAST AFRICA</div>
                </div>
              </div>

              {/* Compliance Badges */}
              <div className="auth-trust-strip mt-4">
                <span className="auth-trust-item">
                  <ShieldCheck size={12} className="text-accent" /> NDPA 2023 COMPLIANT
                </span>
                <span className="auth-trust-item">
                  <Lock size={12} className="text-accent" /> CBN TIER-1 BANKING SPEC
                </span>
                <span className="auth-trust-item">
                  <CheckCircle2 size={12} className="text-accent" /> FIDO2 / WEBAUTHN
                </span>
              </div>
            </div>

            {/* Testimonial Quote */}
            <div className="p-3.5 rounded border border-line bg-inset/60 text-xs text-soft leading-relaxed flex items-start gap-3">
              <span className="font-serif text-2xl text-accent leading-none select-none">"</span>
              <p>
                <strong className="text-ink">CYPHWARD</strong> gives our Board continuous verification across Pan-African switches with zero compliance guesswork.
                <span className="block mt-1 text-[10.5px] mono text-soft">— Folake Adeyemi, Lead DPO, Lagos Core Switch</span>
              </p>
            </div>
          </div>

          {/* Right Column: Authentication Terminal */}
          <div className="lg:col-span-5 order-1 lg:order-2">
            <div className="login-terminal-card">
              {/* Card Tabs */}
              <div className="auth-tabs">
                <button type="button" className="auth-tab active">
                  <User size={13} className="inline mr-1.5" /> CREATE ENCLAVE
                </button>
              </div>

              <form onSubmit={submit}>
                  {/* Full Name Field */}
                  <div className="field">
                    <label htmlFor="fullName">FULL NAME</label>
                    <input
                      id="fullName"
                      type="text"
                      placeholder="e.g. Ibrahim Abubakar"
                      value={name}
                      onChange={e => setName(e.target.value)}
                      autoComplete="name"
                      required
                    />
                  </div>

                  {/* Email Field */}
                  <div className="field mt-4">
                    <label htmlFor="regEmail">WORK ENCLAVE EMAIL</label>
                    <input
                      id="regEmail"
                      type="email"
                      placeholder="you@organization.africa"
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                      autoComplete="username"
                      required
                    />
                  </div>

                  {/* Password Field with Eye Toggle */}
                  <div className="field mt-4">
                    <div className="flex items-center justify-between mb-2">
                      <label htmlFor="regPw" className="mb-0">HARDWARE PASSPHRASE</label>
                    </div>

                    <div className="pw-input-wrap">
                      <input
                        id="regPw"
                        type={showPw ? 'text' : 'password'}
                        placeholder="••••••••••••••"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        autoComplete="new-password"
                        required
                        minLength={8}
                      />
                      <button
                        type="button"
                        className="pw-toggle-btn"
                        onClick={() => setShowPw(!showPw)}
                        title={showPw ? 'Hide passphrase' : 'Show passphrase'}
                        aria-label={showPw ? 'Hide passphrase' : 'Show passphrase'}
                      >
                        {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                    <p className="text-[10px] mono text-soft mt-1">Minimum 8 characters</p>
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
                      <span>TRUST THIS HARDWARE ENCLAVE</span>
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
                      <>PROVISIONING ENCLAVE SESSION…</>
                    ) : (
                      <>
                        CREATE SOVEREIGN ENCLAVE <ArrowRight size={14} className="ml-1" />
                      </>
                    )}
                  </button>

                  {/* Dedicated Login Link */}
                  <div className="mt-4 pt-3.5 border-t border-line text-center">
                    <span className="text-xs mono text-soft">
                      Already have an account?{' '}
                      <Link to="/login" className="text-accent underline font-medium ml-1">
                        Sign In
                      </Link>
                    </span>
                  </div>
              </form>

              {/* Hardware attestation footer */}
              <div className="mt-5 pt-3 border-t border-line/60 flex items-center justify-between text-[9.5px] mono text-soft">
                <span className="flex items-center gap-1.5">
                  <Lock size={11} className="text-accent" /> FIDO2 HARDWARE BACKED
                </span>
                <span>SHA-256 HSM ATTESTED</span>
              </div>
            </div>
          </div>
        </div>

        {/* Global Metadata Footer */}
        <div className="mt-10 pt-6 border-t border-line">
          <dl className="meta-row">
            <div><dt>DEFAULT TENANT</dt><dd>ACME TRADERS LTD (KANO)</dd></div>
            <div><dt>REGULATORY REGIME</dt><dd>NDPA 2023 · CBN REGULATED</dd></div>
            <div><dt>DATA RESIDENCY</dt><dd>LAGOS AWS LOCAL ZONE · NAIROBI</dd></div>
            <div><dt>SECURITY LEVEL</dt><dd className="text-ok font-medium">SOVEREIGN ENCLAVE ACTIVE</dd></div>
          </dl>
        </div>
      </div>
    </div>
  );
}
