import { FormEvent, useCallback, useEffect, useState } from 'react';
import { AlertCircle, Building2, CreditCard, KeyRound, LayoutDashboard, LogOut, Radar, ScrollText, Server, Users } from 'lucide-react';
import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom';
import CyphwardLogo from '../components/CyphwardLogo';
import { OwnerApiError, ownerMe, ownerSignIn, ownerSignOut, type OwnerMe } from './ownerApi';
import { SessionEndedContext } from './ui';
import { OrganizationDetailView, OrganizationsView, OverviewView, UserDetailView, UsersView } from './peopleViews';
import { LogsView, ScanDetailView, ScansView, SubscriptionsView, SystemView } from './opsViews';

/**
 * Platform owner console (admin.cyphward.com; /admin on localhost).
 *
 * A separate app from the customer product: no customer session, workspace
 * or CyphBot. Entry needs email + password + an authenticator code; the
 * session is an httpOnly cookie that ends after inactivity or at its fixed
 * expiry. Every view is recorded in the owner audit log by the API.
 */

type State =
  | { kind: 'loading' }
  | { kind: 'signed-out'; notice?: string }
  | { kind: 'signed-in'; me: OwnerMe }
  | { kind: 'unavailable'; message: string };

export default function OwnerApp() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  const load = useCallback(async (notice?: string) => {
    try {
      setState({ kind: 'signed-in', me: await ownerMe() });
    } catch (e) {
      const err = e as OwnerApiError;
      if (err.status === 401) setState({ kind: 'signed-out', notice });
      else setState({ kind: 'unavailable', message: err.message });
    }
  }, []);

  useEffect(() => {
    document.title = 'Cyphward — Owner console';
    const robots = document.createElement('meta');
    robots.name = 'robots';
    robots.content = 'noindex, nofollow';
    document.head.appendChild(robots);
    // Keep the URL inside the console's own space.
    const base = window.location.hostname === 'admin.cyphward.com' ? '/console' : '/admin';
    if (!window.location.pathname.startsWith(base)) window.history.replaceState({}, '', base);
    void load();
    return () => robots.remove();
  }, [load]);

  if (state.kind === 'loading') {
    return (
      <Frame>
        <p className="mono text-[11px] text-soft tracking-widest text-center">CHECKING OWNER SESSION…</p>
      </Frame>
    );
  }
  if (state.kind === 'unavailable') {
    return (
      <Frame>
        <div className="auth-card text-center">
          <AlertCircle className="mx-auto text-accent mb-3" size={28} />
          <h1 className="font-display text-2xl mb-2">Console unavailable</h1>
          <p className="text-sm text-soft mb-5">{state.message}</p>
          <button type="button" className="btn btn-solid justify-center w-full" onClick={() => void load()}>
            RETRY
          </button>
        </div>
      </Frame>
    );
  }
  if (state.kind === 'signed-out') {
    return <SignIn notice={state.notice} onSignedIn={() => void load()} />;
  }
  return (
    <Console
      me={state.me}
      onSignedOut={() => setState({ kind: 'signed-out', notice: 'Signed out.' })}
      onSessionEnded={() => setState({ kind: 'signed-out', notice: 'Your owner session ended. Sign in again.' })}
    />
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="login-wrap">
      <div className="relative z-10 w-full max-w-md mx-auto">
        <div className="flex items-center justify-center gap-3 mb-2">
          <CyphwardLogo size={22} />
          <span className="tag text-[10px]">OWNER CONSOLE</span>
        </div>
        {children}
      </div>
    </div>
  );
}

