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

export function SkeletonBadge({
  width = 64,
  className = '',
}: {
  width?: string | number;
  className?: string;
}) {
  return (
    <Skeleton
      width={width}
      height={20}
      className={`skeleton-badge ${className}`}
    />
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

export function SeverityBarSkeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`p-4 rounded-lg border border-line bg-inset/50 space-y-2.5 ${className}`}
      aria-hidden="true"
    >
      <div className="flex items-center justify-between">
        <Skeleton width={140} height={11} />
        <Skeleton width={90} height={11} />
      </div>
      <div className="h-3 w-full bg-raised rounded-full overflow-hidden flex gap-0.5 p-0.5 border border-line">
        <div className="h-full bg-accent/40 rounded-l-full w-[25%] skeleton" />
        <div className="h-full bg-amber-600/40 w-[35%] skeleton" />
        <div className="h-full bg-amber-400/30 w-[20%] skeleton" />
        <div className="h-full bg-blue-500/30 rounded-r-full w-[20%] skeleton" />
      </div>
    </div>
  );
}

export function ThreatTickerSkeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`ticker-card h-11 flex items-center border border-line-strong bg-raised overflow-hidden px-4 ${className}`}
      aria-hidden="true"
    >
      <div className="flex items-center gap-2 pr-4 border-r border-line shrink-0">
        <span className="live-dot" />
        <Skeleton width={90} height={11} />
      </div>
      <div className="flex items-center gap-8 pl-4 w-full overflow-hidden">
        <Skeleton width={220} height={11} />
        <Skeleton width={180} height={11} className="hidden sm:block" />
        <Skeleton width={160} height={11} className="hidden md:block" />
      </div>
    </div>
  );
}

// ==========================================
// 4. TABLE & LIST SKELETONS
// ==========================================

export function TableRowSkeleton({
  cols = [160, 120, 90, 60, 140, 100, 70, 40],
  className = '',
}: {
  cols?: (number | string)[];
  className?: string;
}) {
  return (
    <tr className={`border-b border-line/50 ${className}`} aria-hidden="true">
      {cols.map((width, idx) => (
        <td key={idx} className="py-3.5 px-4">
          <Skeleton
            width={typeof width === 'number' ? `${width}px` : width}
            height={14}
          />
        </td>
      ))}
    </tr>
  );
}

