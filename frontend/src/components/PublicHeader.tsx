import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Sun, Moon, X, Menu, ArrowRight, ChevronRight } from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import CyphwardLogo from './CyphwardLogo';

const NAV = [
  ['/', 'HOME'],
  ['/about', 'ABOUT'],
  ['/teams', 'TEAM'],
  ['/pricing', 'PRICING'],
  ['/contact', 'CONTACT'],
] as const;

/** The public navigation header, shared by every marketing page. */
export default function PublicHeader() {
  const nav = useNavigate();
  const { pathname } = useLocation();
  const [theme, setTheme] = useState(getTheme());
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const onToggleTheme = () => {
    toggleTheme();
    setTheme(getTheme());
  };

  const handleGetStarted = () => {
    // Real flow only: no mock sessions. Send visitors to create a real account.
    nav('/signup', { replace: true });
  };

  return (
    <header className={`landing-nav ${mobileMenuOpen ? 'menu-open' : ''}`}>
      <div className="landing-nav-inner">
        <Link to="/" className="landing-brand" onClick={() => setMobileMenuOpen(false)}>
          <CyphwardLogo variant="compact" size={19} />
          <span className="!hidden lg:!inline-block tag text-[9px] ml-1">STRATA 2.0</span>
        </Link>

        <nav className="landing-links">
          {NAV.map(([to, label]) => (
            <Link key={to} to={to} className={`landing-link${pathname === to ? ' is-on' : ''}`}>{label}</Link>
          ))}
        </nav>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            className="icon-btn"
            onClick={onToggleTheme}
            aria-label="Toggle visual theme"
            title="Switch light/dark theme"
          >
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>

          <Link to="/login" className="btn-mini !hidden sm:!inline-flex">
            SIGN IN
          </Link>

          <button className="btn btn-solid btn-mini hover-lift text-[11px] py-1.5 px-3 flex-none" onClick={handleGetStarted}>
            <span className="hidden sm:inline">GET </span>STARTED <ArrowRight size={11} className="ml-1 inline" />
          </button>

          <button
            className="icon-btn min-[901px]:hidden min-h-[44px] min-w-[44px]"
            onClick={() => setMobileMenuOpen(o => !o)}
            aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
          >
            {mobileMenuOpen ? <X size={15} /> : <Menu size={15} />}
          </button>
        </div>
      </div>

      {/* Mobile Dropdown Menu Panel */}
      {mobileMenuOpen && (
        <div className="landing-mobile-menu min-[901px]:hidden border-t border-line px-4 py-3 flex flex-col gap-2.5 bg-raised/95 backdrop-blur-md rounded-b-2xl">
          <nav className="flex flex-col gap-1 pt-1">
            {NAV.map(([to, label]) => (
              <Link
                key={to}
                to={to}
                className={`py-2 px-2.5 rounded text-xs font-mono tracking-wider flex items-center justify-between transition-colors ${pathname === to ? 'text-ink bg-inset' : 'text-soft hover:text-ink hover:bg-inset'}`}
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>{label}</span>
                <ChevronRight size={13} className="text-soft" />
              </Link>
            ))}
          </nav>

          <div className="grid grid-cols-2 gap-2 pt-2 border-t border-line/60">
            <Link
              to="/login"
              className="btn btn-ghost text-xs justify-center py-2"
              onClick={() => setMobileMenuOpen(false)}
            >
              SIGN IN
            </Link>
            <button
              className="btn btn-solid text-xs justify-center py-2"
              onClick={() => {
                setMobileMenuOpen(false);
                handleGetStarted();
              }}
            >
              GET STARTED ↗
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
