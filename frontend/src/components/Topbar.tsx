import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Moon, Sun, LogOut, PanelLeftClose, PanelLeftOpen, Sparkles } from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';
import CyphwardLogo from './CyphwardLogo';

const modKey = /mac/i.test(navigator.platform || '') ? '⌘K' : 'CTRL·K';

interface Props {
  onPalette: () => void;
  onCyphBot?: () => void;
  onCopilot?: () => void;
  section: { idx: string; label: string };
  sidebarCollapsed?: boolean;
  onToggleSidebar?: () => void;
  mobileAi?: boolean;
}

export default function Topbar({
  onPalette,
  onCyphBot,
  onCopilot,
  section,
  sidebarCollapsed = false,
  onToggleSidebar,
  mobileAi = false,
}: Props) {
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

  const doSignOut = async () => {
    try {
      await signOut();
    } finally {
      toast('Signed out. See you next time!');
      nav('/login', { replace: true });
    }
  };

  const handleAiClick = onCyphBot || onCopilot;

  return (
    <header className="topbar">
      <div className="page-bar">
        {/* Brand & Layer Status */}
        <div className="flex items-center gap-2.5 min-w-0">
          {onToggleSidebar && (
            <button
              onClick={onToggleSidebar}
              className="side-collapse-btn hidden min-[901px]:inline-flex shrink-0"
              title={sidebarCollapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)'}
              aria-label="Toggle sidebar collapse"
            >
              {sidebarCollapsed ? <PanelLeftOpen size={13} /> : <PanelLeftClose size={13} />}
            </button>
          )}

          {/* Full brand remains readable on phones and tablets. */}
          <Link
            to="/overview"
            className={`${sidebarCollapsed ? 'flex' : 'min-[901px]:hidden flex'} items-center text-ink hover:opacity-85 transition-opacity flex-none`}
            title="Cyphward dashboard"
            aria-label="Cyphward dashboard"
          >
            <CyphwardLogo variant="compact" size={32} />
          </Link>
          <span className={`${sidebarCollapsed ? 'min-[400px]:inline' : 'min-[400px]:inline min-[901px]:hidden'} hidden text-line text-xs select-none`}>/</span>
          <p className="bar-sec truncate hidden min-[400px]:block">
            <span className="hidden sm:inline">SECTION {section.idx} · {section.label}</span>
            <span className="sm:hidden text-[11px] mono">SEC {section.idx} · {section.label}</span>
          </p>
          <span className="flex items-center flex-none" title="Live activity">
            <span className="live-dot" />
          </span>
        </div>

        {/* Action Tools */}
        <div className="bar-tools flex-none">
          <span className="bar-live mono"><span className="live-dot" />LIVE</span>
          <span className="bar-clock mono">{time}</span>

          {handleAiClick && (
            <button
              className={`${mobileAi ? 'inline-flex min-h-[44px] min-w-[44px] justify-center' : 'hidden sm:inline-flex'} items-center gap-1.5 py-1 px-2.5 rounded border border-line bg-inset/40 hover:border-accent hover:text-ink text-soft text-xs mono transition-colors hover-lift`}
              onClick={handleAiClick}
              title="Open CyphBot (Ctrl+J)"
              aria-label="Open CyphBot"
            >
              <Sparkles size={13} className="text-accent" />
              <span className={`${mobileAi ? 'hidden sm:inline' : ''} font-semibold`}>CYPHBOT</span>
              <span className={`${mobileAi ? 'hidden sm:inline' : ''} tag text-[9px] py-0 px-1`}>⌘J</span>
            </button>
          )}

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

          <button data-tour="palette" className="kbd-btn hover-lift hidden sm:inline-flex" onClick={onPalette} title="Open Command Palette">
            {modKey}
          </button>
        </div>
      </div>
    </header>
  );
}
