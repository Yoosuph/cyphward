import { Link } from 'react-router-dom';
import PublicShell from '../components/PublicShell';

const FACTS: { label: string; value: string; href?: string }[] = [
  { label: 'LEGAL NAME', value: 'Cyphward Ltd' },
  { label: 'BRAND', value: 'Cyphward' },
  { label: 'FOUNDER', value: 'Yusuf Lawan Nuhu' },
  { label: 'FOUNDED', value: '2026' },
  { label: 'COUNTRY', value: 'Nigeria' },
  { label: 'GENERAL', value: 'info@cyphward.com', href: 'mailto:info@cyphward.com' },
  { label: 'PRIVACY', value: 'privacy@cyphward.com', href: 'mailto:privacy@cyphward.com' },
  { label: 'LEGAL', value: 'legal@cyphward.com', href: 'mailto:legal@cyphward.com' },
  { label: 'SECURITY', value: 'security@cyphward.com', href: 'mailto:security@cyphward.com' },
];

const PROFILES = [
  { label: 'X', href: 'https://x.com/cyphward' },
  { label: 'INSTAGRAM', href: 'https://www.instagram.com/cyphward_/' },
  { label: 'LINKEDIN', href: 'https://www.linkedin.com/company/cyphward/' },
];

export default function About() {
  return (
    <PublicShell
      eyebrow="ABOUT"
      title={
        <>
          The company behind <em>the score.</em>
        </>
      }
      lede="Cyphward Ltd builds Cyphward, external security scoring for Nigerian businesses. You prove a domain is yours. We scan what the internet can already see. You get one 0–100 score, and a fix for every finding."
    >
      <div className="space-y-10 text-sm text-soft leading-relaxed">
        <section className="space-y-3">
          <h2 className="font-display text-2xl font-medium text-ink">What we scan</h2>
          <p>
            A scan covers SPF and DMARC, security headers, TLS certificates, open ports
            and known weaknesses on the sites you verify. Verified domains are checked
            again every day. The report is written so a founder or a board can read it
            without a security team translating it.
          </p>
          <p>
            Nothing is scanned until you prove the domain is yours, with a DNS TXT
            record. Cyphward is built with Nigeria’s Data Protection Act 2023 in mind.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-2xl font-medium text-ink">Who it is for</h2>
          <p>
            A Nigerian business that wants to know how it looks from the outside:
            a small company on the Starter plan, or a team on Growth that shares
            findings and reports. Plans are ₦7,000 and ₦15,000 a month.{' '}
            <Link to="/pricing" className="text-accent underline">See pricing</Link>.
          </p>
          <p>
            Yusuf Lawan Nuhu founded Cyphward Ltd in 2026. The product is in testing
            with real users, and it is being built with the iDICE Founders Lab, Cohort 2.
          </p>
        </section>

        <section>
          <h2 className="font-display text-2xl font-medium text-ink mb-4">Company details</h2>
          <dl className="panel p-6 md:p-8 grid sm:grid-cols-2 gap-x-8 gap-y-5">
            {FACTS.map(fact => (
              <div key={fact.label}>
                <dt className="eyebrow mb-1">{fact.label}</dt>
                <dd className="text-sm text-ink">
                  {fact.href ? (
                    <a className="mono hover:text-accent" href={fact.href}>{fact.value}</a>
                  ) : (
                    fact.value
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-2xl font-medium text-ink">Profiles</h2>
          <p>The same name, Cyphward, on each of these:</p>
          <ul className="flex flex-wrap gap-3">
            {PROFILES.map(profile => (
              <li key={profile.href}>
                <a
                  href={profile.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-ghost text-xs py-2 px-3"
                >
                  {profile.label}
                </a>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </PublicShell>
  );
}
