import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { lockScroll, unlockScroll } from '../../lib/scrollLock';

/**
 * The one accessible dialog used for every "view", "preview", form-in-a-popup and confirmation.
 *
 *   <Dialog open={!!viewing} onClose={() => setViewing(null)} title="Privacy policy">…</Dialog>
 *
 * What it provides (tested in frontend/scripts/check-compliance-page.mjs):
 *  - role="dialog", aria-modal, named by its title (or `ariaLabel` when there is no visible title).
 *  - Focus moves in on open (to `[data-autofocus]`, else the first control in the body, else the panel),
 *    Tab and Shift+Tab cycle inside it, Esc closes it, and focus returns to the opener on close.
 *  - The page behind is `inert` and scroll-locked. Dialogs can stack: only the top one reacts to keys.
 *  - A click on the backdrop closes it, unless `dirty` is set: then it asks before throwing input away.
 *  - Full screen on phones (sticky title bar with a 44px close button, safe-area padding, body scrolls inside).
 *
 * Put `data-autofocus` on the control that should start focused (Cancel for a destructive confirmation).
 * Inside a dialog, call `useDialogClose()` for a Cancel button so it asks first when `dirty` is true.
 */

export interface DialogProps {
  open: boolean;
  /** Called when the user dismisses the dialog (Esc, backdrop, close button). Not called while `dirty` until they confirm. */
  onClose: () => void;
  title?: ReactNode;
  /** Accessible name when `title` is not a plain visible heading. */
  ariaLabel?: string;
  icon?: ReactNode;
  /** A Tailwind `max-w-*` token (kept from the old Modal API) or any CSS width. */
  maxWidth?: string;
  className?: string;
  backdropClassName?: string;
  showCloseButton?: boolean;
  /** A small card that stays centred on phones (confirmations). Everything else is full screen on phones. */
  compact?: boolean;
  /** True while the dialog holds input that would be lost. Backdrop click, Esc and the close button then ask first. */
  dirty?: boolean;
  /** Pinned to the bottom of the dialog (primary actions). Scrolls with nothing; the body scrolls above it. */
  footer?: ReactNode;
  /** Where focus returns if the opener no longer exists (for example a row that re-rendered). */
  returnFocusTo?: () => HTMLElement | null;
  children: ReactNode;
}

const MAX_WIDTH_MAP: Record<string, string> = {
  'max-w-xs': '20rem', 'max-w-sm': '24rem', 'max-w-md': '28rem', 'max-w-lg': '32rem', 'max-w-xl': '36rem',
  'max-w-2xl': '42rem', 'max-w-3xl': '48rem', 'max-w-4xl': '56rem', 'max-w-5xl': '64rem',
};

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), summary, iframe, [tabindex]:not([tabindex="-1"])';

/** Open dialogs, bottom to top. Only the last one handles keys; the others are inert. */
const stack: string[] = [];
const nodes = new Map<string, HTMLElement>();

function syncInert() {
  if (typeof document === 'undefined') return;
  const root = document.getElementById('root');
  if (root) {
    if (stack.length > 0) root.setAttribute('inert', '');
    else root.removeAttribute('inert');
  }
  stack.forEach((id, i) => {
    const node = nodes.get(id);
    if (!node) return;
    if (i === stack.length - 1) node.removeAttribute('inert');
    else node.setAttribute('inert', '');
  });
}

/**
 * Drawers (components/Drawer.tsx) join the same stack, so a dialog over a drawer, or a drawer over a drawer,
 * behaves the same way: only the top layer handles Tab and Escape, and the layers under it are inert.
 */
export function enterLayer(id: string, node: HTMLElement) {
  if (!stack.includes(id)) stack.push(id);
  nodes.set(id, node);
  syncInert();
}
export function leaveLayer(id: string) {
  const at = stack.indexOf(id);
  if (at >= 0) stack.splice(at, 1);
  nodes.delete(id);
  syncInert();
}
export function isTopLayer(id: string) {
  return stack[stack.length - 1] === id;
}

