import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ShieldCheck, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';

const JURISDICTIONS = [
  { code: 'NG', name: 'Nigeria (Lagos / Kano / Abuja)', flag: '🇳🇬', defaultFramework: 'NDPA 2023' },
  { code: 'KE', name: 'Kenya (Nairobi)', flag: '🇰🇪', defaultFramework: 'Kenya DPA 2019' },
  { code: 'ZA', name: 'South Africa (Johannesburg / Cape Town)', flag: '🇿🇦', defaultFramework: 'PoPIA 2013' },
  { code: 'GH', name: 'Ghana (Accra)', flag: '🇬🇭', defaultFramework: 'Ghana DPA 2012' },
  { code: 'EG', name: 'Egypt (Cairo)', flag: '🇪🇬', defaultFramework: 'Egypt Law 151' },
  { code: 'RW', name: 'Rwanda (Kigali)', flag: '🇷🇼', defaultFramework: 'Law No. 058/2021' },
];

const FRAMEWORKS = [
  'NDPA 2023 (Nigeria Data Protection Act)',
  'CBN Cybersecurity Guidelines for OFIs & DMBs',
  'Kenya Data Protection Act 2019',
  'PoPIA (Protection of Personal Information Act)',
  'ISO/IEC 27001:2022',
  'PCI-DSS v4.0 (African Payment Rail Extension)',
];

