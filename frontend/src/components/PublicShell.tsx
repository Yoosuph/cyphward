import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import StrataField from './StrataField';
import PublicHeader from './PublicHeader';

/**
 * Shared chrome for public marketing pages (/pricing, /about).
 * No session required, so the prerendered HTML is the page.
 */
export default function PublicShell({
  eyebrow,
  title,
  lede,
  wide,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />

      <PublicHeader anchorPrefix="/" />

      <main className="landing-container relative z-10">
        <div className={`${wide ? 'max-w-5xl' : 'max-w-3xl'} mx-auto py-12`}>
          <p className="eyebrow mb-3">{eyebrow}</p>
          <h1 className="display-h">{title}</h1>
          {lede && <p className="text-sm text-soft leading-relaxed max-w-2xl">{lede}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </main>

      <footer className="landing-footer">
        <div className="landing-container flex flex-col sm:flex-row items-center justify-between gap-4 text-xs mono text-soft">
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
            <Link to="/pricing" className="hover:text-ink transition-colors">PRICING</Link>
            <span className="text-line">·</span>
            <Link to="/about" className="hover:text-ink transition-colors">ABOUT</Link>
            <span className="text-line">·</span>
            <Link to="/terms" className="hover:text-ink transition-colors">TERMS</Link>
            <span className="text-line">·</span>
            <Link to="/privacy" className="hover:text-ink transition-colors">PRIVACY</Link>
            <span className="text-line">·</span>
            <Link to="/login" className="hover:text-ink transition-colors">SIGN IN</Link>
          </div>
          <div>© 2026 CYPHWARD LTD</div>
        </div>
      </footer>
    </div>
  );
}
