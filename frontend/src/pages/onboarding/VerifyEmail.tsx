import { useEffect, useRef, useState, type ClipboardEvent, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, ArrowRight, MailCheck, RefreshCw } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';
import { getVerificationStatus, sendVerificationOtp, verifyEmailOtp } from '../../lib/api';

const BOX_COUNT = 6;

const NEXT_ROUTE: Record<string, string> = {
  verify_email: '/onboarding/verify-email',
  create_org: '/onboarding/create-org',
  add_domain: '/onboarding/add-domain',
  verify_domain: '/onboarding/verify-domain',
  complete: '/',
  none: '/',
};

function parseCooldown(message: string): number {
  const match = /Resend available in (\d+)s/.exec(message);
  return match ? parseInt(match[1], 10) : 60;
}

export default function VerifyEmail() {
  const { user, refreshOnboarding } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const toast = useToast();

  const [digits, setDigits] = useState<string[]>(Array(BOX_COUNT).fill(''));
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [cooldown, setCooldown] = useState(0);
  const [sentTo, setSentTo] = useState(user?.email || '');

  const inputsRef = useRef<Array<HTMLInputElement | null>>([]);
  const autoSentRef = useRef(false);
  const submittingRef = useRef(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setTimeout(() => setCooldown((c) => (c > 0 ? c - 1 : 0)), 1000);
    return () => clearTimeout(id);
  }, [cooldown]);

  const finish = async () => {
    const step = await refreshOnboarding();
    // Keep ?invite= (and any other query) so invitation links survive the
    // onboarding hop back into the product.
    nav(`${NEXT_ROUTE[step] || '/'}${location.search}`, { replace: true });
  };

  const sendCode = async (opts?: { silent?: boolean }) => {
    setSending(true);
    setError('');
    try {
      const res = await sendVerificationOtp();
      if (res.sent === false && res.reason === 'already_verified') {
        toast('Email verified.');
        await finish();
        return;
      }
      setCooldown(res.resend_after ?? 60);
      if (!opts?.silent) toast('Verification code sent.');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Could not send the code.';
      if (/Resend available in/.test(msg)) {
        // A code is already on its way (e.g. sent at signup) — just show the window.
        setCooldown(parseCooldown(msg));
      } else {
        setError(msg);
      }
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    if (autoSentRef.current) return;
    autoSentRef.current = true;
    void (async () => {
      const status = await getVerificationStatus();
      if (status?.verified) {
        await finish();
        return;
      }
      if (status?.email) setSentTo(status.email);
      await sendCode({ silent: true });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (code: string) => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setBusy(true);
    setError('');
    try {
      await verifyEmailOtp(code);
      toast('Email verified!');
      await finish();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Verification failed. Please try again.';
      setError(msg);
      setDigits(Array(BOX_COUNT).fill(''));
      inputsRef.current[0]?.focus();
    } finally {
      setBusy(false);
      submittingRef.current = false;
    }
  };

  const handleChange = (idx: number, raw: string) => {
    const value = raw.replace(/\D/g, '').slice(-1);
    const next = [...digits];
    next[idx] = value;
    setDigits(next);
    if (value && idx < BOX_COUNT - 1) inputsRef.current[idx + 1]?.focus();
    if (value && next.every((d) => d !== '')) void submit(next.join(''));
  };

  const handleKeyDown = (idx: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[idx] && idx > 0) {
      e.preventDefault();
      const next = [...digits];
      next[idx - 1] = '';
      setDigits(next);
      inputsRef.current[idx - 1]?.focus();
    } else if (e.key === 'ArrowLeft' && idx > 0) {
      e.preventDefault();
      inputsRef.current[idx - 1]?.focus();
    } else if (e.key === 'ArrowRight' && idx < BOX_COUNT - 1) {
      e.preventDefault();
      inputsRef.current[idx + 1]?.focus();
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, BOX_COUNT);
    if (!text) return;
    e.preventDefault();
    const next = Array(BOX_COUNT).fill('');
    for (let i = 0; i < text.length; i++) next[i] = text[i];
    setDigits(next);
    inputsRef.current[Math.min(text.length, BOX_COUNT - 1)]?.focus();
    if (text.length === BOX_COUNT) void submit(text);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const code = digits.join('');
    if (code.length === BOX_COUNT && !busy) void submit(code);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="text-center">
        <MailCheck size={36} className="text-accent mx-auto mb-2" />
        <h3 className="font-display text-lg font-medium text-ink mb-1">
          Verify your email address
        </h3>
        <p className="text-xs text-soft">
          Enter the 6-digit code we sent to{' '}
          <span className="mono text-ink break-all">{sentTo}</span>.
          <br />
          The code expires in 10 minutes.
        </p>
      </div>

      <div className="pin-row mt-6" onPaste={handlePaste}>
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              inputsRef.current[i] = el;
            }}
            className="pin-input"
            type="text"
            inputMode="numeric"
            autoComplete={i === 0 ? 'one-time-code' : 'off'}
            maxLength={1}
            value={d}
            disabled={busy}
            onChange={(e) => handleChange(i, e.target.value)}
            onKeyDown={(e) => handleKeyDown(i, e)}
            aria-label={`Digit ${i + 1} of ${BOX_COUNT}`}
            autoFocus={i === 0}
          />
        ))}
      </div>
      <p className="text-center text-[10px] mono text-soft -mt-2">
        The code submits automatically when the last digit is entered.
      </p>

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
          <AlertCircle size={14} className="flex-none mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={busy || digits.some((d) => !d)}
        className="btn btn-solid w-full justify-center"
      >
        {busy ? (
          <span>VERIFYING…</span>
        ) : (
          <>
            VERIFY EMAIL <ArrowRight size={14} />
          </>
        )}
      </button>

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => sendCode()}
          disabled={sending || cooldown > 0}
          className="btn text-xs mono text-soft hover:text-ink disabled:opacity-50 flex items-center gap-1.5"
        >
          <RefreshCw size={13} className={sending ? 'animate-spin' : ''} />
          {cooldown > 0 ? `RESEND CODE (${cooldown}s)` : 'RESEND CODE'}
        </button>
        <span className="text-[10px] mono text-soft">5 attempts per code</span>
      </div>
    </form>
  );
}
