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
    priceLabel: '₦15,000',
    blurb: 'For one domain and one person working through external security findings.',
    points: [
      '1 domain · 1 member · 30 scans per calendar month',
      'DNS, email authentication, web headers, TLS and exposure checks',
      'Findings, remediation guidance and supported rechecks',
      '30 report/evidence units per calendar month',
      'Limited Compliance view: readiness counts and security measures',
    ],
    cta: 'TRY STARTER FOR 30 DAYS',
  },
  {
    id: 'growth',
    name: 'Growth',
    priceLabel: '₦25,000',
    blurb: 'For teams preparing security and Nigerian data-protection evidence.',
    featured: true,
    points: [
      'Everything in Starter',
      'Up to 10 domains · 25 members · 300 scans per calendar month',
      '300 report/evidence units per calendar month',
      'Compliance questionnaires, evidence owners and expiry reminders',
      'Incident records, document drafts and approval history',
      'Dated evidence packs and customer-granted reviewer access',
    ],
    cta: 'TRY GROWTH FOR 30 DAYS',
  },
];
