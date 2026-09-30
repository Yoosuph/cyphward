import { NavLink, useLocation } from 'react-router-dom';
import {
  Activity,
  Server,
  ShieldAlert,
  Radar,
  Menu,
  Search,
} from 'lucide-react';

interface Props {
  onPalette: () => void;
  onOpenMenu?: () => void;
  openAlertsCount?: number;
}

const NAV_ITEMS = [
  { to: '/', label: 'CMD', full: 'Overview Command', idx: '01', icon: Activity, end: true },
  { to: '/assets', label: 'ASSETS', full: 'Attack Surface Assets', idx: '02', icon: Server, end: false },
  { to: '/findings', label: 'FINDINGS', full: 'Vulnerability Findings', idx: '03', icon: ShieldAlert, end: false, hasBadge: true },
  { to: '/scans', label: 'SCANS', full: 'Recon & Scan Pipelines', idx: '04', icon: Radar, end: false },
];

export default function ButtonPlate({
  onPalette,
  onOpenMenu,
  openAlertsCount = 5,
}: Props) {
  const location = useLocation();

  const isItemActive = (to: string, end?: boolean) => {
    if (to === '/') {
      return location.pathname === '/' || location.pathname === '/overview' || location.pathname === '/dashboard';
    }
    return end ? location.pathname === to : location.pathname.startsWith(to);
  };

  return (
    <>
      {/* Smooth bottom gradient scrim so content gracefully fades behind the floating dock */}
      <div className="button-plate-scrim" aria-hidden="true" />

      <nav className="button-plate-wrapper" aria-label="Mobile sovereign navigation dock">
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

          {/* Full Navigation Drawer / Rest of Pages Trigger */}
          {onOpenMenu ? (
            <button
              type="button"
              className="plate-btn"
              onClick={onOpenMenu}
              title="Open Navigation Menu — View All Modules"
              aria-label="Open Navigation Menu"
            >
              <div className="relative flex items-center justify-center">
                <Menu size={16} strokeWidth={1.8} />
              </div>
              <span className="plate-lbl">MENU</span>
            </button>
          ) : (
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
          )}
        </div>
      </nav>
    </>
  );
}
