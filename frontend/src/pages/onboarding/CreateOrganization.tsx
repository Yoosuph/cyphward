import { FormEvent, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, Building, AlertCircle } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { useToast } from '../../components/Toast';

const PLANS = [
  { id: 'starter', label: 'Starter', price: '₦7,000/mo', desc: 'One business, one domain' },
  { id: 'growth', label: 'Growth', price: '₦15,000/mo', desc: 'Teams, more domains and reports' },
];

function initialPlan(searchParams: URLSearchParams): string {
  const p = (searchParams.get('plan') || '').toLowerCase();
  return p === 'starter' || p === 'growth' ? p : 'growth';
}

export default function CreateOrganization() {
  const { createOrganization } = useAuth();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const toast = useToast();

  const [orgName, setOrgName] = useState('');
  const [plan, setPlan] = useState(() => initialPlan(searchParams));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !orgName.trim()) return;
    setBusy(true);
    setError('');

    const result = await createOrganization(orgName.trim(), plan);

    if (!result.ok) {
      setBusy(false);
      setError(result.error || 'Failed to create organization. Please try again.');
      return;
    }

    toast('Organization created successfully!');
    nav('/onboarding/add-domain', { replace: true });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <h3 className="font-display text-lg font-medium text-ink mb-1">
          Create Your Organization
        </h3>
        <p className="text-xs text-soft">
          Your organization's name is shown across your workspace.
        </p>
      </div>

      <div className="field">
        <label htmlFor="orgName">ORGANIZATION NAME</label>
        <input
          id="orgName"
          type="text"
          placeholder="e.g. Continental Merchant Bank"
          value={orgName}
          onChange={e => setOrgName(e.target.value)}
          required
          autoFocus
        />
      </div>

      <div className="space-y-2">
        <label className="text-xs mono text-soft">PLAN · 30-DAY TRIAL INCLUDED</label>
        <div className="grid grid-cols-2 gap-2">
          {PLANS.map(p => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPlan(p.id)}
              className={`p-3 rounded border text-left transition-all ${
                plan === p.id
                  ? 'border-accent bg-accent/5 ring-1 ring-accent'
                  : 'border-line bg-inset hover:border-line-strong'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`text-xs mono font-semibold ${plan === p.id ? 'text-accent' : 'text-ink'}`}>
                  {p.label}
                </span>
                {plan === p.id && <div className="w-2 h-2 rounded-full bg-accent" />}
              </div>
              <div className={`text-sm font-medium mt-1 ${plan === p.id ? 'text-accent' : 'text-ink'}`}>
                {p.price}
              </div>
              <p className="text-[10px] text-soft mt-1">{p.desc}</p>
            </button>
          ))}
        </div>
        <p className="text-[10px] text-soft">
          Need single sign-on, a private deployment, or a custom agreement?{' '}
          <a className="underline" href="mailto:info@cyphward.com">Talk to us</a> — enterprise
          onboarding is assisted, not self-serve.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
          <AlertCircle size={14} className="flex-none mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={busy || !orgName.trim()}
        className="btn btn-solid w-full justify-center"
      >
        {busy ? (
          <span>CREATING ORGANIZATION…</span>
        ) : (
          <>
            CONTINUE <ArrowRight size={14} />
          </>
        )}
      </button>
    </form>
  );
}
