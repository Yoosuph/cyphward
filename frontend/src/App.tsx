import { lazy, Suspense, useEffect, useLayoutEffect, useState, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';
import { appPageLoaders, prefetchAppPagesWhenIdle } from './lib/routePrefetch';
import { AuthProvider, useAuth, IDLE_REASON_KEY } from './lib/auth';
import { hostTarget, IDLE_NOTICE_PARAM } from './lib/hosts';
import { buildAppHandoff } from './lib/session';
import { ToastProvider } from './components/Toast';
import { ConfirmProvider } from './components/ConfirmDialog';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import CommandPalette from './components/CommandPalette';
import ProductTour from './components/ProductTour';
import { TOUR_EVENT } from './lib/tour';
import StrataField from './components/StrataField';
import BrandedCursor from './components/BrandedCursor';
import CookieBanner from './components/CookieBanner';
import AccountRecoveryGate from './components/AccountRecoveryGate';
import { DocumentTitle } from './lib/seo';
import InviteAcceptance from './components/InviteAcceptance';
import ButtonPlate from './components/ButtonPlate';
import { LoadingScreen } from './components/ui';

// Public / prerendered pages — eager: built into the landing bundle.
import Landing from './pages/Landing';
import Terms from './pages/Terms';
import Privacy from './pages/Privacy';
import Pricing from './pages/Pricing';
import About from './pages/About';
import Scanner from './pages/Scanner';
import Teams from './pages/Teams';
import Contact from './pages/Contact';
import Health from './pages/Health';
import NotFound from './pages/NotFound';
import Newsletter from './pages/Newsletter';
import NewsletterResult from './pages/NewsletterResult';

// Route-split pages: loaded on demand so the public landing payload doesn't
// ship the dashboard, auth screens and chart library (recharts).
const Login = lazy(() => import('./pages/Login'));
const Signup = lazy(() => import('./pages/Signup'));
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'));
const ResetPassword = lazy(() => import('./pages/ResetPassword'));
const AuthCallback = lazy(() => import('./pages/AuthCallback'));

// Onboarding Pages
const OnboardingLayout = lazy(() => import('./pages/onboarding/OnboardingLayout'));
const VerifyEmail = lazy(() => import('./pages/onboarding/VerifyEmail'));
const CreateOrganization = lazy(() => import('./pages/onboarding/CreateOrganization'));
const AddDomain = lazy(() => import('./pages/onboarding/AddDomain'));
const VerifyDomain = lazy(() => import('./pages/onboarding/VerifyDomain'));
const OnboardingComplete = lazy(() => import('./pages/onboarding/OnboardingComplete'));

// Core MVP Pages
// Shared loaders so the shell can prefetch them (see lib/routePrefetch).
const Overview = lazy(appPageLoaders['/overview']);
const Assets = lazy(appPageLoaders['/assets']);
const Findings = lazy(appPageLoaders['/findings']);
const Scans = lazy(appPageLoaders['/scans']);
const Domains = lazy(appPageLoaders['/domains']);
const Settings = lazy(appPageLoaders['/settings']);
const Remediation = lazy(appPageLoaders['/remediation']);
const Reports = lazy(appPageLoaders['/reports']);
const Platform = lazy(appPageLoaders['/platform']);
const Compliance = lazy(appPageLoaders['/comply']);
const Reviews = lazy(() => import('./pages/Reviews'));
import CyphBotDrawer from './components/CyphBotDrawer';
import CyphBotFloatingButton from './components/CyphBotFloatingButton';
import MobileMenuSheet from './components/MobileMenuSheet';

const SECTION_BY_PATH: Record<string, { idx: string; label: string }> = {
  '/': { idx: '01', label: 'OVERVIEW' },
  '/overview': { idx: '01', label: 'OVERVIEW' },
  '/assets': { idx: '02', label: 'ASSETS' },
  '/findings': { idx: '03', label: 'FINDINGS' },
  '/scans': { idx: '04', label: 'SCANS' },
  '/domains': { idx: '05', label: 'DOMAINS' },
  '/remediation': { idx: '06', label: 'REMEDIATION' },
  '/reports': { idx: '07', label: 'REPORTS' },
  '/settings': { idx: '08', label: 'SETTINGS' },
  '/platform': { idx: '09', label: 'PLATFORM' },
  '/comply': { idx: '10', label: 'COMPLIANCE' },
};

/**
 * In-shell placeholder for a cold page chunk (a deep link straight to an app
 * page). Later navigations never show it: route changes run as transitions,
 * so the current page stays up until the next one is ready.
 */
function PageFallback() {
  return (
    <div className="page page-fallback" aria-busy="true" aria-label="Loading page">
      <div className="skeleton skeleton-text" style={{ width: 180, height: 30 }} />
      <div className="skeleton skeleton-text mt-3" style={{ width: '62%', height: 13 }} />
      <div className="grid gap-4 mt-8 sm:grid-cols-2">
        <div className="skeleton" style={{ height: 132, borderRadius: 10 }} />
        <div className="skeleton" style={{ height: 132, borderRadius: 10 }} />
      </div>
      <div className="skeleton mt-4" style={{ height: 260, borderRadius: 10 }} />
    </div>
  );
}

/** Fallback while a route-split page chunk downloads. */
function RouteLoading() {
  return <LoadingScreen label="Opening this page" />;
}

/**
 * Public homepage: the landing page for signed-out visitors, an automatic
 * hand-off to /overview for signed-in users (search engines and first-time
 * visitors both get the marketing page at / instead of a login wall).
 */
function HomeRoute() {
  const { tenant, loading } = useAuth();

  if (loading) {
    return <LoadingScreen label="Checking your workspace" />;
  }

  if (tenant) return <Navigate to="/overview" replace />;
  return <Landing />;
}

function AppShell() {
  const { tenant, user, loading, onboardingStep } = useAuth();
  const location = useLocation();
  const [palOpen, setPalOpen] = useState(false);
  const [cyphBotOpen, setCyphBotOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cyphward-sidebar-collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const navigationType = useNavigationType();

  // Close mobile drawer when route changes
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const closeOverlays = () => { setMobileMenuOpen(false); setCyphBotOpen(false); setPalOpen(false); };
    window.addEventListener(TOUR_EVENT, closeOverlays);
    return () => window.removeEventListener(TOUR_EVENT, closeOverlays);
  }, []);

  // New pages open at the top; back/forward keeps the browser's position.
  useLayoutEffect(() => {
    if (navigationType !== 'POP') window.scrollTo(0, 0);
  }, [location.pathname, navigationType]);

  // Warm every app page chunk once the shell is idle, so taps never wait on a download.
  useEffect(() => (tenant ? prefetchAppPagesWhenIdle() : undefined), [tenant]);

  const toggleSidebar = () => {
    setSidebarCollapsed(prev => {
      const next = !prev;
      try {
        localStorage.setItem('cyphward-sidebar-collapsed', String(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPalOpen(o => !o);
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        toggleSidebar();
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') {
        e.preventDefault();
        setCyphBotOpen(o => !o);
      } else if (e.key === 'Escape') {
        setPalOpen(false);
        setCyphBotOpen(false);
        setMobileMenuOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (loading) {
    return <LoadingScreen label="Checking your workspace" />;
  }

  if (!tenant) return <Navigate to={{ pathname: "/login", search: location.search }} replace />;

  // Real onboarding gate: a signed-in user without a completed setup never
  // reaches the dashboard (and can't be shown mock data instead). Send them
  // to the route of *their* step — the bare /onboarding index always lands
  // on create-org, which silently skipped verify-domain on reload.
  const onboardingRoute: Record<string, string> = {
    verify_email: '/onboarding/verify-email',
    create_org: '/onboarding/create-org',
    add_domain: '/onboarding/add-domain',
    verify_domain: '/onboarding/verify-domain',
  };
  if (onboardingStep in onboardingRoute) {
    return <Navigate to={{ pathname: onboardingRoute[onboardingStep], search: location.search }} replace />;
  }

  const section = SECTION_BY_PATH[location.pathname] ?? { idx: '01', label: 'OVERVIEW' };

  return (
    <div className={`shell relative min-h-screen ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <a href="#main" className="skip-link">Skip to content</a>
      {/* Crisp, clearly visible mini strata dots behind the main app shell */}
      <StrataField variant="mini" opacity={0.88} className="fixed inset-0 pointer-events-none z-0" />
      <Sidebar
        open={mobileMenuOpen}
        onClose={() => setMobileMenuOpen(false)}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebar}
      />
      <div className="shell-main relative z-10">
        <Topbar
          onPalette={() => setPalOpen(true)}
          onCyphBot={() => setCyphBotOpen(true)}
          onCopilot={() => setCyphBotOpen(true)}
          section={section}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={toggleSidebar}
        />
        {/* Boundary sits outside the keyed page so later navigations (transitions)
            keep the current page visible instead of re-showing a fallback. */}
        <Suspense fallback={<PageFallback />}>
          <main id="main" tabIndex={-1} className="page" key={location.pathname}>
            {user?.demo_session && <div role="note" className="mb-5 rounded-lg border border-accent/30 bg-raised p-3 text-xs text-soft"><strong className="text-ink">Demo workspace · View only.</strong> Account and organisation changes are disabled.</div>}
            <Outlet />
          </main>
        </Suspense>
      </div>
      {/* Mobile Floating Bottom Dock (CMD, ASSETS, FINDINGS, SCANS, MENU) */}
      <ButtonPlate
        onPalette={() => setPalOpen(true)}
        onOpenMenu={() => setMobileMenuOpen(true)}
      />

      {/* Floating Sovereign AI Assistant Trigger Button */}
      <CyphBotFloatingButton
        open={cyphBotOpen || mobileMenuOpen || palOpen}
        onClick={() => setCyphBotOpen(o => !o)}
      />

      {/* Mobile Menu Bottom Sheet — Discloses the rest of the pages (Layers 05–10) */}
      <MobileMenuSheet
        open={mobileMenuOpen}
        onClose={() => setMobileMenuOpen(false)}
        onPalette={() => {
          setMobileMenuOpen(false);
          setPalOpen(true);
        }}
      />

      <CommandPalette open={palOpen} onClose={() => setPalOpen(false)} />
      {/* First-run guided tour (once per user; replay from checklist or palette) */}
      <ProductTour />
      {/* Floating CyphBot Sovereign AI Intelligence Window */}
      <CyphBotDrawer open={cyphBotOpen} onClose={() => setCyphBotOpen(false)} />
    </div>
  );
}

/**
 * Cross-origin route guard for the split-domain layout. React Router cannot
 * navigate between hosts, so a mismatched (host, path) pair triggers a full
 * location.replace() — checked during render (before any page content), so
 * nothing from the wrong host flashes. vercel.json redirects cover cold
 * loads; this covers client-side <Link> navigations. A sessionStorage flag
 * makes the replace idempotent under StrictMode double-renders.
 */
function HostGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const target = hostTarget(location.pathname);

  if (!target) {
    try {
      sessionStorage.removeItem('cyphward-host-redirect');
    } catch {
      // ignore
    }
    return <>{children}</>;
  }

  const url = new URL(target + location.search + location.hash);

  // The idle-logout explanation lives in localStorage, which is per-origin —
  // carry it to auth.cyphward.com as a query param (the Login page consumes it).
  let idleNotice = false;
  try {
    if (url.hostname === 'auth.cyphward.com' && localStorage.getItem(IDLE_REASON_KEY) === '1') {
      localStorage.removeItem(IDLE_REASON_KEY);
      idleNotice = true;
    }
  } catch {
    // ignore
  }
  if (idleNotice && !url.searchParams.has(IDLE_NOTICE_PARAM)) {
    url.searchParams.set(IDLE_NOTICE_PARAM, 'idle');
  }

  // Leaving the auth host with a session: hand it to the app host inside the
  // fragment (localStorage doesn't cross origins) and consume the auth-host
  // copy so a stale snapshot can't cause a login loop later.
  let href = url.toString();
  if (url.hostname === 'app.cyphward.com' && window.location.hostname === 'auth.cyphward.com') {
    href = buildAppHandoff(href) ?? href;
  }

  try {
    if (sessionStorage.getItem('cyphward-host-redirect') !== href) {
      sessionStorage.setItem('cyphward-host-redirect', href);
      window.location.replace(href);
    }
  } catch {
    // ignore
  }
  return <RouteLoading />;
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <ConfirmProvider>
        <BrowserRouter future={{ v7_startTransition: true }}>
          <HostGate>
          {/* Custom precision branded cursor active throughout application */}
          <BrandedCursor />
          {/* Per-route <title> so auth/app tabs don't keep the marketing title */}
          <DocumentTitle />
          {/* Emailed team-invitation links (?invite=) — joins on success */}
          <InviteAcceptance />
          {/* Essential-storage cookie notice (Privacy §09) — dismiss persists */}
          <CookieBanner />
          <AccountRecoveryGate>
          <Suspense fallback={<RouteLoading />}>
            <Routes>
            {/* Public and Dedicated Auth Routes */}
            <Route path="/" element={<HomeRoute />} />
            <Route path="/landing" element={<Navigate to="/" replace />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="/terms" element={<Terms />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/health" element={<Health />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/about" element={<About />} />
            <Route path="/scanner" element={<Scanner />} />
            <Route path="/teams" element={<Teams />} />
            <Route path="/contact" element={<Contact />} />
            <Route path="/newsletter" element={<Newsletter />} />
            <Route path="/newsletter/confirmed" element={<NewsletterResult kind="confirmed" />} />
            <Route path="/newsletter/unsubscribed" element={<NewsletterResult kind="unsubscribed" />} />

            {/* Onboarding Routes */}
            <Route path="/onboarding" element={<OnboardingLayout />}>
              <Route index element={<Navigate to="/onboarding/create-org" replace />} />
              <Route path="verify-email" element={<VerifyEmail />} />
              <Route path="create-org" element={<CreateOrganization />} />
              <Route path="add-domain" element={<AddDomain />} />
              <Route path="verify-domain" element={<VerifyDomain />} />
              <Route path="complete" element={<OnboardingComplete />} />
            </Route>

            {/* Reviewer area (C6): outside AppShell, whose onboarding gate would send a reviewer without a workspace to setup. */}
            <Route path="/reviews" element={<Reviews />} />

            {/* Authenticated App Routes — Protected inside AppShell */}
            <Route element={<AppShell />}>
              {/* Core MVP Routes */}
              <Route path="/overview" element={<Overview />} />
              <Route path="/assets" element={<Assets />} />
              <Route path="/findings" element={<Findings />} />
              <Route path="/scans" element={<Scans />} />
              <Route path="/domains" element={<Domains />} />
              <Route path="/remediation" element={<Remediation />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/platform" element={<Platform />} />
              <Route path="/comply" element={<Compliance />} />

              {/* Legacy alias redirects */}
              <Route path="/analytics" element={<Navigate to="/overview" replace />} />
              <Route path="/dashboard" element={<Navigate to="/overview" replace />} />
              <Route path="/copilot" element={<Navigate to="/overview" replace />} />
              <Route path="/detect" element={<Navigate to="/scans" replace />} />
              <Route path="/score" element={<Navigate to="/overview" replace />} />
              <Route path="/academy" element={<Navigate to="/overview" replace />} />
              <Route path="/sso" element={<Navigate to="/login" replace />} />
            </Route>

            <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
          </AccountRecoveryGate>
          </HostGate>
        </BrowserRouter>
        </ConfirmProvider>
      </ToastProvider>
    </AuthProvider>
  );
}
