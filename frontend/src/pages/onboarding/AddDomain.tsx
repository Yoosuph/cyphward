import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Globe, AlertCircle, Info } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';

/** Accept pasted URLs: drop scheme, path, port and a trailing dot. */
function cleanInput(value: string) {
  return value.trim().toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/[/?#].*$/, '')
    .replace(/:\d+$/, '')
    .replace(/\.$/, '');
}

export default function AddDomain() {
  const { addPrimaryDomain, organization, completeOnboarding } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [domain, setDomain] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !domain.trim()) return;
    setBusy(true);
    setError('');

    const cleanDomain = cleanInput(domain);

    const result = await addPrimaryDomain(cleanDomain);

    if (!result.ok) {
      setBusy(false);
      setError(result.error || 'Failed to add domain. Please try again.');
      return;
    }

    toast('Domain added.');
    nav('/onboarding/verify-domain', { replace: true });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <h3 className="font-display text-lg font-medium text-ink mb-1">
          Add your domain
        </h3>
        <p className="text-xs text-soft">
          Usually your main website, like example.com. Subdomains we discover, such as www or mail, are included in the scan.
        </p>
      </div>

      {organization && (
        <div className="p-3 bg-inset rounded border border-line">
          <p className="text-[10px] mono text-soft">ORGANIZATION</p>
          <p className="text-xs font-semibold text-ink">{organization.name}</p>
        </div>
      )}

      <div className="field">
        <label htmlFor="domain">DOMAIN</label>
        <input
          id="domain"
          type="text"
          placeholder="e.g. example.com"
          value={domain}
          onChange={e => setDomain(e.target.value)}
          required
          autoFocus
          autoCapitalize="none"
          spellCheck={false}
        />
        {cleanInput(domain).startsWith('www.') && cleanInput(domain).split('.').length > 2 && (
          <p className="text-xs text-soft mt-1.5">
            Most people mean the root domain.{' '}
            <button type="button" className="text-accent underline" onClick={() => setDomain(cleanInput(domain).slice(4))}>
              Use {cleanInput(domain).slice(4)} instead
            </button>
          </p>
        )}
      </div>

      <div className="p-3 bg-accent/5 border border-accent/20 rounded text-xs text-soft flex items-start gap-2">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>
          Next you'll add one DNS record to prove you own this domain. If someone else manages your DNS, you can copy the instructions for them.
        </span>
      </div>

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
          <AlertCircle size={14} className="flex-none mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={busy || !domain.trim()}
        className="btn btn-solid w-full justify-center"
      >
        {busy ? (
          <span>ADDING DOMAIN…</span>
        ) : (
          <>
            CONTINUE <ArrowRight size={14} />
          </>
        )}
      </button>
      <button
        type="button"
        onClick={() => { completeOnboarding(); nav('/overview', { replace: true }); }}
        className="w-full text-xs text-soft hover:text-ink"
      >
        Do this later · Open dashboard
      </button>
    </form>
  );
}
