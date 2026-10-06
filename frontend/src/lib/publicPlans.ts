/** Public prices shown on the marketing site. Kept in one place so the
 * homepage and /pricing cannot drift. These are not the in-app billing ledger. */
export type PublicPlan = {
  id: 'starter' | 'growth';
  name: string;
  priceLabel: string;
  blurb: string;
  points: string[];
  featured?: boolean;
  cta: string;
};

export const PUBLIC_PLANS: PublicPlan[] = [
  {
    id: 'starter',
    name: 'Starter',
    priceLabel: '₦7,000',
    blurb: 'For one business that wants a clear external score.',
    points: [
      'Verify your domain with a DNS record before any scan',
      'SPF, DMARC, security headers, TLS and exposure checks',
      'A 0–100 score and a written fix for every finding',
      'Daily rescan of domains you have verified',
    ],
    cta: 'START WITH STARTER',
  },
  {
    id: 'growth',
    name: 'Growth',
    priceLabel: '₦15,000',
    blurb: 'For a team that shares findings, fixes and reports.',
    featured: true,
    points: [
      'Everything in Starter',
      'Invite teammates by email and set their roles',
      'Turn a finding into a task, then recheck the live host',
      'Print-ready reports for a founder or a board',
    ],
    cta: 'START WITH GROWTH',
  },
];
