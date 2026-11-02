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

/** Whether a request still belongs to the current session, workspace and cache generation. */
export function isCacheTicketCurrent(ticket: CacheTicket): boolean {
  return !!ticket.scope && ticket.gen === generation
    && ticket.scope === currentScope(ticket.scope.startsWith('owner\u0000') ? 'owner' : 'app');
}

/** Stores a read result only while its request ticket is current. */
export function writeQueryCache<T>(key: string, value: T, ticket: CacheTicket): boolean {
  if (!isCacheTicketCurrent(ticket)) return false;
  store.set(full(ticket.scope!, key), { data: value, at: Date.now() });
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

/**
 * Guard every asynchronous state update, including errors/loading, against superseded requests.
 * If only the cache generation changed, isLatest() permits a replacement read on settlement;
 * isCurrent() must still pass before showing or storing any result.
 */
export function useRequestGuard(space: CacheSpace = 'app', key: string | null = null) {
  const scope = currentScope(space);
  const identity = JSON.stringify([space, scope, key]);
  const latest = useRef({ identity, sequence: 0, mounted: true });
  if (latest.current.identity !== identity) {
    latest.current.identity = identity;
    latest.current.sequence++;
  }
  useEffect(() => {
    latest.current.mounted = true;
    return () => { latest.current.mounted = false; latest.current.sequence++; };
  }, []);
  return useCallback(() => {
    // A callback retained by an old view must not supersede the current view's request.
    const sequence = latest.current.identity === identity && latest.current.mounted
      ? ++latest.current.sequence : -1;
    const ticket = cacheTicket(space);
    const isLatest = () => latest.current.mounted && latest.current.identity === identity
      && latest.current.sequence === sequence && !!scope && ticket.scope === scope && scope === currentScope(space);
    return { ticket, isLatest, isCurrent: () => isLatest() && isCacheTicketCurrent(ticket) };
  }, [identity, space, scope]);
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
  { space = 'app', revalidateOnFocus = space === 'app', focusThrottleMs = 30_000, pollMs, keepPrevious = false, cache = true }: {
    /** False bypasses both cache reads and writes; request guards still apply. */
    cache?: boolean; space?: CacheSpace; revalidateOnFocus?: boolean; focusThrottleMs?: number; pollMs?: number;
    /** On a key change with nothing cached (a filter or page change), keep the current rows until the new ones arrive. */
    keepPrevious?: boolean;
  } = {},
): CachedQuery<T> {
  const scope = currentScope(space);
  const identity = JSON.stringify([space, scope, key, cache]);
  const beginRequest = useRequestGuard(space, identity);
  const initial = cache && key ? readQueryCache<T>(key, space) : undefined;
  const [data, setData] = useState<T | null>(initial ? initial.data : null);
  const [placeholder, setPlaceholder] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fetching, setFetching] = useState<boolean>(!!key);
  const lastFetch = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Reset during render, so an old request cannot paint between a key change and the next effect.
  const shown = useRef({ identity, scope });
  const placeholderRef = useRef(false);
  if (shown.current.identity !== identity) {
    const sameScope = shown.current.scope === scope;
    shown.current = { identity, scope };
    const cached = cache && key ? readQueryCache<T>(key, space) : undefined;
    const previous = !!key && sameScope && keepPrevious && data !== null && !cached;
    placeholderRef.current = previous;
    setData(cached ? cached.data : previous ? data : null);
    setPlaceholder(previous);
    setError(null);
    setFetching(!!key);
  }

  const run = useCallback(async (): Promise<void> => {
    if (!key) return;
    const { ticket, isCurrent, isLatest } = beginRequest();
    if (!isCurrent()) return;
    lastFetch.current = Date.now();
    setFetching(true);
    try {
      const value = await fetcherRef.current();
      if (!isCurrent()) return;
      if (cache) writeQueryCache(key, value, ticket);
      setData(value);
      placeholderRef.current = false;
      setPlaceholder(false);
      setError(null);
    } catch (e) {
      if (!isCurrent()) return;
      // Previous-filter rows are never evidence for a failed new-filter request.
      if (placeholderRef.current) {
        setData(null);
        placeholderRef.current = false;
        setPlaceholder(false);
      }
      setError(e);
    } finally {
      if (isCurrent()) setFetching(false);
      // A write invalidated this response, but this is still the visible request: replace it with a fresh read.
      else if (isLatest()) void run();
    }
  }, [key, beginRequest, cache]);

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
