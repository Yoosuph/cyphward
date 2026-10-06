import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sun, Moon, X, Menu, ArrowRight, ChevronRight } from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import CyphwardLogo from './CyphwardLogo';

/**
 * The full landing navigation header, shared by every public page.
 * `anchorPrefix` is '' on the landing itself (same-page anchors) and '/'
 * everywhere else (e.g. /pricing links back to /#layers).
 */
export default function PublicHeader({ anchorPrefix = '' }: { anchorPrefix?: string }) {
  const nav = useNavigate();
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

  const a = (hash: string) => `${anchorPrefix}${hash}`;

  return (
    <header className={`landing-nav ${mobileMenuOpen ? 'menu-open' : ''}`}>
      <div className="landing-nav-inner">
        <Link to="/" className="landing-brand" onClick={() => setMobileMenuOpen(false)}>
          <CyphwardLogo variant="compact" size={19} />
          <span className="!hidden lg:!inline-block tag text-[9px] ml-1">STRATA 2.0</span>
        </Link>

        <nav className="landing-links">
          <a href={a('#layers')} className="landing-link">LAYERS</a>
          <a href={a('#checks')} className="landing-link">WHAT WE CHECK</a>
          <a href={a('#compliance')} className="landing-link">REGULATION</a>
          <a href={a('#teams')} className="landing-link">TEAMS</a>
          <Link to="/pricing" className="landing-link">PRICING</Link>
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
            className="icon-btn md:hidden"
            onClick={() => setMobileMenuOpen(o => !o)}
            aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
          >
            {mobileMenuOpen ? <X size={15} /> : <Menu size={15} />}
          </button>
        </div>
      </div>

      {/* Mobile Dropdown Menu Panel */}
      {mobileMenuOpen && (
        <div className="landing-mobile-menu md:hidden border-t border-line px-4 py-3 flex flex-col gap-2.5 bg-raised/95 backdrop-blur-md rounded-b-2xl">
          <nav className="flex flex-col gap-1 pt-1">
            <a
              href={a('#layers')}
              className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
              onClick={() => setMobileMenuOpen(false)}
            >
              <span>01–06 · DEFENSE LAYERS</span>
              <ChevronRight size={13} className="text-soft" />
            </a>
            <a
              href={a('#checks')}
              className="py-2 px-2.5 rounded text-xs mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
              onClick={() => setMobileMenuOpen(false)}
            >
              <span>WHAT WE CHECK</span>
              <ChevronRight size={13} className="text-soft" />
            </a>
            <a
              href={a('#compliance')}
              className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
              onClick={() => setMobileMenuOpen(false)}
            >
              <span>PENALTY CALCULATOR</span>
              <ChevronRight size={13} className="text-soft" />
            </a>
            <a
              href={a('#teams')}
              className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
              onClick={() => setMobileMenuOpen(false)}
            >
              <span>TEAMS &amp; ROLES</span>
              <ChevronRight size={13} className="text-soft" />
            </a>
            <Link
              to="/pricing"
              className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
              onClick={() => setMobileMenuOpen(false)}
            >
              <span>PLANS &amp; PRICING</span>
              <ChevronRight size={13} className="text-soft" />
            </Link>
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
