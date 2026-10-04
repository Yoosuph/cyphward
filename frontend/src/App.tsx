import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth, IDLE_REASON_KEY } from './lib/auth';
import { hostTarget, IDLE_NOTICE_PARAM } from './lib/hosts';
import { buildAppHandoff } from './lib/session';
import { ToastProvider } from './components/Toast';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import CommandPalette from './components/CommandPalette';
import StrataField from './components/StrataField';
import BrandedCursor from './components/BrandedCursor';
import CookieBanner from './components/CookieBanner';
import { DocumentTitle } from './lib/seo';
import InviteAcceptance from './components/InviteAcceptance';
import ButtonPlate from './components/ButtonPlate';

// Public / prerendered pages — eager: built into the landing bundle.
import Landing from './pages/Landing';
import Terms from './pages/Terms';
import Privacy from './pages/Privacy';

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
const Overview = lazy(() => import('./pages/Overview'));
const Assets = lazy(() => import('./pages/Assets'));
const Findings = lazy(() => import('./pages/Findings'));
const Scans = lazy(() => import('./pages/Scans'));
const Domains = lazy(() => import('./pages/Domains'));
const Settings = lazy(() => import('./pages/Settings'));
const Remediation = lazy(() => import('./pages/Remediation'));
const Reports = lazy(() => import('./pages/Reports'));
const Platform = lazy(() => import('./pages/Platform'));
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
};

/** Fallback while a route-split page chunk downloads. */
function RouteLoading() {
  return (
    <div className="shell relative min-h-screen flex items-center justify-center">
      <div className="text-center p-8 z-10">
        <div className="inline-block w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin mb-3" />
        <p className="mono text-[11px] text-soft tracking-widest">LOADING…</p>
      </div>
    </div>
  );
}

/**
 * Public homepage: the landing page for signed-out visitors, an automatic
 * hand-off to /overview for signed-in users (search engines and first-time
 * visitors both get the marketing page at / instead of a login wall).
 */
function HomeRoute() {
  const { tenant, loading } = useAuth();

  if (loading) {
    return (
      <div className="shell relative min-h-screen flex items-center justify-center">
        <div className="text-center p-8 z-10">
          <div className="inline-block w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin mb-3" />
          <p className="mono text-[11px] text-soft tracking-widest">LOADING YOUR WORKSPACE…</p>
        </div>
      </div>
    );
  }

  if (tenant) return <Navigate to="/overview" replace />;
  return <Landing />;
}

function AppShell() {
  const { tenant, loading, onboardingStep } = useAuth();
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

  // Close mobile drawer when route changes
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

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
    return (
      <div className="shell relative min-h-screen flex items-center justify-center">
        <StrataField variant="mini" opacity={0.88} className="fixed inset-0 pointer-events-none z-0" />
        <div className="text-center p-8 z-10">
          <div className="inline-block w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin mb-3" />
          <p className="mono text-[11px] text-soft tracking-widest">LOADING YOUR WORKSPACE…</p>
        </div>
      </div>
    );
  }

  if (!tenant) return <Navigate to="/login" replace />;

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
    return <Navigate to={onboardingRoute[onboardingStep]} replace />;
  }

  const section = SECTION_BY_PATH[location.pathname] ?? { idx: '01', label: 'OVERVIEW' };

  return (
    <div className={`shell relative min-h-screen ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
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
        <div className="page" key={location.pathname}>
          <Outlet />
        </div>
      </div>
      {/* Mobile Floating Bottom Dock (CMD, ASSETS, FINDINGS, SCANS, MENU) */}
      <ButtonPlate
        onPalette={() => setPalOpen(true)}
        onOpenMenu={() => setMobileMenuOpen(true)}
      />

      {/* Floating Sovereign AI Assistant Trigger Button */}
      <CyphBotFloatingButton
        open={cyphBotOpen}
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
        <BrowserRouter>
          <HostGate>
          {/* Custom precision branded cursor active throughout application */}
          <BrandedCursor />
          {/* Per-route <title> so auth/app tabs don't keep the marketing title */}
          <DocumentTitle />
          {/* Emailed team-invitation links (?invite=) — joins on success */}
          <InviteAcceptance />
          {/* Essential-storage cookie notice (Privacy §09) — dismiss persists */}
          <CookieBanner />
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

            {/* Onboarding Routes */}
            <Route path="/onboarding" element={<OnboardingLayout />}>
              <Route index element={<Navigate to="/onboarding/create-org" replace />} />
              <Route path="verify-email" element={<VerifyEmail />} />
              <Route path="create-org" element={<CreateOrganization />} />
              <Route path="add-domain" element={<AddDomain />} />
              <Route path="verify-domain" element={<VerifyDomain />} />
              <Route path="complete" element={<OnboardingComplete />} />
            </Route>

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

              {/* Legacy alias redirects */}
              <Route path="/analytics" element={<Navigate to="/overview" replace />} />
              <Route path="/comply" element={<Navigate to="/overview" replace />} />
              <Route path="/dashboard" element={<Navigate to="/overview" replace />} />
              <Route path="/copilot" element={<Navigate to="/overview" replace />} />
              <Route path="/detect" element={<Navigate to="/scans" replace />} />
              <Route path="/score" element={<Navigate to="/overview" replace />} />
              <Route path="/academy" element={<Navigate to="/overview" replace />} />
              <Route path="/sso" element={<Navigate to="/login" replace />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
          </HostGate>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
