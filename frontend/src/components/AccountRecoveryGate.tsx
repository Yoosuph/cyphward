import { useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { useAuth } from '../lib/auth';

export default function AccountRecoveryGate({ children }: { children: ReactNode }) {
  const { bootstrapError, loading, refreshOnboarding, signOut } = useAuth();
  const [busy, setBusy] = useState(false);
  const location = useLocation();
  const nav = useNavigate();
  const publicPage = ['/privacy', '/terms', '/pricing', '/about', '/health'].includes(location.pathname);

  if (loading || !bootstrapError || publicPage) return <>{children}</>;

  return (
    <div className="auth-wrap">
      <div className="auth-card panel max-w-lg mx-auto w-full space-y-4 text-center">
        <AlertCircle size={32} className="text-accent mx-auto" />
        <h1 className="text-xl font-semibold text-ink">Reconnect to your workspace</h1>
        <p role="alert" className="text-sm text-soft">{bootstrapError}</p>
        <button type="button" disabled={busy} className="btn btn-solid w-full justify-center min-h-[44px]" onClick={async () => {
          setBusy(true);
          try { await refreshOnboarding(); } finally { setBusy(false); }
        }}>
          <RefreshCw size={14} className={busy ? 'animate-spin' : ''} /> {busy ? 'RETRYING…' : 'RETRY WORKSPACE'}
        </button>
        <button type="button" disabled={busy} className="btn w-full justify-center min-h-[44px]" onClick={async () => {
          await signOut();
          nav({ pathname: '/login', search: location.search }, { replace: true });
        }}>Sign out and use another account</button>
      </div>
    </div>
  );
}