export function TableSkeleton({
  headers,
  rows = 6,
  cols = [180, 120, 90, 70, 140, 110, 80, 40],
  className = '',
}: {
  headers?: string[];
  rows?: number;
  cols?: (number | string)[];
  className?: string;
}) {
  return (
    <div className={`overflow-x-auto ${className}`} aria-hidden="true">
      <table className="w-full text-left text-xs mono">
        {headers && (
          <thead>
            <tr className="border-b border-line bg-inset/40 text-soft text-[11px]">
              {headers.map((h, i) => (
                <th key={i} className="py-3 px-4 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody className="divide-y divide-line/60">
          {Array.from({ length: rows }).map((_, i) => (
            <TableRowSkeleton key={i} cols={cols} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FindingCardSkeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`p-4 rounded-lg border border-line bg-raised flex flex-col md:flex-row md:items-center justify-between gap-4 ${className}`}
      aria-hidden="true"
    >
      <div className="space-y-2 flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <Skeleton width={68} height={18} />
          <Skeleton width={88} height={18} />
          <Skeleton width={120} height={14} />
        </div>
        <Skeleton width="65%" height={16} />
        <Skeleton width="90%" height={12} />
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <Skeleton width={70} height={12} />
        <Skeleton width={24} height={24} rounded="sm" />
      </div>
    </div>
  );
}

export function ScanStepperSkeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`p-6 rounded-lg border border-line bg-raised space-y-6 ${className}`}
      aria-hidden="true"
    >
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-line">
        <div className="space-y-1.5">
          <Skeleton width={160} height={12} />
          <Skeleton width={220} height={20} />
        </div>
        <div className="flex items-center gap-2">
          <Skeleton width={90} height={24} rounded="full" />
          <Skeleton width={120} height={14} />
        </div>
      </div>

      {/* 6 Stage Stepper items */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="p-3 rounded border border-line bg-inset/40 space-y-2">
            <div className="flex items-center justify-between">
              <Skeleton width={18} height={18} rounded="full" />
              <Skeleton width={40} height={12} />
            </div>
            <Skeleton width="85%" height={13} />
            <Skeleton width="60%" height={10} />
          </div>
        ))}
      </div>

      {/* Log Console Box */}
      <div className="p-4 rounded bg-inset border border-line space-y-2">
        <Skeleton width={140} height={11} />
        <Skeleton width="95%" height={12} />
        <Skeleton width="80%" height={12} />
      </div>
    </div>
  );
}

// ==========================================
// 5. DRAWER & MODAL SKELETONS
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

export function FindingDrawerSkeleton() {
  return (
    <div className="space-y-6 pt-2" aria-hidden="true">
      {/* Header Info */}
      <div className="space-y-2 pb-4 border-b border-line">
        <div className="flex items-center gap-2">
          <Skeleton width={70} height={20} />
          <Skeleton width={90} height={20} />
        </div>
        <Skeleton width="85%" height={20} />
        <SkeletonText lines={2} lastLineWidth="75%" />
      </div>

      {/* Host Card */}
      <div className="p-3 bg-inset rounded border border-line flex items-center justify-between">
        <Skeleton width={140} height={12} />
        <Skeleton width={100} height={12} />
      </div>

      {/* Status Row */}
      <div className="flex items-center justify-between p-3 rounded bg-inset/60 border border-line">
        <Skeleton width={120} height={12} />
        <div className="flex items-center gap-2">
          <Skeleton width={50} height={22} />
          <Skeleton width={65} height={22} />
          <Skeleton width={75} height={22} />
        </div>
      </div>

      {/* Codebox Evidence */}
      <div className="space-y-2">
        <Skeleton width={180} height={13} />
        <div className="p-4 rounded-lg bg-inset border border-line space-y-2">
          <Skeleton width="60%" height={11} />
          <Skeleton width="90%" height={11} />
          <Skeleton width="75%" height={11} />
          <Skeleton width="40%" height={11} />
        </div>
      </div>

      {/* Remediation */}
      <div className="space-y-2">
        <Skeleton width={160} height={13} />
        <div className="p-3.5 rounded bg-inset border border-line space-y-2">
          <Skeleton width="95%" height={12} />
          <Skeleton width="85%" height={12} />
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

// ==========================================
// 6. PAGE-LEVEL HIGH FIDELITY SKELETONS
// ==========================================

export function OverviewSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-fade-in" aria-busy="true">
      {/* Ticker */}
      <ThreatTickerSkeleton />

      {/* Enclave Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={180} height={11} />
          </div>
          <Skeleton width={260} height={28} />
          <Skeleton width={380} height={12} />
        </div>
        <div className="flex items-center gap-3">
          <Skeleton width={150} height={34} />
          <Skeleton width={120} height={34} />
        </div>
      </div>

      {/* Top 12-Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Main Score Gauge */}
        <div className="lg:col-span-4 p-6 rounded-lg border border-line bg-raised/70 backdrop-blur flex flex-col items-center justify-center text-center relative overflow-hidden min-h-[320px]">
          <div className="absolute top-3 left-4">
            <Skeleton width={140} height={10} />
          </div>
          <div className="absolute top-3 right-4">
            <Skeleton width={60} height={18} />
          </div>
          <div className="my-3">
            <ScoreRingSkeleton size={190} />
          </div>
          <div className="mt-1 space-y-2 flex flex-col items-center">
            <Skeleton width={140} height={20} rounded="full" />
            <Skeleton width={180} height={10} />
          </div>
        </div>

        {/* 4 Stat Cards + Severity Bar */}
        <div className="lg:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
          <SeverityBarSkeleton className="col-span-2 md:col-span-4" />
        </div>
      </div>

      {/* Middle Grid: Four Pillars Subscores + Key Posture Drivers */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className="lg:col-span-7 p-5 rounded-lg border border-line bg-raised space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-line mb-4">
            <Skeleton width={220} height={12} />
            <Skeleton width={110} height={10} />
          </div>
          <div className="space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Skeleton width={130} height={12} />
                  <Skeleton width={60} height={12} />
                </div>
                <Skeleton width="100%" height={8} rounded="full" />
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-5 p-5 rounded-lg border border-line bg-raised flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-line mb-3">
              <Skeleton width={140} height={12} />
              <Skeleton width={80} height={10} />
            </div>
            <div className="space-y-2.5">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="p-2 rounded bg-inset/50 border border-line/60 flex items-center gap-2.5">
                  <Skeleton width={32} height={18} rounded="sm" />
                  <Skeleton width={`${75 - i * 8}%`} height={12} />
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-line flex justify-end">
            <Skeleton width={180} height={12} />
          </div>
        </div>
      </div>

      {/* Bottom Grid: Recent Inngest Workflow Executions */}
      <div className="p-5 rounded-lg border border-line bg-raised">
        <div className="flex items-center justify-between pb-3 border-b border-line mb-4">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={220} height={12} />
          </div>
          <Skeleton width={80} height={12} />
        </div>
        <TableSkeleton
          headers={['DOMAIN', 'STATUS', 'STAGE TRACKER', 'SCORE', 'TIMESTAMP', 'ACTION']}
          rows={3}
          cols={[140, 80, 160, 70, 90, 50]}
        />
      </div>
    </div>
  );
}

export function AssetsSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-fade-in" aria-busy="true">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={160} height={11} />
          </div>
          <Skeleton width={280} height={28} />
          <Skeleton width={420} height={12} />
        </div>
        <Skeleton width={85} height={32} />
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col md:flex-row gap-3 items-center justify-between">
        <Skeleton width={320} height={32} className="w-full md:w-80" />
        <div className="flex items-center gap-1.5 overflow-x-auto w-full md:w-auto pb-1 md:pb-0">
          <Skeleton width={45} height={26} />
          <Skeleton width={95} height={26} />
          <Skeleton width={85} height={26} />
          <Skeleton width={85} height={26} />
          <Skeleton width={95} height={26} />
        </div>
      </div>

      {/* Table Container */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="p-4 border-b border-line bg-inset/30 flex items-center justify-between">
          <Skeleton width={180} height={12} />
          <Skeleton width={80} height={12} />
        </div>
        <TableSkeleton
          headers={['HOSTNAME & DOMAIN', 'IP ADDRESS', 'ASSET TYPE', 'HTTP STATUS', 'DETECTED TECH', 'TLS / CIPHER', 'RISKS', 'ACTION']}
          rows={7}
          cols={[170, 110, 85, 45, 130, 105, 65, 24]}
        />
      </div>
    </div>
  );
}


export function FindingsSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-fade-in" aria-busy="true">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={180} height={11} />
          </div>
          <Skeleton width={300} height={28} />
          <Skeleton width={440} height={12} />
        </div>
        <Skeleton width={90} height={32} />
      </div>

      {/* Scope Bar */}
      <div className="flex flex-col lg:flex-row gap-3 items-start lg:items-center justify-between">
        <div className="flex flex-wrap gap-1.5">
          <Skeleton width={50} height={28} />
          <Skeleton width={85} height={28} />
          <Skeleton width={65} height={28} />
          <Skeleton width={75} height={28} />
          <Skeleton width={60} height={28} />
        </div>
        <div className="flex items-center gap-3 w-full lg:w-auto">
          <Skeleton width={130} height={28} />
          <Skeleton width={220} height={28} className="flex-1 lg:flex-none" />
        </div>
      </div>

      {/* Findings List Skeletons */}
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <FindingCardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

export function ScansSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-fade-in" aria-busy="true">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={220} height={11} />
          </div>
          <Skeleton width={320} height={28} />
          <Skeleton width={460} height={12} />
        </div>
        <div className="flex items-center gap-2.5">
          <Skeleton width={85} height={32} />
          <Skeleton width={110} height={32} />
        </div>
      </div>

      {/* Workflow Stepper Tracker */}
      <ScanStepperSkeleton />

      {/* Historical Ledger */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="p-4 border-b border-line bg-inset/30 flex items-center justify-between">
          <Skeleton width={160} height={12} />
          <Skeleton width={90} height={12} />
        </div>
        <TableSkeleton
          headers={['DOMAIN ZONE', 'RUN STATUS', 'STAGE PROGRESSION', 'SCORE', 'FINDINGS', 'TIMESTAMP', 'ACTION']}
          rows={5}
          cols={[140, 90, 160, 80, 80, 110, 60]}
        />
      </div>
    </div>
  );
}

export function DomainsSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-fade-in" aria-busy="true">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={180} height={11} />
          </div>
          <Skeleton width={300} height={28} />
          <Skeleton width={480} height={12} />
        </div>
        <div className="flex items-center gap-2.5">
          <Skeleton width={85} height={32} />
          <Skeleton width={110} height={32} />
        </div>
      </div>

      {/* Scope Banner */}
      <div className="p-4 rounded-lg bg-inset/40 border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Skeleton width={20} height={20} rounded="full" />
          <div className="space-y-1">
            <Skeleton width={160} height={12} />
            <Skeleton width={320} height={10} />
          </div>
        </div>
        <Skeleton width={120} height={22} />
      </div>

      {/* Domains Table */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="p-4 border-b border-line bg-inset/30 flex items-center justify-between">
          <Skeleton width={180} height={12} />
          <Skeleton width={80} height={12} />
        </div>
        <TableSkeleton
          headers={['DOMAIN ZONE', 'VERIFICATION STATUS', 'DNS TXT TOKEN', 'VERIFIED AT', 'ASSETS', 'ACTIONS']}
          rows={4}
          cols={[140, 100, 220, 100, 70, 120]}
        />
      </div>
    </div>
  );
}

