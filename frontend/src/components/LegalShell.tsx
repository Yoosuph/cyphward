import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import StrataField from './StrataField';
import PublicHeader from './PublicHeader';

/**
 * Shared landing-style chrome for the legal pages (/terms, /privacy).
 * Public — no session required, so OAuth verification crawlers can read them.
 */
export default function LegalShell({
  eyebrow,
  title,
  effective,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  effective: string;
  children: ReactNode;
}) {
  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />

      <PublicHeader anchorPrefix="/" />

      {/* Document */}
      <main className="landing-container relative z-10">
        <div className="max-w-3xl mx-auto py-12">
          <p className="eyebrow mb-3">{eyebrow}</p>
          <h1 className="display-h">{title}</h1>
          <p className="mono text-[11px] text-soft mt-3">EFFECTIVE: {effective}</p>

          <div className="legal-body panel mt-8 p-6 md:p-9 space-y-7">{children}</div>
        </div>
      </main>

      {/* Minimal footer */}
      <footer className="landing-footer">
        <div className="landing-container flex flex-col sm:flex-row items-center justify-between gap-4 text-xs mono text-soft">
          <div className="flex items-center gap-4">
            <Link to="/pricing" className="hover:text-ink transition-colors">PRICING</Link>
            <span className="text-line">·</span>
            <Link to="/about" className="hover:text-ink transition-colors">ABOUT</Link>
            <span className="text-line">·</span>
            <Link to="/terms" className="hover:text-ink transition-colors">TERMS OF SERVICE</Link>
            <span className="text-line">·</span>
            <Link to="/privacy" className="hover:text-ink transition-colors">PRIVACY POLICY</Link>
            <span className="text-line">·</span>
            <Link to="/login" className="hover:text-ink transition-colors">SIGN IN</Link>
          </div>
          <div>© 2026 CYPHWARD LTD</div>
        </div>
      </footer>
    </div>
  );
}
