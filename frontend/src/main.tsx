import { lazy, StrictMode, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { LoadingScreen } from './components/ui';
import { consumeHandoff } from './lib/session';
import './index.css';

// The platform owner console is a separate app (its own sign-in and session),
// served on admin.cyphward.com and, for local development only, under /admin.
const isOwnerConsole = (() => {
  const { hostname, pathname } = window.location;
  if (hostname === 'admin.cyphward.com') return true;
  const local = hostname === 'localhost' || hostname === '127.0.0.1';
  return local && (pathname === '/admin' || pathname.startsWith('/admin/'));
})();
const OwnerApp = lazy(() => import('./owner/OwnerApp'));

// Pick up a cross-origin session handoff (auth.cyphward.com → app.cyphward.com)
// before anything reads the session store.
if (!isOwnerConsole) consumeHandoff();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isOwnerConsole ? (
      <Suspense fallback={<LoadingScreen label="Opening the console" />}>
        <OwnerApp />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>
);
