import { useRef } from 'react';
import { NavLink, useNavigate, Link } from 'react-router-dom';
import {
  Activity,
  Server,
  ShieldAlert,
  Radar,
  Globe,
  Network,
  ShieldCheck,
  Sliders,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';
import StatusChip from './StatusChip';
import CyphwardLogo from './CyphwardLogo';

const NAV = [
  { to: '/', label: 'OVERVIEW', idx: '01', icon: Activity, end: true },
  { to: '/assets', label: 'ASSETS', idx: '02', icon: Server, end: false },
  { to: '/findings', label: 'FINDINGS', idx: '03', icon: ShieldAlert, end: false },
  { to: '/scans', label: 'SCANS', idx: '04', icon: Radar, end: false },
  { to: '/domains', label: 'DOMAINS', idx: '05', icon: Globe, end: false },
  { to: '/remediation', label: 'REMEDIATION', idx: '06', icon: ShieldCheck, end: false },
  { to: '/reports', label: 'REPORTS', idx: '07', icon: Network, end: false },
  { to: '/settings', label: 'SETTINGS', idx: '08', icon: Sliders, end: false },
];

interface SidebarProps {
  open?: boolean;
  onClose?: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export default function Sidebar({
  open = false,
  onClose,
  collapsed = false,
  onToggleCollapse,
}: SidebarProps) {
  const { tenant, signOut } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);

  const handleTouchStart = (e: React.TouchEvent) => {
    touchStartRef.current = {
      x: e.touches[0].clientX,
      y: e.touches[0].clientY,
    };
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (!touchStartRef.current) return;
    const dx = e.changedTouches[0].clientX - touchStartRef.current.x;
    const dy = Math.abs(e.changedTouches[0].clientY - touchStartRef.current.y);
    if (dx < -50 && dy < 75 && onClose) {
      onClose();
    }
    touchStartRef.current = null;
  };

  const doSignOut = async () => {
    try {
      await signOut();
    } finally {
      toast('Session closed — see you on the next layer.');
      nav('/login', { replace: true });
    }
  };

  const tenantName = tenant?.name || 'DataGrid Africa';
  const tenantInitials = tenantName
    .split(' ')
    .map(w => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase() || 'CW';

  return (
    <>
      <div className={`side-scrim ${open ? 'show' : ''}`} onClick={onClose} />
      <aside
        className={`sidebar ${open ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {/* Header / Brand Area */}
        <div className={`side-brand-row flex items-center border-b border-line ${collapsed ? 'flex-col gap-2 py-3 px-2' : 'justify-between px-4 py-3.5'}`}>
          <Link
            to="/"
            className="flex items-center gap-2 hover:opacity-90 transition-opacity"
            onClick={onClose}
            title="Cyphward — Sovereign Defense Platform"
          >
            <CyphwardLogo
              variant={collapsed ? 'mark' : 'full'}
              size={collapsed ? 22 : 20}
              showSubtitle={!collapsed}
            />
          </Link>
          <div className="flex items-center gap-1">
            {onToggleCollapse && (
              <button
                className="side-collapse-btn hidden md:inline-flex"
                onClick={onToggleCollapse}
                title={collapsed ? 'Expand sidebar (Ctrl+B)' : 'Collapse sidebar (Ctrl+B)'}
                aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              >
                {collapsed ? <PanelLeftOpen size={13} /> : <PanelLeftClose size={13} />}
              </button>
            )}
            {onClose && (
              <button
                className="side-collapse-btn sidebar-mobile-close md:hidden"
                onClick={onClose}
                title="Close Navigation"
                aria-label="Close Navigation"
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        <p className="eyebrow side-eyebrow">SECTIONS</p>
        <nav>
          {NAV.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              title={collapsed ? `LAYER ${n.idx} · ${n.label}` : undefined}
            >
              <n.icon size={15} strokeWidth={1.7} />
              <span className="idx">{n.idx}</span>
              <span className="nav-label">{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="side-foot">
          {/* Compact avatar visible only in collapsed mode */}
          <div
            className="side-avatar-compact"
            title={`${tenantName} · ${(tenant?.plan || 'GROWTH').toUpperCase()} PLAN`}
          >
            {tenantInitials}
            <span className="live-dot" />
          </div>

          {/* Full Tenant detail visible in expanded mode */}
          <p className="eyebrow">TENANT ENCLAVE</p>
          <p className="side-tenant mono font-medium truncate">{tenantName}</p>
          <div className="side-plan-row">
            <span className="tag">{(tenant?.plan || 'GROWTH').toUpperCase()} PLAN</span>
            <StatusChip level="ok">MONITORED</StatusChip>
          </div>

          <button
            className="side-out"
            onClick={doSignOut}
            title={collapsed ? 'Sign Out' : undefined}
          >
            <span className="side-out-text">SIGN OUT</span> <LogOut size={12} />
          </button>
        </div>
      </aside>
    </>
  );
}
