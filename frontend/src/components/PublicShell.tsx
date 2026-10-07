import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import StrataField from './StrataField';
import PublicHeader from './PublicHeader';
import PublicFooter from './PublicFooter';

/**
 * Shared chrome for public marketing pages (/pricing, /about).
 * No session required, so the prerendered HTML is the page.
 */
export default function PublicShell({
  eyebrow,
  title,
  lede,
  wide,
  centered,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
  wide?: boolean;
  centered?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />

      <PublicHeader anchorPrefix="/" />

      <main className="landing-container relative z-10">
        <div className={`${wide ? 'max-w-5xl' : 'max-w-3xl'} mx-auto py-12 ${centered ? 'min-h-[62svh] flex flex-col justify-center' : ''}`}>
          <p className="eyebrow mb-3">{eyebrow}</p>
          <h1 className="display-h">{title}</h1>
          {lede && <p className="text-sm text-soft leading-relaxed max-w-2xl">{lede}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </main>

      <PublicFooter anchorPrefix="/" />
    </div>
  );
}