export default function Register() {
  const { signIn } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const [step, setStep] = useState<'form' | 'provisioning' | 'done'>('form');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [org, setOrg] = useState('');
  const [jurisdiction, setJurisdiction] = useState('NG');
  const [framework, setFramework] = useState(FRAMEWORKS[0]);
  const [plan, setPlan] = useState<'Growth' | 'Scale' | 'Sovereign'>('Scale');
  const [provisionProgress, setProvisionProgress] = useState(0);
  const [provisionStatus, setProvisionStatus] = useState('Initializing isolated tenant enclave…');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setStep('provisioning');

    const steps = [
      { p: 25, msg: 'Provisioning isolated African data enclave (Lagos AWS Local Zone)…' },
      { p: 55, msg: 'Calibrating NDPA 2023 & CBN telemetry compliance baseline…' },
      { p: 85, msg: 'Deploying USSD & SIM-swap threat vector detectors…' },
      { p: 100, msg: 'Generating 256-bit tenant master cryptographic certificates…' },
    ];

    let current = 0;
    const iv = setInterval(() => {
      if (current < steps.length) {
        setProvisionProgress(steps[current].p);
        setProvisionStatus(steps[current].msg);
        current++;
      } else {
        clearInterval(iv);
        const newTenant = {
          name: org || 'Acme African Conglomerate',
          plan,
          region: jurisdiction.toLowerCase(),
          email: email || 'ciso@enterprise.af',
        };
        signIn(newTenant);
        toast(`Tenant initialized: ${newTenant.name} (${plan} Plan)`);
        setStep('done');
        setTimeout(() => {
          nav('/', { replace: true });
        }, 1000);
      }
    }, 550);
  };

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-xl mx-auto my-auto px-4">
        <div className="flex items-center justify-between mb-4">
          <p className="eyebrow flex items-center gap-2">
            <span className="live-dot" /> CYPHWARD — PROVISIONING ENCLAVE
          </p>
          <Link to="/login" className="stat-link text-xs">
            EXISTING TENANT LOGIN →
          </Link>
        </div>

        <h1 className="display-h">
          Deploy sovereign <em>cyber defense.</em>
        </h1>
        <p className="login-sub">
          Spin up an isolated sovereign security enclave with localized African threat intelligence,
          compliance mapping, and frontline academy training in minutes.
        </p>

        <div className="auth-card panel mt-6">
          {step === 'form' && (
            <form onSubmit={handleSubmit}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="field">
                  <label htmlFor="fullName">SECURITY LEAD NAME</label>
                  <input
                    id="fullName"
                    type="text"
                    placeholder="e.g. Ibrahim Abubakar"
                    value={name}
                    onChange={e => setName(e.target.value)}
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor="regEmail">WORK ENCLAVE EMAIL</label>
                  <input
                    id="regEmail"
                    type="email"
                    placeholder="ciso@organization.africa"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="field mt-4">
                <label htmlFor="orgName">ORGANIZATION / INSTITUTION NAME</label>
                <input
                  id="orgName"
                  type="text"
                  placeholder="e.g. Continental Merchant Bank"
                  value={org}
                  onChange={e => setOrg(e.target.value)}
                  required
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                <div className="field">
                  <label htmlFor="jurisdiction">PRIMARY JURISDICTION</label>
                  <select
                    id="jurisdiction"
                    value={jurisdiction}
                    onChange={e => {
                      setJurisdiction(e.target.value);
                      const match = JURISDICTIONS.find(j => j.code === e.target.value);
                      if (match) setFramework(match.defaultFramework);
                    }}
                  >
                    {JURISDICTIONS.map(j => (
                      <option key={j.code} value={j.code}>
                        {j.flag} {j.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="tierPlan">ENCLAVE DEPLOYMENT TIER</label>
                  <select
                    id="tierPlan"
                    value={plan}
                    onChange={e => setPlan(e.target.value as any)}
                  >
                    <option value="Growth">Growth (SaaS Enclave)</option>
                    <option value="Scale">Scale (High-Velocity Multi-Switch)</option>
                    <option value="Sovereign">Sovereign (Air-Gapped / Private Cloud)</option>
                  </select>
                </div>
              </div>

              <div className="field mt-4">
                <label htmlFor="framework">PRIMARY REGULATORY BASELINE</label>
                <select
                  id="framework"
                  value={framework}
                  onChange={e => setFramework(e.target.value)}
                >
                  {FRAMEWORKS.map(f => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>

              <div className="p-3 my-4 bg-inset border border-line rounded text-xs mono text-soft flex items-start gap-2.5">
                <ShieldCheck size={16} className="text-accent flex-none mt-0.5" />
                <span>
                  All telemetry is cryptographically isolated and guaranteed 100% in-region data residency
                  under NDPA Section 41 and the African Union Malabo Convention.
                </span>
              </div>

              <button className="btn btn-solid" type="submit">
                PROVISION DEDICATED TENANT <ArrowRight size={14} />
              </button>

              <div className="mt-4 pt-3 border-t border-line text-center">
                <span className="text-xs mono text-soft">
                  Already have access credentials?{' '}
                  <Link to="/login" className="text-accent underline font-medium ml-1">
                    Sign in here
                  </Link>
                </span>
              </div>
            </form>
          )}

          {step === 'provisioning' && (
            <div className="py-8 text-center">
              <div className="inline-block p-4 rounded-full bg-inset border border-line mb-4 animate-pulse">
                <ShieldCheck size={36} className="text-accent" />
              </div>
              <h3 className="font-display text-xl font-medium mb-2">
                Deploying Enclave Infrastructure…
              </h3>
              <p className="text-xs mono text-soft mb-6 max-w-sm mx-auto">
                {provisionStatus}
              </p>

              <div className="w-full bg-line h-2 rounded-full overflow-hidden max-w-md mx-auto">
                <div
                  className="h-full bg-accent transition-all duration-300 ease-out"
                  style={{ width: `${provisionProgress}%` }}
                />
              </div>

              <div className="flex justify-between items-center text-[10px] mono text-soft mt-3 max-w-md mx-auto">
                <span>LATENCY: 14MS</span>
                <span className="text-accent font-medium">{provisionProgress}%</span>
                <span>ZONE: AF-SOUTH-1</span>
              </div>
            </div>
          )}

          {step === 'done' && (
            <div className="py-8 text-center">
              <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30 mb-4">
                <CheckCircle2 size={36} />
              </div>
              <h3 className="font-display text-2xl font-medium mb-2">
                Enclave Successfully Initialized
              </h3>
              <p className="text-xs mono text-soft mb-4">
                Routing you to your new sovereign Command Center…
              </p>
              <div className="loading-line">LAUNCHING CONSOLE</div>
            </div>
          )}
        </div>

        <dl className="meta-row mt-6">
          <div><dt>STANDARDS</dt><dd>NDPA · CBN · ISO 27001</dd></div>
          <div><dt>PROVISION TIME</dt><dd>&lt; 45 SECONDS</dd></div>
          <div><dt>SOVEREIGNTY</dt><dd>100% AIR-GAPPABLE</dd></div>
        </dl>
      </div>
    </div>
  );
}
