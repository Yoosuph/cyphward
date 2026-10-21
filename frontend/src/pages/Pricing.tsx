import { Link } from 'react-router-dom';
import { Check, ArrowRight } from 'lucide-react';
import PublicShell from '../components/PublicShell';
import { PUBLIC_PLANS } from '../lib/publicPlans';

const SHARED_CHECKS = [
  'You prove the domain is yours with a DNS TXT record before a scan starts',
  'Published SPF and DMARC policies; these checks do not establish mail delivery or prevent all impersonation',
  'Security headers, including HSTS, CSP and clickjacking protection',
  'TLS certificate health, open ports, and known-CVE template matches (matches reported; clean results not proven)',
  'Evidence-based scoring when coverage supports it, with partial and unassessed results clearly labelled',
  'Remediation guidance, supported rechecks, and automatic scheduling within your scan allowance',
];

export default function Pricing() {
  return (
    <PublicShell
      eyebrow="PRICING"
      wide
      title={
        <>
          Find weaknesses. <em>Build the evidence.</em>
        </>
      }
      lede="Starter is ₦15,000 and Growth is ₦25,000 per 30-day paid period. Start with a 30-day trial of your chosen plan. No card required; payment and continuation are arranged manually."
    >
      <div className="pricing-grid cols-2">
        {PUBLIC_PLANS.map(plan => (
          <article key={plan.id} className={`pricing-card ${plan.featured ? 'featured' : ''} rise-in ${plan.featured ? 'rise-in-4' : 'rise-in-3'}`}>
            <div className="flex justify-between items-center mb-6 gap-2">
              <span className="tag w-fit">{plan.name.toUpperCase()}</span>
              {plan.featured && <span className="tag acc text-[9px]">TEAM + COMPLIANCE</span>}
            </div>
            <h2 className="font-display text-3xl font-medium">{plan.name}</h2>
            <p className="text-xs mono text-soft mt-2 mb-6">{plan.blurb}</p>
            <p className="pricing-price">
              <span className="pricing-amount">{plan.priceLabel}</span>
              <span className="pricing-unit">/ 30 days</span>
            </p>
            <ul className="pricing-points">
              {plan.points.map(point => (
                <li key={point}>
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
            <Link to={`/signup?plan=${plan.id}`} className={`btn ${plan.featured ? 'btn-solid' : 'btn-ghost'} w-full justify-center`}>
              {plan.cta} <ArrowRight size={14} />
            </Link>
          </article>
        ))}
      </div>

      <p className="text-xs mono text-soft mt-6 text-center">
        Both plans use the external scanner. Growth adds team capacity and the fuller Compliance workflow.
        Requirement references remain pending professional review; packs support preparation rather than certification.
      </p>

      <section className="mt-14" data-reveal>
        <p className="eyebrow mb-3">ON EVERY PLAN</p>
        <h2 className="font-display text-2xl font-medium mb-5">What a scan actually covers.</h2>
        <ul className="panel shared-checks p-6 md:p-8 text-sm text-soft">
          {SHARED_CHECKS.map((item, index) => (
            <li key={item}>
              <span className="shared-index">0{index + 1}</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-14 panel p-6 md:p-8" data-reveal>
        <p className="eyebrow mb-3">SCOPE AND ALLOWANCES</p>
        <h2 className="font-display text-2xl font-medium mb-3">Know what is included.</h2>
        <div className="space-y-3 text-sm text-soft leading-relaxed">
          <p>Scheduled and manually launched assessments share the monthly scan allowance across your domains. Queued and failed jobs count too. Allowances reset on the first day of each calendar month in UTC; paid periods last 30 days. Daily scheduling can pause when you reach the allowance.</p>
          <p>Reports, assessment snapshots and evidence packs use the shared report/evidence allowance according to the action shown in the app. Domain count is not a promise of unlimited discovered hosts or checks: each assessment records its caps, omissions and coverage.</p>
          <p>Plans include product support. Guided onboarding, hands-on remediation, legal review and audit filing require an agreed scope and separate quote. Cyphward does not replace your mail provider, security adviser or licensed DPCO.</p>
        </div>
      </section>

      <section className="mt-14 panel p-6 md:p-8" data-reveal>
        <p className="eyebrow mb-3">PAYMENT</p>
        <h2 className="font-display text-2xl font-medium mb-3">Try it first. Agree continuation with us.</h2>
        <p className="text-sm text-soft leading-relaxed">
          Your trial starts when you create the workspace and lasts 30 days, with the chosen plan's limits.
          There is no automatic charge or automatic paid renewal. After the trial, new scans and report generation pause until payment or an explicit trial extension is confirmed.
          An open invoice is not payment confirmation. Use{' '}
          <Link to="/contact" className="text-accent underline">Contact</Link> to arrange payment, renewal or a plan change.
          Fees already paid follow the{' '}
          <Link to="/terms" className="text-accent underline">Terms of Service</Link>.
        </p>
      </section>
    </PublicShell>
  );
}
