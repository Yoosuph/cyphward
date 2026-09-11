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
import Landing from './pages/Landing';
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import SSO from './pages/SSO';
import Dashboard from './pages/Dashboard';
import Comply from './pages/Comply';
import Detect from './pages/Detect';
import Score from './pages/Score';
import Academy from './pages/Academy';
import Copilot from './pages/Copilot';

const SECTION_BY_PATH: Record<string, { idx: string; label: string }> = {
  '/': { idx: '01', label: 'COMMAND' },
  '/dashboard': { idx: '01', label: 'COMMAND' },
  '/comply': { idx: '02', label: 'COMPLY' },
  '/detect': { idx: '03', label: 'DETECT' },
  '/score': { idx: '04', label: 'SCORE' },
  '/academy': { idx: '05', label: 'ACADEMY' },
  '/copilot': { idx: '06', label: 'COPILOT' },
};

function AppShell() {
  const { tenant } = useAuth();
  const location = useLocation();
  const [palOpen, setPalOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPalOpen(o => !o);
      } else if (e.key === 'Escape') {
        setPalOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (!tenant) return <Navigate to="/landing" replace />;

  const section = SECTION_BY_PATH[location.pathname] ?? { idx: '01', label: 'COMMAND' };

  return (
    <div className="shell relative min-h-screen">
      {/* Crisp, clearly visible mini strata dots behind the main app shell */}
      <StrataField variant="mini" opacity={0.88} className="fixed inset-0 pointer-events-none z-0" />
      <Sidebar />
      <div className="shell-main relative z-10">
        <Topbar onPalette={() => setPalOpen(true)} section={section} />
        <div className="page" key={location.pathname}>
          <Outlet />
        </div>
      </div>
      {/* Mobile Floating Button Plate */}
      <ButtonPlate onPalette={() => setPalOpen(true)} />
      <CommandPalette open={palOpen} onClose={() => setPalOpen(false)} />
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
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/sso" element={<SSO />} />

            {/* Authenticated App Routes — All protected inside AppShell */}
            <Route element={<AppShell />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/comply" element={<Comply />} />
              <Route path="/detect" element={<Detect />} />
              <Route path="/score" element={<Score />} />
              <Route path="/academy" element={<Academy />} />
              <Route path="/copilot" element={<Copilot />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
