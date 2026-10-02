import { ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sun, Moon, ArrowLeft } from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import StrataField from './StrataField';
import CyphwardLogo from './CyphwardLogo';

/**
 * Shared landing-style chrome for the legal pages (/terms, /privacy).
 * Public — no session required, so OAuth verification crawlers can read them.
 */
export default function LegalShell({
  eyebrow,
  title,
  effective,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  effective: string;
  children: ReactNode;
}) {
  const [theme, setTheme] = useState(getTheme());

  useEffect(() => {
    const onThemeChange = () => setTheme(getTheme());
    window.addEventListener('cyphward:theme', onThemeChange);
    return () => window.removeEventListener('cyphward:theme', onThemeChange);
  }, []);

  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />

      {/* Minimal header */}
      <header className="relative z-10 px-5 md:px-8 pt-5">
        <div className="landing-container flex items-center justify-between py-3 border-b border-line">
          <div className="flex items-center gap-3">
            <Link to="/" className="flex items-center text-ink hover:opacity-85 transition-opacity">
              <CyphwardLogo variant="compact" size={20} />
            </Link>
            <span className="text-line select-none hidden sm:inline">/</span>
            <span className="eyebrow text-[10px] hidden sm:inline">{eyebrow}</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="icon-btn hover-lift"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            </button>
            <Link to="/" className="stat-link text-xs flex items-center gap-1.5 py-1 px-2.5 rounded border border-line hover:border-ink transition-all">
              <ArrowLeft size={13} className="text-accent" />
              <span>BACK TO HOME</span>
            </Link>
          </div>
        </div>
      </header>

      {/* Document */}
      <main className="landing-container relative z-10">
        <div className="max-w-3xl mx-auto py-12">
          <p className="eyebrow mb-3">{eyebrow}</p>
          <h1 className="display-h">{title}</h1>
          <p className="mono text-[11px] text-soft mt-3">EFFECTIVE: {effective}</p>

          <div className="legal-body panel mt-8 p-6 md:p-9 space-y-7">{children}</div>
        </div>
      </main>

      {/* Minimal footer */}
      <footer className="landing-footer">
        <div className="landing-container flex flex-col sm:flex-row items-center justify-between gap-4 text-xs mono text-soft">
          <div className="flex items-center gap-4">
            <Link to="/terms" className="hover:text-ink transition-colors">TERMS OF SERVICE</Link>
            <span className="text-line">·</span>
            <Link to="/privacy" className="hover:text-ink transition-colors">PRIVACY POLICY</Link>
            <span className="text-line">·</span>
            <Link to="/login" className="hover:text-ink transition-colors">SIGN IN</Link>
          </div>
          <div>© 2026 CYPHWARD TECHNOLOGIES LTD</div>
        </div>
      </footer>
    </div>
  );
}
