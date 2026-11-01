/**
 * The one client-side cache for read requests, shared by the customer app and the owner console
 * (docs/ui-motion-cache-2026-11-01/AUDIT.md, "Caching").
 *
 * Policy: stale-while-revalidate. A page that has been shown before paints its last data at once and asks the
 * server again in the background; a page never seen shows its skeleton. Rules:
 *  - memory only (a Map in this module), never Web Storage, so it dies with the tab and holds no customer data
 *    on disk;
 *  - every key is scoped: customer app = signed-in user id + active organisation id; owner console = the owner's
 *    email. Nothing is read or written without a scope;
 *  - the scope and a generation number are captured when a request STARTS. clearQueryCache() bumps the
 *    generation, so a response that was in flight across a sign-out, an organisation switch or a write is dropped
 *    instead of being stored under the new scope;
 *  - cleared on sign-in, sign-out, idle sign-out, organisation switch, a 401 in the owner console and after every
 *    write request (apiFetch / ownerFetch); write responses are never stored;
 *  - opt-in per read. Auth, MFA, billing, invoices and live scan progress never go through it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { loadSession } from './session';

type Entry = { data: unknown; at: number };

const store = new Map<string, Entry>();
let generation = 0;

/** Owner console scope, set by the console once its session is known (null when signed out). */
let ownerScope: string | null = null;

export type CacheSpace = 'app' | 'owner';

function activeOrgId(): string | null {
  try {
    return localStorage.getItem('cyphward-org-id') || sessionStorage.getItem('cyphward-org-id');
  } catch {
    return null;
  }
}

/** The scope reads and writes use right now, or null when nothing may be cached. */
export function currentScope(space: CacheSpace = 'app'): string | null {
  if (space === 'owner') return ownerScope ? `owner\u0000${ownerScope}` : null;
  const userId = loadSession()?.user?.id;
  const orgId = activeOrgId();
  if (!userId || !orgId) return null;
  return `app\u0000${userId}\u0000${orgId}`;
}

export function setOwnerScope(email: string | null): void {
  if (email !== ownerScope) clearQueryCache('owner');
  ownerScope = email;
}

/** Captured when a request starts; a write with an old ticket is dropped. */
export type CacheTicket = { scope: string | null; gen: number };

export function cacheTicket(space: CacheSpace = 'app'): CacheTicket {
  return { scope: currentScope(space), gen: generation };
}

function full(scope: string, key: string) {
  return `${scope}\u0000${key}`;
}

export function readQueryCache<T>(key: string, space: CacheSpace = 'app'): { data: T; at: number } | undefined {
  const scope = currentScope(space);
  if (!scope) return undefined;
  return store.get(full(scope, key)) as { data: T; at: number } | undefined;
}

/** Stores a read result if the scope and generation it started with are still current. Returns whether it did. */
export function writeQueryCache<T>(key: string, value: T, ticket: CacheTicket): boolean {
  if (!ticket.scope || ticket.gen !== generation || ticket.scope !== currentScope(ticket.scope.startsWith('owner') ? 'owner' : 'app')) return false;
  store.set(full(ticket.scope, key), { data: value, at: Date.now() });
  return true;
}

/** Drops every entry (or one space's entries) and invalidates every request already in flight. */
export function clearQueryCache(space?: CacheSpace): void {
  generation++;
  if (!space) {
    store.clear();
    return;
  }
  for (const k of [...store.keys()]) if (k.startsWith(`${space}\u0000`)) store.delete(k);
}

/** For tests and the audit: how many entries the cache holds. */
export function queryCacheSize(): number {
  return store.size;
}

export type CachedQuery<T> = {
  data: T | null;
  error: unknown;
  /** True only when there is nothing to show yet (first visit): render the skeleton. */
  loading: boolean;
  /** A request is running while cached or earlier data stays on screen. */
  refreshing: boolean;
  /** The data on screen belongs to the previous key (keepPrevious), shown until this key's data arrives. */
  placeholder: boolean;
  reload: () => Promise<void>;
};

