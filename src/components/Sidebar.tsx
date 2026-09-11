import { NavLink, useNavigate, Link } from 'react-router-dom';
import { Activity, ShieldCheck, Radar, Gauge, GraduationCap, MessageSquare, LogOut, Globe, Sparkles } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';
import StatusChip from './StatusChip';

const NAV = [
  { to: '/', label: 'COMMAND', idx: '01', icon: Activity, end: true },
  { to: '/comply', label: 'COMPLY', idx: '02', icon: ShieldCheck, end: false },
  { to: '/detect', label: 'DETECT', idx: '03', icon: Radar, end: false },
  { to: '/score', label: 'SCORE', idx: '04', icon: Gauge, end: false },
  { to: '/academy', label: 'ACADEMY', idx: '05', icon: GraduationCap, end: false },
  { to: '/copilot', label: 'COPILOT', idx: '06', icon: MessageSquare, end: false },
];

export default function Sidebar({ open = false, onClose }: { open?: boolean; onClose?: () => void }) {
  const { tenant, signOut } = useAuth();
  const nav = useNavigate();
  const toast = useToast();

  const doSignOut = () => {
    signOut();
    toast('Session closed — see you on the next layer.');
    nav('/login', { replace: true });
  };

  return (
    <>
      <div className={`side-scrim ${open ? 'show' : ''}`} onClick={onClose} />
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <Link to="/landing" className="side-brand hover:opacity-90 transition-opacity" onClick={onClose}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
            <path d="M4 6h16M4 11h10M4 16h13" />
          </svg>
          <span className="tracking-wider">CYPHWARD</span>
        </Link>

        <p className="eyebrow side-eyebrow">SECTIONS</p>
        <nav>
          {NAV.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
            >
              <n.icon size={15} strokeWidth={1.7} />
              <span className="idx">{n.idx}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 my-3">
          <Link
            to="/landing"
            className="flex items-center gap-2 p-2 rounded text-[10.5px] mono text-soft border border-line hover:border-ink hover:text-ink transition-colors"
            onClick={onClose}
          >
            <Globe size={13} className="text-accent" />
            <span>PUBLIC PLATFORM</span>
            <span className="ml-auto text-[9px] tag py-0 px-1">OVERVIEW</span>
          </Link>
        </div>

        <div className="side-foot">
          <p className="eyebrow">TENANT ENCLAVE</p>
          <p className="side-tenant mono font-medium truncate">{tenant?.name || 'Acme Traders Ltd'}</p>
          <div className="side-plan-row">
            <span className="tag">{(tenant?.plan || 'GROWTH').toUpperCase()} PLAN</span>
            <StatusChip level="ok">MONITORED</StatusChip>
          </div>
          <button className="side-out" onClick={doSignOut}>
            SIGN OUT <LogOut size={12} />
          </button>
        </div>
      </aside>
    </>
  );
}
