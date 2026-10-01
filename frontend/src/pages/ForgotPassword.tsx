import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ShieldAlert, CheckCircle2, RefreshCw } from 'lucide-react';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import { forgotPasswordRequest } from '../lib/api';

type Step = 'email' | 'sent';

export default function ForgotPassword() {
  const toast = useToast();

  const [step, setStep] = useState<Step>('email');
  const [email, setEmail] = useState('');
  const [sentTo, setSentTo] = useState('');
  const [busy, setBusy] = useState(false);

  const handleEmailSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email || busy) return;
    setBusy(true);
    try {
      // The backend always answers {ok:true} (no account enumeration) and
      // sends the reset email through Brevo when an account exists.
      await forgotPasswordRequest(email);
      setSentTo(email);
      setStep('sent');
    } catch (err) {
      console.error('forgot-password failed:', err);
      toast('We could not start recovery. Please try again shortly.');
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
