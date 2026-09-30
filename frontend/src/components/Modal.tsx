import React, { ReactNode, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { lockScroll, unlockScroll } from '../lib/scrollLock';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  icon?: ReactNode;
  maxWidth?: string;
  className?: string;
  backdropClassName?: string;
  children: ReactNode;
  showCloseButton?: boolean;
}

const MAX_WIDTH_MAP: Record<string, string> = {
  'max-w-xs': '20rem',
  'max-w-sm': '24rem',
  'max-w-md': '28rem',
  'max-w-lg': '32rem',
  'max-w-xl': '36rem',
  'max-w-2xl': '42rem',
  'max-w-3xl': '48rem',
  'max-w-4xl': '56rem',
  'max-w-5xl': '64rem',
};

export default function Modal({
  open,
  onClose,
  title,
  icon,
  maxWidth = 'max-w-2xl',
  className = '',
  backdropClassName = '',
  children,
  showCloseButton = true,
}: ModalProps) {
  const [mounted, setMounted] = useState(open);
  const [isClosing, setIsClosing] = useState(false);
  const [cachedChildren, setCachedChildren] = useState<ReactNode>(children);
  const [cachedTitle, setCachedTitle] = useState<ReactNode>(title);

  const resolvedMaxWidth = MAX_WIDTH_MAP[maxWidth]
    ? `min(${MAX_WIDTH_MAP[maxWidth]}, calc(100vw - 32px))`
    : maxWidth.startsWith('max-w-')
    ? undefined
    : maxWidth;

  useEffect(() => {
    if (open) {
      setMounted(true);
      setIsClosing(false);
      setCachedChildren(children);
      setCachedTitle(title);
    } else if (mounted) {
      setIsClosing(true);
      const timer = setTimeout(() => {
        setMounted(false);
        setIsClosing(false);
      }, 200);
      return () => clearTimeout(timer);
    }
  }, [open, mounted, children, title]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose();
      }
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

  if (!mounted || typeof document === 'undefined') return null;

  const displayChildren = children || cachedChildren;
  const displayTitle = title || cachedTitle;

  return createPortal(
    <div
      className={`modal-backdrop ${backdropClassName} ${isClosing ? 'closing' : ''}`}
      onClick={e => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`modal-panel w-full ${maxWidth} p-4 sm:p-6 space-y-4 shadow-2xl max-h-[85vh] max-h-[85dvh] overflow-y-auto ${className} ${isClosing ? 'closing' : ''}`}
        style={resolvedMaxWidth ? { maxWidth: resolvedMaxWidth } : undefined}
        onClick={e => e.stopPropagation()}
      >
        {(displayTitle || showCloseButton) && (
          <div className="flex items-center justify-between pb-3 border-b border-line no-print">
            <div className="flex items-center gap-2 min-w-0 pr-2">
              {icon && <span className="text-accent shrink-0">{icon}</span>}
              {displayTitle && (
                <div className="mono font-semibold text-ink text-xs sm:text-sm uppercase tracking-wider truncate">
                  {displayTitle}
                </div>
              )}
            </div>
            {showCloseButton && (
              <button
                onClick={onClose}
                className="p-1.5 sm:p-1 rounded hover:bg-inset text-soft hover:text-ink mono text-xs transition-colors btn-tactile min-w-[34px] min-h-[34px] flex items-center justify-center shrink-0"
                aria-label="Close dialog"
              >
                <X size={16} />
              </button>
            )}
          </div>
        )}
        <div>{displayChildren}</div>
      </div>
    </div>,
    document.body
  );
}

