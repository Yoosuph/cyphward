import { FormEvent, useCallback, useEffect, useState } from 'react';
import { AlertCircle, KeyRound, LogOut, ShieldCheck } from 'lucide-react';
import CyphwardLogo from '../components/CyphwardLogo';
import { OwnerApiError, ownerMe, ownerSignIn, ownerSignOut, type OwnerMe } from './ownerApi';

/**
 * Platform owner console (admin.cyphward.com; /admin on localhost).
 *
 * A separate app from the customer product: no customer session, workspace
 * or CyphBot. Entry needs email + password + an authenticator code; the
 * session is an httpOnly cookie that ends after inactivity or at its fixed
 * expiry. Data sections are added in the next stages.
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
  return <Console me={state.me} onSignedOut={() => setState({ kind: 'signed-out', notice: 'Signed out.' })} />;
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

function Console({ me, onSignedOut }: { me: OwnerMe; onSignedOut: () => void }) {
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

  return (
    <div className="min-h-[100svh] bg-[var(--bg)]">
      <header className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3 border-b border-line bg-raised">
        <div className="flex items-center gap-3 min-w-0">
          <CyphwardLogo size={20} showSubtitle={false} />
          <span className="hidden min-[440px]:inline-block">
            <span className="tag text-[10px]">OWNER CONSOLE</span>
          </span>
        </div>
        <div className="flex items-center gap-3 min-w-0">
          <span className="hidden sm:inline text-xs mono text-soft truncate">{me.email}</span>
          <button type="button" className="btn btn-ghost whitespace-nowrap" onClick={() => void signOut()} disabled={busy}>
            <LogOut size={13} /> {busy ? 'SIGNING OUT…' : 'SIGN OUT'}
          </button>
        </div>
      </header>
      <main className="max-w-4xl mx-auto px-5 py-10">
        <div className="panel">
          <div className="panel-body flex items-start gap-3">
            <ShieldCheck size={20} className="text-ok flex-none mt-0.5" />
            <div>
              <h1 className="font-display text-2xl mb-1">Signed in as the platform owner</h1>
              <p className="text-sm text-soft">
                This session ends after {me.idle_minutes} minutes without activity, and at{' '}
                {ends.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} at the latest. Every sign-in and
                action here is recorded in the owner audit log.
              </p>
              <p className="text-sm text-soft mt-3">
                Organizations, users, subscriptions, scans, logs and system health arrive in the next release.
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
