import type { ReactNode } from 'react';
import StrataField from './StrataField';
import PublicHeader from './PublicHeader';
import PublicFooter from './PublicFooter';
import SocialFloat from './SocialFloat';
import { usePageMotion } from '../lib/usePageMotion';

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
  const motionRef = usePageMotion<HTMLDivElement>();
  return (
    <div className="landing-wrap">
      <StrataField variant="hero" opacity={0.6} />

      <PublicHeader />

      <main className="landing-container relative z-10">
        <div ref={motionRef} className={`${wide ? 'max-w-5xl' : 'max-w-3xl'} mx-auto pt-28 pb-16 ${centered ? 'min-h-[62svh] flex flex-col justify-center' : ''}`}>
          <p className="eyebrow mb-3 rise-in">{eyebrow}</p>
          <h1 className="display-h rise-in rise-in-2">{title}</h1>
          {lede && <p className="text-sm text-soft leading-relaxed max-w-2xl rise-in rise-in-3">{lede}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </main>

      <PublicFooter anchorPrefix="/" />
      <SocialFloat />
    </div>
  );
}