export function SettingsSkeleton() {
  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12 animate-fade-in" aria-busy="true">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <Skeleton width={180} height={11} />
          </div>
          <Skeleton width={280} height={28} />
          <Skeleton width={440} height={12} />
        </div>
        <Skeleton width={180} height={34} />
      </div>

      {/* 1. Profile Panel */}
      <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
        <div className="flex items-center gap-2 pb-3 border-b border-line">
          <Skeleton width={16} height={16} />
          <Skeleton width={240} height={13} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Skeleton width={110} height={11} />
            <Skeleton width="100%" height={36} />
          </div>
          <div className="space-y-1.5">
            <Skeleton width={140} height={11} />
            <Skeleton width="100%" height={36} />
          </div>
          <div className="space-y-1.5">
            <Skeleton width={100} height={11} />
            <Skeleton width="100%" height={36} />
          </div>
          <div className="space-y-1.5">
            <Skeleton width={120} height={11} />
            <Skeleton width="100%" height={36} />
          </div>
        </div>
      </div>

      {/* 2. Team Member Panel */}
      <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-line">
          <div className="flex items-center gap-2">
            <Skeleton width={16} height={16} />
            <Skeleton width={160} height={13} />
          </div>
          <Skeleton width={100} height={28} />
        </div>
        <div className="space-y-2.5">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="p-3 rounded border border-line bg-inset/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Skeleton width={32} height={32} rounded="full" />
                <div className="space-y-1">
                  <Skeleton width={120} height={13} />
                  <Skeleton width={160} height={10} />
                </div>
              </div>
              <Skeleton width={90} height={22} />
            </div>
          ))}
        </div>
      </div>

      {/* 3. API Credentials Panel */}
      <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
        <div className="flex items-center gap-2 pb-3 border-b border-line">
          <Skeleton width={16} height={16} />
          <Skeleton width={200} height={13} />
        </div>
        <div className="p-4 rounded bg-inset border border-line space-y-3">
          <div className="flex items-center justify-between">
            <Skeleton width={130} height={11} />
            <Skeleton width={80} height={24} />
          </div>
          <Skeleton width="100%" height={32} />
        </div>
      </div>
    </div>
  );
}

