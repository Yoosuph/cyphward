import { NavLink, useLocation } from 'react-router-dom';
import {
  Activity, ShieldCheck, Radar, Gauge, GraduationCap,
  MessageSquare, Search
} from 'lucide-react';

interface Props {
  onPalette: () => void;
  openAlertsCount?: number;
}

const NAV_ITEMS = [
  { to: '/', label: 'CMD', full: 'Command', idx: '01', icon: Activity, end: true },
  { to: '/comply', label: 'CMP', full: 'Comply', idx: '02', icon: ShieldCheck, end: false },
  { to: '/detect', label: 'DET', full: 'Detect', idx: '03', icon: Radar, end: false, hasBadge: true },
  { to: '/score', label: 'SCR', full: 'Score', idx: '04', icon: Gauge, end: false },
  { to: '/academy', label: 'ACD', full: 'Academy', idx: '05', icon: GraduationCap, end: false },
  { to: '/copilot', label: 'AI', full: 'Copilot', idx: '06', icon: MessageSquare, end: false },
];

export default function ButtonPlate({ onPalette, openAlertsCount = 5 }: Props) {
  const location = useLocation();

  const isItemActive = (to: string, end?: boolean) => {
    if (to === '/') {
      return location.pathname === '/' || location.pathname === '/dashboard';
    }
    return end ? location.pathname === to : location.pathname.startsWith(to);
  };

  return (
    <>
      {/* Smooth bottom gradient scrim so content gracefully fades behind the floating dock */}
      <div className="button-plate-scrim" aria-hidden="true" />

      <nav className="button-plate-wrapper" aria-label="Mobile navigation plate">
        <div className="button-plate">
        {NAV_ITEMS.map(item => {
          const active = isItemActive(item.to, item.end);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={`plate-btn ${active ? 'active' : ''}`}
              title={item.full}
            >
              <div className="relative flex items-center justify-center">
                <item.icon size={16} strokeWidth={active ? 2.2 : 1.8} />
                {item.hasBadge && openAlertsCount > 0 && (
                  <span className="plate-badge" />
                )}
              </div>
              <span className="plate-lbl">{item.label}</span>
            </NavLink>
          );
        })}

        {/* Quick Palette / Search Action */}
        <button
          type="button"
          className="plate-btn plate-action-btn"
          onClick={onPalette}
          title="Search / Command Palette (⌘K)"
          aria-label="Open Command Palette"
        >
          <Search size={16} strokeWidth={2} />
          <span className="plate-lbl">⌘K</span>
        </button>
      </div>
    </nav>
  </>
);
}
