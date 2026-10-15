/**
 * Route-split page loaders, shared by React.lazy (App.tsx) and the prefetcher
 * so a nav tap never waits on a chunk download. import() is cached by the
 * module system, so calling a loader again is free.
 */
export const appPageLoaders = {
  '/overview': () => import('../pages/Overview'),
  '/assets': () => import('../pages/Assets'),
  '/findings': () => import('../pages/Findings'),
  '/scans': () => import('../pages/Scans'),
  '/domains': () => import('../pages/Domains'),
  '/remediation': () => import('../pages/Remediation'),
  '/reports': () => import('../pages/Reports'),
  '/settings': () => import('../pages/Settings'),
  '/platform': () => import('../pages/Platform'),
} as const;

type AppPath = keyof typeof appPageLoaders;

const ALIASES: Record<string, AppPath> = { '/': '/overview', '/dashboard': '/overview' };

/** Warm the chunk for a route on intent (hover, focus, touch). Never throws. */
export function prefetchRoute(path: string) {
  const key = (ALIASES[path] ?? path) as AppPath;
  const load = appPageLoaders[key];
  if (load) load().catch(() => {});
}

/**
 * Warm every app page once the shell is idle. Skipped under Save-Data, where
 * intent prefetch still covers the page the user is about to open.
 */
export function prefetchAppPagesWhenIdle(): () => void {
  try {
    if ((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData) return () => {};
  } catch {
    // ignore
  }
  const run = () => Object.values(appPageLoaders).forEach(load => load().catch(() => {}));
  if ('requestIdleCallback' in window) {
    const id = window.requestIdleCallback(run, { timeout: 4000 });
    return () => window.cancelIdleCallback(id);
  }
  const id = setTimeout(run, 1500);
  return () => clearTimeout(id);
}
