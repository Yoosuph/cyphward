import { FormEvent, useCallback, useEffect, useState } from 'react';
import { AlertCircle, ArrowRight, Eye, EyeOff, KeyRound, Lock, ShieldCheck } from 'lucide-react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import CyphwardLogo from '../components/CyphwardLogo';
import StrataField from '../components/StrataField';
import { QRCodeSVG } from 'qrcode.react';
import { OwnerShell, ThemeButton } from './shell';
import { OwnerApiError, ownerMe, ownerSetupAuthenticator, ownerSetupComplete, ownerSignIn, ownerSignOut, type OwnerMe } from './ownerApi';
import { OwnerMeContext, SessionEndedContext } from './ui';
import { ToastProvider } from '../components/Toast';
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
  | { kind: 'setup'; email: string }
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
      <div className="shell relative min-h-screen flex items-center justify-center">
        <StrataField variant="mini" opacity={0.88} className="fixed inset-0 pointer-events-none z-0" />
        <div className="text-center p-8 z-10">
          <div className="inline-block w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin mb-3" />
          <p className="mono text-[11px] text-soft tracking-widest">CHECKING OWNER SESSION…</p>
        </div>
      </div>
    );
  }
  if (state.kind === 'unavailable') {
    return (
      <Frame tab="CONSOLE UNAVAILABLE">
        <div className="text-center">
          <AlertCircle className="mx-auto text-accent mb-3" size={24} />
          <p className="text-sm mono mb-5">{state.message}</p>
          <button type="button" className="btn btn-solid justify-center w-full" onClick={() => void load()}>
            RETRY
          </button>
        </div>
      </Frame>
    );
  }
  if (state.kind === 'signed-out') {
    return <SignIn notice={state.notice} onSignedIn={() => void load()}
                   onSetup={email => setState({ kind: 'setup', email })} />;
  }
  if (state.kind === 'setup') {
    return <Setup email={state.email} onDone={() => void load()}
                  onExpired={() => setState({ kind: 'signed-out', notice: 'Setup timed out — sign in again with the same password.' })} />;
  }
  return (
    <Console
      me={state.me}
      onSignedOut={() => setState({ kind: 'signed-out', notice: 'Signed out.' })}
      onSessionEnded={() => setState({ kind: 'signed-out', notice: 'Your owner session ended. Sign in again.' })}
    />
  );
}

/** The customer login page's layout: strata field, utility bar, terminal card. */
function Frame({ tab, wide = false, children }: { tab: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <div className="login-wrap">
      <StrataField variant="auth" />
      <div className="relative z-10 w-full max-w-6xl mx-auto my-auto py-6">
        <div className="flex items-center justify-between pb-6 mb-8 border-b border-line">
          <div className="flex items-center gap-3">
            <CyphwardLogo variant="compact" size={20} />
            <span className="text-line select-none">/</span>
            <div className="eyebrow flex items-center gap-1.5 text-[10px]">
              <span className="live-dot" /> CYPHWARD · OWNER CONSOLE
            </div>
          </div>
          <ThemeButton />
        </div>

        <div className={`mx-auto w-full ${wide ? 'max-w-lg' : 'max-w-md'}`}>
          <div className="login-terminal-card">
            <div className="auth-tabs">
              <button type="button" className="auth-tab active" tabIndex={-1}>
                <KeyRound size={13} className="inline mr-1.5" /> {tab}
              </button>
            </div>
            {children}
            <div className="mt-5 pt-3 border-t border-line/60 flex items-center justify-between text-[9.5px] mono text-soft">
              <span className="flex items-center gap-1.5">
                <Lock size={11} className="text-accent" /> PROTECTED CONNECTION
              </span>
              <span>EVERY VIEW IS LOGGED</span>
            </div>
          </div>
        </div>

        <div className="mt-10 pt-6 border-t border-line">
          <dl className="meta-row">
            <div><dt>ACCESS</dt><dd>PLATFORM OWNER ONLY</dd></div>
            <div><dt>SIGN-IN</dt><dd>PASSWORD + AUTHENTICATOR APP</dd></div>
            <div><dt>SESSION</dt><dd>ENDS AFTER 30 MIN IDLE</dd></div>
          </dl>
        </div>
      </div>
    </div>
  );
}

function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div role="alert" className="p-3 mb-4 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
      <AlertCircle size={14} className="flex-none mt-0.5" />
      <span>{children}</span>
    </div>
  );
}

