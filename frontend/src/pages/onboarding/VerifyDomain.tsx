import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Loader2, AlertCircle, Copy, Check } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';

export default function VerifyDomain() {
  const { primaryDomain, verifyDomain, completeOnboarding } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [verified, setVerified] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!primaryDomain) return null;

  const domain = primaryDomain.domain;
  const token = primaryDomain.verification_token || primaryDomain.id;
  const txtHost = `@ or _cyphward`;
  const txtName = `_cyphward.${domain}`;
  const txtValue = token.startsWith('cyphward-verification=') ? token : `cyphward-verification=${token}`;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(txtValue);
    setCopied(true);
    toast('TXT value copied to clipboard');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleVerify = async () => {
    if (busy) return;
    setBusy(true);
    setError('');

    const result = await verifyDomain();

    if (!result.ok || !result.verified) {
      setBusy(false);
      setError(result.error || 'Verification failed. Make sure the TXT record has been added and DNS has propagated.');
      return;
    }

    setBusy(false);
    setVerified(true);
    toast('Domain verified successfully!');

    setTimeout(() => {
      completeOnboarding();
      nav('/onboarding/complete', { replace: true });
    }, 1200);
  };

  const handleSkip = () => {
    completeOnboarding();
    nav('/onboarding/complete', { replace: true });
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
        <p className="text-xs text-soft text-center">Configuring sovereign perimeter…</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="font-display text-lg font-medium text-ink mb-1">
          Verify Domain Ownership
        </h3>
        <p className="text-xs text-soft">
          Add a DNS TXT record to prove you own <span className="text-ink font-medium">{domain}</span>.
        </p>
      </div>

      <div className="p-3 bg-inset rounded border border-line">
        <p className="text-[10px] mono text-soft mb-2">DNS RECORD TO ADD</p>
        <div className="space-y-2">
          <div>
            <p className="text-[10px] mono text-soft">TYPE</p>
            <p className="text-xs mono font-medium text-ink">TXT</p>
          </div>
          <div>
            <p className="text-[10px] mono text-soft">NAME</p>
            <p className="text-xs mono font-medium text-ink break-all">{txtName}</p>
          </div>
          <div>
            <p className="text-[10px] mono text-soft">VALUE</p>
            <div className="flex items-center gap-2">
              <p className="text-xs mono font-medium text-ink break-all flex-1">{txtValue}</p>
              <button
                type="button"
                onClick={handleCopy}
                className="flex-none p-1.5 rounded hover:bg-accent/10 transition-colors text-soft hover:text-ink"
                title="Copy value"
              >
                {copied ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="p-3 bg-accent/5 border border-accent/20 rounded text-xs text-soft">
        <p>
          Add this TXT record to your DNS settings. Propagation may take a few minutes.
          Once added, click "Verify Domain" to confirm ownership.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
          <AlertCircle size={14} className="flex-none mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <button
        type="button"
        onClick={handleVerify}
        disabled={busy}
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
          Skip for now
        </button>
      </div>
    </div>
  );
}
