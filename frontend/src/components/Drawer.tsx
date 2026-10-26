import { ReactNode, useEffect, useId, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { lockScroll, unlockScroll } from '../lib/scrollLock';
import { enterLayer, isTopLayer, leaveLayer } from './ui/Dialog';

interface Props {
  open: boolean;
  onClose: () => void;
  eyebrow?: string;
  title?: ReactNode;
  icon?: ReactNode;
  size?: 'default' | 'lg' | 'xl' | '2xl';
  widthClass?: string;
  headerExtra?: ReactNode;
  children: ReactNode;
}

export default function Drawer({
  open,
  onClose,
  eyebrow = 'DETAIL',
  title,
  icon,
  size = 'default',
  widthClass,
  headerExtra,
  children,
}: Props) {
  const [cachedChildren, setCachedChildren] = useState<ReactNode>(children);
  const [cachedTitle, setCachedTitle] = useState<ReactNode>(title);
  const [cachedEyebrow, setCachedEyebrow] = useState<string>(eyebrow);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const layerId = useId();

  const handleTouchStart = (e: React.TouchEvent) => {
    touchStartRef.current = {
      x: e.touches[0].clientX,
      y: e.touches[0].clientY,
    };
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (!touchStartRef.current) return;
    const dy = e.changedTouches[0].clientY - touchStartRef.current.y;
    const dx = Math.abs(e.changedTouches[0].clientX - touchStartRef.current.x);
    if (window.innerWidth <= 900 && dy > 50 && dx < 80) {
      onClose();
    } else if (window.innerWidth > 900 && e.changedTouches[0].clientX - touchStartRef.current.x > 60 && Math.abs(dy) < 75) {
      onClose();
    }
    touchStartRef.current = null;
  };

  useEffect(() => {
    if (open) {
      if (children) setCachedChildren(children);
      if (title) setCachedTitle(title);
      if (eyebrow) setCachedEyebrow(eyebrow);
    }
  }, [open, children, title, eyebrow]);

  // Keyboard: a closed drawer is inert (its off-screen controls leave the Tab order). An open one joins the shared
  // overlay stack (components/ui/Dialog.tsx), so the page and any layer under it are inert and only the top layer
  // handles Tab and Escape; it takes focus, and hands focus back to whatever opened it when it closes.
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    (panel as HTMLElement & { inert: boolean }).inert = !open;
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    enterLayer(layerId, panel);
    const id = window.setTimeout(() => closeRef.current?.focus({ preventScroll: true }), 0);
    return () => {
      window.clearTimeout(id);
      leaveLayer(layerId);
      (panel as HTMLElement & { inert: boolean }).inert = true;
      if (opener && opener.isConnected && !opener.closest('[inert]')) opener.focus({ preventScroll: true });
    };
  }, [open, layerId]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // A dialog or a later drawer on top of this one owns the keyboard.
      if (!open || !isTopLayer(layerId)) return;
      if (e.key === 'Escape') onClose();
      if (e.key === 'Tab' && panelRef.current) {
        const items = [...panelRef.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')].filter(el => el.offsetParent !== null);
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (!panelRef.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
        else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose, layerId]);

  useEffect(() => {
    if (open) {
      lockScroll();
      return () => {
        unlockScroll();
      };
    }
  }, [open]);

  if (typeof document === 'undefined') return null;

  const sizeClass = widthClass
    ? widthClass
    : size === '2xl'
    ? 'drawer-2xl'
    : size === 'xl'
    ? 'drawer-xl'
    : size === 'lg'
    ? 'drawer-lg'
    : '';

  const displayChildren = children || cachedChildren;
  const displayTitle = title || cachedTitle;
  const displayEyebrow = eyebrow || cachedEyebrow;

  return createPortal(
    <>
      <div
        className={`scrim ${open ? 'show' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={panelRef}
        className={`drawer ${sizeClass} ${open ? 'open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-labelledby={displayTitle ? titleId : undefined}
        aria-label={displayTitle ? undefined : displayEyebrow}
      >
        <div
          className="drawer-handle md:hidden"
          aria-hidden="true"
          onClick={onClose}
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
          title="Drag down or tap to close"
        />
        <div
          className="drawer-head flex items-center justify-between"
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div className="flex items-center gap-2">
            {icon && <span className="text-accent shrink-0">{icon}</span>}
            <div>
              {displayEyebrow && <p className="eyebrow">{displayEyebrow}</p>}
              {displayTitle && (
                <h2 id={titleId} className="mono font-bold text-sm text-ink uppercase tracking-wider mt-0.5">
                  {displayTitle}
                </h2>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {headerExtra}
            <button
              ref={closeRef}
              type="button"
              className="icon-btn min-w-[44px] min-h-[44px] flex items-center justify-center"
              onClick={onClose}
              aria-label="Close detail drawer"
            >
              <X size={15} />
            </button>
          </div>
        </div>
        <div className="drawer-body flex-1 overflow-y-auto">{displayChildren}</div>
      </aside>
    </>,
    document.body
  );
}

