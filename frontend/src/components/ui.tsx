import { ReactNode } from 'react';
import CyphwardLogo from './CyphwardLogo';
import type { ChipLevel } from './StatusChip';

export * from './Skeleton';

/**
 * Consistent, low-motion loading state for app and owner-console handoffs. A plain status region, not a <main>
 * landmark: it can render inside a shell that already has main#main.
 */
export function LoadingScreen({ label = 'Loading your workspace' }: { label?: string }) {
  return (
    <div className="loading-screen" role="status" aria-live="polite" aria-busy="true">
      <CyphwardLogo variant="mark" size={34} className="loading-screen-mark" />
      <p className="loading-screen-label">{label}</p>
      <div className="loading-track" aria-hidden="true"><span /></div>
    </div>
  );
}

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

export const sevLevel = (s: string): ChipLevel =>
  s === 'CRITICAL' ? 'bad' : s === 'HIGH' ? 'warn' : s === 'MEDIUM' ? 'warn' : 'idle';

export const statusLevel = (s: string): ChipLevel =>
  s === 'CONTAINED' ? 'ok' : s === 'TRIAGED' ? 'idle' : 'warn';

export const ctlLevel = (s: string): ChipLevel =>
  s === 'PASS' ? 'ok' : s === 'FAIL' ? 'bad' : 'warn';
