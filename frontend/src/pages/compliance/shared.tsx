import { Link } from 'react-router-dom';
import { Lock } from 'lucide-react';
import { ErrorPanel, humanError } from '../../components/ui/StatePanels';
import { FIELD_CONTROL, FIELD_LABEL_CLASS } from '../../components/ui/DateTimeField';

/** Times on the compliance pages are shown in the organisation's display zone, never the viewer's. */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function safeZone(zone: string): string | undefined {
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: zone });
    return zone;
  } catch {
    return undefined;
  }
}

export function fmtDayZone(value: string | null | undefined, zone: string): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: safeZone(zone) }).format(d);
}

export function fmtTimeZone(value: string | null | undefined, zone: string): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: safeZone(zone),
  }).format(d).replace(',', '');
}

/** Formats the wall-clock part of an offset ISO string from the API's `local` block (already in the organisation's zone). */
export function fmtLocal(value: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value || '');
  if (!m) return '—';
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]} ${m[4]}:${m[5]}`;
}

/** A message that is safe to show people: short server text for 4xx, the fallback for anything technical. */
export function errorText(e: unknown, fallback: string): string {
  return humanError(e, fallback);
}

export const isGrowthGate = (e: unknown) => (e as { status?: number })?.status === 403;

export const FIELD_BOX = FIELD_CONTROL;
export const FIELD_LABEL = FIELD_LABEL_CLASS;

export function GrowthGate({ what }: { what: string }) {
  return (
    <div className="rounded-lg border border-line bg-raised p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-3" data-testid="growth-gate">
      <div className="space-y-1.5">
        <span className="tag uppercase inline-flex items-center gap-1.5"><Lock size={10} /> Growth plan</span>
        <p className="text-sm text-soft">{what} is part of the Growth plan.</p>
      </div>
      <Link to="/settings" className="btn-mini whitespace-nowrap self-start">SEE PLANS</Link>
    </div>
  );
}

export function LoadError({ title = 'We could not load this section', message, onRetry }: { title?: string; message: string; onRetry: () => void }) {
  return <ErrorPanel title={title} message={message} onRetry={onRetry} />;
}

export function ReadOnlyNote() {
  return (
    <p className="text-xs mono text-soft" data-testid="read-only-note">
      You can look at this page. Only owners and admins can make changes.
    </p>
  );
}
