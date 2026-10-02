import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

export function getTheme(): Theme {
  if (typeof document === 'undefined') return 'light';
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

export function toggleTheme(): void {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('cyphward-theme', next); } catch { /* ignore */ }
  window.dispatchEvent(new Event('cyphward:theme'));
}

/** Re-renders the consumer whenever the theme flips. */
export function useThemeState(): Theme {
  const [t, setT] = useState<Theme>(getTheme);
  useEffect(() => {
    const h = () => setT(getTheme());
    window.addEventListener('cyphward:theme', h);
    return () => window.removeEventListener('cyphward:theme', h);
  }, []);
  return t;
}
