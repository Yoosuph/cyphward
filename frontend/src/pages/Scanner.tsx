import PublicShell from '../components/PublicShell';

const USER_AGENT = 'Cyphward-Security-Scanner/1.0 (+https://cyphward.com/scanner)';

const CHECKS = [
  'Looks up public DNS records for the domain and its subdomains, including SPF and DMARC.',
  'Lists subdomains from public sources such as certificate transparency logs.',
  "Requests public web pages: each host's homepage and robots.txt, and for the privacy check up to ten public pages such as /privacy, /cookies and /.well-known/security.txt.",
  'Checks which of the 100 most common TCP ports accept a connection.',
  'Reads TLS certificates and connection settings.',
  'Runs read-only known-vulnerability checks (open-source Nuclei templates), rate-limited.',
];

const NEVER = [
  'No login attempts and no password guessing.',
  'No form submissions and no submitting credentials.',
  'No denial-of-service, stress or load testing.',
  'No fuzzing.',
];

export default function Scanner() {
  return (
    <PublicShell
      eyebrow="SCANNER"
      title={
        <>
          The Cyphward <em>scanner.</em>
        </>
      }
      lede="If you found this address in your logs, Cyphward's security scanner visited your site. Here is what it does, why, and how to reach us."
    >
      <div className="space-y-10 text-sm text-soft leading-relaxed">
        <section className="space-y-3 about-section" data-reveal>
          <p className="eyebrow">01 · WHO ASKED FOR IT</p>
          <h2 className="font-display text-2xl font-medium text-ink">Only domains their owners verified</h2>
          <p>
            Cyphward scans a domain only after its owner proves control of it by adding a DNS TXT record.
            Scans run when the owner starts one, and once a day at about 06:00 UTC.
          </p>
          <p>Results go only to that verified owner, in their private Cyphward workspace.</p>
        </section>

        <section className="space-y-3 about-section" data-reveal>
          <p className="eyebrow">· WHAT IT NEVER DOES</p>
          <h2 className="font-display text-2xl font-medium text-ink">Read-only, and gentle</h2>
          <ul className="list-disc pl-5 space-y-2">
            {NEVER.map(item => <li key={item}>{item}</li>)}
          </ul>
          <p>
            The known-vulnerability checks are limited to about 10 requests a second per host, run one
            at a time, and templates that would log in, submit a form, fuzz or stress a service are
            excluded from the set.
          </p>
        </section>

        <section className="space-y-3 about-section" data-reveal>
          <p className="eyebrow">02 · WHAT IT DOES</p>
          <h2 className="font-display text-2xl font-medium text-ink">What the scanner checks</h2>
          <ul className="list-disc pl-5 space-y-2">
            {CHECKS.map(item => <li key={item}>{item}</li>)}
          </ul>
        </section>

        <section className="space-y-3 about-section" data-reveal>
          <p className="eyebrow">03 · HOW TO RECOGNISE IT</p>
          <h2 className="font-display text-2xl font-medium text-ink">User-Agent</h2>
          <p>Every web request the scanner makes carries this User-Agent:</p>
          <p className="panel p-4 mono text-xs text-ink break-all" data-testid="scanner-user-agent">{USER_AGENT}</p>
          <p>
            Requests can come from more than one network: Cyphward's scanning servers and the Cyphward service
            itself. Port and TLS checks are network connections, so they carry no User-Agent.
          </p>
        </section>

        <section className="space-y-3 about-section" data-reveal>
          <p className="eyebrow">04 · CONTACT</p>
          <h2 className="font-display text-2xl font-medium text-ink">Something look wrong?</h2>
          <p>
            If the scanner visited a domain you own and you did not verify it with Cyphward, or the scans are
            causing you trouble, email{' '}
            <a href="mailto:security@cyphward.com" className="text-accent underline">security@cyphward.com</a>{' '}
            with your domain and the time you saw the requests. We will look into it and can stop scans of a
            domain while we do.
          </p>
        </section>
      </div>
    </PublicShell>
  );
}
