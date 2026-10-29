import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import {
  Activity, BarChart3, Building2, CreditCard, LogOut, Mail, Menu, Moon, PanelLeftClose, PanelLeftOpen, Radar, ScrollText,
  Server, Sun, Users, X, type LucideIcon,
} from 'lucide-react';
import CyphwardLogo from '../components/CyphwardLogo';
import StatusChip from '../components/StatusChip';
import StrataField from '../components/StrataField';
import { toggleTheme, useThemeState } from '../lib/theme';
import { lockScroll, unlockScroll } from '../lib/scrollLock';
import type { OwnerMe } from './ownerApi';

/**
 * Owner console chrome. Same classes and markup as the customer app's shell
 * (Sidebar, Topbar, ButtonPlate, MobileMenuSheet) so the console looks and
 * behaves like the product, but with its own sections and session.
 */

type NavEntry = { to: string; label: string; icon: LucideIcon; end: boolean; dock?: boolean };

export const OWNER_NAV: NavEntry[] = [
  { to: '/', label: 'OVERVIEW', icon: Activity, end: true, dock: true },
  { to: '/analytics', label: 'ANALYTICS', icon: BarChart3, end: false },
  { to: '/organizations', label: 'ORGANIZATIONS', icon: Building2, end: false, dock: true },
  { to: '/users', label: 'USERS', icon: Users, end: false, dock: true },
  { to: '/subscriptions', label: 'SUBSCRIPTIONS', icon: CreditCard, end: false },
  { to: '/scans', label: 'SCANS', icon: Radar, end: false, dock: true },
  { to: '/newsletter', label: 'NEWSLETTER', icon: Mail, end: false },
  { to: '/logs', label: 'LOGS', icon: ScrollText, end: false },
  { to: '/system', label: 'SYSTEM', icon: Server, end: false },
];

function sectionFor(pathname: string) {
  return OWNER_NAV.find(n => (n.end ? pathname === n.to : pathname.startsWith(n.to))) ?? OWNER_NAV[0];
}

