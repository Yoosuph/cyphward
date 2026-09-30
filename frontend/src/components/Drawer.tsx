import { ReactNode, useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { lockScroll, unlockScroll } from '../lib/scrollLock';

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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

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
        className={`drawer ${sizeClass} ${open ? 'open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <div
          className="drawer-handle md:hidden"
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
                <h3 className="mono font-bold text-sm text-ink uppercase tracking-wider mt-0.5">
                  {displayTitle}
                </h3>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {headerExtra}
            <button
              className="icon-btn min-w-[36px] min-h-[36px] flex items-center justify-center"
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

