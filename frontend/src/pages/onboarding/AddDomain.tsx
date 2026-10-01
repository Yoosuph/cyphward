import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Globe, AlertCircle, Info } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';

export default function AddDomain() {
  const { addPrimaryDomain, organization } = useAuth();
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

    // Clean domain input
    let cleanDomain = domain.trim().toLowerCase();
    cleanDomain = cleanDomain.replace(/^https?:\/\//, '').replace(/\/.*$/, '');

    const result = await addPrimaryDomain(cleanDomain);

    if (!result.ok) {
      setBusy(false);
      setError(result.error || 'Failed to add domain. Please try again.');
      return;
    }

    toast('Domain added successfully!');
    nav('/onboarding/verify-domain', { replace: true });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <h3 className="font-display text-lg font-medium text-ink mb-1">
          Add Your Primary Domain
        </h3>
        <p className="text-xs text-soft">
          Add the domain you want to monitor for security threats and compliance.
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
        />
      </div>

      <div className="p-3 bg-accent/5 border border-accent/20 rounded text-xs text-soft flex items-start gap-2">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>
          You can add more domains later. This one will be used for your first security scan.
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
    </form>
  );
}