function endsAt(me: OwnerMe) {
  return new Date(me.expires_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function OwnerShell({ me, signingOut, onSignOut, children }: {
  me: OwnerMe; signingOut: boolean; onSignOut: () => void; children: ReactNode;
}) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cyphward-owner-sidebar-collapsed') === 'true';
    } catch {
      return false;
    }
  });
  const toggleCollapsed = () => setCollapsed(prev => {
    try {
      localStorage.setItem('cyphward-owner-sidebar-collapsed', String(!prev));
    } catch {
      // ignore
    }
    return !prev;
  });

  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => {
    if (location.key !== 'default') window.scrollTo(0, 0);
  }, [location.pathname, location.key]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        toggleCollapsed();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const section = sectionFor(location.pathname);

  return (
    <div className={`shell relative min-h-screen ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <a href="#main" className="skip-link">Skip to content</a>
      <StrataField variant="mini" opacity={0.88} className="fixed inset-0 pointer-events-none z-0" />
      <OwnerSidebar me={me} collapsed={collapsed} onToggleCollapse={toggleCollapsed} signingOut={signingOut} onSignOut={onSignOut} />
      <div className="shell-main relative z-10">
        <OwnerTopbar section={section.label} collapsed={collapsed} onToggleSidebar={toggleCollapsed} onSignOut={onSignOut} />
        <main id="main" tabIndex={-1} className="page" key={location.pathname}>{children}</main>
      </div>
      <OwnerDock onOpenMenu={() => setMenuOpen(true)} />
      <OwnerMenuSheet me={me} open={menuOpen} onClose={() => setMenuOpen(false)} onSignOut={onSignOut} />
    </div>
  );
}

function OwnerSidebar({ me, collapsed, onToggleCollapse, signingOut, onSignOut }: {
  me: OwnerMe; collapsed: boolean; onToggleCollapse: () => void; signingOut: boolean; onSignOut: () => void;
}) {
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`} aria-label="Owner console">
      <div className={`side-brand-row flex items-center border-b border-line ${collapsed ? 'flex-col gap-2 py-3 px-2' : 'justify-between px-4 py-3.5'}`}>
        <Link to="/" className="flex items-center gap-2 hover:opacity-90 transition-opacity" title="Cyphward — Owner console">
          <CyphwardLogo variant={collapsed ? 'mark' : 'full'} size={collapsed ? 22 : 20} showSubtitle={false} />
        </Link>
        <button
          className="side-collapse-btn hidden md:inline-flex"
          onClick={onToggleCollapse}
          title={collapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen size={13} /> : <PanelLeftClose size={13} />}
        </button>
      </div>

      <nav>
        {OWNER_NAV.map(n => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            title={collapsed ? n.label : undefined}
          >
            <n.icon size={15} strokeWidth={1.7} />
            <span className="nav-label">{n.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="side-foot">
        <div className="side-avatar-compact" title={`${me.email} · session ends ${endsAt(me)}`}>
          {me.email.slice(0, 2).toUpperCase()}
          <span className="live-dot" />
        </div>
        <p className="eyebrow">OWNER CONSOLE</p>
        <p className="side-tenant mono font-medium truncate" title={me.email}>{me.email}</p>
        <div className="side-plan-row">
          <span className="tag">ENDS {endsAt(me)}</span>
          <StatusChip level="ok">{me.idle_minutes} MIN IDLE</StatusChip>
        </div>
        <button className="side-out" onClick={onSignOut} disabled={signingOut} title={collapsed ? 'Sign out' : undefined}>
          <span className="side-out-text">{signingOut ? 'SIGNING OUT…' : 'SIGN OUT'}</span> <LogOut size={12} />
        </button>
      </div>
    </aside>
  );
}

export function ThemeButton() {
  const theme = useThemeState();
  return (
    <button type="button" className="icon-btn hover-lift" onClick={toggleTheme} aria-label="Toggle color theme"
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
      {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

function OwnerTopbar({ section, collapsed, onToggleSidebar, onSignOut }: {
  section: string; collapsed: boolean; onToggleSidebar: () => void; onSignOut: () => void;
}) {
  return (
    <header className="topbar">
      <div className="page-bar">
        <div className="flex items-center gap-2.5 min-w-0">
          <button
            onClick={onToggleSidebar}
            className="side-collapse-btn hidden min-[901px]:inline-flex shrink-0"
            title={collapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)'}
            aria-label="Toggle sidebar collapse"
          >
            {collapsed ? <PanelLeftOpen size={13} /> : <PanelLeftClose size={13} />}
          </button>
          <Link
            to="/"
            className={`topbar-brand ${collapsed ? 'flex' : 'min-[901px]:hidden flex'} items-center text-ink hover:opacity-85 transition-opacity flex-none`}
            aria-label="Owner console overview"
          >
            <CyphwardLogo variant="compact" size={32} />
          </Link>
          <span className={`${collapsed ? 'min-[400px]:inline' : 'min-[400px]:inline min-[901px]:hidden'} hidden text-line text-xs select-none`} aria-hidden="true">/</span>
          <p className="bar-sec truncate hidden min-[400px]:block">{section}</p>
        </div>
        <div className="bar-tools flex-none">
          <span className="eyebrow hidden sm:flex items-center gap-1.5 text-[10px]">
            <span className="live-dot" /> OWNER CONSOLE
          </span>
          <ThemeButton />
          <button className="icon-btn hover-lift md:hidden text-soft hover:text-accent" onClick={onSignOut} title="Sign out" aria-label="Sign out">
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </header>
  );
}

function OwnerDock({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { pathname } = useLocation();
  return (
    <>
      <div className="button-plate-scrim" aria-hidden="true" />
      <nav className="button-plate-wrapper" aria-label="Mobile navigation">
        <div className="button-plate">
          {OWNER_NAV.filter(n => n.dock).map(n => {
            const active = n.end ? pathname === n.to : pathname.startsWith(n.to);
            return (
              <NavLink key={n.to} to={n.to} end={n.end} className={`plate-btn ${active ? 'active' : ''}`} title={n.label}>
                <div className="relative flex items-center justify-center">
                  <n.icon size={16} strokeWidth={active ? 2.2 : 1.8} />
                </div>
                <span className="plate-lbl">{n.label === 'ORGANIZATIONS' ? 'ORGS' : n.label}</span>
              </NavLink>
            );
          })}
          <button type="button" className="plate-btn" onClick={onOpenMenu} aria-label="Open menu" title="All sections">
            <div className="relative flex items-center justify-center"><Menu size={16} strokeWidth={1.8} /></div>
            <span className="plate-lbl">MENU</span>
          </button>
        </div>
      </nav>
    </>
  );
}

function OwnerMenuSheet({ me, open, onClose, onSignOut }: { me: OwnerMe; open: boolean; onClose: () => void; onSignOut: () => void }) {
  const theme = useThemeState();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    if (!dialog) return;
    lockScroll();
    const targets = () => [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]')];
    targets()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); }
      if (event.key !== 'Tab') return;
      const list = targets();
      if (event.shiftKey && document.activeElement === list[0]) { event.preventDefault(); list[list.length - 1]?.focus(); }
      else if (!event.shiftKey && document.activeElement === list[list.length - 1]) { event.preventDefault(); list[0]?.focus(); }
    };
    const resize = () => { if (window.innerWidth >= 901) closeRef.current(); };
    document.addEventListener('keydown', keydown);
    window.addEventListener('resize', resize);
    return () => {
      document.removeEventListener('keydown', keydown);
      window.removeEventListener('resize', resize);
      unlockScroll();
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 bg-black/40 backdrop-blur-xs z-[1040] animate-fade-in min-[901px]:hidden" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        className="fixed inset-x-3 bottom-[74px] max-w-[390px] max-h-[calc(100dvh-100px)] mx-auto bg-raised border border-line text-ink rounded-2xl z-[1050] flex flex-col shadow-2xl animate-in slide-in-from-bottom-4 duration-200 overflow-y-auto min-[901px]:hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Owner console menu"
      >
        <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-line bg-inset/70">
          <div className="flex items-center gap-2 min-w-0">
            <CyphwardLogo variant="cyph" size={15} />
            <span className="text-line text-xs select-none" aria-hidden="true">/</span>
            <span className="text-[10.5px] font-mono font-bold tracking-wider text-ink uppercase truncate">OWNER CONSOLE</span>
          </div>
          <button type="button" onClick={onClose} className="icon-btn" aria-label="Close menu"><X size={14} /></button>
        </div>
        <nav className="p-2 flex flex-col gap-0.5" aria-label="Owner console sections">
          {OWNER_NAV.map(n => (
            <NavLink key={n.to} to={n.to} end={n.end} onClick={onClose}
                     className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 rounded-lg text-[11px] mono tracking-[.12em] transition-colors ${isActive ? 'bg-inset text-ink' : 'text-soft hover:bg-inset hover:text-ink'}`}>
              <n.icon size={15} strokeWidth={1.7} className="text-accent" /> {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3 space-y-2.5">
          <p className="text-[10.5px] mono text-soft truncate">{me.email} · ENDS {endsAt(me)}</p>
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={toggleTheme} className="btn-mini justify-center">
              {theme === 'dark' ? <Sun size={12} /> : <Moon size={12} />} {theme === 'dark' ? 'LIGHT' : 'DARK'}
            </button>
            <button type="button" onClick={() => { onClose(); onSignOut(); }} className="btn-mini justify-center hover:!text-accent">
              <LogOut size={12} /> SIGN OUT
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