function SignIn({ notice, onSignedIn, onSetup }: { notice?: string; onSignedIn: () => void; onSetup: (email: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await ownerSignIn(email.trim(), password, code.trim());
      setPassword('');
      setCode('');
      if (result.setup_required) onSetup(result.email);
      else onSignedIn();
    } catch (err) {
      const e2 = err as OwnerApiError;
      setError(e2.status === 401 ? 'Sign-in failed. Check your email, password and authenticator code.' : e2.message);
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Frame tab="OWNER SIGN-IN">
      <form onSubmit={submit} className="content-fade-in">
        <p className="text-xs mono text-soft leading-relaxed mb-5">
          Admin password plus the 6-digit code from your authenticator app. Google sign-in and emailed codes don't open
          this console. First sign-in with a new admin login? Leave the code empty.
        </p>
        {notice && <div className="p-3 mb-4 bg-accent/10 border border-accent/30 rounded text-xs mono text-ink">{notice}</div>}
        <div className="field">
          <label htmlFor="owner-email">EMAIL</label>
          <input id="owner-email" type="email" autoComplete="username" required value={email}
                 onChange={e => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="owner-password">PASSWORD</label>
          <div className="pw-input-wrap">
            <input id="owner-password" type={showPw ? 'text' : 'password'} autoComplete="current-password" required value={password}
                   placeholder="••••••••••••••" onChange={e => setPassword(e.target.value)} />
            <button type="button" className="pw-toggle-btn" onClick={() => setShowPw(v => !v)}
                    aria-label={showPw ? 'Hide password' : 'Show password'} title={showPw ? 'Hide password' : 'Show password'}>
              {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="owner-code">AUTHENTICATOR CODE</label>
          <input id="owner-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" placeholder="000000"
                 className="tracking-[.4em]" maxLength={6} value={code}
                 onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} />
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
        <button type="submit" className="btn btn-solid w-full justify-center mt-5" disabled={busy || (code.length > 0 && code.length !== 6)}>
          {busy ? 'SIGNING IN…' : <>SIGN IN <ArrowRight size={14} className="ml-1" /></>}
        </button>
      </form>
    </Frame>
  );
}

function Setup({ email, onDone, onExpired }: { email: string; onDone: () => void; onExpired: () => void }) {
  const [auth, setAuth] = useState<{ secret: string; otpauth_url: string } | null>(null);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    ownerSetupAuthenticator().then(setAuth).catch((e: OwnerApiError) => (e.status === 401 ? onExpired() : setError(e.message)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tooShort = password.length > 0 && password.length < 12;
  const mismatch = confirm.length > 0 && confirm !== password;
  const ready = !!auth && password.length >= 12 && confirm === password && code.length === 6;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError('');
    try {
      await ownerSetupComplete(password, code);
      onDone();
    } catch (err) {
      const e2 = err as OwnerApiError;
      if (e2.status === 401 && /expired/i.test(e2.message)) onExpired();
      else setError(e2.message);
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  const step = (n: string, label: string, gap = true) => (
    <p className={`eyebrow text-[10px] mb-3 ${gap ? 'mt-6' : 'mt-1'} flex items-center gap-2`}><span className="text-accent">{n}</span> {label}</p>
  );

  return (
    <Frame tab="SET UP ADMIN LOGIN" wide>
      <form onSubmit={submit} className="content-fade-in">
        <p className="text-xs mono text-soft leading-relaxed mb-5">
          {email} · one time only. Choose your own password and connect an authenticator app. The password you were
          given stops working when you finish. This screen expires after 15 minutes.
        </p>

        {step('01', 'NEW PASSWORD', false)}
        <div className="field">
          <label htmlFor="setup-password">PASSWORD (12+ CHARACTERS)</label>
          <input id="setup-password" type="password" autoComplete="new-password" value={password}
                 onChange={e => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="setup-confirm">CONFIRM PASSWORD</label>
          <input id="setup-confirm" type="password" autoComplete="new-password" value={confirm}
                 onChange={e => setConfirm(e.target.value)} />
        </div>
        {(tooShort || mismatch) && (
          <p className="text-xs mono text-warn -mt-2 mb-4">{tooShort ? 'Use at least 12 characters.' : 'The passwords don\'t match.'}</p>
        )}

        {step('02', 'AUTHENTICATOR APP')}
        {auth ? (
          <div className="flex flex-col sm:flex-row items-center gap-4 p-3 rounded border border-line bg-inset/50">
            <div className="bg-white p-2 rounded border border-line flex-none">
              <QRCodeSVG value={auth.otpauth_url} size={132} />
            </div>
            <div className="text-xs text-soft min-w-0">
              Scan with Google Authenticator, Microsoft Authenticator or 1Password. Can't scan? Enter this key:
              <code className="block mono text-ink break-all mt-1.5 select-all">{auth.secret}</code>
            </div>
          </div>
        ) : (
          <div className="skeleton" style={{ height: 150, borderRadius: 6 }} />
        )}

        {step('03', 'CONFIRM')}
        <div className="field">
          <label htmlFor="setup-code">6-DIGIT CODE FROM THE APP</label>
          <input id="setup-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="000000"
                 className="tracking-[.4em]" value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} />
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
        <button type="submit" className="btn btn-solid justify-center w-full mt-5" disabled={!ready || busy}>
          {busy ? 'FINISHING…' : <><ShieldCheck size={14} className="mr-1" /> FINISH SETUP</>}
        </button>
      </form>
    </Frame>
  );
}

function Console({ me, onSignedOut, onSessionEnded }: { me: OwnerMe; onSignedOut: () => void; onSessionEnded: () => void }) {
  const [busy, setBusy] = useState(false);
  const signOut = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await ownerSignOut();
    } finally {
      setBusy(false);
      onSignedOut();
    }
  };
  const basename = window.location.hostname === 'admin.cyphward.com' ? '/console' : '/admin';

  return (
    <SessionEndedContext.Provider value={onSessionEnded}>
    <OwnerMeContext.Provider value={me}>
    <ToastProvider>
      <BrowserRouter basename={basename}>
        <OwnerShell me={me} signingOut={busy} onSignOut={() => void signOut()}>
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
        </OwnerShell>
      </BrowserRouter>
    </ToastProvider>
    </OwnerMeContext.Provider>
    </SessionEndedContext.Provider>
  );
}
