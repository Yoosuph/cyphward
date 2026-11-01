import React from 'react';

// ==========================================
// 1. PRIMITIVE SKELETON ELEMENTS
// ==========================================

export interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
  width?: string | number;
  height?: string | number;
  variant?: 'rect' | 'circle' | 'text' | 'badge';
  rounded?: 'none' | 'sm' | 'md' | 'lg' | 'full';
}

const RADIUS: Record<string, string | number> = { full: 9999, lg: 8, md: 6, none: 0 };

export function Skeleton({
  className = '',
  style,
  width,
  height,
  variant = 'rect',
  rounded,
}: SkeletonProps) {
  const roundedClass =
    rounded === 'full' || variant === 'circle'
      ? 'rounded-full'
      : rounded === 'none'
      ? 'rounded-none'
      : rounded === 'lg'
      ? 'rounded-lg'
      : rounded === 'md'
      ? 'rounded-md'
      : 'rounded';

  return (
    <div
      className={`skeleton ${roundedClass} ${className}`}
      style={{
        width: width !== undefined ? width : undefined,
        maxWidth: '100%',
        height: height !== undefined ? height : undefined,
        // The .skeleton rule sets a 3px radius after the utilities, so the requested shape is set here.
        ...(RADIUS[variant === 'circle' ? 'full' : rounded ?? ''] !== undefined ? { borderRadius: RADIUS[variant === 'circle' ? 'full' : rounded ?? ''] } : {}),
        ...style,
      }}
      aria-hidden="true"
    />
  );
}

export function SkeletonText({
  lines = 3,
  className = '',
  lastLineWidth = '60%',
}: {
  lines?: number;
  className?: string;
  lastLineWidth?: string | number;
}) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={12}
          width={i === lines - 1 ? lastLineWidth : '100%'}
          className="skeleton-text"
        />
      ))}
    </div>
  );
}

// ==========================================
// 2. SCORE RING SKELETON (HIGH FIDELITY)
// ==========================================

