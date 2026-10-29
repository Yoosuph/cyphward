import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ChevronLeft, ChevronRight, Search, type LucideIcon } from 'lucide-react';
import StatusChip, { type ChipLevel } from '../components/StatusChip';
import { PageHead as AppPageHead } from '../components/ui';
import { ErrorPanel, LoadingPanel } from '../components/ui/StatePanels';
import { OwnerApiError, ownerGet } from './ownerApi';

/* ── Session expiry plumbing: any 401 sends the console back to sign-in ── */
export const SessionEndedContext = createContext<() => void>(() => {});

/** The signed-in owner (to hide actions that would target their own account). */
export const OwnerMeContext = createContext<{ email: string } | null>(null);

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
      // The message is already reviewed wording (ownerApi.ownerErrorText): never the server's own text.
      else if (latest.current === key) setError(err.message || 'The console could not load this view. Try again in a moment.');
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

/* ── Building blocks (the customer app's own classes and markup) ──────── */
const CARD = 'rounded-lg border border-line bg-raised';

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6">
      <AppPageHead title={title} note={subtitle} actions={actions} />
    </div>
  );
}

export function Panel({ title, right, children, className = '' }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`${CARD} min-w-0 ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-line">
          <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">{title}</h2>
          {right}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, to, tone, icon: Icon }: {
  label: string; value: ReactNode; hint?: ReactNode; to?: string; tone?: 'warn' | 'bad'; icon?: LucideIcon;
}) {
  const toneText = tone === 'bad' ? 'text-accent' : tone === 'warn' ? 'text-warn' : 'text-ink';
  const body = (
    <div className={`p-4 h-full ${CARD} flex flex-col justify-between group transition-all ${to ? `card-hover cursor-pointer ${tone === 'bad' ? 'hover:border-accent' : 'hover:border-line-strong'}` : ''}`}>
      <div className="flex items-center justify-between gap-2 text-soft">
        <span className={`text-[11px] mono uppercase ${tone ? `${toneText} font-medium` : ''}`}>{label}</span>
        {Icon && <Icon size={15} className={tone === 'bad' ? 'text-accent' : 'group-hover:text-accent transition-colors'} />}
      </div>
      <div className="my-2">
        <div className={`text-3xl font-bold mono ${toneText}`}>{value}</div>
        {hint && <p className="text-[11px] text-soft">{hint}</p>}
      </div>
      {to && <div className={`text-[10px] mono flex items-center gap-1 ${tone === 'bad' ? 'text-accent' : 'text-soft group-hover:text-accent'}`}>OPEN <ArrowRight size={10} /></div>}
    </div>
  );
  return to ? <Link to={to} className="block">{body}</Link> : body;
}

type Tone = 'good' | 'warn' | 'bad' | 'neutral';
const CHIP_LEVEL: Record<Tone, ChipLevel> = { good: 'ok', warn: 'warn', bad: 'bad', neutral: 'idle' };

/** Status reads as the app's dot chip; plain labels (roles, neutral) as a tag. */
export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  if (tone === 'neutral') return <span className="tag uppercase">{children}</span>;
  return <span className="uppercase"><StatusChip level={CHIP_LEVEL[tone]}>{children}</StatusChip></span>;
}

export function statusTone(status?: string | null): Tone {
  const s = (status || '').toLowerCase();
  if (['completed', 'verified', 'active', 'paid', 'complete', 'success'].includes(s)) return 'good';
  if (['queued', 'running', 'pending', 'trialing', 'partial', 'issued', 'open', 'queued_delayed'].includes(s)) return 'warn';
  if (['failed', 'cancelled', 'canceled', 'expired', 'past_due', 'denied', 'running_lease_expired', 'unassessed', 'void'].includes(s)) return 'bad';
  return 'neutral';
}

/** Filter chip row button (status / state filters). */
export function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
            className={`btn-mini shrink-0 whitespace-nowrap uppercase ${active ? '!border-[var(--ink)] !text-ink bg-inset' : ''}`}>
      {children}
    </button>
  );
}

export function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    const id = setTimeout(() => draft !== value && onChange(draft), 300);
    return () => clearTimeout(id);
  }, [draft, value, onChange]);
  return (
    <label className="relative w-full md:w-80">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-soft" aria-hidden="true" />
      <input
        value={draft}
        onChange={e => setDraft(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="app-form-control w-full pl-9 pr-3 py-1.5 rounded bg-raised border border-line text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
      />
    </label>
  );
}

export function Pager({ offset, limit, total, count, onChange }: { offset: number; limit: number; total?: number; count: number; onChange: (o: number) => void }) {
  const end = offset + count;
  return (
    <div className="flex items-center justify-between gap-3 pt-4 text-[10.5px] mono tracking-[.12em] text-soft">
      <span>{count === 0 ? 'NO RESULTS' : `${offset + 1}–${end}${total !== undefined ? ` OF ${total}` : ''}`}</span>
      <div className="flex gap-2">
        <button type="button" className="btn-mini" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))} aria-label="Previous page">
          <ChevronLeft size={12} />
        </button>
        <button type="button" className="btn-mini" disabled={total !== undefined ? end >= total : count < limit} onClick={() => onChange(offset + limit)} aria-label="Next page">
          <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}

/** Loading and error states for a console view: the same shared panels the customer app uses. */
export function ViewState({ loading, error, onRetry, empty, children }: { loading: boolean; error: string | null; onRetry: () => void; empty?: boolean; children: ReactNode }) {
  if (error) return <ErrorPanel title="This view did not load" message={error} onRetry={onRetry} retrying={loading} />;
  if (loading && empty !== false) return <LoadingPanel label="this view" />;
  return <div className="content-fade-in">{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-xs text-soft" data-testid="state-empty">{children}</p>;
}

/** The app's ledger table; rows become labelled cards below 640px (table-stack). */
export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="ledger-wrap -mx-5 first:-mt-5">
      <table className="ledger table-stack">
        <thead>
          <tr>{head.map(h => <th key={h}>{h.toUpperCase()}</th>)}</tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({ label, children, title }: { label?: string; children: ReactNode; title?: boolean }) {
  return (
    <td data-label={title ? undefined : label} className={title ? 'stack-title' : undefined}>
      {children}
    </td>
  );
}
