import { ReactNode } from 'react';
import type { ChipLevel } from './StatusChip';
import { Skeleton, SkeletonText } from './Skeleton';

export * from './Skeleton';

/**
 * The one page header used by every app page: title, a single plain-language
 * line, and actions on the right (stacked full width on phones).
 */
export function PageHead({ title, note, actions, meta }: {
  /** @deprecated Section labels were removed; kept so older callers compile. */
  eyebrow?: string;
  title: ReactNode;
  note?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-row">
        <div className="min-w-0">
          <h1 className="page-head-title">{title}</h1>
          {note && <p className="page-head-note">{note}</p>}
        </div>
        {actions && <div className="page-head-actions">{actions}</div>}
      </div>
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
