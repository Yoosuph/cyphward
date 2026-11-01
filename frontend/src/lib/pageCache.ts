/**
 * Last-seen data for the app's pages: the customer-app face of lib/queryCache (one store, one policy; see there
 * and docs/ui-motion-cache-2026-11-01/AUDIT.md). Pages with their own loaders (filters, polling, several requests)
 * use these calls; simpler reads use useCachedQuery.
 *
 *   const ticket = pageCacheTicket();          // when the request STARTS
 *   const res = await getThing();
 *   writePageCache('thing', res, ticket);      // dropped if the user, organisation or a write changed meanwhile
 *
 * Memory only, scoped to the signed-in user AND organisation; cleared on sign-in, sign-out, idle logout,
 * organisation switch and after any write request (see apiFetch).
 */
import { cacheTicket, clearQueryCache, readQueryCache, writeQueryCache, type CacheTicket } from './queryCache';

export function readPageCache<T>(key: string): T | undefined {
  return readQueryCache<T>(key, 'app')?.data;
}

export function pageCacheTicket(): CacheTicket {
  return cacheTicket('app');
}

export function writePageCache<T>(key: string, value: T, ticket: CacheTicket): void {
  writeQueryCache(key, value, ticket);
}

export function clearPageCache(): void {
  clearQueryCache();
}
