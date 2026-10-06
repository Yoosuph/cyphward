import { Link } from 'react-router-dom';
import { Check, ArrowRight } from 'lucide-react';
import PublicShell from '../components/PublicShell';
import { PUBLIC_PLANS } from '../lib/publicPlans';

const SHARED_CHECKS = [
  'You prove the domain is yours with a DNS TXT record before a scan starts',
  'SPF and DMARC, so a spoofer cannot quietly send mail as you',
  'Security headers, including HSTS, CSP and clickjacking protection',
  'TLS certificate health, open ports, and known web vulnerabilities',
  'One 0–100 score across network, web apps, encryption and exposure',
  'A written fix for every finding, and a daily rescan after you verify',
];

export default function Pricing() {
  return (
    <PublicShell
      eyebrow="PRICING"
      wide
      title={
        <>
          Two plans. <em>Same checks.</em>
        </>
      }
      lede="Starter is ₦7,000 a month. Growth is ₦15,000 a month. Prices are in Nigerian naira. Both plans scan domains you verify and return one score your team can act on."
    >
      <div className="pricing-grid cols-2">
        {PUBLIC_PLANS.map(plan => (
          <article key={plan.id} className={`pricing-card ${plan.featured ? 'featured' : ''}`}>
            <div className="flex justify-between items-center mb-3 gap-2">
              <span className="tag w-fit">{plan.name.toUpperCase()}</span>
              {plan.featured && <span className="tag acc text-[9px]">FOR TEAMS</span>}
            </div>
            <h2 className="font-display text-2xl font-medium mb-1">{plan.name}</h2>
            <p className="text-xs mono text-soft mb-4">{plan.blurb}</p>
            <p className="font-display text-3xl font-medium my-2">
              {plan.priceLabel} <span className="text-xs font-mono text-soft">/ month</span>
            </p>
            <ul className="space-y-2.5 my-6 text-xs mono text-soft flex-1">
              {plan.points.map(point => (
                <li key={point} className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
            <Link to="/signup" className={`btn ${plan.featured ? 'btn-solid' : 'btn-ghost'} w-full justify-center`}>
              {plan.cta} <ArrowRight size={14} />
            </Link>
          </article>
        ))}
      </div>

      <p className="text-xs mono text-soft mt-6 text-center">
        The checks are the same on both plans. Growth is the plan when more than one person works the fixes.
      </p>

      <section className="mt-14">
        <p className="eyebrow mb-3">ON EVERY PLAN</p>
        <h2 className="font-display text-2xl font-medium mb-5">What a scan actually covers.</h2>
        <ul className="panel p-6 md:p-8 space-y-3 text-sm text-soft">
          {SHARED_CHECKS.map(item => (
            <li key={item} className="flex items-start gap-2.5">
              <Check size={14} className="text-ok flex-none mt-1" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-14 panel p-6 md:p-8">
        <p className="eyebrow mb-3">PAYMENT</p>
        <h2 className="font-display text-2xl font-medium mb-3">Monthly, until you cancel.</h2>
        <p className="text-sm text-soft leading-relaxed">
          A plan renews each month until you cancel it. Close an account from Settings, or email{' '}
          <a className="text-ink mono" href="mailto:legal@cyphward.com">legal@cyphward.com</a>.
          Fees already paid follow the{' '}
          <Link to="/terms" className="text-accent underline">Terms of Service</Link>.
        </p>
      </section>
    </PublicShell>
  );
}
