import { ReactNode } from 'react';
import type { ChipLevel } from './StatusChip';
import { Skeleton, SkeletonText } from './Skeleton';

export * from './Skeleton';

export function PageHead({ eyebrow, title, note, meta }: {
  eyebrow: string; title: string; note?: string; meta?: ReactNode;
}) {
  return (
    <header className="sec-head">
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {note && <p className="sec-note">{note}</p>}
      {meta}
    </header>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="space-y-4 py-4 animate-fade-in w-full" aria-busy="true">
      <div className="flex items-center gap-2">
        <span className="live-dot" />
        <p className="eyebrow text-accent">LOADING · {label}</p>
      </div>
      <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
        <Skeleton width="45%" height={24} />
        <SkeletonText lines={3} lastLineWidth="55%" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-3">
          <Skeleton height={68} rounded="md" />
          <Skeleton height={68} rounded="md" />
          <Skeleton height={68} rounded="md" />
          <Skeleton height={68} rounded="md" />
        </div>
      </div>
    </div>
  );
}

export const sevLevel = (s: string): ChipLevel =>
  s === 'CRITICAL' ? 'bad' : s === 'HIGH' ? 'warn' : s === 'MEDIUM' ? 'warn' : 'idle';

export const statusLevel = (s: string): ChipLevel =>
  s === 'CONTAINED' ? 'ok' : s === 'TRIAGED' ? 'idle' : 'warn';

export const ctlLevel = (s: string): ChipLevel =>
  s === 'PASS' ? 'ok' : s === 'FAIL' ? 'bad' : 'warn';
