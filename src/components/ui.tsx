import { ReactNode } from 'react';
import type { ChipLevel } from './StatusChip';

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
  return <p className="loading-line">FETCHING {label} —</p>;
}

export const sevLevel = (s: string): ChipLevel =>
  s === 'CRITICAL' ? 'bad' : s === 'HIGH' ? 'warn' : s === 'MEDIUM' ? 'warn' : 'idle';

export const statusLevel = (s: string): ChipLevel =>
  s === 'CONTAINED' ? 'ok' : s === 'TRIAGED' ? 'idle' : 'warn';

export const ctlLevel = (s: string): ChipLevel =>
  s === 'PASS' ? 'ok' : s === 'FAIL' ? 'bad' : 'warn';
