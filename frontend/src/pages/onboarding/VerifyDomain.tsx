import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Loader2, AlertCircle, RefreshCw } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';
import DomainDnsInstructions from '../../components/DomainDnsInstructions';

// DNS changes often take a few minutes to appear. After a failed check we keep
// trying on a fixed interval instead of making the user click repeatedly.
const RECHECK_SECONDS = 30;
const MAX_AUTO_CHECKS = 20; // 10 minutes

export default function VerifyDomain() {
  const { primaryDomain, verifyDomain, completeOnboarding } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [verified, setVerified] = useState(false);
  const [watching, setWatching] = useState(false);
  const [nextIn, setNextIn] = useState(RECHECK_SECONDS);
  const [autoChecks, setAutoChecks] = useState(0);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const check = useCallback(async (manual: boolean) => {
    if (busy) return;
    setBusy(true);
    if (manual) setError('');
    const result = await verifyDomain();
    if (!mounted.current) return;
    setBusy(false);
    if (result.ok && result.verified) {
      setWatching(false);
      setVerified(true);
      toast('Domain verified!');
      setTimeout(() => {
        completeOnboarding();
        nav('/onboarding/complete', { replace: true });
      }, 1200);
      return;
    }
    setError(result.error || "We can't see the TXT record yet. If you just saved it, that's normal: DNS changes can take a few minutes.");
    setNextIn(RECHECK_SECONDS);
    if (manual) {
      setAutoChecks(0);
      setWatching(true);
    }
  }, [busy, verifyDomain, toast, completeOnboarding, nav]);

  useEffect(() => {
    if (!watching || busy || verified) return;
    if (autoChecks >= MAX_AUTO_CHECKS) {
      setWatching(false);
      setError("We still can't see the record after 10 minutes. Check that the name and value match exactly, then try again. Some providers take up to an hour.");
      return;
    }
    if (nextIn <= 0) {
      setAutoChecks(count => count + 1);
      void check(false);
      return;
    }
    const id = setTimeout(() => setNextIn(seconds => seconds - 1), 1000);
    return () => clearTimeout(id);
  }, [watching, busy, verified, nextIn, autoChecks, check]);

  if (!primaryDomain) return null;
  const domain = primaryDomain.domain;

  const handleSkip = () => {
    completeOnboarding();
    nav('/overview', { replace: true });
  };

  if (verified) {
    return (
      <div className="space-y-5">
        <div className="p-4 bg-ok/10 border border-ok/30 rounded text-center space-y-3">
          <CheckCircle2 size={40} className="mx-auto text-ok" />
          <div>
            <h3 className="font-display text-lg font-medium text-ink">Domain verified</h3>
            <p className="text-xs text-soft mt-1">{domain} is yours. You can scan it now.</p>
          </div>
        </div>
        <p className="text-xs text-soft text-center">Finishing setup…</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="font-display text-lg font-medium text-ink mb-1">
          Prove you own {domain}
        </h3>
        <p className="text-xs text-soft">
          Add this TXT record wherever your domain's DNS is managed (for example your registrar, hosting panel or Cloudflare). We never scan a domain before it's verified.
        </p>
      </div>

      <DomainDnsInstructions key={primaryDomain.id} domain={domain} token={primaryDomain.verification_token} />

      {error && (
        <div
          role={watching ? 'status' : 'alert'}
          className={`p-3 rounded text-xs flex items-start gap-2 ${watching
            ? 'bg-inset border border-line text-soft'
            : 'bg-red-500/10 border border-red-500/30 mono text-red-500'}`}
        >
          <AlertCircle size={14} className="flex-none mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {watching && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-soft" aria-live="polite">
          <span className="flex items-center gap-1.5">
            <RefreshCw size={12} className={busy ? 'animate-spin' : ''} />
            {busy ? 'Checking…' : `Checking again automatically in ${nextIn}s`}
          </span>
          <button type="button" className="underline hover:text-ink" onClick={() => setWatching(false)}>
            Stop checking
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => void check(true)}
        disabled={busy || !primaryDomain.verification_token}
        className="btn btn-solid w-full justify-center"
      >
        {busy ? (
          <>
            <Loader2 size={14} className="animate-spin" />
            <span>CHECKING…</span>
          </>
        ) : watching ? 'CHECK NOW' : "I'VE ADDED THE RECORD · VERIFY"}
      </button>

      <div className="text-center">
        <button
          type="button"
          onClick={handleSkip}
          className="text-xs text-soft hover:text-ink transition-colors"
        >
          Do this later · Open dashboard
        </button>
      </div>
    </div>
  );
}
