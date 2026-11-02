/**
 * The one skeleton system (docs/ui-motion-cache-2026-11-01/AUDIT.md, "Skeletons").
 *
 * A data page renders its real header and controls at once and puts a skeleton only where the data goes, built
 * from these shapes, so the first screen keeps its size when the data arrives. Every skeleton region is a
 * labelled status (`role=status`, `aria-busy`, `data-testid="state-loading"`) with "Loading …" for screen
 * readers; the shapes themselves are hidden from assistive technology (Skeleton is aria-hidden; any placeholder
 * text inside a region must be aria-hidden too).
 *
 *   <SkeletonRegion label="saved reports"><SkTableRows columns={['Report', 'Domain', 'Created', '']} rows={4} /></SkeletonRegion>
 *
 * Shapes: SkLine, SkBlock, SkCard, SkTableRows, SkKpi, SkChart, SkListItem, SkField, SkControl. Tables use the app's
 * ledger markup with `table-stack`, so below 640px each row is a stacked card like the real table. Control
 * placeholders (buttons, selects, tabs) are 44px tall on phones, like the controls they stand for.
 */
import type { CSSProperties, ReactNode } from 'react';
import { Skeleton, SkeletonText } from '../Skeleton';

export { Skeleton, SkeletonText };

type Size = number | string;

/** The labelled loading region every page and panel uses while it has nothing to show. */
export function SkeletonRegion({ label, children, className = '', as: Tag = 'div' }: {
  label: string; children: ReactNode; className?: string; as?: 'div' | 'section';
}) {
  return (
    <Tag className={`sk-region ${className}`} role="status" aria-busy="true" aria-live="polite" data-testid="state-loading">
      {children}
      {/* Last, so spacing utilities on the region (space-y, grids) apply to the shapes as they do to the content. */}
      <span className="sr-only">Loading {label}…</span>
    </Tag>
  );
}

/** One line of text. `size` is the font size it stands in for (its line box is 1.5x). */
export function SkLine({ width = '100%', size = 12, className = '' }: { width?: Size; size?: number; className?: string }) {
  return <div className={`sk-line ${className}`} style={{ height: Math.round(size * 1.5) }}><Skeleton width={width} height={size} className="skeleton-text" /></div>;
}

export function SkBlock({ width = '100%', height, rounded = 'md', className = '', style }: {
  width?: Size; height: Size; rounded?: 'sm' | 'md' | 'lg'; className?: string; style?: CSSProperties;
}) {
  return <Skeleton width={width} height={height} rounded={rounded} className={className} style={style} />;
}

/** A button, select, chip or tab: 44px tall on phones, its desktop height above. */
export function SkControl({ width = 96, height = 32, className = '' }: { width?: Size | null; height?: number; className?: string }) {
  // width null: the className sets it (for widths that change between phone and desktop).
  return <div className={`sk-control ${className}`} style={{ ...(width === null ? {} : { width }), ['--sk-h' as string]: `${height}px` } as CSSProperties}><Skeleton width="100%" height="100%" /></div>;
}

/** A label above a field. */
export function SkField({ width = '100%', className = '' }: { width?: Size; className?: string }) {
  return (
    <div className={`sk-field ${className}`} style={{ width }}>
      <SkLine width="35%" size={10} />
      <SkControl width="100%" height={42} />
    </div>
  );
}

/** The app's panel: optional title bar, then lines. */
export function SkCard({ title = true, lines = 3, height, className = '', children }: {
  title?: boolean; lines?: number; height?: Size; className?: string; children?: ReactNode;
}) {
  return (
    <div className={`rounded-lg border border-line bg-raised min-w-0 ${className}`} style={height !== undefined ? { minHeight: height } : undefined}>
      {title && <div className="px-5 py-3.5 border-b border-line"><SkLine width="32%" size={11} /></div>}
      <div className="p-5 space-y-2">{children ?? <SkeletonText lines={lines} lastLineWidth="55%" />}</div>
    </div>
  );
}

/** A KPI tile the size of a Stat / StatCard. */
export function SkKpi({ className = '', hint = true }: { className?: string; hint?: boolean }) {
  return (
    <div className={`sk-kpi rounded-lg border border-line bg-raised p-4 flex flex-col justify-between ${className}`}>
      <SkLine width="45%" size={11} />
      <div className="my-2 space-y-1">
        <SkLine width="38%" size={30} />
        {hint && <SkLine width="70%" size={11} />}
      </div>
    </div>
  );
}

/** A chart area of a fixed height (the real chart draws into the same box). */
export function SkChart({ height = 160, bars = 14, className = '' }: { height?: number; bars?: number; className?: string }) {
  return (
    <div className={`flex items-end gap-1.5 ${className}`} style={{ height }}>
      {Array.from({ length: bars }).map((_, i) => (
        <div key={i} className="flex-1 min-w-0 h-full flex items-end"><Skeleton width="100%" height={`${30 + ((i * 37) % 60)}%`} /></div>
      ))}
    </div>
  );
}

/** A row in a list: an optional mark, two lines and something on the right. */
export function SkListItem({ mark = false, aside = true, className = '' }: { mark?: boolean; aside?: boolean; className?: string }) {
  return (
    <div className={`flex items-center gap-3 py-3 ${className}`}>
      {mark && <Skeleton width={28} height={28} rounded="md" />}
      <div className="flex-1 min-w-0 space-y-1"><SkLine width="55%" size={13} /><SkLine width="80%" size={11} /></div>
      {aside && <SkControl width={72} height={28} />}
    </div>
  );
}

/**
 * Table rows in the app's ledger markup (header row with the real column names, then rows). Pass `bare` to render
 * only the <tr>s for a <tbody> the page already owns.
 */
export function SkTableRows({ columns, rows = 5, bare = false, framed = true, className = '' }: {
  columns: string[]; rows?: number; bare?: boolean; framed?: boolean; className?: string;
}) {
  const widths = ['72%', '58%', '46%', '64%', '40%', '52%', '36%', '48%'];
  const body = Array.from({ length: rows }).map((_, r) => (
    <tr key={r} aria-hidden="true">
      {columns.map((c, i) => (
        <td key={i} data-label={i === 0 || !c ? undefined : c} className={i === 0 ? 'stack-title' : undefined}>
          <SkLine width={widths[(i + r) % widths.length]} size={i === 0 ? 13 : 12} />
        </td>
      ))}
    </tr>
  ));
  if (bare) return <>{body}</>;
  const table = (
    <div className="ledger-wrap">
      <table className="ledger table-stack sk-table">
        <thead><tr>{columns.map((c, i) => <th key={i} scope="col">{c.toUpperCase()}</th>)}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  );
  return framed ? <div className={`rounded-lg border border-line bg-raised min-w-0 ${className}`}>{table}</div> : table;
}
