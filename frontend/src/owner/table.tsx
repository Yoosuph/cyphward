import { useCallback, useContext, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/ui/StatePanels';
import { useToast } from '../components/Toast';
import { OwnerApiError, ownerDownload } from './ownerApi';
import { RefreshNotice, SessionEndedContext, Stat } from './ui';
import { SkControl, SkLine, SkTableRows, SkeletonRegion } from '../components/ui/Skeleton';

/**
 * The owner console's list building blocks (docs/admin-2026-10-29): one table, one filter bar, one pager, one KPI
 * strip and one time-range selector, built from the app's own classes (ledger table, btn-mini, StatePanels).
 *
 * Lists are searched, filtered, sorted and paged on the server; the state lives in the URL so back and forward keep
 * it. The table header sticks while its body scrolls (wider screens); below 640px each row becomes a card
 * (table-stack) and the Sort control in the filter bar replaces the header buttons.
 */

export type Dir = 'asc' | 'desc';

/** List state in the URL: q, offset, limit, sort, dir and any filter. Changing a filter goes back to page 1. */
export function useListParams(defaults: { sort?: string; dir?: Dir; limit?: number } = {}) {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') || '';
  const offset = Math.max(0, Number(params.get('offset') || 0) || 0);
  const limit = [25, 50, 100].includes(Number(params.get('limit'))) ? Number(params.get('limit')) : (defaults.limit || 50);
  const sort = params.get('sort') || defaults.sort || '';
  const dir: Dir = params.get('dir') === 'asc' ? 'asc' : params.get('dir') === 'desc' ? 'desc' : (defaults.dir || 'desc');
  const set = useCallback((next: Record<string, string | number>) => {
    const merged = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v === '' || v === 0 ? merged.delete(k) : merged.set(k, String(v))));
    setParams(merged, { replace: true });
  }, [params, setParams]);
  return { q, offset, limit, sort, dir, set, params };
}

/* ── Table ─────────────────────────────────────────────────────────────── */
export type Column<T> = {
  key: string;
  label: string;
  /** Server sort key; the header becomes a button and carries aria-sort. */
  sortKey?: string;
  /** Direction used when this column is first chosen (dates and counts start newest/largest first). */
  firstDir?: Dir;
  /** The row's heading on phones (one per table). */
  title?: boolean;
  cell: (row: T) => ReactNode;
};

const SORT_LABEL: Record<Dir, 'ascending' | 'descending'> = { asc: 'ascending', desc: 'descending' };

