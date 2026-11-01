import { useLayoutEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

/**
 * Route changes, the same in the customer app and the owner console (docs/ui-motion-cache-2026-11-01):
 * a new page opens at the top before it paints (no frame of the old scroll position); back and forward keep the
 * browser's own position. The shell stays mounted; only the keyed content area (main.page) re-enters.
 */
export function useRouteScroll(): void {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  // Read through a ref: only a new path scrolls (a filter or sort written to the query string never does).
  const typeRef = useRef(navigationType);
  typeRef.current = navigationType;
  useLayoutEffect(() => {
    if (typeRef.current !== 'POP') window.scrollTo(0, 0);
  }, [pathname]);
}