function visibleFocusables(panel: HTMLElement): HTMLElement[] {
  return [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(el => {
    if (el.closest('[inert]') !== panel.closest('[inert]')) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && el.getClientRects().length > 0;
  });
}

const CloseContext = createContext<() => void>(() => {});
/** The dialog's close request: asks first when the dialog is `dirty`. Use it for Cancel buttons. */
export function useDialogClose() {
  return useContext(CloseContext);
}

export default function Dialog({
  open, onClose, title, ariaLabel, icon, maxWidth = 'max-w-2xl', className = '', backdropClassName = '',
  showCloseButton = true, compact = false, dirty = false, footer, returnFocusTo, children,
}: DialogProps) {
  const id = useId();
  const titleId = `${id}-title`;
  const [mounted, setMounted] = useState(open);
  const [isClosing, setIsClosing] = useState(false);
  const [asking, setAsking] = useState(false);
  const [cached, setCached] = useState<{ children: ReactNode; title: ReactNode; footer: ReactNode }>({ children, title, footer });
  const backdropRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const downOnBackdrop = useRef(false);
  const latest = useRef({ dirty, onClose, returnFocusTo });
  latest.current = { dirty, onClose, returnFocusTo };

  const resolvedMaxWidth = MAX_WIDTH_MAP[maxWidth]
    ? `min(${MAX_WIDTH_MAP[maxWidth]}, calc(100vw - 32px))`
    : maxWidth.startsWith('max-w-') ? undefined : maxWidth;

  useEffect(() => {
    if (open) {
      setMounted(true);
      setIsClosing(false);
      setCached({ children, title, footer });
    } else if (mounted) {
      setIsClosing(true);
      const timer = setTimeout(() => { setMounted(false); setIsClosing(false); setAsking(false); }, 200);
      return () => clearTimeout(timer);
    }
  }, [open, mounted, children, title, footer]);

  const requestClose = useCallback(() => {
    if (latest.current.dirty) setAsking(true);
    else latest.current.onClose();
  }, []);

  // Open: remember the opener, join the stack, lock the page, move focus in. Close: undo all of it and give focus back.
  useLayoutEffect(() => {
    if (!open || !mounted) return;
    const panel = panelRef.current;
    const backdrop = backdropRef.current;
    if (!panel || !backdrop) return;
    // Development re-runs effects once: keep the first opener rather than the dialog's own element.
    if (!openerRef.current || !openerRef.current.isConnected || panel.contains(openerRef.current)) {
      openerRef.current = document.activeElement instanceof HTMLElement && !panel.contains(document.activeElement) ? document.activeElement : openerRef.current;
    }
    stack.push(id);
    nodes.set(id, backdrop);
    syncInert();
    lockScroll();
    const target = panel.querySelector<HTMLElement>('[data-autofocus]')
      ?? (bodyRef.current ? visibleFocusables(bodyRef.current)[0] : undefined)
      ?? panel;
    target.focus({ preventScroll: true });
    return () => {
      const at = stack.indexOf(id);
      if (at >= 0) stack.splice(at, 1);
      nodes.delete(id);
      syncInert();
      unlockScroll();
      const opener = openerRef.current;
      // Wait until the whole commit is done, so a parent and its nested dialog finish closing before anyone takes focus.
      queueMicrotask(() => {
        if (stack.includes(id)) return; // re-opened straight away (React development re-run)
        const current = document.activeElement;
        // A page control already has focus (the user moved on): leave it there.
        if (current && current !== document.body && current.isConnected && !current.closest('.dialog-panel')) return;
        const usable = (el: HTMLElement | null): el is HTMLElement =>
          !!el && el !== document.body && el.isConnected && !el.closest('[inert]') && !(el as HTMLButtonElement).disabled;
        const give = (el: HTMLElement) => {
          if (!el.matches(FOCUSABLE)) el.setAttribute('tabindex', '-1');
          el.focus({ preventScroll: true });
          return document.activeElement === el;
        };
        // The opener, else (if it is gone or disabled) the dialog still open, else the page's tab panel or main area.
        if (usable(opener) && give(opener)) return;
        const topId = stack[stack.length - 1];
        const topNode = topId ? nodes.get(topId) : null;
        // The layer underneath may be another dialog (focus its panel) or a drawer (focus the drawer itself).
        const top = topNode ? (topNode.querySelector<HTMLElement>('.dialog-panel') ?? topNode) : null;
        if (usable(top ?? null) && give(top as HTMLElement)) return;
        const page = latest.current.returnFocusTo?.() ?? document.querySelector<HTMLElement>('[role="tabpanel"], main');
        if (usable(page)) give(page);
      });
    };
  }, [open, mounted, id]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        requestClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const panel = panelRef.current;
      if (!panel) return;
      const items = visibleFocusables(panel);
      if (items.length === 0) { e.preventDefault(); panel.focus(); return; }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (!panel.contains(active) || active === panel) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [open, id, requestClose]);

  if (!mounted || typeof document === 'undefined') return null;
  const shownTitle = title || cached.title;
  const shownFooter = footer || cached.footer;

  return createPortal(
    <>
    <div
      ref={backdropRef}
      className={`modal-backdrop dialog-backdrop ${backdropClassName} ${isClosing ? 'closing' : ''}`}
      onMouseDown={e => { downOnBackdrop.current = e.target === e.currentTarget; }}
      onClick={e => {
        if (e.target === e.currentTarget && downOnBackdrop.current) requestClose();
        downOnBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={shownTitle ? titleId : undefined}
        aria-label={shownTitle ? undefined : ariaLabel}
        tabIndex={-1}
        className={`modal-panel dialog-panel ${compact ? 'dialog-card' : ''} w-full ${maxWidth} shadow-2xl ${className} ${isClosing ? 'closing' : ''}`}
        style={resolvedMaxWidth ? { maxWidth: resolvedMaxWidth } : undefined}
      >
        {(shownTitle || showCloseButton) && (
          <div className="dialog-bar no-print">
            <div className="flex items-center gap-2 min-w-0 pr-2">
              {icon && <span className="text-accent shrink-0" aria-hidden="true">{icon}</span>}
              {shownTitle && (
                <h2 id={titleId} className="mono font-semibold text-ink text-xs sm:text-sm uppercase tracking-wider truncate m-0">
                  {shownTitle}
                </h2>
              )}
            </div>
            {showCloseButton && (
              <button type="button" onClick={requestClose} aria-label="Close dialog" className="dialog-close btn-tactile">
                <X size={18} />
              </button>
            )}
          </div>
        )}
        <CloseContext.Provider value={requestClose}>
          <div ref={bodyRef} className="dialog-body">{children || cached.children}</div>
          {shownFooter && <div className="dialog-footer">{shownFooter}</div>}
        </CloseContext.Provider>
      </div>
    </div>
      {asking && (
        <Dialog open onClose={() => setAsking(false)} title="Discard your changes?" maxWidth="max-w-sm" compact>
          <div className="space-y-4">
            <p className="text-sm text-soft leading-relaxed">You have not saved what you typed. If you close this window, it is lost.</p>
            <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
              <button type="button" className="btn btn-ghost justify-center touch-target" onClick={() => { setAsking(false); onClose(); }}>Discard changes</button>
              <button type="button" className="btn btn-solid justify-center touch-target" data-autofocus onClick={() => setAsking(false)}>Keep editing</button>
            </div>
          </div>
        </Dialog>
      )}
    </>,
    document.body,
  );
}
