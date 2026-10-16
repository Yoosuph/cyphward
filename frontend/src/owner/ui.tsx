import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-react';
import { OwnerApiError, ownerGet } from './ownerApi';

/* ── Session expiry plumbing: any 401 sends the console back to sign-in ── */
export const SessionEndedContext = createContext<() => void>(() => {});

/** Load one console view; stale responses (filters changed) are ignored. */
export function useOwnerView<T>(path: string, params?: Record<string, string | number | undefined>) {
  const onSessionEnded = useContext(SessionEndedContext);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const key = `${path}?${JSON.stringify(params || {})}`;
  const latest = useRef(key);

  const load = useCallback(async () => {
    latest.current = key;
    setLoading(true);
    setError(null);
    try {
      const result = await ownerGet<T>(path, params);
      if (latest.current === key) setData(result);
    } catch (e) {
      const err = e as OwnerApiError;
      if (err.status === 401) onSessionEnded();
      else if (latest.current === key) setError(err.message);
    } finally {
      if (latest.current === key) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load };
}

/* ── Formatting ─────────────────────────────────────────────────────────── */
export function fmtDate(value?: string | null, withTime = true) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, withTime
    ? { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { day: 'numeric', month: 'short', year: 'numeric' });
}

export function fmtAgo(value?: string | null) {
  if (!value) return 'never';
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (Number.isNaN(seconds)) return '—';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

export function fmtDuration(seconds?: number | null) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function fmtMoney(minor?: number | null, currency?: string | null) {
  if (minor === null || minor === undefined) return '—';
  const amount = Number(minor) / 100;
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'NGN', maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${currency || ''} ${amount.toLocaleString()}`;
  }
}

/* ── Building blocks ────────────────────────────────────────────────────── */
export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-6">
      <div className="min-w-0">
        <h1 className="font-display text-3xl sm:text-4xl leading-tight">{title}</h1>
        {subtitle && <p className="text-sm text-soft mt-1">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Panel({ title, right, children, className = '' }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && (
        <div className="panel-head">
          <h2 className="mono text-[11px] tracking-[.16em] text-soft uppercase">{title}</h2>
          {right}
        </div>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, to, tone }: { label: string; value: ReactNode; hint?: ReactNode; to?: string; tone?: 'warn' | 'bad' }) {
  const body = (
    <div className={`panel p-4 h-full transition-colors ${to ? 'hover:border-[var(--ink)]' : ''}`}>
      <div className="mono text-[10px] tracking-[.16em] text-soft uppercase">{label}</div>
      <div className={`font-display text-3xl mt-2 ${tone === 'bad' ? 'text-accent' : tone === 'warn' ? 'text-amber-600' : ''}`}>{value}</div>
      {hint && <div className="text-xs text-soft mt-1">{hint}</div>}
    </div>
  );
  return to ? <Link to={to} className="block">{body}</Link> : body;
}

const PILL_TONES: Record<string, string> = {
  good: 'bg-ok/10 text-ok border-ok/30',
  warn: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  bad: 'bg-accent/10 text-accent border-accent/30',
  neutral: 'bg-inset text-soft border-line',
};

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: keyof typeof PILL_TONES }) {
  return <span className={`inline-block px-2 py-0.5 rounded border text-[10.5px] mono whitespace-nowrap ${PILL_TONES[tone]}`}>{children}</span>;
}

export function statusTone(status?: string | null): keyof typeof PILL_TONES {
  const s = (status || '').toLowerCase();
  if (['completed', 'verified', 'active', 'paid', 'complete', 'success'].includes(s)) return 'good';
  if (['queued', 'running', 'pending', 'trialing', 'partial', 'issued', 'open', 'queued_delayed'].includes(s)) return 'warn';
  if (['failed', 'cancelled', 'canceled', 'expired', 'past_due', 'denied', 'running_lease_expired', 'unassessed', 'void'].includes(s)) return 'bad';
  return 'neutral';
}

export function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    const id = setTimeout(() => draft !== value && onChange(draft), 300);
    return () => clearTimeout(id);
  }, [draft, value, onChange]);
  return (
    <label className="relative flex-1 min-w-[200px] max-w-md">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-soft" />
      <input
        value={draft}
        onChange={e => setDraft(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full pl-9 pr-3 py-2.5 rounded border border-line bg-raised text-sm mono focus:outline-none focus:border-[var(--ink)]"
      />
    </label>
  );
}

export function Pager({ offset, limit, total, count, onChange }: { offset: number; limit: number; total?: number; count: number; onChange: (o: number) => void }) {
  const end = offset + count;
  return (
    <div className="flex items-center justify-between gap-3 mt-4 text-xs mono text-soft">
      <span>{count === 0 ? 'No results' : `${offset + 1}–${end}${total !== undefined ? ` of ${total}` : ''}`}</span>
      <div className="flex gap-2">
        <button type="button" className="btn btn-ghost" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))} aria-label="Previous page">
          <ChevronLeft size={13} />
        </button>
        <button type="button" className="btn btn-ghost" disabled={total !== undefined ? end >= total : count < limit} onClick={() => onChange(offset + limit)} aria-label="Next page">
          <ChevronRight size={13} />
        </button>
      </div>
    </div>
  );
}

export function ViewState({ loading, error, onRetry, empty, children }: { loading: boolean; error: string | null; onRetry: () => void; empty?: boolean; children: ReactNode }) {
  if (error) {
    return (
      <div className="panel p-6 text-center">
        <AlertCircle className="mx-auto text-accent mb-2" size={22} />
        <p className="text-sm mb-3">{error}</p>
        <button type="button" className="btn btn-ghost" onClick={onRetry}><RefreshCw size={13} /> RETRY</button>
      </div>
    );
  }
  if (loading && empty !== false) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2].map(i => <div key={i} className="skeleton" style={{ height: 64, borderRadius: 6 }} />)}
      </div>
    );
  }
  return <>{children}</>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-soft py-6 text-center">{children}</p>;
}

/** Responsive table: rows become labelled cards below 640px (table-stack). */
export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto -mx-5 px-5 sm:mx-0 sm:px-0">
      <table className="table-stack w-full text-left text-[12.5px]">
        <thead>
          <tr className="border-b border-line text-soft">
            {head.map(h => <th key={h} className="mono text-[10px] tracking-[.14em] uppercase font-medium py-2.5 pr-4">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({ label, children, title }: { label?: string; children: ReactNode; title?: boolean }) {
  return (
    <td data-label={title ? undefined : label} className={`${title ? 'stack-title ' : ''}py-2.5 pr-4 align-top`}>
      {children}
    </td>
  );
}
