import { Link } from 'react-router-dom';
import { AlertTriangle, Lock } from 'lucide-react';

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

/** Value for a datetime-local input from an API `local` string. Wall time in the organisation's zone. */
export function toInputValue(value: string | null | undefined): string {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value || '') ? (value as string).slice(0, 16) : '';
}

/** A datetime-local value sent as naive wall time; the server reads it in the organisation's zone. */
export function naiveTime(value: string): string {
  return value.length === 16 ? `${value}:00` : value;
}

export function errorText(e: unknown, fallback: string): string {
  return (e as Error)?.message || fallback;
}

export const isGrowthGate = (e: unknown) => (e as { status?: number })?.status === 403;

export const FIELD_BOX = 'w-full font-mono text-[12.5px] bg-inset border border-line rounded-[3px] px-3 py-3 text-ink outline-none focus:border-ink min-w-0';
export const FIELD_LABEL = 'block mono text-[10px] tracking-[.18em] text-soft mb-2 uppercase';

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

export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="bg-inset border border-line rounded p-8 text-center space-y-3">
      <AlertTriangle size={20} className="mx-auto text-accent" />
      <p className="text-sm mono">We couldn't load this section.</p>
      <p className="text-xs mono text-soft max-w-md mx-auto">{message}</p>
      <button type="button" className="btn btn-solid btn-mini" onClick={onRetry}>RETRY</button>
    </div>
  );
}

export function ReadOnlyNote() {
  return (
    <p className="text-xs mono text-soft" data-testid="read-only-note">
      You can view this section. Owners and admins can change it.
    </p>
  );
}