/**
 * Read one resource through the cache. `key` null skips the request (for example while a parameter is unknown).
 * Revalidates on mount, on `reload()`, when the window regains focus (if `revalidateOnFocus`, throttled to
 * once per `focusThrottleMs`) and every `pollMs` while mounted (if given).
 */
export function useCachedQuery<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  { space = 'app', revalidateOnFocus = space === 'app', focusThrottleMs = 30_000, pollMs, keepPrevious = false }: {
    space?: CacheSpace; revalidateOnFocus?: boolean; focusThrottleMs?: number; pollMs?: number;
    /** On a key change with nothing cached (a filter or page change), keep the current rows until the new ones arrive. */
    keepPrevious?: boolean;
  } = {},
): CachedQuery<T> {
  const initial = key ? readQueryCache<T>(key, space) : undefined;
  const [data, setData] = useState<T | null>(initial ? initial.data : null);
  const [placeholder, setPlaceholder] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fetching, setFetching] = useState<boolean>(!!key);
  const latest = useRef<string | null>(key);
  const lastFetch = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // A new key shows that key's cached data (or nothing) at once; never the previous key's rows unless asked to.
  const shownKey = useRef(key);
  if (shownKey.current !== key) {
    shownKey.current = key;
    const cached = key ? readQueryCache<T>(key, space) : undefined;
    // Setting state during render is the documented way to reset derived state on a prop change.
    if (cached) { setData(cached.data); setPlaceholder(false); }
    else if (keepPrevious && data !== null) setPlaceholder(true);
    else { setData(null); setPlaceholder(false); }
    setError(null);
  }

  const run = useCallback(async () => {
    if (!key) return;
    latest.current = key;
    lastFetch.current = Date.now();
    const ticket = cacheTicket(space);
    setFetching(true);
    try {
      const value = await fetcherRef.current();
      // Another account or organisation by now: never show or store it. (A write in between only stops the
      // store: the response is still this workspace's, and the page reloads after its own writes.)
      if (latest.current !== key || ticket.scope !== currentScope(space)) return;
      writeQueryCache(key, value, ticket);
      setData(value);
      setPlaceholder(false);
      setError(null);
    } catch (e) {
      if (latest.current === key) setError(e);
    } finally {
      if (latest.current === key) setFetching(false);
    }
  }, [key, space]);

  useEffect(() => {
    void run();
  }, [run]);

  useEffect(() => {
    if (!revalidateOnFocus && !pollMs) return;
    const onFocus = () => {
      if (document.visibilityState === 'hidden') return;
      if (Date.now() - lastFetch.current >= focusThrottleMs) void run();
    };
    if (revalidateOnFocus) {
      window.addEventListener('focus', onFocus);
      document.addEventListener('visibilitychange', onFocus);
    }
    const timer = pollMs ? window.setInterval(() => { if (document.visibilityState !== 'hidden') void run(); }, pollMs) : undefined;
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
      if (timer) window.clearInterval(timer);
    };
  }, [run, revalidateOnFocus, focusThrottleMs, pollMs]);

  return { data, error, loading: data === null && fetching && !error, refreshing: data !== null && fetching, placeholder, reload: run };
}

/**
 * For pages with their own loader (lib/pageCache): run it again when the tab or window regains focus, at most once
 * per `throttleMs`, so a page left open shows current data when the person comes back. Not for pages with forms a
 * person may be filling in (a refresh would overwrite what they typed).
 */
export function useRevalidateOnFocus(fn: () => unknown, throttleMs = 30_000): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    let last = Date.now();
    const onFocus = () => {
      if (document.visibilityState === 'hidden' || Date.now() - last < throttleMs) return;
      last = Date.now();
      void ref.current();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [throttleMs]);
}
