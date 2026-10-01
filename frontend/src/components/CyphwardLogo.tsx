import { memo } from 'react';

interface CyphwardLogoProps {
  size?: number;
  variant?: 'full' | 'mark' | 'compact' | 'cyph' | 'acronym';
  className?: string;
  showSubtitle?: boolean;
}

export const CyphwardLogo = memo(function CyphwardLogo({
  size = 24,
  variant = 'full',
  className = '',
  showSubtitle = true,
}: CyphwardLogoProps) {
  // Compute aspect-correct dimensions
  const markSize = size;

  const markSvg = (
    <svg
      width={markSize}
      height={markSize}
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="shrink-0 transition-transform duration-200 hover:scale-105"
      aria-label="Cyphward shield"
    >
      <defs>
        {/* Sovereign Amber Copper Gradient */}
        <linearGradient id="cyphGradOuter" x1="4" y1="2" x2="32" y2="34" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FF7A50" />
          <stop offset="50%" stopColor="#E5532B" />
          <stop offset="100%" stopColor="#B33614" />
        </linearGradient>

        <linearGradient id="cyphGradInner" x1="10" y1="8" x2="26" y2="28" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FF8F6B" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#E5532B" stopOpacity="0.2" />
        </linearGradient>

        <linearGradient id="cyphCoreGlow" x1="18" y1="13" x2="18" y2="23" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#FF8F6B" />
        </linearGradient>

        {/* Ambient Drop Glow */}
        <filter id="cyphShieldGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.5" floodColor="#E5532B" floodOpacity="0.38" />
        </filter>
      </defs>

      {/* Layer 1: Outer Sovereign Bastion Shield Outline */}
      <path
        d="M18 2.5 L30.5 7.5 V17.2 C30.5 24.8 25.1 31.4 18 33.5 C10.9 31.4 5.5 24.8 5.5 17.2 V7.5 L18 2.5 Z"
        stroke="url(#cyphGradOuter)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#cyphShieldGlow)"
      />

      {/* Layer 2: Inner Interlocking Defense Chevron */}
      <path
        d="M18 7.8 L26.2 11.2 V17.4 C26.2 22.4 22.7 26.8 18 28.5 C13.3 26.8 9.8 22.4 9.8 17.4 V11.2 L18 7.8 Z"
        fill="url(#cyphGradInner)"
        stroke="url(#cyphGradOuter)"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.85"
      />

      {/* Layer 3: Central Cryptographic Core Node */}
      <path
        d="M18 13.5 L22 18 L18 22.5 L14 18 L18 13.5 Z"
        fill="url(#cyphCoreGlow)"
        stroke="#E5532B"
        strokeWidth="1"
      />

      {/* Layer 4: Sovereign Horizontal Threat Horizon */}
      <line x1="11" y1="18" x2="25" y2="18" stroke="#FFE4DC" strokeWidth="1" strokeLinecap="round" opacity="0.75" />
      <line x1="18" y1="11" x2="18" y2="25" stroke="#FFE4DC" strokeWidth="1" strokeLinecap="round" opacity="0.75" />
    </svg>
  );

  if (variant === 'mark') {
    return (
      <div className={`inline-flex items-center justify-center ${className}`} title="CYPH — Security Platform">
        {markSvg}
      </div>
    );
  }

  if (variant === 'cyph' || variant === 'acronym') {
    return (
      <div className={`inline-flex items-center gap-1.5 ${className}`} title="CYPH — Security Platform">
        {markSvg}
        <span className="font-mono font-bold tracking-widest text-ink text-sm">
          CYPH
        </span>
      </div>
    );
  }

  if (variant === 'compact') {
    return (
      <div className={`inline-flex items-center gap-2 ${className}`}>
        {markSvg}
        <span className="font-mono font-bold tracking-wider text-ink text-sm">
          CYPH<span className="text-accent">WARD</span>
        </span>
      </div>
    );
  }

  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`}>
      {markSvg}
      <div className="flex flex-col min-w-0">
        <div className="flex items-center gap-1 leading-none">
          <span className="font-mono font-bold tracking-widest text-ink text-[14px]">
            CYPH<span className="text-accent">WARD</span>
          </span>
          <span className="live-dot ml-1" />
        </div>
        {showSubtitle && (
          <span className="font-mono text-[9px] tracking-[0.2em] text-soft uppercase mt-1">
            Security Platform
          </span>
        )}
      </div>
    </div>
  );
});

export default CyphwardLogo;
