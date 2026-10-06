import { ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sun, Moon, ArrowLeft } from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import StrataField from './StrataField';
import CyphwardLogo from './CyphwardLogo';

/**
 * Shared chrome for public marketing pages (/pricing, /about).
 * No session required, so the prerendered HTML is the page.
 */
export default function PublicShell({
  eyebrow,
  title,
  lede,
  wide,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  wide?: boolean;
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

      <header className="relative z-10 px-5 md:px-8 pt-5">
        <div className="landing-container flex items-center justify-between py-3 border-b border-line">
          <div className="flex items-center gap-3 min-w-0">
            <Link to="/" className="flex items-center text-ink hover:opacity-85 transition-opacity">
              <CyphwardLogo variant="compact" size={20} />
            </Link>
            <span className="text-line select-none hidden sm:inline">/</span>
            <span className="eyebrow text-[10px] hidden sm:inline truncate">{eyebrow}</span>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <Link to="/pricing" className="hidden sm:inline text-xs mono text-soft hover:text-ink py-1 px-2">
              PRICING
            </Link>
            <Link to="/about" className="hidden sm:inline text-xs mono text-soft hover:text-ink py-1 px-2">
              ABOUT
            </Link>
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
              <span className="hidden sm:inline">BACK TO HOME</span>
              <span className="sm:hidden">HOME</span>
            </Link>
          </div>
        </div>
      </header>

      <main className="landing-container relative z-10">
        <div className={`${wide ? 'max-w-5xl' : 'max-w-3xl'} mx-auto py-12`}>
          <p className="eyebrow mb-3">{eyebrow}</p>
          <h1 className="display-h">{title}</h1>
          {lede && <p className="text-sm text-soft leading-relaxed max-w-2xl">{lede}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </main>

      <footer className="landing-footer">
        <div className="landing-container flex flex-col sm:flex-row items-center justify-between gap-4 text-xs mono text-soft">
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
            <Link to="/pricing" className="hover:text-ink transition-colors">PRICING</Link>
            <span className="text-line">·</span>
            <Link to="/about" className="hover:text-ink transition-colors">ABOUT</Link>
            <span className="text-line">·</span>
            <Link to="/terms" className="hover:text-ink transition-colors">TERMS</Link>
            <span className="text-line">·</span>
            <Link to="/privacy" className="hover:text-ink transition-colors">PRIVACY</Link>
            <span className="text-line">·</span>
            <Link to="/login" className="hover:text-ink transition-colors">SIGN IN</Link>
          </div>
          <div>© 2026 CYPHWARD LTD</div>
        </div>
      </footer>
    </div>
  );
}
