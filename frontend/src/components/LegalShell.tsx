import type { ReactNode } from 'react';
import StrataField from './StrataField';
import PublicHeader from './PublicHeader';
import PublicFooter from './PublicFooter';
import { usePageMotion } from '../lib/usePageMotion';

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
  const motionRef = usePageMotion<HTMLDivElement>();
  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />

      <PublicHeader />

      {/* Document */}
      <main className="landing-container relative z-10">
        <div ref={motionRef} className="max-w-3xl mx-auto pt-28 pb-16">
          <p className="eyebrow mb-3 rise-in">{eyebrow}</p>
          <h1 className="display-h rise-in rise-in-2">{title}</h1>
          <p className="mono text-[11px] text-soft mt-3 rise-in rise-in-3">EFFECTIVE: {effective}</p>

          <div className="legal-body panel mt-8 p-6 md:p-9 space-y-7" data-reveal>{children}</div>
        </div>
      </main>

      <PublicFooter anchorPrefix="/" />
    </div>
  );
}
