/**
 * Last-seen data for the app's list pages, so revisiting a page paints its
 * previous contents at once while a fresh request runs (stale-while-revalidate).
 *
 * Deliberately narrow:
 *  - memory only (never Web Storage), so it dies with the tab;
 *  - every key is scoped to the signed-in user AND organization, and nothing
 *    is read or written without both;
 *  - cleared on sign-in, sign-out, idle logout and after any write request
 *    (see apiFetch), so a page never re-shows data a mutation changed;
 *  - opt-in per page for display data only. Auth, MFA, billing and live scan
 *    progress never go through it.
 */
import { loadSession } from './session';

const store = new Map<string, unknown>();

function activeOrgId(): string | null {
  try {
    return localStorage.getItem('cyphward-org-id') || sessionStorage.getItem('cyphward-org-id');
  } catch {
    return null;
  }
}

function scopedKey(key: string): string | null {
  const userId = loadSession()?.user?.id;
  const orgId = activeOrgId();
  if (!userId || !orgId) return null;
  return `${userId}\u0000${orgId}\u0000${key}`;
}

export function readPageCache<T>(key: string): T | undefined {
  const k = scopedKey(key);
  return k ? (store.get(k) as T | undefined) : undefined;
}

export function writePageCache<T>(key: string, value: T): void {
  const k = scopedKey(key);
  if (k) store.set(k, value);
}

export function clearPageCache(): void {
  store.clear();
}
