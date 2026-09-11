import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ShieldCheck, Lock, Globe, KeyRound } from 'lucide-react';
import { login } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';

const ENTERPRISE_DOMAINS: Record<string, { idp: string; tenant: string; icon: string }> = {
  'acmetraders.ng': { idp: 'Okta Enterprise', tenant: 'Acme Traders Ltd (Kano)', icon: 'okta' },
  'switch.lagos': { idp: 'Microsoft Entra ID', tenant: 'Lagos Core Switch Ltd', icon: 'entra' },
  'panbank.africa': { idp: 'Ping Identity SAML', tenant: 'PanBank Africa (Johannesburg)', icon: 'ping' },
  'fintech.ke': { idp: 'Google Cloud Identity', tenant: 'Nairobi Mobile Pay', icon: 'google' },
};

export default function SSO() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [domain, setDomain] = useState('');
  const [busy, setBusy] = useState(false);
  const [detected, setDetected] = useState<typeof ENTERPRISE_DOMAINS[string] | null>(null);

  const handleDomainChange = (val: string) => {
    setDomain(val);
    const cleaned = val.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0];
    if (ENTERPRISE_DOMAINS[cleaned]) {
      setDetected(ENTERPRISE_DOMAINS[cleaned]);
    } else {
      setDetected(null);
    }
  };

  const handleSsoSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);

    const match = detected ?? {
      idp: 'Enterprise SAML 2.0 / OIDC',
      tenant: domain ? `Enterprise (${domain})` : 'Acme Traders Ltd (Kano)',
      icon: 'saml',
    };

    toast(`Connecting to ${match.idp} identity provider…`);

    setTimeout(async () => {
      const t = await login(`sso-user@${domain || 'acmetraders.ng'}`, 'sso');
      signIn({
        name: match.tenant,
        plan: 'Sovereign',
        region: 'ng-lagos',
        email: `sso-user@${domain || 'acmetraders.ng'}`,
      });
      toast(`Federated session authenticated via ${match.idp}.`);
      nav('/', { replace: true });
    }, 900);
  };

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-xl mx-auto my-auto px-4">
        <div className="flex items-center justify-between mb-4">
          <p className="eyebrow flex items-center gap-2">
            <span className="live-dot" /> CYPHWARD — ENTERPRISE SSO ENCLAVE
          </p>
          <Link to="/login" className="stat-link text-xs">
            CREDENTIAL LOGIN →
          </Link>
        </div>

        <h1 className="display-h">
          Federated single <em>sign-on portal.</em>
        </h1>
        <p className="login-sub">
          Enterprise identity provider routing. Enter your corporate email domain to route
          to your dedicated SAML 2.0 / OIDC authentication gateway.
        </p>

        <div className="auth-card panel mt-6">
          <form onSubmit={handleSsoSubmit}>
            <div className="field">
              <label htmlFor="domainInput">CORPORATE IDENTITY DOMAIN</label>
              <div className="relative">
                <input
                  id="domainInput"
                  type="text"
                  placeholder="e.g. acmetraders.ng or switch.lagos"
                  value={domain}
                  onChange={e => handleDomainChange(e.target.value)}
                  required
                />
              </div>
            </div>

            {detected && (
              <div className="p-3 my-3 bg-inset border border-accent/40 rounded text-xs mono flex items-center justify-between animate-fadeIn">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={16} className="text-accent" />
                  <span>IDENTIFIED: <strong>{detected.idp}</strong></span>
                </div>
                <span className="tag text-[9px]">ENCLAVE READY</span>
              </div>
            )}

            <div className="my-4">
              <p className="eyebrow text-[10px] mb-2">QUICK TEST CORPORATE DOMAINS</p>
              <div className="flex flex-wrap gap-2">
                {Object.keys(ENTERPRISE_DOMAINS).map(d => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => handleDomainChange(d)}
                    className="chip text-[10px] py-1 px-2.5"
                  >
                    <Globe size={11} className="mr-1 text-soft inline" /> {d}
                  </button>
                ))}
              </div>
            </div>

            <button className="btn btn-solid w-full justify-center mt-4" type="submit" disabled={busy}>
              {busy ? (
                'FEDERATING IDENTITY PROVIDER…'
              ) : (
                <>CONTINUE TO IDENTITY PROVIDER <ArrowRight size={14} /></>
              )}
            </button>

            <div className="mt-4 pt-3 border-t border-line text-center">
              <span className="text-xs mono text-soft">
                Looking for standard passphrase login?{' '}
                <Link to="/login" className="text-accent underline font-medium ml-1">
                  Back to Sign In
                </Link>
              </span>
            </div>
          </form>
        </div>

        <dl className="meta-row mt-6">
          <div><dt>SAML VERSION</dt><dd>SAML 2.0 / WS-FED</dd></div>
          <div><dt>OIDC SPEC</dt><dd>CORE 1.0 CERTIFIED</dd></div>
          <div><dt>MFA REQUIREMENT</dt><dd>FIDO2 / WEBAUTHN</dd></div>
        </dl>
      </div>
    </div>
  );
}