export function ScoreRingSkeleton({
  size = 190,
  className = '',
}: {
  size?: number;
  className?: string;
}) {
  const stroke = size >= 220 ? 9 : 7;
  const r = (size - stroke * 2 - 10) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const C = 2 * Math.PI * r;

  return (
    <div
      className={`score-ring relative flex items-center justify-center ${className}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg width={size} height={size} className="overflow-visible">
        {/* Static Background Track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
        />
        {/* Pulsing Accent Arc Shimmer */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={stroke}
          strokeDasharray={C}
          strokeDashoffset={C * 0.65}
          strokeLinecap="round"
          className="skeleton-gauge-arc"
          transform={`rotate(-90 ${cx} ${cy})`}
        />
        {/* Oxide Diamond Accent Tick Placeholder */}
        <rect
          x={-4}
          y={-4}
          width={8}
          height={8}
          fill="var(--accent)"
          opacity={0.7}
          transform={`translate(${cx}, ${cy - r}) rotate(45)`}
        />
      </svg>
      <div className="ring-center flex flex-col items-center justify-center text-center">
        {/* Main numerical block */}
        <Skeleton width={size * 0.42} height={size * 0.22} className="mb-1.5" />
        {/* /100 sublabel */}
        <Skeleton width={size * 0.25} height={10} className="mb-2" />
        {/* Trend badge */}
        <Skeleton width={size * 0.48} height={14} rounded="full" />
      </div>
    </div>
  );
}

// ==========================================
// 3. METRIC & STAT CARD SKELETONS
// ==========================================

export function StatCardSkeleton({
  className = '',
}: {
  className?: string;
}) {
  return (
    <div
      className={`p-4 rounded-lg border border-line bg-raised flex flex-col justify-between h-[132px] ${className}`}
      aria-hidden="true"
    >
      <div className="flex items-center justify-between">
        <Skeleton width={80} height={12} />
        <Skeleton width={16} height={16} rounded="sm" />
      </div>
      <div className="my-2 space-y-1">
        <Skeleton width={64} height={28} />
        <Skeleton width={110} height={10} />
      </div>
      <Skeleton width={76} height={10} />
    </div>
  );
}

// ==========================================
// 4. DRAWER & MODAL SKELETONS
// ==========================================

export function AssetDrawerSkeleton() {
  return (
    <div className="space-y-6 pt-2" aria-hidden="true">
      {/* Identity Card */}
      <div className="p-4 rounded-lg bg-inset/50 border border-line space-y-3">
        <div className="flex items-center justify-between">
          <Skeleton width={180} height={16} />
          <Skeleton width={70} height={18} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Skeleton width={120} height={12} />
          <Skeleton width={100} height={12} />
          <Skeleton width={110} height={12} />
          <Skeleton width={130} height={12} />
        </div>
      </div>

      {/* Tech Stack */}
      <div className="space-y-2">
        <Skeleton width={140} height={12} />
        <div className="flex flex-wrap gap-2">
          <Skeleton width={70} height={22} />
          <Skeleton width={85} height={22} />
          <Skeleton width={60} height={22} />
          <Skeleton width={90} height={22} />
        </div>
      </div>

      {/* TLS Box */}
      <div className="p-4 rounded-lg bg-inset/50 border border-line space-y-2">
        <Skeleton width={120} height={14} />
        <Skeleton width={190} height={12} />
        <Skeleton width={150} height={12} />
      </div>

      {/* Findings */}
      <div className="space-y-2">
        <Skeleton width={130} height={14} />
        <div className="p-3 rounded border border-line bg-inset/30 space-y-1.5">
          <Skeleton width="70%" height={14} />
          <Skeleton width="90%" height={11} />
        </div>
      </div>
    </div>
  );
}

export function ScanDrawerSkeleton() {
  return (
    <div className="space-y-5 pt-2" aria-hidden="true">
      {/* Scan Header Card */}
      <div className="p-4 bg-inset rounded border border-line space-y-3">
        <div className="flex items-center gap-3">
          <Skeleton width={80} height={12} />
          <Skeleton width={140} height={18} />
          <Skeleton width={65} height={20} />
        </div>
        <Skeleton width={200} height={11} />
      </div>

      {/* Pipeline Stages Grid */}
      <div className="space-y-2">
        <Skeleton width={120} height={12} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="p-2.5 rounded border border-line/50 bg-inset/30 space-y-2">
              <div className="flex items-center justify-between">
                <Skeleton width={20} height={10} />
                <Skeleton width={12} height={12} />
              </div>
              <Skeleton width="80%" height={11} />
              <Skeleton width="60%" height={10} />
            </div>
          ))}
        </div>
      </div>

      {/* AI Analysis Box */}
      <div className="p-4 bg-accent-soft/20 rounded border border-accent/30 space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton width={14} height={14} />
          <Skeleton width={160} height={12} />
        </div>
        <div className="p-3 bg-inset rounded border border-line space-y-2">
          <Skeleton width={100} height={10} />
          <SkeletonText lines={2} lastLineWidth="80%" />
        </div>
      </div>

      {/* Raw Telemetry Accordion */}
      <div className="border border-line rounded-lg bg-inset/30 p-4 space-y-2">
        <Skeleton width={220} height={12} />
        <div className="bg-inset rounded border border-line p-4 space-y-1.5">
          <Skeleton width="70%" height={10} />
          <Skeleton width="90%" height={10} />
          <Skeleton width="50%" height={10} />
        </div>
      </div>
    </div>
  );
}

export function AIExecutiveReportSkeleton() {
  return (
    <div className="space-y-4 text-xs" aria-hidden="true">
      {/* Executive Header Banner */}
      <div className="p-3.5 bg-inset rounded border border-line flex items-center justify-between">
        <div className="space-y-1.5">
          <Skeleton width={180} height={16} />
          <Skeleton width={110} height={11} />
        </div>
        <div className="text-right space-y-1">
          <Skeleton width={75} height={22} />
          <Skeleton width={110} height={10} />
        </div>
      </div>

      {/* Executive Summary */}
      <div className="space-y-2">
        <Skeleton width={130} height={12} />
        <div className="bg-inset/40 p-3 rounded border border-line/60 space-y-2">
          <Skeleton width="98%" height={12} />
          <Skeleton width="94%" height={12} />
          <Skeleton width="70%" height={12} />
        </div>
      </div>

      {/* Observed Strengths */}
      <div className="space-y-2">
        <Skeleton width={180} height={12} />
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton width={14} height={14} rounded="full" />
              <Skeleton width={`${80 - i * 10}%`} height={12} />
            </div>
          ))}
        </div>
      </div>

      {/* Action Items */}
      <div className="space-y-2">
        <Skeleton width={190} height={12} />
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="p-3 rounded bg-inset border border-line flex items-center justify-between"
            >
              <div className="space-y-1.5 w-3/4">
                <div className="flex items-center gap-2">
                  <Skeleton width={60} height={16} />
                  <Skeleton width={140} height={14} />
                </div>
                <Skeleton width="90%" height={11} />
              </div>
              <Skeleton width={90} height={20} />
            </div>
          ))}
        </div>
      </div>

      {/* Compliance Verdict Callout */}
      <div className="p-3 bg-accent-soft/30 rounded border border-accent/20 space-y-1.5">
        <Skeleton width={160} height={12} />
        <Skeleton width="90%" height={11} />
      </div>
    </div>
  );
}

// Page, table, list, KPI and form-field shapes live in components/ui/Skeleton.tsx; page skeletons in
// components/skeletons/RouteSkeleton.tsx (customer app) and owner/skeletons.tsx (owner console).
