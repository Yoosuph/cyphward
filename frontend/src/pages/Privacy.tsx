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

export default function Privacy() {
  return (
    <LegalShell
      eyebrow="PRIVACY POLICY"
      title={
        <>
          How we handle <em>your data.</em>
        </>
      }
      effective="1 October 2026"
    >
      <Section n="01" heading="Who we are">
        <p>
          CYPHWARD LTD (“Cyphward”, “we”, “us”) runs the Cyphward security
          platform at cyphward.com. This policy explains what we collect, why, and what
          you can ask us to do about it. It follows Nigeria's Data Protection Act
          (NDPA 2023) and comparable rules in the countries where we operate.
        </p>
        <p>
          Questions? Email <span className="text-ink mono">privacy@cyphward.com</span> —
          a real person replies.
        </p>
      </Section>

      <Section n="02" heading="What we collect">
        <p><span className="text-ink">Account details:</span> your name, work email, and an encrypted (hashed) version of your password. We never see or store your password in plain text.</p>
        <p><span className="text-ink">What you point us at:</span> the domains and websites you add, and everything our scans discover about them — open ports, TLS certificates, DNS records, headers, and security findings.</p>
        <p><span className="text-ink">How you use the product:</span> sign-in times, pages visited, and actions like starting a scan — used to keep your account secure and to fix bugs.</p>
        <p><span className="text-ink">Payment details:</span> handled by our payment provider; we only keep billing status and receipts.</p>
      </Section>

      <Section n="03" heading="Signing in with Google">
        <p>
          If you choose “Continue with Google”, we receive your Google account ID, name,
          and email address. We use them for one thing only: to sign you in and keep
          your account matched to the right email address.
        </p>
        <p>
          We do not use your Google data for advertising, and we do not sell it or share
          it with anyone else. This follows Google's Limited Use rules and the Google
          API Services User Data Policy, including the Limited Use requirements.
        </p>
        <p>
          You can disconnect Google sign-in at any time by setting a password and
          signing out, or by removing the app from your Google account's
          “Third-party access” page.
        </p>
      </Section>

      <Section n="04" heading="Emails we send">
        <p>
          All product email — welcome notes, email verification codes, password reset
          links, scan reports — is sent through <span className="text-ink">Brevo</span>,
          our email provider. Brevo processes your name, email address, and the message
          content solely to deliver it on our behalf. We never rent or sell mailing
          lists, and we don't send marketing email unless you opt in.
        </p>
      </Section>

      <Section n="05" heading="Who else touches your data">
        <p>We use a small set of processors to run the platform:</p>
        <ul className="space-y-1.5 pl-4 list-disc marker:text-accent">
          <li><span className="text-ink">Supabase</span> — hosts our database (your account and scan data)</li>
          <li><span className="text-ink">Brevo</span> — sends transactional email</li>
          <li><span className="text-ink">Google</span> — optional sign-in only</li>
          <li><span className="text-ink">Cloud AI providers</span> — when you ask CyphBot or an “explain finding” action to summarise a finding, the relevant finding text is processed to generate that answer</li>
          <li><span className="text-ink">Hosting &amp; CDN</span> — serves the app and blocks abuse</li>
        </ul>
        <p>
          Each processor is bound by contract to use your data only for our
          instructions. We do not sell your personal data. If a regulator in another
          country requires it, we may disclose data we are legally compelled to hand
          over — never otherwise.
        </p>
      </Section>

      <Section n="06" heading="How long we keep it">
        <p>
          We keep account data while your account is open. Scan history and findings
          stay while the account is active so your reports remain complete.
        </p>
        <p>
          Workspace owners can self-serve most of this in Settings: download a full
          JSON export of the workspace, or close the workspace, which deletes its
          members, domains, assets, findings, scans and reports at once (a tamper-proof
          closure record is kept). Ask us to delete your account and we remove your
          profile, domains, and scan
          data within <span className="text-ink">30 days</span>, keeping only the
          minimum records the law requires (for example, billing invoices).
          Password reset links expire after 30 minutes and work once.
        </p>
      </Section>

      <Section n="07" heading="Security">
        <p>
          Passwords are stored with argon2id (one-way). Sessions are signed JWTs with
          rotating refresh tokens you can revoke. Traffic is encrypted in transit
          (HTTPS). Access inside the company is limited to the people who need it to
          run the service, and org data is isolated per tenant with role checks on
          every request.
        </p>
        <p>
          If we ever learn of a breach that affects your personal data, we will tell
          you and the relevant regulator as the law requires.
        </p>
      </Section>

      <Section n="08" heading="Your rights">
        <p>
          Under the NDPA 2023 (and similar laws) you can ask us to:
        </p>
        <ul className="space-y-1.5 pl-4 list-disc marker:text-accent">
          <li>give you a copy of the personal data we hold about you</li>
          <li>correct anything that is wrong</li>
          <li>delete your data (“right to be forgotten”)</li>
          <li>stop or restrict how we use it</li>
          <li>hand your data to another provider in a portable format</li>
        </ul>
        <p>
          Email <span className="text-ink mono">privacy@cyphward.com</span>. We respond
          within the time the law allows (and aim for 7 days). You may also complain to
          your national data protection authority — in Nigeria, the NDPC.
        </p>
      </Section>

      <Section n="09" heading="Cookies and local storage">
        <p>
          We don't run advertising trackers. We use essential browser storage only:
          to stay signed in, remember your theme (light/dark), and keep your
          workspace preferences on your device.
        </p>
      </Section>

      <Section n="10" heading="Children">
        <p>
          Cyphward is built for businesses. It is not directed at children under 16,
          and we do not knowingly collect their data.
        </p>
      </Section>

      <Section n="11" heading="Changes to this policy">
        <p>
          When we make a material change, we will update the date at the top and, for
          significant changes, notify you by email or in the product before the change
          takes effect.
        </p>
      </Section>

      <Section n="12" heading="Contact">
        <p>
          CYPHWARD LTD — Data protection questions:{' '}
          <span className="text-ink mono">privacy@cyphward.com</span>
        </p>
        <p>
          See also our <Link to="/terms" className="text-accent underline">Terms of Service</Link>.
        </p>
      </Section>
    </LegalShell>
  );
}
