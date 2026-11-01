/* Notifications phase 1 (backend/app/services/notifications.py): the bell's data, wording and polling.
 *
 * The customer bell asks for the newest page of notifications (which carries the unread count) every 60 seconds while
 * the tab is visible, and again when the tab or window comes back into focus. A source with a count-only call (the
 * owner console) polls only that call, open or closed: the count route is not counted as session activity and is
 * not audited, so an idle owner session still signs out. Its list is fetched only when the panel opens and after a
 * mark. No websockets in phase 1.
 * The customer app and the owner console share this module; each passes its own source.
 *
 * Wording is reviewed: plain English, no claim language (backend/tests/test_ux_copy_claims.py). A failed request
 * shows NOTIFY_ERROR, never the server's text.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type NotificationSeverity = 'info' | 'warning' | 'critical';

export interface NotificationItem {
  id: string;
  kind: string;
  category: string;
  severity: NotificationSeverity | string;
  title: string;
  body?: string | null;
  link?: string | null;
  count?: number;
  read_at?: string | null;
  created_at: string;
  org_id?: string;
  org_name?: string | null;
}

export interface NotificationPage {
  notifications: NotificationItem[];
  unread_count: number;
  has_more?: boolean;
}

export interface NotificationPreference {
  category: string;
  label: string;
  hint: string;
  in_app: boolean;
  email: boolean;
}

/** Where a bell reads from and writes to. Every call throws on failure; the bell shows reviewed wording. */
export interface NotificationSource {
  list(limit: number): Promise<NotificationPage>;
  markRead(id: string): Promise<unknown>;
  markAllRead(): Promise<unknown>;
  /** Owner console: the count-only poll. The list is audited and counts as activity, so it is never polled. */
  unreadCount?(): Promise<number>;
}

export const POLL_MS = 60_000;
export const PAGE_SIZE = 50;

export const NOTIFY_TITLE = 'Notifications';
export const NOTIFY_EMPTY = 'Nothing new. Scan results, findings and account changes will show here.';
export const NOTIFY_ERROR = 'Notifications could not be loaded. Try again in a moment.';
export const NOTIFY_MARK_ERROR = 'That could not be marked as read. Try again in a moment.';
export const PREFS_ERROR = 'Your notification settings could not be loaded. Try again in a moment.';
export const PREFS_SAVE_ERROR = 'That setting could not be saved. Nothing was changed.';
export const PREFS_NOTE =
  'Email goes out for critical alerts, such as a critical finding or a suspension, and for compliance reminders ' +
  '(an answer about to expire, the six-monthly report). Everything else stays in the app.';

export const SEVERITY_LABEL: Record<string, string> = { info: 'Info', warning: 'Warning', critical: 'Critical' };

/** "Today", "Yesterday", else a short date. Days follow the browser's clock. */
export function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'Earlier';
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(now) - start(d)) / 86_400_000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
}

/** Newest first, grouped by day (the server already orders newest first). */
export function groupByDay(items: NotificationItem[], now = new Date()): { label: string; items: NotificationItem[] }[] {
  const groups: { label: string; items: NotificationItem[] }[] = [];
  for (const item of items) {
    const label = dayLabel(item.created_at, now);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}

export function timeLabel(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** A link the bell may follow: an in-app path only. */
export function safePath(link?: string | null): string | null {
  return typeof link === 'string' && link.startsWith('/') && !link.startsWith('//') ? link : null;
}

/** Poll while visible, refresh on focus (see the module note for which call each source polls). */
export function useNotifications(source: NotificationSource, open: boolean, enabled = true) {
  const [page, setPage] = useState<NotificationPage | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const busy = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;

  // A list load asked for while another call is in flight is queued, never dropped: it runs as soon as that call
  // ends (otherwise a count poll in flight when the panel opens would leave the panel on "Loading…").
  const listQueued = useRef(false);

  /** `list`: load the page (panel opened, or after a mark). Otherwise a poll. */
  const load = useCallback(async (list: boolean): Promise<void> => {
    if (!enabled) return;
    if (busy.current) {
      if (list) listQueued.current = true;
      return;  // a poll that finds a call in flight is simply skipped; the next tick asks again
    }
    if (!list && typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    busy.current = true;
    setLoading(true);
    try {
      if (!list && source.unreadCount) {
        setCount(await source.unreadCount());
      } else {
        const next = await source.list(PAGE_SIZE);
        setPage(next);
        setCount(next.unread_count || 0);
      }
      setError(false);
    } catch {
      setError(true);
    } finally {
      busy.current = false;
      setLoading(false);
      if (listQueued.current) {
        listQueued.current = false;
        void load(true);  // the list load that arrived while this call was in flight
      }
    }
  }, [source, enabled]);

  const poll = useCallback(() => load(false), [load]);
  const refresh = useCallback(() => load(true), [load]);

  useEffect(() => {
    if (!enabled) return;
    poll();
    const timer = window.setInterval(poll, POLL_MS);
    const onVisible = () => { if (document.visibilityState === 'visible') poll(); };
    window.addEventListener('focus', poll);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', poll);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [poll, enabled]);

  useEffect(() => { if (open) refresh(); }, [open, refresh]);

  /** Mark one row read in place (optimistic), then reload the list. Returns false when the server refused. */
  const markRead = useCallback(async (id: string) => {
    const before = page;
    const wasUnread = Boolean(before?.notifications.find(n => n.id === id && !n.read_at));
    setPage(p => p && { ...p, unread_count: Math.max(0, p.unread_count - (wasUnread ? 1 : 0)),
      notifications: p.notifications.map(n => (n.id === id && !n.read_at ? { ...n, read_at: new Date().toISOString() } : n)) });
    setCount(c => Math.max(0, c - (wasUnread ? 1 : 0)));
    try {
      await source.markRead(id);
      return true;
    } catch {
      setPage(before);
      return false;
    } finally {
      if (openRef.current) refresh(); else poll();
    }
  }, [page, source, refresh, poll]);

  const markAllRead = useCallback(async () => {
    try {
      await source.markAllRead();
      return true;
    } catch {
      return false;
    } finally {
      if (openRef.current) refresh(); else poll();
    }
  }, [source, refresh, poll]);

  return { page, count, error, loading, refresh, markRead, markAllRead };
}