export function OwnerTable<T>({ caption, columns, rows, rowKey, sort, dir, onSort, testId }: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sort: string;
  dir: Dir;
  onSort: (sortKey: string, dir: Dir) => void;
  testId?: string;
}) {
  const sortedBy = columns.find(c => c.sortKey && c.sortKey === sort);
  return (
    <div className="rounded-lg border border-line bg-raised min-w-0">
      <div className="ledger-wrap owner-table-wrap">
        <table className="ledger table-stack owner-table" data-testid={testId}>
          <caption className="sr-only">
            {caption}{sortedBy ? `, sorted by ${sortedBy.label.toLowerCase()}, ${SORT_LABEL[dir]}` : ''}
          </caption>
          <thead>
            <tr>
              {columns.map(c => {
                if (!c.sortKey) return <th key={c.key} scope="col">{c.label.toUpperCase()}</th>;
                const active = c.sortKey === sort;
                const nextDir: Dir = active ? (dir === 'asc' ? 'desc' : 'asc') : (c.firstDir || 'asc');
                const Icon = !active ? ArrowUpDown : dir === 'asc' ? ArrowUp : ArrowDown;
                return (
                  <th key={c.key} scope="col" aria-sort={active ? SORT_LABEL[dir] : 'none'}>
                    <button type="button" className="owner-sort-btn" onClick={() => onSort(c.sortKey!, nextDir)}
                            data-sort-key={c.sortKey}>
                      {c.label.toUpperCase()} <Icon size={11} aria-hidden="true" />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={rowKey(row)} data-testid={testId ? `${testId}-row` : undefined} data-id={rowKey(row)}>
                {columns.map(c => (
                  <td key={c.key} data-label={c.title ? undefined : c.label} className={c.title ? 'stack-title' : undefined}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Loading, error and empty states for a list, from the shared StatePanels; children render only with rows.
 * Nothing to show yet: the list's own skeleton (its column names, table rows, the pager line), or `skeleton`.
 * A filter or page change keeps the current rows, dimmed, until the new ones arrive (`placeholder`); a background
 * refresh changes nothing on screen. A failed refresh with rows on screen shows a notice above them.
 */
export function ListState({ loading, error, onRetry, hasData, count, label, empty, children, columns, skeleton, placeholder = false }: {
  loading: boolean; error: string | null; onRetry: () => void; hasData: boolean; count: number; label: string;
  empty: { title: string; help: string }; children: ReactNode; columns?: string[]; skeleton?: ReactNode; placeholder?: boolean;
}) {
  if (error && !hasData) return <ErrorPanel title={`The ${label} did not load`} message={error} onRetry={onRetry} retrying={loading} />;
  if (!hasData) {
    if (skeleton) return <SkeletonRegion label={label}>{skeleton}</SkeletonRegion>;
    if (!columns) return <LoadingPanel label={label} />;
    return (
      <SkeletonRegion label={label}>
        <SkTableRows columns={columns} rows={8} />
        <div className="flex items-center justify-between gap-3 pt-4"><SkLine width={110} size={10.5} /><div className="flex gap-2"><SkControl width={110} height={32} /><SkControl width={34} height={32} /><SkControl width={34} height={32} /></div></div>
      </SkeletonRegion>
    );
  }
  if (count === 0 && !error) return <EmptyPanel title={empty.title} help={empty.help} />;
  return (
    <div className={`content-fade-in transition-opacity ${placeholder ? 'opacity-70' : ''}`} aria-busy={placeholder || undefined}>
      {error && <RefreshNotice message={error} onRetry={onRetry} retrying={loading} />}
      {children}
    </div>
  );
}

/* ── Filter bar ─────────────────────────────────────────────────────────── */
export function FilterBar({ children, label = 'Filters' }: { children: ReactNode; label?: string }) {
  return (
    <div role="group" aria-label={label} className="owner-filter-bar flex flex-wrap items-end gap-3 mb-4">
      {children}
    </div>
  );
}

export function SelectFilter({ id, label, value, options, onChange }: {
  id: string; label: string; value: string; options: [string, string][]; onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <label htmlFor={id} className="mono text-[10px] tracking-[.16em] text-soft uppercase">{label}</label>
      <select id={id} value={value} onChange={e => onChange(e.target.value)}
              className="app-form-control owner-select mono text-xs bg-raised border border-line rounded px-2.5 py-1.5 text-ink">
        {options.map(([v, l]) => <option key={v || 'all'} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

/** Sort control for every width (the header buttons are hidden when rows become cards on phones). */
export function SortSelect<T>({ id, columns, sort, dir, onChange }: {
  id: string; columns: Column<T>[]; sort: string; dir: Dir; onChange: (sort: string, dir: Dir) => void;
}) {
  const options: [string, string][] = columns.filter(c => c.sortKey).flatMap(c => [
    [`${c.sortKey}:asc`, `${c.label}, ascending`] as [string, string],
    [`${c.sortKey}:desc`, `${c.label}, descending`] as [string, string],
  ]);
  return (
    <SelectFilter id={id} label="Sort" value={`${sort}:${dir}`} options={options}
                  onChange={v => { const [s, d] = v.split(':'); onChange(s, d === 'asc' ? 'asc' : 'desc'); }} />
  );
}

/** Server-side CSV of the list as filtered (capped at 10,000 rows on the server; every export is logged). */
export function ExportButton({ path, params, label = 'Export CSV' }: {
  path: string; params: Record<string, string | number | undefined>; label?: string;
}) {
  const toast = useToast();
  const onSessionEnded = useContext(SessionEndedContext);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await ownerDownload(path, params);
      toast(r.truncated
        ? `Exported the first ${r.rows.toLocaleString()} rows. Narrow the filters to export the rest.`
        : `Exported ${r.rows.toLocaleString()} row${r.rows === 1 ? '' : 's'}. The export is recorded in the owner log.`);
    } catch (e) {
      const err = e as OwnerApiError;
      if (err.status === 401) onSessionEnded();
      else toast(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="btn-mini whitespace-nowrap" onClick={() => void run()} disabled={busy}
            data-testid="owner-export">
      <Download size={12} aria-hidden="true" /> {busy ? 'EXPORTING…' : label.toUpperCase()}
    </button>
  );
}

/* ── Pager ──────────────────────────────────────────────────────────────── */
export function PagerBar({ offset, limit, total, count, onPage, onLimit }: {
  offset: number; limit: number; total: number; count: number; onPage: (offset: number) => void; onLimit: (limit: number) => void;
}) {
  const end = offset + count;
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-3 pt-4 text-[10.5px] mono tracking-[.12em] text-soft">
      <span aria-live="polite">{count === 0 ? 'NO RESULTS' : `${offset + 1}–${end} OF ${total.toLocaleString()}`}</span>
      <div className="flex items-center gap-2">
        <label htmlFor="owner-page-size" className="sr-only">Rows per page</label>
        <select id="owner-page-size" value={limit} onChange={e => onLimit(Number(e.target.value))}
                className="app-form-control owner-select mono text-xs bg-raised border border-line rounded px-2 py-1.5 text-ink">
          {[25, 50, 100].map(n => <option key={n} value={n}>{n} per page</option>)}
        </select>
        <button type="button" className="btn-mini" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))} aria-label="Previous page">
          <ChevronLeft size={12} aria-hidden="true" />
        </button>
        <button type="button" className="btn-mini" disabled={end >= total} onClick={() => onPage(offset + limit)} aria-label="Next page">
          <ChevronRight size={12} aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
}

/* ── KPI strip and time range ───────────────────────────────────────────── */
export type Kpi = { label: string; value: ReactNode; hint?: ReactNode; tone?: 'warn' | 'bad'; to?: string };

export function KpiStrip({ items, label }: { items: Kpi[]; label: string }) {
  return (
    <section aria-label={label} className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4" data-testid="kpi-strip">
      {items.map(k => <Stat key={k.label} label={k.label} value={k.value} hint={k.hint} tone={k.tone} to={k.to} />)}
    </section>
  );
}

export const RANGES = ['7', '30', '90'] as const;
export type Range = typeof RANGES[number];

export function RangeSelector({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  return (
    <div role="group" aria-label="Time range" className="flex gap-2" data-testid="range-selector">
      {RANGES.map(r => (
        <button key={r} type="button" aria-pressed={value === r} onClick={() => onChange(r)}
                className={`btn-mini whitespace-nowrap ${value === r ? '!border-[var(--ink)] !text-ink bg-inset' : ''}`}>
          {r} DAYS
        </button>
      ))}
    </div>
  );
}
