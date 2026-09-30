import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Globe,
  Network,
  ShieldCheck,
  Sliders,
  X,
  Search,
  Moon,
  Sun,
  LogOut,
  ArrowUpRight,
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';
import { getTheme, toggleTheme } from '../lib/theme';
import CyphwardLogo from './CyphwardLogo';

interface Props {
  open: boolean;
  onClose: () => void;
  onPalette: () => void;
}

const EXTENDED_MODULES = [
  {
    to: '/domains',
    idx: '05',
    label: 'DOMAINS',
    icon: Globe,
    badge: 'DNS VERIFICATION',
  },
  {
    to: '/remediation',
    idx: '06',
    label: 'REMEDIATION',
    icon: ShieldCheck,
    badge: 'FIX & VERIFY',
  },
  {
    to: '/reports',
    idx: '07',
    label: 'REPORTS',
    icon: Network,
    badge: 'ASSESSMENTS',
  },
  {
    to: '/settings',
    idx: '08',
    label: 'SETTINGS',
    icon: Sliders,
    badge: 'ORG & MEMBERS',
  },
];

export default function MobileMenuSheet({ open, onClose, onPalette }: Props) {
  const { signOut } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const theme = getTheme();
  const touchStartY = useRef<number | null>(null);

  if (!open) return null;

  const handleTouchStart = (e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY;
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (touchStartY.current === null) return;
    const deltaY = e.changedTouches[0].clientY - touchStartY.current;
    if (deltaY > 50) {
      onClose();
    }
    touchStartY.current = null;
  };

  const handleNavigate = (to: string) => {
    nav(to);
    onClose();
  };

  const doSignOut = async () => {
    onClose();
    try {
      await signOut();
    } finally {
      toast('Session closed — see you on the next layer.');
      nav('/login', { replace: true });
    }
  };

  return (
    <>
      {/* Light backdrop for dismissing sheet */}
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-xs z-[1040] animate-fade-in transition-opacity md:hidden"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Compact Bottom Sheet Menu (Mobile Only) */}
      <div
        className="fixed inset-x-3 bottom-[74px] max-w-[390px] mx-auto bg-raised border border-line text-ink rounded-2xl z-[1050] flex flex-col shadow-2xl animate-in slide-in-from-bottom-4 duration-200 overflow-hidden md:hidden"
        role="dialog"
        aria-label="Extended Modules Menu"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {/* Compact Header */}
        <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-line bg-inset/70">
          <div className="flex items-center gap-2 min-w-0">
            <CyphwardLogo variant="cyph" size={15} />
            <span className="text-line text-xs select-none">/</span>
            <span className="text-[10.5px] font-mono font-bold tracking-wider text-ink uppercase truncate">
              EXTENDED MODULES (05–10)
            </span>
          </div>

          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-inset text-soft hover:text-ink transition-colors btn-tactile"
            aria-label="Close menu"
            title="Close menu"
          >
            <X size={14} />
          </button>
        </div>

        {/* Sleek Single-Column Rows of Extended Modules */}
        <div className="p-2 space-y-1">
          {EXTENDED_MODULES.map((mod) => (
            <button
              key={mod.to}
              onClick={() => handleNavigate(mod.to)}
              className="flex items-center justify-between px-3 py-2 rounded-xl border border-line/60 bg-inset/30 hover:bg-inset hover:border-accent/40 transition-all text-left group btn-tactile w-full"
            >
              <div className="flex items-center gap-2.5 min-w-0 pr-2">
                <mod.icon size={14} className="text-accent shrink-0" />
                <span className="text-[11.5px] font-mono font-semibold text-ink group-hover:text-accent truncate">
                  {mod.idx} · {mod.label}
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[8.5px] font-mono px-1.5 py-0.5 rounded bg-raised border border-line text-soft">
                  {mod.badge}
                </span>
                <ArrowUpRight size={12} className="text-soft group-hover:text-accent transition-colors" />
              </div>
            </button>
          ))}
        </div>

        {/* Compact Utility Bar */}
        <div className="px-3 pb-2.5 pt-1.5 flex items-center gap-2 border-t border-line bg-raised">
          <button
            onClick={() => {
              onClose();
              onPalette();
            }}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2.5 rounded-lg border border-line bg-inset/40 hover:bg-inset text-[10.5px] mono text-ink transition-colors btn-tactile"
          >
            <Search size={12} className="text-accent" />
            <span>COMMAND ⌘K</span>
          </button>

          <button
            onClick={toggleTheme}
            className="flex items-center justify-center p-2 rounded-lg border border-line bg-inset/40 hover:bg-inset text-soft hover:text-ink transition-colors btn-tactile"
            title="Toggle theme"
          >
            {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
          </button>

          <button
            onClick={doSignOut}
            className="flex items-center justify-center p-2 rounded-lg border border-line bg-inset/40 hover:bg-red-500/10 hover:border-red-500/30 text-soft hover:text-red-500 transition-colors btn-tactile"
            title="Sign out"
          >
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </>
  );
}
