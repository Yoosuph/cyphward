import { ReactNode } from 'react';

export type ChipLevel = 'ok' | 'warn' | 'bad' | 'idle';

export default function StatusChip({ level, children }: { level: ChipLevel; children: ReactNode }) {
  return (
    <span className={`st ${level}`}>
      <i />
      {children}
    </span>
  );
}
