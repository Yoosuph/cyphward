import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './lib/auth';
import { ToastProvider } from './components/Toast';
import Sidebar from './components/Sidebar';
import Topbar from './components/Topbar';
import CommandPalette from './components/CommandPalette';
import StrataField from './components/StrataField';
import BrandedCursor from './components/BrandedCursor';
import ButtonPlate from './components/ButtonPlate';

// Public / Auth Pages
import Landing from './pages/Landing';
import Login from './pages/Login';
import Signup from './pages/Signup';
import ForgotPassword from './pages/ForgotPassword';

// Onboarding Pages
import OnboardingLayout from './pages/onboarding/OnboardingLayout';
import VerifyEmail from './pages/onboarding/VerifyEmail';
import CreateOrganization from './pages/onboarding/CreateOrganization';
import AddDomain from './pages/onboarding/AddDomain';
import VerifyDomain from './pages/onboarding/VerifyDomain';
import OnboardingComplete from './pages/onboarding/OnboardingComplete';

// Core MVP Pages
import Overview from './pages/Overview';
import Assets from './pages/Assets';
import Findings from './pages/Findings';
import Scans from './pages/Scans';
import Domains from './pages/Domains';
import Settings from './pages/Settings';
import Remediation from './pages/Remediation';
import Reports from './pages/Reports';
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
          <p className="mono text-[11px] text-soft tracking-widest">INITIALIZING SOVEREIGN ENCLAVE…</p>
        </div>
      </div>
    );
  }

  if (!tenant) return <Navigate to="/login" replace />;

  // Real onboarding gate: a signed-in user without a completed setup never
  // reaches the dashboard (and can't be shown mock data instead).
  if (onboardingStep === 'create_org' || onboardingStep === 'verify_email' || onboardingStep === 'add_domain' || onboardingStep === 'verify_domain') {
    return <Navigate to="/onboarding" replace />;
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

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          {/* Custom precision branded cursor active throughout application */}
          <BrandedCursor />
          <Routes>
            {/* Public and Dedicated Auth Routes */}
            <Route path="/landing" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />

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
              <Route path="/" element={<Overview />} />
              <Route path="/overview" element={<Overview />} />
              <Route path="/assets" element={<Assets />} />
              <Route path="/findings" element={<Findings />} />
              <Route path="/scans" element={<Scans />} />
              <Route path="/domains" element={<Domains />} />
              <Route path="/remediation" element={<Remediation />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/settings" element={<Settings />} />

              {/* Legacy alias redirects */}
              <Route path="/analytics" element={<Navigate to="/" replace />} />
              <Route path="/comply" element={<Navigate to="/" replace />} />
              <Route path="/dashboard" element={<Navigate to="/" replace />} />
              <Route path="/copilot" element={<Navigate to="/" replace />} />
              <Route path="/detect" element={<Navigate to="/scans" replace />} />
              <Route path="/score" element={<Navigate to="/" replace />} />
              <Route path="/academy" element={<Navigate to="/" replace />} />
              <Route path="/sso" element={<Navigate to="/login" replace />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