function SignIn({ notice, onSignedIn }: { notice?: string; onSignedIn: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await ownerSignIn(email.trim(), password, code.trim());
      setPassword('');
      setCode('');
      onSignedIn();
    } catch (err) {
      const e2 = err as OwnerApiError;
      setError(e2.status === 401 ? 'Sign-in failed. Check your email, password and authenticator code.' : e2.message);
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame>
      <form className="auth-card" onSubmit={submit}>
        <div className="flex items-center gap-2 mb-1">
          <KeyRound size={16} className="text-accent" />
          <h1 className="font-display text-2xl">Owner sign-in</h1>
        </div>
        <p className="text-xs text-soft mb-5">
          Your Cyphward password plus the 6-digit code from your authenticator app. Google sign-in and emailed codes
          don't open this console.
        </p>
        {notice && <p className="text-xs mono text-soft mb-4">{notice}</p>}
        <div className="field">
          <label htmlFor="owner-email">EMAIL</label>
          <input id="owner-email" type="email" autoComplete="username" required value={email}
                 onChange={e => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="owner-password">PASSWORD</label>
          <input id="owner-password" type="password" autoComplete="current-password" required value={password}
                 onChange={e => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="owner-code">AUTHENTICATOR CODE</label>
          <input id="owner-code" inputMode="numeric" autoComplete="one-time-code" required pattern="[0-9]{6}"
                 maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} />
        </div>
        {error && (
          <div role="alert" className="p-3 mb-4 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex gap-2">
            <AlertCircle size={14} className="flex-none mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        <button type="submit" className="btn btn-solid justify-center w-full" disabled={busy || code.length !== 6}>
          {busy ? 'SIGNING IN…' : 'SIGN IN'}
        </button>
      </form>
    </Frame>
  );
}

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/organizations', label: 'Organizations', icon: Building2, end: false },
  { to: '/users', label: 'Users', icon: Users, end: false },
  { to: '/subscriptions', label: 'Subscriptions', icon: CreditCard, end: false },
  { to: '/scans', label: 'Scans', icon: Radar, end: false },
  { to: '/logs', label: 'Logs', icon: ScrollText, end: false },
  { to: '/system', label: 'System', icon: Server, end: false },
];

function Console({ me, onSignedOut, onSessionEnded }: { me: OwnerMe; onSignedOut: () => void; onSessionEnded: () => void }) {
  const [busy, setBusy] = useState(false);
  const signOut = async () => {
    setBusy(true);
    try {
      await ownerSignOut();
    } finally {
      setBusy(false);
      onSignedOut();
    }
  };
  const ends = new Date(me.expires_at);
  const basename = window.location.hostname === 'admin.cyphward.com' ? '/console' : '/admin';
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2.5 px-3 py-2 rounded text-[12.5px] mono whitespace-nowrap transition-colors ${
      isActive ? 'bg-inset text-ink border border-line-strong' : 'text-soft hover:text-ink border border-transparent'}`;

  return (
    <SessionEndedContext.Provider value={onSessionEnded}>
      <BrowserRouter basename={basename}>
        <div className="min-h-[100svh] bg-[var(--bg)] lg:flex">
          <aside className="hidden lg:flex lg:flex-col w-60 shrink-0 border-r border-line bg-raised sticky top-0 h-[100svh]">
            <div className="px-5 py-4 border-b border-line">
              <CyphwardLogo size={20} showSubtitle={false} />
              <span className="tag text-[10px] mt-2">OWNER CONSOLE</span>
            </div>
            <nav className="flex-1 p-3 space-y-1" aria-label="Owner console">
              {NAV.map(n => (
                <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
                  <n.icon size={15} /> {n.label}
                </NavLink>
              ))}
            </nav>
            <div className="p-4 border-t border-line text-[11px] mono text-soft">
              <div className="truncate" title={me.email}>{me.email}</div>
              <div className="mt-1">Ends {ends.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · {me.idle_minutes} min idle</div>
              <button type="button" className="btn btn-ghost w-full justify-center mt-3" onClick={() => void signOut()} disabled={busy}>
                <LogOut size={13} /> {busy ? 'SIGNING OUT…' : 'SIGN OUT'}
              </button>
            </div>
          </aside>

          <div className="flex-1 min-w-0">
            <header className="lg:hidden sticky top-0 z-20 bg-raised border-b border-line">
              <div className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="flex items-center gap-3 min-w-0">
                  <CyphwardLogo size={20} showSubtitle={false} />
                  <span className="hidden min-[440px]:inline-block"><span className="tag text-[10px]">OWNER CONSOLE</span></span>
                </div>
                <button type="button" className="btn btn-ghost whitespace-nowrap" onClick={() => void signOut()} disabled={busy}>
                  <LogOut size={13} /> {busy ? '…' : 'SIGN OUT'}
                </button>
              </div>
              <nav className="no-scrollbar flex gap-1.5 px-4 pb-3 overflow-x-auto" aria-label="Owner console sections">
                {NAV.map(n => (
                  <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
                    <n.icon size={14} /> {n.label}
                  </NavLink>
                ))}
              </nav>
            </header>
            <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
              <Routes>
                <Route path="/" element={<OverviewView />} />
                <Route path="/organizations" element={<OrganizationsView />} />
                <Route path="/organizations/:id" element={<OrganizationDetailView />} />
                <Route path="/users" element={<UsersView />} />
                <Route path="/users/:id" element={<UserDetailView />} />
                <Route path="/subscriptions" element={<SubscriptionsView />} />
                <Route path="/scans" element={<ScansView />} />
                <Route path="/scans/:id" element={<ScanDetailView />} />
                <Route path="/logs" element={<LogsView />} />
                <Route path="/system" element={<SystemView />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </div>
        </div>
      </BrowserRouter>
    </SessionEndedContext.Provider>
  );
}
