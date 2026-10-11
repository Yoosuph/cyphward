import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Loader2, AlertCircle } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';
import DomainDnsInstructions from '../../components/DomainDnsInstructions';

export default function VerifyDomain() {
  const { primaryDomain, verifyDomain, completeOnboarding } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [verified, setVerified] = useState(false);

  if (!primaryDomain) return null;

  const domain = primaryDomain.domain;
  const handleVerify = async () => {
    if (busy) return;
    setBusy(true);
    setError('');

    const result = await verifyDomain();

    if (!result.ok || !result.verified) {
      setBusy(false);
      setError(result.error || "We couldn't verify it yet. Make sure the TXT record is saved — it can take a few minutes to appear.");
      return;
    }

    setBusy(false);
    setVerified(true);
    toast('Domain verified!');

    setTimeout(() => {
      completeOnboarding();
      nav('/onboarding/complete', { replace: true });
    }, 1200);
  };

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
            <h3 className="font-display text-lg font-medium text-ink">Domain Verified!</h3>
            <p className="text-xs text-soft mt-1">{domain} has been verified successfully.</p>
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
          Verify your domain
        </h3>
        <p className="text-xs text-soft">
          Add a DNS TXT record to prove you own <span className="text-ink font-medium">{domain}</span>.
        </p>
      </div>

      <DomainDnsInstructions key={primaryDomain.id} domain={domain} token={primaryDomain.verification_token} />

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
          <AlertCircle size={14} className="flex-none mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <button
        type="button"
        onClick={handleVerify}
        disabled={busy || !primaryDomain.verification_token}
        className="btn btn-solid w-full justify-center"
      >
        {busy ? (
          <>
            <Loader2 size={14} className="animate-spin" />
            <span>VERIFYING…</span>
          </>
        ) : (
          'VERIFY DOMAIN'
        )}
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
