import { FormEvent, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Key, CheckCircle2, ShieldAlert } from 'lucide-react';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import { resetPasswordRequest } from '../lib/api';
import { checkPasswordStrength } from '../lib/password';

export default function ResetPassword() {
  const nav = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();
  const token = (params.get('token') || '').trim();

  const [newPass, setNewPass] = useState('');
  const [confirmPass, setConfirmPass] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const strength = checkPasswordStrength(newPass);
  const mismatch = confirmPass.length > 0 && newPass !== confirmPass;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!token || newPass !== confirmPass || !strength.ok || busy) return;
    setBusy(true);
    try {
      await resetPasswordRequest(token, newPass);
      setDone(true);
    } catch (err: any) {
      const msg = err?.message || 'Could not update the password.';
      toast(msg);
      if (/expired|invalid|used/i.test(msg)) {
        // Dead link — send the user back to request a fresh one.
        setTimeout(() => nav('/forgot-password', { replace: true }), 1800);
      }
    } finally {
      setBusy(false);
    }
  };

  const missingToken = (
    <div className="py-8 text-center">
      <div className="inline-block p-4 rounded-full bg-warn/10 text-warn border border-warn/30 mb-4">
        <ShieldAlert size={36} />
      </div>
      <h3 className="font-display text-2xl font-medium mb-2">Link missing or expired</h3>
      <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
        This page needs a reset link from your email. Request a new one and open it
        within 30 minutes.
      </p>
      <Link to="/forgot-password" className="btn btn-solid w-full justify-center">
        REQUEST A NEW LINK <ArrowRight size={14} />
      </Link>
    </div>
  );

  const successScreen = (
    <div className="py-8 text-center">
      <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30 mb-4">
        <CheckCircle2 size={36} />
      </div>
      <h3 className="font-display text-2xl font-medium mb-2">Password updated</h3>
      <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
        Your password has been changed. Use it the next time you sign in.
        All other sessions were signed out for safety.
      </p>
      <button
        className="btn btn-solid w-full justify-center"
        onClick={() => nav('/login', { replace: true })}
      >
        RETURN TO SIGN IN <ArrowRight size={14} />
      </button>
    </div>
  );

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-xl mx-auto my-auto px-4">
        <div className="flex items-center justify-between mb-4">
          <p className="eyebrow flex items-center gap-2">
            <span className="live-dot" /> CYPHWARD — SET A NEW PASSWORD
          </p>
          <Link to="/login" className="stat-link text-xs">
            BACK TO SIGN IN →
          </Link>
        </div>

        <h1 className="display-h">
          Choose a new <em>password.</em>
        </h1>
        <p className="login-sub">
          Pick something you don't use anywhere else. We'll sign out your other
          devices once the change is saved.
        </p>

        <div className="auth-card panel mt-6">
          {!token ? (
            missingToken
          ) : done ? (
            successScreen
          ) : (
            <form onSubmit={submit}>
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
                  maxLength={128}
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
                  minLength={8}
                  required
                />
              </div>

              {mismatch && (
                <div className="p-3 mt-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500">
                  Passwords don't match.
                </div>
              )}

              <button
                className="btn btn-solid mt-5"
                type="submit"
                disabled={busy || !strength.ok || newPass !== confirmPass}
              >
                {busy ? 'SAVING…' : 'UPDATE PASSWORD'} <ArrowRight size={14} />
              </button>
            </form>
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
