/* The bell and its panel (notifications phase 1). Used in the customer app header and the owner console header.
 *
 * Keyboard: the bell is a button (Enter/Space opens); focus moves to the panel heading; Tab and Shift+Tab walk the
 * panel's controls and wrap inside it; Escape or the close button closes and returns focus to the bell. A click
 * outside closes it too. The unread count is in the bell's accessible name. Errors show reviewed wording only
 * (lib/notifications.ts).
 *
 * Phones and tablets (900px and narrower): the panel is a full-width sheet under the top bar with a 16px gutter
 * (plus any safe-area inset). It is rendered into <body> because the top bar's backdrop blur would otherwise pin a
 * fixed panel to the bar and draw the bottom dock over it. Its header stays put and the list scrolls inside it.
 * Wider screens keep the popover under the bell.
 *
 * Clear (a button on every row, or a swipe on touch screens; components/NotificationRow.tsx) hides the row for as
 * long as the app stays open and marks it read through the existing mark-read route. Nothing is deleted: after a
 * reload the row is back, as read. A second clear of the same row sends nothing.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCheck, Settings as SettingsIcon, X } from 'lucide-react';
import {
  NOTIFY_CLEARED, NOTIFY_CLOSE, NOTIFY_EMPTY, NOTIFY_ERROR, NOTIFY_MARK_ERROR, NOTIFY_TITLE,
  groupByDay, safePath, useNotifications,
  type NotificationItem, type NotificationSource,
} from '../lib/notifications';
import { useMediaQuery } from '../lib/useMediaQuery';
import NotificationRow from './NotificationRow';

/** Where the panel becomes a sheet (the same breakpoint as the bottom dock and the 44px touch targets). */
export const SHEET_QUERY = '(max-width: 900px)';

interface Props {
  source: NotificationSource;
  /** Where an item opens. Defaults to the item's own in-app path. */
  linkFor?: (item: NotificationItem) => string | null;
  /** The preferences page, when this app has one. */
  settingsPath?: string;
  enabled?: boolean;
}

