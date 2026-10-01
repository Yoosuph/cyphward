import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ShieldAlert, Key, CheckCircle2, RefreshCw } from 'lucide-react';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import { supabase, isSupabaseConfigured } from '../lib/supabase';
import { checkPasswordStrength } from '../lib/password';

type Step = 'email' | 'sent' | 'newpass' | 'done';

export default function ForgotPassword() {
  const nav = useNavigate();
  const toast = useToast();

  const [step, setStep] = useState<Step>('email');
  const [email, setEmail] = useState('');
  const [sentTo, setSentTo] = useState('');
  const [expired, setExpired] = useState(false);
  const [newPass, setNewPass] = useState('');
  const [confirmPass, setConfirmPass] = useState('');
  const [busy, setBusy] = useState(false);

  const hasRecoveryCode = () => {
    try {
      const u = new URL(window.location.href);
      return u.searchParams.has('code') || u.hash.includes('access_token');
    } catch {
      return false;
    }
  };

  // A recovery link lands here with ?code=… — the Supabase client exchanges it
  // automatically (detectSessionInUrl). When a session materialises, switch to
  // the set-new-password step; if nothing arrives, the link is dead.
  useEffect(() => {
    if (!isSupabaseConfigured || !hasRecoveryCode()) return;

    let settled = false;
    const enterReset = () => {
      settled = true;
      setExpired(false);
      setStep('newpass');
    };

    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!settled && data.session) enterReset();
      })
      .catch(() => {});

    const { data: sub } = supabase.auth.onAuthStateChange(event => {
      if (event === 'PASSWORD_RECOVERY' || event === 'SIGNED_IN') enterReset();
    });

    const timer = window.setTimeout(() => {
      if (!settled) setExpired(true);
    }, 6000);

    return () => {
      sub.subscription.unsubscribe();
      window.clearTimeout(timer);
    };
  }, []);

  const handleEmailSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email || busy) return;
    if (!isSupabaseConfigured) {
      toast('Authentication is not configured on this deployment.');
      return;
    }
    setBusy(true);
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/forgot-password`,
      });
      if (error) {
        const msg = error.message || '';
        if (/rate|too many/i.test(msg)) {
          toast(msg);
        } else if (/redirect|allow/i.test(msg)) {
          toast('Recovery links are misconfigured (redirect URL not allowed). Ask your administrator to allow this origin.');
        } else if (/confirm/i.test(msg)) {
          toast('That address is not verified yet — check your inbox for the verification email first.');
        } else {
          console.error('resetPasswordForEmail failed:', error);
          toast('We could not start recovery. Please try again shortly.');
        }
      } else {
        setSentTo(email);
        setExpired(false);
        setStep('sent');
      }
    } catch (err) {
      console.error('resetPasswordForEmail failed:', err);
      toast('We could not start recovery. Please try again shortly.');
    } finally {
      setBusy(false);
    }
  };

  const strength = checkPasswordStrength(newPass);
  const mismatch = confirmPass.length > 0 && newPass !== confirmPass;

  const handlePasswordSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (newPass !== confirmPass) return;
    setBusy(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPass });
      if (error) {
        const msg = error.message || '';
        toast(msg || 'Could not update the password.');
        if (/expired|jwt|session/i.test(msg)) setStep('email');
      } else {
        setStep('done');
      }
    } catch (err) {
      console.error('updateUser failed:', err);
      toast('Could not update the password. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-xl mx-auto my-auto px-4">
        <div className="flex items-center justify-between mb-4">
          <p className="eyebrow flex items-center gap-2">
            <span className="live-dot" /> CYPHWARD — RESET YOUR PASSWORD
          </p>
          <Link to="/login" className="stat-link text-xs">
            BACK TO SIGN IN →
          </Link>
        </div>

        <h1 className="display-h">
          Reset your <em>password.</em>
        </h1>
        <p className="login-sub">
          Enter your email address and we'll send you a link to set a new password.
          The link works once and expires after a short time.
        </p>

        <div className="auth-card panel mt-6">
          {step === 'email' && (
            <form onSubmit={handleEmailSubmit}>
              <div className="flex items-center gap-3 p-3 bg-inset border border-line rounded mb-5 text-xs mono text-soft">
                <ShieldAlert size={18} className="text-warn flex-none" />
                <span>
                  Only account owners can reset a password. Every request is recorded for safety.
                </span>
              </div>

              {expired && (
                <div className="flex items-center gap-3 p-3 bg-inset border border-accent/40 rounded mb-5 text-xs mono text-warn">
                  <ShieldAlert size={16} className="flex-none" />
                  <span>That link is invalid or has expired. Request a new one below.</span>
                </div>
              )}

              <div className="field">
                <label htmlFor="recEmail">WORK EMAIL</label>
                <input
                  id="recEmail"
                  type="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                />
              </div>

              <button className="btn btn-solid" type="submit" disabled={busy}>
                {busy ? 'SENDING…' : 'EMAIL ME A RESET LINK'} <ArrowRight size={14} />
              </button>

              <div className="mt-4 pt-3 border-t border-line text-center">
                <span className="text-xs mono text-soft">
                  Remembered your password?{' '}
                  <Link to="/login" className="text-accent underline font-medium ml-1">
                    Sign in here
                  </Link>
                </span>
              </div>
            </form>
          )}

          {step === 'sent' && (
            <div className="py-8 text-center">
              <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30 mb-4">
                <CheckCircle2 size={36} />
              </div>
              <h3 className="font-display text-2xl font-medium mb-2">Reset link sent</h3>
              <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
                If an account exists for <span className="text-accent">{sentTo}</span>, a reset
                link is on its way. Check your spam folder if you don't see it.
              </p>
              <div className="space-y-3">
                <button
                  className="btn btn-solid w-full justify-center"
                  onClick={() => setStep('email')}
                >
                  <RefreshCw size={13} className="mr-1" /> USE A DIFFERENT EMAIL
                </button>
                <Link to="/login" className="btn btn-ghost w-full justify-center block">
                  RETURN TO SIGN IN
                </Link>
              </div>
            </div>
          )}

          {step === 'newpass' && (
            <form onSubmit={handlePasswordSubmit}>
              <div className="flex items-center gap-2 mb-4">
                <Key size={16} className="text-accent" />
                <p className="eyebrow">SET A NEW PASSWORD</p>
              </div>

              <div className="field">
                <label htmlFor="newPass">NEW PASSWORD</label>
                <input
                  id="newPass"
                  type="password"
                  placeholder="At least 8 characters"
                  value={newPass}
                  onChange={e => setNewPass(e.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </div>

              <div className="mt-2">
                <div className="flex justify-between text-[10px] mono mb-1">
                  <span className="text-soft">PASSWORD STRENGTH</span>
                  <span style={{ color: strength.color }}>{strength.label || 'ENTER A PASSWORD'}</span>
                </div>
                <div className="pwd-meter">
                  <div
                    className="pwd-meter-fill"
                    style={{ width: `${strength.pct}%`, backgroundColor: strength.color }}
                  />
                </div>
                {strength.hint && <p className="text-[10px] mono text-soft">{strength.hint}</p>}
              </div>

              <div className="field mt-3">
                <label htmlFor="confirmPass">CONFIRM PASSWORD</label>
                <input
                  id="confirmPass"
                  type="password"
                  placeholder="Type it again"
                  value={confirmPass}
                  onChange={e => setConfirmPass(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </div>

              {mismatch && (
                <div className="p-3 mt-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500">
                  Passwords don't match.
                </div>
              )}

              <button
                className="btn btn-solid"
                type="submit"
                disabled={busy || !strength.ok || newPass !== confirmPass}
              >
                {busy ? 'SAVING…' : 'UPDATE PASSWORD'} <ArrowRight size={14} />
              </button>
            </form>
          )}

          {step === 'done' && (
            <div className="py-8 text-center">
              <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30 mb-4">
                <CheckCircle2 size={36} />
              </div>
              <h3 className="font-display text-2xl font-medium mb-2">Password updated</h3>
              <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
                Your password has been changed. Use it the next time you sign in.
              </p>
              <button
                className="btn btn-solid w-full justify-center"
                onClick={() => nav('/login')}
              >
                RETURN TO SIGN IN <ArrowRight size={14} />
              </button>
            </div>
          )}
        </div>

        <dl className="meta-row mt-6">
          <div><dt>PASSWORDS</dt><dd>NEVER STORED IN PLAIN TEXT</dd></div>
          <div><dt>RESET LINKS</dt><dd>SINGLE-USE &amp; EXPIRING</dd></div>
          <div><dt>YOUR DATA</dt><dd>ENCRYPTED IN TRANSIT</dd></div>
        </dl>
      </div>
    </div>
  );
}
