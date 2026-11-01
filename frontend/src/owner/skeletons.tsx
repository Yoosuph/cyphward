/**
 * Owner console skeletons: the same shapes as the customer app (components/ui/Skeleton) in the console's own
 * grids (Panel, Stat, ledger tables), one per view, so a view keeps its layout when its data arrives. Views pass
 * these to ViewState / ListState, which wrap them in the labelled loading region.
 */
import { SkControl, SkKpi, SkLine, SkTableRows } from '../components/ui/Skeleton';
import type { ReactNode } from 'react';

/** The console's Panel with a title bar. */
export function SkPanel({ className = '', children, title = true }: { className?: string; children: ReactNode; title?: boolean }) {
  return (
    <section className={`rounded-lg border border-line bg-raised min-w-0 ${className}`}>
      {title && <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-line"><SkLine width={140} size={11} /></div>}
      <div className="p-5">{children}</div>
    </section>
  );
}

/** A definition list (label / value rows) inside a panel. */
export function SkDefinitions({ rows = 5 }: { rows?: number }) {
  return (
    <div className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2">
      {Array.from({ length: rows }).map((_, i) => [<SkLine key={`k${i}`} width={84} size={14} />, <SkLine key={`v${i}`} width={`${45 + ((i * 17) % 40)}%`} size={14} />])}
    </div>
  );
}

/** A table inside a panel (the panel's Table sits flush with its edges). */
export function SkPanelTable({ columns, rows = 3 }: { columns: string[]; rows?: number }) {
  return <div className="-mx-5 -my-5"><SkTableRows columns={columns} rows={rows} framed={false} /></div>;
}

export function SkKpiRow({ count = 4, className = 'mb-4' }: { count?: number; className?: string }) {
  // A Stat card: 137px with a one-line hint; its hint wraps to two lines in the two-column phone grid.
  return <div className={`grid grid-cols-2 lg:grid-cols-4 gap-4 ${className}`}>{Array.from({ length: count }).map((_, i) => <SkKpi key={i} className="!min-h-[146px] lg:!min-h-[137px]" />)}</div>;
}

export function OverviewSkeleton() {
  return (
    <>
      <SkKpiRow />
      <SkKpiRow className="mb-5" />
      <div className="grid lg:grid-cols-2 gap-5">
        <SkPanel><div className="h-32 flex items-end gap-1.5">{Array.from({ length: 14 }).map((_, i) => <div key={i} className="flex-1 h-full flex items-end"><div className="skeleton w-full" style={{ height: `${20 + ((i * 29) % 70)}%` }} /></div>)}</div></SkPanel>
        <SkPanel><div className="space-y-2">{[0, 1, 2].map(i => <SkLine key={i} width="80%" size={14} />)}</div></SkPanel>
        <SkPanel className="lg:col-span-2"><SkPanelTable columns={['Action', 'Organization', 'User', 'When']} rows={4} /></SkPanel>
      </div>
    </>
  );
}

export type PanelSpec = { wide?: boolean; kind: 'dl' | 'table' | 'text'; rows?: number; cols?: string[] };

/** A detail view: its panels in order (half or full width), each a definition list, a table or a line of text. */
export function DetailSkeleton({ panels }: { panels: PanelSpec[] }) {
  return (
    <div className="grid lg:grid-cols-2 gap-5">
      {panels.map((p, i) => (
        <SkPanel key={i} className={p.wide ? 'lg:col-span-2' : ''}>
          {p.kind === 'dl' ? <SkDefinitions rows={p.rows ?? 4} />
            : p.kind === 'table' ? <SkPanelTable columns={p.cols ?? ['', '', '']} rows={p.rows ?? 2} />
            : <div className="py-8 flex justify-center"><SkLine width="40%" size={12} /></div>}
        </SkPanel>
      ))}
    </div>
  );
}

export function SystemSkeleton() {
  return (
    <div className="grid lg:grid-cols-2 gap-5">
      <SkPanel><SkDefinitions rows={5} /></SkPanel>
      <SkPanel><SkDefinitions rows={4} /><div className="mt-3"><SkLine width="85%" size={12} /></div></SkPanel>
      <SkPanel className="lg:col-span-2"><SkPanelTable columns={['Job', 'Day', 'Status', 'Started', 'Finished']} rows={1} /></SkPanel>
    </div>
  );
}

/** A panel holding a table and a pager (the console's scans list). */
export function PanelListSkeleton({ columns, rows = 8 }: { columns: string[]; rows?: number }) {
  return (
    <SkPanel title={false}>
      <SkPanelTable columns={columns} rows={rows} />
      <div className="flex items-center justify-between gap-3 pt-9"><SkLine width={90} size={10.5} /><div className="flex gap-2"><SkControl width={34} height={32} /><SkControl width={34} height={32} /></div></div>
    </SkPanel>
  );
}

export function NewsletterListSkeleton() {
  return (
    <>
      <SkKpiRow className="mb-5" />
      <SkPanel><SkPanelTable columns={['Subject', 'Status', 'Created', 'Created by', 'Sections']} rows={4} /></SkPanel>
    </>
  );
}

export function NewsletterDraftSkeleton() {
  return (
    <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-5 items-start">
      <div className="space-y-5 min-w-0">
        <SkPanel><SkDefinitions rows={7} /></SkPanel>
        <SkPanel><div className="space-y-5">{[0, 1, 2].map(i => <div key={i} className="space-y-1"><SkLine width={80} size={11} /><SkLine width="60%" size={14} /><SkLine width="90%" size={14} /></div>)}</div></SkPanel>
      </div>
      <SkPanel><div className="skeleton w-full rounded" style={{ height: 520 }} /></SkPanel>
    </div>
  );
}

/** A day-by-day chart area (StackedDays draws into h-36 with a caption line). */
export function ChartSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="flex items-end gap-px h-36">{Array.from({ length: 30 }).map((_, i) => <div key={i} className="flex-1 h-full flex items-end"><div className="skeleton w-full" style={{ height: `${10 + ((i * 37) % 80)}%`, borderRadius: 0 }} /></div>)}</div>
      <div className="flex justify-between gap-2 mt-2"><SkLine width={120} size={10} /><SkLine width={200} size={10} /></div>
    </div>
  );
}

/** Stands in for a PageHead subtitle that arrives with the data, so the header keeps its height. */
export function SubtitleSkeleton({ width = 260, phoneLines = 2 }: { width?: number; phoneLines?: 1 | 2 }) {
  // One line from 640px; on phones as many lines as the loaded subtitle wraps to (an email and a date take two).
  return (
    <span aria-hidden="true">
      <span className="inline-block align-middle skeleton" style={{ width, maxWidth: '100%', height: 12 }} />
      {phoneLines === 2 && <span className="sm:hidden block skeleton" style={{ width: '45%', height: 12, marginTop: 9 }} />}
    </span>
  );
}

export function AnalyticsKpiSkeleton() {
  return <><SkKpiRow className="mb-4" /><SkKpiRow className="mb-4" /></>;
}
