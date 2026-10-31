/* The bell and its panel (notifications phase 1). Used in the customer app header and the owner console header.
 *
 * Keyboard: the bell is a button (Enter/Space opens); focus moves to the panel heading; Tab walks the items and
 * their "Mark read" buttons; Escape closes and returns focus to the bell. A click outside closes it too.
 * The unread count is in the bell's accessible name. Errors show reviewed wording only (lib/notifications.ts).
 */
import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCheck, Settings as SettingsIcon } from 'lucide-react';
import {
  NOTIFY_EMPTY, NOTIFY_ERROR, NOTIFY_MARK_ERROR, NOTIFY_TITLE, SEVERITY_LABEL,
  groupByDay, safePath, timeLabel, useNotifications,
  type NotificationItem, type NotificationSource,
} from '../lib/notifications';

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

  useEffect(() => {
    if (!open) return;
    heading.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
        bell.current?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open]);

  const items = page?.notifications ?? [];
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

      {open && (
        <div id={panelId} className="notif-panel" role="dialog" aria-labelledby={headingId} data-testid="notif-panel">
          <div className="notif-head">
            <h2 id={headingId} ref={heading} tabIndex={-1} className="notif-title">{NOTIFY_TITLE}</h2>
            <div className="notif-head-tools">
              {settingsPath && (
                <button type="button" className="notif-tool" onClick={() => { setOpen(false); nav(settingsPath); }}
                        aria-label="Notification settings" title="Notification settings" data-testid="notif-settings">
                  <SettingsIcon size={14} aria-hidden="true" />
                </button>
              )}
              <button type="button" className="notif-tool notif-tool-text" disabled={count === 0}
                      onClick={async () => setMarkError(!(await markAllRead()))} data-testid="notif-read-all">
                <CheckCheck size={14} aria-hidden="true" /> Mark all read
              </button>
            </div>
          </div>

          <div className="notif-body" aria-busy={loading && !page}>
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
                    <li key={item.id} className={`notif-item ${item.read_at ? 'is-read' : 'is-unread'}`}
                        data-testid="notif-item" data-id={item.id} data-read={item.read_at ? 'true' : 'false'}>
                      <button type="button" className="notif-open" onClick={() => openItem(item)}>
                        <span className={`notif-sev sev-${item.severity}`}>
                          {SEVERITY_LABEL[item.severity] || 'Info'}
                          {!item.read_at && <span className="sr-only">, unread</span>}
                        </span>
                        <span className="notif-item-title">{item.title}</span>
                        {item.body && <span className="notif-item-body">{item.body}</span>}
                        <span className="notif-meta">
                          {timeLabel(item.created_at)}
                          {item.count && item.count > 1 ? ` · ${item.count} events` : ''}
                        </span>
                      </button>
                      {!item.read_at && (
                        <button type="button" className="notif-tool notif-mark" data-testid="notif-mark"
                                aria-label={`Mark read: ${item.title}`}
                                onClick={async () => setMarkError(!(await markRead(item.id)))}>
                          Mark read
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