export function ScoreSkeleton() {
  return (
    <div className="space-y-6 animate-fade-in" aria-busy="true">
      {/* PageHead Skeleton */}
      <div className="border-b border-line pb-5 space-y-2">
        <div className="flex items-center gap-2">
          <span className="live-dot" />
          <Skeleton width={140} height={11} />
        </div>
        <Skeleton width={320} height={28} />
        <Skeleton width={520} height={13} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Composite Gauge Panel */}
        <div className="panel lg:col-span-5">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={90} height={12} />
            <Skeleton width={110} height={10} />
          </header>
          <div className="panel-body flex flex-col items-center py-6 space-y-4">
            <ScoreRingSkeleton size={252} />
            <Skeleton width={320} height={10} />
          </div>
        </div>

        {/* Sub-scores Panel */}
        <div className="panel lg:col-span-7">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={90} height={12} />
            <Skeleton width={50} height={10} />
          </header>
          <div className="panel-body pt-6 space-y-5">
            {['EXTERNAL EXPOSURE', 'THREAT LEVEL', 'COMPLIANCE', 'HUMAN DEFENSE', 'DARK WEB'].map((lbl, i) => (
              <div key={i} className="space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className="mono text-[11px] text-soft">{lbl}</span>
                  <Skeleton width={35} height={12} />
                </div>
                <Skeleton width="100%" height={11} rounded="sm" />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
        {/* Factors Panel */}
        <div className="panel lg:col-span-7">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={110} height={12} />
            <Skeleton width={80} height={10} />
          </header>
          <div className="panel-body pt-2 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="factor-row flex justify-between py-2 border-b border-line/40">
                <Skeleton width={260} height={12} />
                <Skeleton width={40} height={16} rounded="sm" />
              </div>
            ))}
          </div>
        </div>

        {/* API Codebox Panel */}
        <div className="panel lg:col-span-5">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={80} height={12} />
            <Skeleton width={140} height={10} />
          </header>
          <div className="panel-body p-4 space-y-2">
            <Skeleton width="90%" height={12} />
            <Skeleton width="75%" height={12} />
            <Skeleton width="85%" height={12} />
            <Skeleton width="60%" height={12} />
            <Skeleton width="80%" height={12} />
            <Skeleton width="70%" height={12} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function AcademySkeleton() {
  return (
    <div className="space-y-6 animate-fade-in" aria-busy="true">
      {/* Header */}
      <div className="border-b border-line pb-5 space-y-2">
        <div className="flex items-center gap-2">
          <span className="live-dot" />
          <Skeleton width={150} height={11} />
        </div>
        <Skeleton width={260} height={28} />
        <Skeleton width={480} height={12} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Courses Panel */}
        <div className="panel lg:col-span-7">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={80} height={12} />
            <Skeleton width={90} height={10} />
          </header>
          <div className="panel-body pt-2 space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="course-row flex items-center justify-between py-2 border-b border-line/40">
                <div className="flex items-center gap-2">
                  <Skeleton width={180} height={13} />
                  <Skeleton width={40} height={16} rounded="sm" />
                </div>
                <div className="flex items-center gap-3">
                  <Skeleton width={100} height={6} rounded="full" />
                  <Skeleton width={35} height={12} />
                  <Skeleton width={50} height={24} rounded="sm" />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Simulation Panel */}
        <div className="panel lg:col-span-5">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={140} height={12} />
            <Skeleton width={70} height={10} />
          </header>
          <div className="panel-body flex flex-col items-center py-6 space-y-4">
            <div className="w-[170px] h-[170px] rounded-full border-4 border-line/60 flex flex-col items-center justify-center relative">
              <Skeleton width={60} height={24} />
              <Skeleton width={70} height={10} className="mt-1" />
            </div>
            <div className="flex gap-4">
              <Skeleton width={90} height={12} />
              <Skeleton width={90} height={12} />
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
        {/* Top Defenders */}
        <div className="panel lg:col-span-4">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={100} height={12} />
            <Skeleton width={30} height={10} />
          </header>
          <div className="panel-body pt-2 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="lb-row flex items-center justify-between py-1.5">
                <div className="flex items-center gap-3">
                  <Skeleton width={18} height={18} rounded="full" />
                  <div className="space-y-1">
                    <Skeleton width={100} height={12} />
                    <Skeleton width={60} height={10} />
                  </div>
                </div>
                <Skeleton width={45} height={14} />
              </div>
            ))}
          </div>
        </div>

        {/* Heatmap */}
        <div className="panel lg:col-span-8">
          <header className="panel-head flex justify-between items-center">
            <Skeleton width={140} height={12} />
            <Skeleton width={120} height={10} />
          </header>
          <div className="panel-body pt-4 space-y-3">
            <div className="grid grid-cols-6 gap-2">
              {Array.from({ length: 24 }).map((_, i) => (
                <Skeleton key={i} height={32} rounded="sm" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
