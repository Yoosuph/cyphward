import { FormEvent, useState, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ShieldAlert, Key, CheckCircle2, RefreshCw } from 'lucide-react';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';

export default function ForgotPassword() {
  const nav = useNavigate();
  const toast = useToast();

  const [step, setStep] = useState<'email' | 'pin' | 'newpass' | 'success'>('email');
  const [email, setEmail] = useState('');
  const [pin, setPin] = useState(['8', '4', '2', '', '', '']);
  const [newPass, setNewPass] = useState('');
  const [confirmPass, setConfirmPass] = useState('');
  const [busy, setBusy] = useState(false);

  const pinRefs = [
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
  ];

  const handleEmailSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!email) return;
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setStep('pin');
      toast('One-time cryptographic token dispatched to enclave email.');
    }, 600);
  };

  const handlePinChange = (index: number, val: string) => {
    const digit = val.slice(-1);
    const updated = [...pin];
    updated[index] = digit;
    setPin(updated);

    if (digit && index < 5) {
      pinRefs[index + 1].current?.focus();
    }
  };

  const handlePinKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !pin[index] && index > 0) {
      pinRefs[index - 1].current?.focus();
    }
  };

  const handlePinSubmit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setStep('newpass');
      toast('Security token verified by enclave root key.');
    }, 500);
  };

  const calculateStrength = (p: string) => {
    if (!p) return { pct: 0, text: 'ENTER PASSPHRASE', color: 'var(--soft)' };
    let score = 0;
    if (p.length >= 10) score += 25;
    if (p.length >= 14) score += 25;
    if (/[A-Z]/.test(p)) score += 15;
    if (/[0-9]/.test(p)) score += 15;
    if (/[^A-Za-z0-9]/.test(p)) score += 20;

    if (score < 40) return { pct: score, text: 'WEAK — REGULATORY HAZARD', color: 'var(--accent)' };
    if (score < 75) return { pct: score, text: 'MODERATE — ACCEPTABLE', color: 'var(--warn)' };
    return { pct: score, text: 'STRONG — MILITARY / NDPA COMPLIANT', color: 'var(--ok)' };
  };

  const strength = calculateStrength(newPass);

  const handlePasswordSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (newPass !== confirmPass) {
      toast('Passphrases do not match.');
      return;
    }
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setStep('success');
      toast('Passphrase updated successfully.');
    }, 600);
  };

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-xl mx-auto my-auto px-4">
        <div className="flex items-center justify-between mb-4">
          <p className="eyebrow flex items-center gap-2">
            <span className="live-dot" /> CYPHWARD — ENCLAVE KEY RECOVERY
          </p>
          <Link to="/login" className="stat-link text-xs">
            RETURN TO SIGN IN →
          </Link>
        </div>

        <h1 className="display-h">
          Cryptographic <em>credential recovery.</em>
        </h1>
        <p className="login-sub">
          Reset your zero-trust workstation passphrase through hardware enclave verification
          and one-time ephemeral token challenge.
        </p>

        <div className="auth-card panel mt-6">
          {step === 'email' && (
            <form onSubmit={handleEmailSubmit}>
              <div className="flex items-center gap-3 p-3 bg-inset border border-line rounded mb-5 text-xs mono text-soft">
                <ShieldAlert size={18} className="text-warn flex-none" />
                <span>
                  Authorized security officers only. Recovery challenges are logged to the NDPA immutable audit trail.
                </span>
              </div>

              <div className="field">
                <label htmlFor="recEmail">WORK ENCLAVE EMAIL</label>
                <input
                  id="recEmail"
                  type="email"
                  placeholder="ciso@acmetraders.ng"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                />
              </div>

              <button className="btn btn-solid" type="submit" disabled={busy}>
                {busy ? 'DISPATCHING TOKEN…' : 'DISPATCH EPHEMERAL TOKEN'} <ArrowRight size={14} />
              </button>

              <div className="mt-4 pt-3 border-t border-line text-center">
                <span className="text-xs mono text-soft">
                  Remembered your credentials?{' '}
                  <Link to="/login" className="text-accent underline font-medium ml-1">
                    Sign in here
                  </Link>
                </span>
              </div>
            </form>
          )}

          {step === 'pin' && (
            <form onSubmit={handlePinSubmit}>
              <div className="text-center mb-4">
                <p className="eyebrow">CHALLENGE VERIFICATION</p>
                <p className="text-xs mono text-soft mt-1">
                  Enter the 6-digit cryptographic challenge code sent to your enclave device.
                </p>
              </div>

              <div className="pin-row">
                {pin.map((digit, i) => (
                  <input
                    key={i}
                    ref={pinRefs[i]}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    onChange={e => handlePinChange(i, e.target.value)}
                    onKeyDown={e => handlePinKeyDown(i, e)}
                    className="pin-input"
                    autoFocus={i === 3}
                  />
                ))}
              </div>

              <div className="flex items-center justify-between text-xs mono text-soft my-3">
                <span>SIMULATED CODE: 842-719</span>
                <button
                  type="button"
                  onClick={() => setPin(['8', '4', '2', '7', '1', '9'])}
                  className="text-accent hover:underline flex items-center gap-1"
                >
                  <RefreshCw size={11} /> AUTOFILL
                </button>
              </div>

              <button className="btn btn-solid" type="submit" disabled={busy || pin.join('').length < 6}>
                {busy ? 'VALIDATING CHALLENGE…' : 'VERIFY IDENTITY TOKEN'} <ArrowRight size={14} />
              </button>
            </form>
          )}

          {step === 'newpass' && (
            <form onSubmit={handlePasswordSubmit}>
              <div className="flex items-center gap-2 mb-4">
                <Key size={16} className="text-accent" />
                <p className="eyebrow">CONFIGURE NEW ENCLAVE PASSPHRASE</p>
              </div>

              <div className="field">
                <label htmlFor="newPass">NEW PASSPHRASE</label>
                <input
                  id="newPass"
                  type="password"
                  placeholder="Min 12 chars with symbol & number"
                  value={newPass}
                  onChange={e => setNewPass(e.target.value)}
                  required
                />
              </div>

              {/* Password strength meter */}
              <div className="mt-2">
                <div className="flex justify-between text-[10px] mono mb-1">
                  <span className="text-soft">ENTROPY STRENGTH</span>
                  <span style={{ color: strength.color }}>{strength.text}</span>
                </div>
                <div className="pwd-meter">
                  <div
                    className="pwd-meter-fill"
                    style={{ width: `${strength.pct}%`, backgroundColor: strength.color }}
                  />
                </div>
              </div>

              <div className="field mt-3">
                <label htmlFor="confirmPass">CONFIRM PASSPHRASE</label>
                <input
                  id="confirmPass"
                  type="password"
                  placeholder="Re-enter passphrase"
                  value={confirmPass}
                  onChange={e => setConfirmPass(e.target.value)}
                  required
                />
              </div>

              <button className="btn btn-solid" type="submit" disabled={busy || strength.pct < 40}>
                {busy ? 'RE-ENCRYPTING VAULT…' : 'UPDATE PASSPHRASE & SIGN IN'} <ArrowRight size={14} />
              </button>
            </form>
          )}

          {step === 'success' && (
            <div className="py-8 text-center">
              <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30 mb-4">
                <CheckCircle2 size={36} />
              </div>
              <h3 className="font-display text-2xl font-medium mb-2">
                Credentials Re-encrypted
              </h3>
              <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
                Your passphrase has been securely rotated and synchronised with your tenant's HSM cluster.
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
          <div><dt>SECURITY STANDARD</dt><dd>FIPS 140-2 LEVEL 3 HSM</dd></div>
          <div><dt>AUDIT LOGGING</dt><dd>IMMUTABLE TELEMETRY</dd></div>
          <div><dt>ENCLAVE</dt><dd>ZERO-TRUST WORKSTATION</dd></div>
        </dl>
      </div>
    </div>
  );
}
