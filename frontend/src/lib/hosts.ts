/**
 * Host-aware routing for the split-domain layout:
 *
 *   cyphward.com      → marketing (/, /privacy, /terms) only
 *   auth.cyphward.com → login / signup / password flows
 *   app.cyphward.com  → authenticated product
 *
 * Cold loads are redirected by vercel.json before any HTML is served; this
 * module backs the React-side guard that catches client-side <Link>
 * navigations (server redirects never see those). Localhost and *.vercel.app
 * previews keep the original single-origin behaviour.
 */

const AUTH_PATHS = new Set([
  '/login',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/auth/callback',
]);

const APP_PATHS = new Set([
  '/overview',
  '/assets',
  '/findings',
  '/scans',
  '/domains',
  '/remediation',
  '/reports',
  '/settings',
  '/analytics',
  '/comply',
  '/dashboard',
  '/copilot',
  '/detect',
  '/score',
  '/academy',
  '/sso',
]);

/** Query param that carries the idle-logout explanation across origins. */
export const IDLE_NOTICE_PARAM = 'notice';

function isMarketingPath(pathname: string): boolean {
  return (
    pathname === '/' ||
    pathname === '/terms' ||
    pathname === '/privacy' ||
    pathname === '/landing'
  );
}

/**
 * Returns the absolute URL the current path must move to for the current
 * host to be correct, or null when the page is already where it belongs.
 */
export function hostTarget(pathname: string): string | null {
  const host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1') return null;

  const onApex = host === 'cyphward.com' || host === 'www.cyphward.com';
  const onAuth = host === 'auth.cyphward.com';
  const onApp = host === 'app.cyphward.com';

  if (onApex) {
    if (AUTH_PATHS.has(pathname)) return `https://auth.cyphward.com${pathname}`;
    if (pathname.startsWith('/onboarding') || APP_PATHS.has(pathname)) {
      return `https://app.cyphward.com${pathname}`;
    }
    return null;
  }

  if (onAuth) {
    if (AUTH_PATHS.has(pathname)) return null;
    if (pathname === '/') return 'https://auth.cyphward.com/login';
    if (pathname.startsWith('/onboarding') || APP_PATHS.has(pathname)) {
      return `https://app.cyphward.com${pathname}`;
    }
    if (isMarketingPath(pathname)) return `https://cyphward.com${pathname}`;
    return `https://app.cyphward.com${pathname}`;
  }

  if (onApp) {
    if (AUTH_PATHS.has(pathname)) return `https://auth.cyphward.com${pathname}`;
    if (pathname === '/') return 'https://app.cyphward.com/overview';
    if (isMarketingPath(pathname)) return `https://cyphward.com${pathname}`;
    return null;
  }

  return null;
}
