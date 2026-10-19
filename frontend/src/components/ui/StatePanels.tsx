import type { ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Skeleton, SkeletonText } from '../Skeleton';

/**
 * The three states every list or panel shows besides "has data". Use them instead of ad-hoc text.
 *
 *   if (error && !data) return <ErrorPanel title="We could not load incidents" message={humanError(error, '…')} onRetry={load} />;
 *   if (!data) return <LoadingPanel label="incidents" />;
 *   if (rows.length === 0) return <EmptyPanel title="No incidents yet" help="…" action={<button …/>} />;
 *
 * Each has a title, one line of help and, where it makes sense, the one action that moves things on.
 */

const PANEL = 'rounded-lg border border-line bg-raised';

export function LoadingPanel({ label, lines = 3 }: { label: string; lines?: number }) {
  return (
    <div className={`${PANEL} p-5 space-y-3`} role="status" aria-busy="true" aria-live="polite" data-testid="state-loading">
      <p className="text-xs mono text-soft">Loading {label}…</p>
      <Skeleton width="40%" height={18} />
      <SkeletonText lines={lines} lastLineWidth="60%" />
    </div>
  );
}

export function EmptyPanel({ icon, title, help, action }: { icon?: ReactNode; title: string; help: string; action?: ReactNode }) {
  return (
    <div className={`${PANEL} px-5 py-9 text-center space-y-2`} data-testid="state-empty">
      {icon && <div className="mx-auto text-accent flex justify-center mb-1" aria-hidden="true">{icon}</div>}
      <p className="text-sm text-ink font-medium">{title}</p>
      <p className="text-xs text-soft max-w-md mx-auto leading-relaxed">{help}</p>
      {action && <div className="pt-2 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorPanel({ title, message, onRetry, retrying = false }: { title: string; message: string; onRetry: () => void; retrying?: boolean }) {
  return (
    <div className={`${PANEL} px-5 py-9 text-center space-y-2`} role="alert" data-testid="state-error">
      <AlertTriangle size={20} className="mx-auto text-accent" aria-hidden="true" />
      <p className="text-sm text-ink font-medium">{title}</p>
      <p className="text-xs text-soft max-w-md mx-auto leading-relaxed">{message}</p>
      <div className="pt-2 flex justify-center">
        <button type="button" className="btn btn-solid btn-mini touch-target" onClick={onRetry} disabled={retrying}>
          <RefreshCw size={12} className={retrying ? 'animate-spin' : ''} aria-hidden="true" /> {retrying ? 'Trying again…' : 'Try again'}
        </button>
      </div>
    </div>
  );
}

/**
 * A message that is safe to show: never a status line, a stack or the server's own wording for a 5xx.
 * Short, plain 4xx messages from the API (for example "That time does not exist in Africa/Lagos") pass through.
 */
export function humanError(e: unknown, fallback: string): string {
  const err = e as { status?: number; message?: string } | null;
  const status = err?.status;
  const text = (err?.message || '').trim();
  if (status === undefined && (e instanceof TypeError || /failed to fetch|network|load failed/i.test(text))) {
    return 'We could not reach Cyphward. Check your connection and try again.';
  }
  if (status === 401) return 'Your session has ended. Sign in again to carry on.';
  if (status === 403) return 'Your role cannot do this. Ask an owner or an admin.';
  if (status === 429) return 'Too many requests. Wait a moment and try again.';
  if (status && status >= 500) return fallback;
  const raw = /^request failed|status \d{3}|traceback|internal server error|unprocessable|bad request|^\{|^\[/i.test(text);
  if (status && status >= 400 && text && text.length <= 240 && !raw) return text;
  return fallback;
}