export default function NotificationBell({ source, linkFor, settingsPath, enabled = true }: Props) {
  const [open, setOpen] = useState(false);
  const [markError, setMarkError] = useState(false);
  const { page, count, error, loading, refresh, markRead, markAllRead } = useNotifications(source, open, enabled);
  const nav = useNavigate();
  const panelId = useId();
  const headingId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const bell = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const sheet = useMediaQuery(SHEET_QUERY);
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [sheetTop, setSheetTop] = useState<number | null>(null);

  // Cleared rows stay hidden while the app is open, across closes and list reloads (the server still lists them).
  const [cleared, setCleared] = useState<ReadonlySet<string>>(() => new Set());
  const clearing = useRef(new Set<string>());  // cleared or being cleared: a second clear sends nothing
  const [announce, setAnnounce] = useState('');
  const focusAfterClear = useRef<string | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    bell.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) { setAnnounce(''); return; }  // a reopened panel starts with nothing to announce
    heading.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return;
      }
      // Keep focus inside the open panel: Tab and Shift+Tab wrap around its controls.
      if (e.key !== 'Tab' || !panel.current) return;
      const stops = [heading.current, ...panel.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]')]
        .filter((el): el is HTMLElement => Boolean(el));
      if (!stops.length) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const at = document.activeElement as HTMLElement | null;
      const inside = Boolean(at && panel.current.contains(at));
      if (e.shiftKey && (!inside || at === first)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (!inside || at === last)) { e.preventDefault(); first.focus(); }
    };
    // The sheet lives in <body>, outside the bell's wrapper, so a press inside either one keeps the panel open.
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (wrap.current?.contains(target) || panel.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open, close]);

  // The sheet hangs 8px under the top bar's real bottom edge (the bar already sits below any safe-area inset).
  useLayoutEffect(() => {
    if (!open || !sheet) return;
    const measure = () => {
      const bar = wrap.current?.closest('header') ?? wrap.current;
      if (bar) setSheetTop(Math.max(0, Math.round(bar.getBoundingClientRect().bottom)) + 8);
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, { passive: true });
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure);
    };
  }, [open, sheet]);

  const items = (page?.notifications ?? []).filter(n => !cleared.has(n.id));
  const label = count > 0 ? `${NOTIFY_TITLE}, ${count} unread` : `${NOTIFY_TITLE}, none unread`;
  const shown = count > 99 ? '99+' : String(count);

  const openItem = async (item: NotificationItem) => {
    if (!item.read_at) setMarkError(!(await markRead(item.id)));
    const to = linkFor ? linkFor(item) : safePath(item.link);
    if (to) {
      setOpen(false);
      nav(to);
    }
  };

  const clearItem = async (item: NotificationItem) => {
    if (clearing.current.has(item.id)) return;
    clearing.current.add(item.id);
    // When focus is on the row being cleared, it moves to the next row (or the one before, or the heading).
    const at = document.activeElement;
    if (at && panel.current?.querySelector(`[data-testid="notif-item"][data-id="${CSS.escape(item.id)}"]`)?.contains(at)) {
      const i = items.findIndex(n => n.id === item.id);
      focusAfterClear.current = (items[i + 1] ?? items[i - 1])?.id ?? '';
    }
    setMarkError(false);
    setCleared(s => new Set(s).add(item.id));
    // Marking read again is harmless (the route is idempotent); the unread count drops only if the row was unread.
    const ok = await markRead(item.id);
    if (ok) {
      setAnnounce('');
      window.setTimeout(() => setAnnounce(NOTIFY_CLEARED), 50);  // emptied first so a second clear is announced too
    } else {
      clearing.current.delete(item.id);
      setCleared(s => { const next = new Set(s); next.delete(item.id); return next; });
      setMarkError(true);
    }
  };

  useLayoutEffect(() => {
    const target = focusAfterClear.current;
    if (target === null || !panel.current) return;
    focusAfterClear.current = null;
    const next = target ? panel.current.querySelector<HTMLElement>(`[data-testid="notif-item"][data-id="${CSS.escape(target)}"] .notif-open`) : null;
    (next ?? heading.current)?.focus();
  }, [cleared]);

  const panelStyle = sheet && sheetTop !== null ? ({ '--notif-sheet-top': `${sheetTop}px` } as CSSProperties) : undefined;
  const body = (
    <div id={panelId} ref={panel} className={`notif-panel${sheet ? ' is-sheet' : ''}`} style={panelStyle}
         role="dialog" aria-labelledby={headingId} data-testid="notif-panel">
      <div className="notif-head">
        <h2 id={headingId} ref={heading} tabIndex={-1} className="notif-title">{NOTIFY_TITLE}</h2>
        <div className="notif-head-tools">
          {settingsPath && (
            <button type="button" className="notif-tool" onClick={() => { setOpen(false); nav(settingsPath); }}
                    aria-label="Notification settings" title="Notification settings" data-testid="notif-settings">
              <SettingsIcon size={14} aria-hidden="true" />
            </button>
          )}
          <button type="button" className="notif-tool notif-tool-text" disabled={count === 0} title="Mark all read"
                  onClick={async () => setMarkError(!(await markAllRead()))} data-testid="notif-read-all">
            <CheckCheck size={14} aria-hidden="true" /> <span className="notif-read-all-label">Mark all read</span>
          </button>
          <button type="button" className="notif-tool notif-close" onClick={close}
                  aria-label={NOTIFY_CLOSE} title={NOTIFY_CLOSE} data-testid="notif-close">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="notif-body" aria-busy={loading && !page}>
        <p className="sr-only" role="status" aria-live="polite" data-testid="notif-announce">{announce}</p>
        {markError && <p className="notif-note" role="alert">{NOTIFY_MARK_ERROR}</p>}
        {error && (
          <div className="notif-state" role="alert" data-testid="notif-error">
            <p>{NOTIFY_ERROR}</p>
            <button type="button" className="notif-tool notif-tool-text" onClick={refresh}>Try again</button>
          </div>
        )}
        {!error && page && items.length === 0 && <p className="notif-state" data-testid="notif-empty">{NOTIFY_EMPTY}</p>}
        {!error && !page && <p className="notif-state">Loading…</p>}
        {!error && items.length > 0 && groupByDay(items).map(group => (
          <section key={group.label} aria-label={group.label}>
            <p className="notif-day">{group.label}</p>
            <ul className="notif-list">
              {group.items.map(item => (
                <NotificationRow key={item.id} item={item} reduceMotion={reduceMotion} onOpen={openItem}
                                 onMark={async n => setMarkError(!(await markRead(n.id)))} onClear={clearItem} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );

  return (
    <div className="notif-wrap" ref={wrap}>
      <button
        ref={bell}
        type="button"
        className="icon-btn hover-lift notif-bell"
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => { setOpen(o => !o); setMarkError(false); }}
        data-testid="notif-bell"
      >
        <Bell size={15} aria-hidden="true" />
        {count > 0 && <span className="notif-badge" data-testid="notif-count" aria-hidden="true">{shown}</span>}
      </button>

      {open && (sheet && typeof document !== 'undefined' ? createPortal(body, document.body) : body)}
    </div>
  );
}
