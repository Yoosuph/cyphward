import { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import LegalShell from '../components/LegalShell';

function Section({ n, heading, children }: { n: string; heading: string; children: ReactNode }) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <span className="eyebrow">{n}</span>
        <h2 className="text-base font-semibold text-ink tracking-wide">{heading}</h2>
      </div>
      <div className="space-y-3 text-sm text-soft leading-relaxed">{children}</div>
    </section>
  );
}

export default function Terms() {
  return (
    <LegalShell
      eyebrow="TERMS OF SERVICE"
      title={
        <>
          The rules of <em>the road.</em>
        </>
      }
      effective="1 October 2026"
    >
      <Section n="01" heading="Acceptance">
        <p>
          These Terms are an agreement between you (the person or company using the
          service) and CYPHWARD TECHNOLOGIES LTD (“Cyphward”, “we”). By creating an
          account or using cyphward.com, you agree to them and to our{' '}
          <Link to="/privacy" className="text-accent underline">Privacy Policy</Link>.
          If you use Cyphward for a company, you confirm you have authority to bind
          that company.
        </p>
      </Section>

      <Section n="02" heading="Your account">
        <ul className="space-y-1.5 pl-4 list-disc marker:text-accent">
          <li>Give us accurate information and keep your password secret.</li>
          <li>One login per person — don't share accounts.</li>
          <li>You are responsible for everything that happens under your account.</li>
          <li>Tell us promptly at <span className="text-ink mono">security@cyphward.com</span> if you suspect your account is compromised.</li>
        </ul>
        <p>
          You can sign in with email and password or with Google. If you use Google
          sign-in, Google's own terms also apply to that part of the login.
        </p>
      </Section>

      <Section n="03" heading="Only scan what you're allowed to scan">
        <p>
          Cyphward checks the security of websites and domains. By adding a domain you
          confirm that <span className="text-ink">you own it or have clear permission</span>{' '}
          from its owner to test it.
        </p>
        <p>
          Do not use Cyphward to scan, probe, or attack systems you don't have
          permission for. That would break these terms, our acceptable-use rules, and
          the law — including Nigeria's Cybercrimes Act and equivalent laws elsewhere.
          We may suspend accounts that violate this, and we may report deliberate
          misuse to the relevant authorities.
        </p>
      </Section>

      <Section n="04" heading="Acceptable use">
        <p>Don't use Cyphward to:</p>
        <ul className="space-y-1.5 pl-4 list-disc marker:text-accent">
          <li>break any law or third-party right</li>
          <li>send malware, phish, spam, or abuse our APIs or email</li>
          <li>try to bypass limits, protections, or access controls</li>
          <li>resell or white-label the service without a written agreement</li>
          <li>interfere with the service or other users</li>
        </ul>
      </Section>

      <Section n="05" heading="Your data stays yours">
        <p>
          You own everything you put into Cyphward — your domains, findings, notes, and
          reports. You give us only the permission needed to run the service (store it,
          process it, show it to your team). We handle it as described in the{' '}
          <Link to="/privacy" className="text-accent underline">Privacy Policy</Link>,
          and you can export or delete it by contacting us.
        </p>
      </Section>

      <Section n="06" heading="What our findings mean">
        <p>
          Cyphward reports what we can see from outside your systems, at the moment of
          the scan. It is an early-warning tool — <span className="text-ink">not a
          guarantee</span> that you are free of every vulnerability or that you will
          never suffer a breach. Findings can be incomplete or affected by timing, and
          automated checks can make mistakes. Act on the reports, but keep your own
          defences and professional advice too.
        </p>
        <p>
          Compliance scores reflect the rules we model at the time; regulators make the
          final call.
        </p>
      </Section>

      <Section n="07" heading="Plans and payment">
        <p>
          Some features are paid. Prices, seats, and limits are shown before you buy.
          Subscriptions renew automatically unless cancelled before the renewal date;
          fees already paid are non-refundable except where the law says otherwise. We
          give reasonable notice before changing prices.
        </p>
      </Section>

      <Section n="08" heading="Suspension and termination">
        <p>
          You can close your account any time (Settings, or email us). We may suspend
          or close an account that breaks these terms, poses a security risk, or
          endangers other users — we will tell you when we reasonably can. On
          termination, your access stops and we delete your data per the Privacy
          Policy.
        </p>
      </Section>

      <Section n="09" heading="The service “as is”">
        <p>
          We work hard to keep Cyphward reliable, but it is provided “as is” and
          “as available”. To the extent the law allows, we are not responsible for
          indirect or consequential losses, lost profits, or lost data arising from
          your use of the service. Our total liability is limited to what you paid us
          in the 12 months before the claim (or ₦100,000 if you are on a free plan).
          Nothing in these terms limits liability that cannot be limited by law,
          including for fraud or personal injury.
        </p>
      </Section>

      <Section n="10" heading="Changes to these terms">
        <p>
          If we make a material change, we will notify you (in the product or by
          email) at least 14 days before it takes effect. Continuing to use Cyphward
          after that means you accept the new terms. If you don't accept them, close
          your account before the change starts.
        </p>
      </Section>

      <Section n="11" heading="Law and disputes">
        <p>
          These terms are governed by the laws of the Federal Republic of Nigeria.
          Disputes go to the courts of Lagos State, unless mandatory consumer
          protections in your country say you may bring a claim where you live. Before
          suing, please email us — most issues are solved with a conversation.
        </p>
      </Section>

      <Section n="12" heading="Contact">
        <p>
          CYPHWARD TECHNOLOGIES LTD — <span className="text-ink mono">legal@cyphward.com</span>{' '}
          · security issues: <span className="text-ink mono">security@cyphward.com</span>
        </p>
        <p>
          See also our <Link to="/privacy" className="text-accent underline">Privacy Policy</Link>.
        </p>
      </Section>
    </LegalShell>
  );
}
