import { ReactNode, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface Props {
  open: boolean;
  onClose: () => void;
  eyebrow?: string;
  children: ReactNode;
}

export default function Drawer({ open, onClose, eyebrow = 'DETAIL', children }: Props) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && open) onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, onClose]);

  useEffect(() => {
    if (open) {
      document.body.classList.add('drawer-open');
      return () => {
        document.body.classList.remove('drawer-open');
      };
    }
  }, [open]);

  if (typeof document === 'undefined') return null;

  return createPortal(
    <>
      <div className={`scrim ${open ? 'show' : ''}`} onClick={onClose} />
      <aside className={`drawer ${open ? 'open' : ''}`} role="dialog" aria-modal="true">
        <div className="drawer-handle md:hidden" onClick={onClose} />
        <div className="drawer-head">
          <p className="eyebrow">{eyebrow}</p>
          <button className="icon-btn" onClick={onClose} aria-label="Close detail">
            <X size={15} />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>,
    document.body
  );
}
