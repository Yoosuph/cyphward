import type { ReactNode } from 'react';
import StrataField from './StrataField';
import PublicHeader from './PublicHeader';
import PublicFooter from './PublicFooter';

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

      <PublicFooter anchorPrefix="/" />
    </div>
  );
}
