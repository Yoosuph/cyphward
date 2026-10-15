import { MailCheck, Building, Globe, Radar, ShieldCheck, FileText, Wrench } from 'lucide-react';

/**
 * Left column of the sign-up and sign-in screens. Everything here must be
 * true of the product today: no testimonials, live metrics or certification
 * badges until there is real evidence behind them.
 */
const SIGNUP_STEPS = [
  { icon: MailCheck, title: 'Confirm your email', body: 'We send a 6-digit code to the address you sign up with.' },
  { icon: Building, title: 'Name your workspace', body: '30-day trial on Starter or Growth. No card needed to start.' },
  { icon: Globe, title: 'Add and verify your domain', body: 'One DNS TXT record proves you own it. Nothing is scanned before that.' },
  { icon: Radar, title: 'Run your first scan', body: 'Results usually arrive within 30–45 minutes, then rescans run daily.' },
];

const CHECKS = [
  { icon: ShieldCheck, title: 'Email authentication', body: 'SPF and DMARC on your domain.' },
  { icon: Globe, title: 'Web exposure', body: 'Security headers, TLS certificates and open ports on each public host.' },
  { icon: FileText, title: 'One clear score', body: 'A 0–100 score within the checks we declare, with history across scans.' },
  { icon: Wrench, title: 'A fix for every finding', body: 'Plain-English steps, and a recheck to confirm the fix.' },
];

const FACTS = ['Scans only domains you verify', 'Built in Kano, Nigeria', 'Plain-English fixes'];

export default function AuthSidePanel({ mode }: { mode: 'signup' | 'login' }) {
  const signup = mode === 'signup';
  const items = signup ? SIGNUP_STEPS : CHECKS;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="display-h">
          {signup ? <>See your business the way <em>the internet does.</em></> : <>Welcome <em>back.</em></>}
        </h1>
        <p className="login-sub">
          {signup
            ? 'Create an account, verify a domain you own, and get a 0–100 score with a written fix for every finding.'
            : 'Sign in to see your latest score, open findings and the fixes your team is working on.'}
        </p>
      </div>

      <div className="login-telemetry-panel">
        <p className="eyebrow text-[10px] tracking-widest pb-3 mb-4 border-b border-line">
          {signup ? 'WHAT HAPPENS NEXT' : 'WHAT CYPHWARD CHECKS'}
        </p>
        <ol className="flex flex-col gap-3.5">
          {items.map((item, index) => {
            const Icon = item.icon;
            return (
              <li key={item.title} className="flex items-start gap-3">
                <span className="flex-none w-7 h-7 rounded-full border border-line-strong bg-raised grid place-items-center text-accent">
                  {signup ? <span className="mono text-[11px] font-semibold">{index + 1}</span> : <Icon size={13} />}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-ink leading-snug">{item.title}</p>
                  <p className="text-xs text-soft leading-relaxed mt-0.5">{item.body}</p>
                </div>
              </li>
            );
          })}
        </ol>
        {!signup && (
          <p className="text-[11px] text-soft leading-relaxed mt-4 pt-4 border-t border-line">
            Known-CVE templates report matches; a clean run is not proof that nothing is there.
          </p>
        )}
        <div className="auth-trust-strip mt-4">
          {FACTS.map(fact => (
            <span key={fact} className="auth-trust-item">
              <ShieldCheck size={12} className="text-accent" /> {fact.toUpperCase()}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
