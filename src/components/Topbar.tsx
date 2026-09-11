import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Moon, Sun, Globe, LogOut } from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';

const modKey = /mac/i.test(navigator.platform || '') ? '⌘K' : 'CTRL·K';

interface Props {
  onPalette: () => void;
  section: { idx: string; label: string };
}

export default function Topbar({ onPalette, section }: Props) {
  const [time, setTime] = useState('');
  const [theme, setTheme] = useState(getTheme());
  const { signOut } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  useEffect(() => {
    const f = () => {
      const d = new Date();
      const p = (n: number) => String(n).padStart(2, '0');
      setTime(`${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`);
    };
    f();
    const iv = setInterval(f, 1000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const h = () => setTheme(getTheme());
    window.addEventListener('cyphward:theme', h);
    return () => window.removeEventListener('cyphward:theme', h);
  }, []);

  const doSignOut = () => {
    signOut();
    toast('Session closed — see you on the next layer.');
    nav('/login', { replace: true });
  };

  return (
    <header className="topbar">
      <div className="page-bar">
        {/* Brand & Layer Status */}
        <div className="flex items-center gap-2 min-w-0">
          <Link to="/" className="flex items-center gap-1.5 text-ink hover:opacity-85 transition-opacity flex-none" title="CYPHWARD Command Center">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 text-accent">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <span className="font-mono text-xs font-semibold tracking-wider">CYPH</span>
          </Link>
          <span className="text-line text-xs select-none">/</span>
          <p className="bar-sec truncate">
            <span className="hidden sm:inline">LAYER {section.idx} · {section.label}</span>
            <span className="sm:hidden">L{section.idx} · {section.label}</span>
          </p>
          <span className="flex items-center flex-none" title="Enclave Live Telemetry">
            <span className="live-dot" />
          </span>
        </div>

        {/* Action Tools */}
        <div className="bar-tools flex-none">
          <Link
            to="/landing"
            className="hidden md:inline-flex items-center gap-1.5 py-1 px-2.5 rounded border border-line hover:border-ink transition-all text-xs text-soft hover:text-ink font-mono"
            title="View public landing page"
          >
            <Globe size={12} className="text-accent" />
            <span>LANDING PAGE ↗</span>
          </Link>

          <span className="bar-live mono"><span className="live-dot" />ENCLAVE LIVE</span>
          <span className="bar-clock mono">{time}</span>

          <button className="icon-btn hover-lift" onClick={toggleTheme} aria-label="Toggle color theme" title="Toggle theme">
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>

          {/* Mobile Quick Sign-out */}
          <button
            className="icon-btn hover-lift md:hidden text-soft hover:text-accent"
            onClick={doSignOut}
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut size={14} />
          </button>

          <button className="kbd-btn hover-lift hidden sm:inline-flex" onClick={onPalette} title="Open Command Palette">
            {modKey}
          </button>
        </div>
      </div>
    </header>
  );
}
