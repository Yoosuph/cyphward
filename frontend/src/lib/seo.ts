import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** Public identity — must stay in sync with <title> in index.html. */
export const SITE_TITLE = 'Cyphward — Attack Surface Protection for African Enterprises';

const TITLES: Record<string, string> = {
  '/': SITE_TITLE,
  '/login': 'Sign In — Cyphward',
  '/signup': 'Create Account — Cyphward',
  '/forgot-password': 'Forgot Password — Cyphward',
  '/reset-password': 'Reset Password — Cyphward',
  '/auth/callback': 'Signing In — Cyphward',
  '/terms': 'Terms of Service — Cyphward',
  '/privacy': 'Privacy Policy — Cyphward',
  '/pricing': 'Pricing — Cyphward',
  '/about': 'About — Cyphward',
  '/overview': 'Overview — Cyphward',
  '/assets': 'Assets — Cyphward',
  '/findings': 'Findings — Cyphward',
  '/scans': 'Scans — Cyphward',
  '/domains': 'Domains — Cyphward',
  '/remediation': 'Remediation — Cyphward',
  '/reports': 'Reports — Cyphward',
  '/settings': 'Settings — Cyphward',
  '/academy': 'Academy — Cyphward',
};

export function documentTitleFor(pathname: string): string {
  if (pathname.startsWith('/onboarding')) return 'Onboarding — Cyphward';
  return TITLES[pathname] ?? 'Cyphward';
}

/** Sets document.title on every route change. Mounted once inside the router. */
export function DocumentTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = documentTitleFor(pathname);
  }, [pathname]);
  return null;
}
