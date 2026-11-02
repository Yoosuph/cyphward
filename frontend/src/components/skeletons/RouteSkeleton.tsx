/**
 * One skeleton per customer-app route and subpage (docs/ui-motion-cache-2026-11-01/AUDIT.md, "Skeletons").
 *
 * Each skeleton renders the page's real header (the same PageHead, title and note) and shapes in the page's own
 * containers and classes, so the first screen keeps its size when the data arrives. A page shows its skeleton on
 * its first data load; RouteSkeleton shows the same thing while a page's code is still downloading (a cold deep
 * link), so a visitor never sees a blank frame or the previous page. Eager and small: no page code, no charts.
 */
import type { ReactNode } from 'react';
import { PageHead } from '../ui';
import { useAuth } from '../../lib/auth';
import { SkBlock, SkCard, SkControl, SkField, SkKpi, SkLine, SkListItem, SkTableRows, SkeletonRegion, Skeleton } from '../ui/Skeleton';
import '../../pages/Scans.css';
import '../../pages/compliance/compliance.css';

/* ── Pieces ─────────────────────────────────────────────────────────────── */

/** Placeholders for a header's action buttons (44px tall on phones, like the buttons). */
export function SkActions({ widths }: { widths: number[] }) {
  return <>{widths.map((w, i) => <SkControl key={i} width={w} height={38} />)}</>;
}

/** A page's table rows in the app's own table markup (`<tbody>` of a page table). */
export function AppTableRows({ columns, rows = 6, twoLine = false }: { columns: string[]; rows?: number; twoLine?: boolean }) {
  const widths = ['70%', '55%', '45%', '62%', '40%', '50%', '35%', '30%'];
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} aria-hidden="true" data-testid="skeleton-row">
          {columns.map((c, i) => (
            <td key={i} data-label={i === 0 ? undefined : c} className={`py-3 px-4 ${i === 0 ? 'stack-title' : ''} ${i === columns.length - 1 ? 'text-right' : ''}`}>
              <SkLine width={widths[(i + r) % widths.length]} size={12} />
              {i === 0 && twoLine && <SkLine width="45%" size={10} className="mt-1" />}
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/** A page table (the app's own markup) whose body is skeleton rows. */
export function AppTableSkeleton({ columns, rows = 6, tableClass = 'sm:min-w-[640px]', twoLine = false, inset = true }: {
  columns: string[]; rows?: number; tableClass?: string; twoLine?: boolean; inset?: boolean;
}) {
  return (
    <div className="rounded-lg border border-line bg-raised overflow-hidden">
      <div className="overflow-x-auto w-full max-w-full">
        <table className={`table-stack w-full text-left text-xs mono ${tableClass}`}>
          <thead>
            <tr className={`border-b border-line ${inset ? 'bg-inset/40' : ''} text-soft text-[11px]`}>
              {columns.map((c, i) => <th key={i} className={`py-3 px-4 font-medium ${i === columns.length - 1 ? 'text-right' : ''}`}>{c}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-line/60"><AppTableRows columns={columns} rows={rows} twoLine={twoLine} /></tbody>
        </table>
      </div>
    </div>
  );
}

/** A row of filter chips (each a 44px control on phones). */
export function SkChips({ widths, className = '', gap = 'gap-1.5', height = 26 }: { widths: number[]; className?: string; gap?: 'gap-1.5' | 'gap-2'; height?: number }) {
  return <div className={`chip-row flex flex-wrap items-center ${gap} ${className}`}>{widths.map((w, i) => <SkControl key={i} width={w} height={height} />)}</div>;
}

/** A finding card the size of the real one. */
export function FindingCardSk() {
  return (
    <div className="p-4 rounded-lg border border-line bg-raised flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div className="space-y-1.5 flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2"><Skeleton width={70} height={22} /><Skeleton width={130} height={22} /><Skeleton width={90} height={12} /></div>
        <SkLine width="60%" size={14} />
        <SkLine width="85%" size={12} />
      </div>
      <div className="flex items-center gap-3 shrink-0"><SkControl width={119} height={30} /></div>
    </div>
  );
}

/* ── Overview ───────────────────────────────────────────────────────────── */
export function OverviewSkeleton() {
  const { organization } = useAuth();
  return (
    <SkeletonRegion label="your overview" className="space-y-6 max-w-7xl mx-auto pb-12">
      <PageHead title={organization?.name || 'Overview'} note="Your score, open issues and latest scans."
                actions={<><SkControl width={null} className="w-[125px] sm:w-[40px]" height={38} /><SkActions widths={[203, 120]} /></>} />
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className="lg:col-span-4 p-6 rounded-lg border border-line bg-raised/70 flex flex-col items-center text-center">
          <div className="w-full flex items-center justify-between gap-2"><SkLine width={110} size={11} /><Skeleton width={71} height={24} /></div>
          <div className="my-3"><Skeleton width={176} height={176} variant="circle" /></div>
          <Skeleton width={70} height={24} rounded="full" />
          <div className="mt-2 w-full flex justify-center"><SkLine width="70%" size={13.5} /></div>
          <div className="score-details"><div className="sk-summary flex items-center justify-center"><Skeleton width={150} height={11} /></div></div>
        </div>
        <div className="lg:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-4 content-start">
          {[0, 1, 2, 3].map(i => <SkKpi key={i} className={i < 2 ? '!min-h-[155px]' : '!min-h-[137px] md:!min-h-[155px]'} />)}
          <div className="col-span-2 md:col-span-4 p-4 rounded-lg border border-line bg-inset/50 space-y-3 min-h-[127px] md:min-h-[101px]">
            <div className="flex justify-between"><SkLine width={140} size={11} /><SkLine width={90} size={11} /></div>
            <Skeleton height={12} rounded="full" />
            <div className="flex flex-wrap gap-x-6 gap-y-2">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} width={80} height={12} />)}</div>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        <div className="lg:col-span-7 p-5 rounded-lg border border-line bg-raised space-y-4 min-h-[183px] lg:min-h-[167px]"><SkLine width="40%" size={13} /><SkLine width="90%" size={12} /><SkLine width="70%" size={12} /></div>
        <div className="lg:col-span-5 p-5 rounded-lg border border-line bg-raised space-y-4 min-h-[236px] lg:min-h-[184px]"><SkLine width="50%" size={13} /><SkLine width="85%" size={12} /><SkLine width="60%" size={12} /></div>
      </div>
      <div className="p-5 rounded-lg border border-line bg-raised">
        <div className="flex items-center justify-between mb-4"><SkLine width={120} size={13} /><SkLine width={90} size={11} /></div>
        <SkTableRows columns={['Domain', 'Status', 'Progress', 'Score', 'Started', 'Action']} rows={3} framed={false} />
      </div>
    </SkeletonRegion>
  );
}

/* ── Findings ───────────────────────────────────────────────────────────── */
export function FindingsListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <SkeletonRegion label="issues" className="space-y-3">
      {Array.from({ length: count }).map((_, i) => <FindingCardSk key={i} />)}
    </SkeletonRegion>
  );
}

function FindingsSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      <PageHead title="Findings" note="Security issues from your scans, worst first. Open one to see the evidence and how to fix it." actions={<SkActions widths={[92]} />} />
      <div className="flex flex-wrap items-center gap-1 p-1 rounded-md border border-line bg-raised w-fit">{[67, 96, 60].map((w, i) => <SkControl key={i} width={w} height={24} />)}</div>
      <div className="flex flex-col md:flex-row md:items-center gap-2"><SkChips widths={[46, 84, 55, 69, 48, 55]} gap="gap-2" className="min-w-0" /><div className="md:ml-auto w-full md:w-64 shrink-0"><SkControl width="100%" height={26} /></div></div>
      <FindingsListSkeleton />
    </div>
  );
}

/* ── Assets, Domains, Remediation, Reports (header + table) ─────────────── */
export const ASSET_COLUMNS = ['HOSTNAME & DOMAIN', 'IP ADDRESS', 'ASSET TYPE', 'HTTP STATUS', 'SOFTWARE FOUND', 'SSL/TLS', 'ISSUES', 'ACTION'];
export const DOMAIN_COLUMNS = ['DOMAIN NAME', 'STATUS', 'VERIFICATION RECORD', 'VERIFIED ON', 'ASSETS FOUND', 'ACTIONS'];
export const TASK_COLUMNS = ['TASK', 'PRIORITY', 'STATUS', 'ASSIGNEE', 'ACTIONS'];
export const REPORT_COLUMNS = ['TITLE', 'DOMAIN', 'STATUS', 'SCORE', 'CREATED', 'ACTIONS'];

function AssetsSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      <PageHead title="Assets" note="Hosts found on your verified domains, with their addresses, open services and software." actions={<SkActions widths={[92]} />} />
      <div className="flex flex-col md:flex-row gap-3 items-center justify-between"><div className="w-full md:w-80"><SkControl width="100%" height={30} /></div><SkChips widths={[40, 100, 90, 84, 92]} className="w-full md:w-auto" /></div>
      <SkeletonRegion label="assets"><AppTableSkeleton columns={ASSET_COLUMNS} rows={7} twoLine tableClass="sm:min-w-[760px]" /></SkeletonRegion>
    </div>
  );
}

function DomainsSkeleton() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      <PageHead title="Domains" note="Add a domain, prove you own it with one DNS record, and it is scanned every day." actions={<SkActions widths={[96, 124]} />} />
      <div><SkLine width="70%" size={12} /><SkLine width="45%" size={12} className="sm:hidden" /></div>
      <SkeletonRegion label="domains"><AppTableSkeleton columns={DOMAIN_COLUMNS} rows={3} tableClass="sm:min-w-[620px]" /></SkeletonRegion>
    </div>
  );
}

function RemediationSkeleton() {
  return (
    <div className="space-y-5 pb-10">
      <PageHead title="Remediation" note="Track each fix to done. A recheck confirms it against the live host." actions={<SkActions widths={[104]} />} />
      <SkChips widths={[48, 48, 86, 72, 66]} />
      <SkeletonRegion label="the remediation queue"><AppTableSkeleton columns={TASK_COLUMNS} rows={6} twoLine inset={false} tableClass="sm:min-w-[720px]" /></SkeletonRegion>
    </div>
  );
}

function ReportsSkeleton() {
  return (
    <div className="space-y-5 pb-10">
      <PageHead title="Reports" note="Create a report from your latest score and share it with your team or board." actions={<SkActions widths={[124, 150]} />} />
      <div className="panel p-4 space-y-3 min-h-[96px]"><SkLine width="35%" size={12} /><div className="flex flex-wrap gap-2"><SkControl width={140} height={26} /><SkControl width={101} height={26} /><SkControl width={55} height={30} /></div></div>
      <SkeletonRegion label="saved reports"><AppTableSkeleton columns={REPORT_COLUMNS} rows={6} twoLine inset={false} /></SkeletonRegion>
    </div>
  );
}

/* ── Scans (its own classes from Scans.css) ─────────────────────────────── */
export function ScansBodySkeleton() {
  return (
    <SkeletonRegion label="scans">
      <section className="scan-panel scan-summary">
        <div className="scan-summary-heading">
          <div className="space-y-2"><SkLine width={110} size={13} /><SkLine width={200} size={24} /><SkLine width={150} size={12} /></div>
          <div className="scan-summary-status"><Skeleton width={110} height={24} /><Skeleton width={100} height={24} /></div>
        </div>
        <div className="scan-metrics">
          {[0, 1, 2].map(i => <div key={i} className="space-y-1"><SkLine width="50%" size={13} /><SkLine width="35%" size={30} /><SkLine width="60%" size={12} /></div>)}
        </div>
        <div className="scan-summary-actions"><SkControl width={null} className="w-full sm:w-[141px]" height={44} /><SkControl width={null} className="w-full sm:w-[141px]" height={44} /></div>
      </section>
      <div className="scans-workspace">
        <div className="scan-panel scan-checks-panel">
          <div className="scan-panel-heading"><span className="space-y-1"><SkLine width={110} size={17} /><SkLine width={160} size={12} /></span></div>
          <div className="px-[18px] pb-4">{[0, 1, 2, 3, 4, 5, 6].map(i => <SkListItem key={i} />)}</div>
        </div>
        <section className="scan-panel scan-history">
          <div className="scan-history-heading"><div className="space-y-1"><SkLine width={120} size={17} /><SkLine width={90} size={12} /></div><div className="scan-filters"><SkControl width={130} height={44} /><SkControl width={130} height={44} /></div></div>
          <div className="px-3 pb-3">{[0, 1, 2, 3].map(i => <SkListItem key={i} />)}</div>
        </section>
      </div>
    </SkeletonRegion>
  );
}

function ScansSkeleton() {
  return (
    <div className="scans-page">
      <header className="scans-heading">
        <div><h1>Scans</h1><p>Monitor your domains and review security checks.</p></div>
        <div className="scans-heading-actions"><SkControl width={107} height={44} /><SkControl width={123} height={44} /></div>
      </header>
      <ScansBodySkeleton />
    </div>
  );
}

/* ── Settings (per tab) ─────────────────────────────────────────────────── */
export type SettingsTabKey = 'general' | 'team' | 'auth' | 'notifications';

export function SettingsPanelSkeleton({ tab }: { tab: SettingsTabKey }) {
  const card = (children: ReactNode, key?: string) => <div key={key} className="p-6 rounded-lg border border-line bg-raised space-y-4">{children}</div>;
  const title = <div className="flex items-center gap-2 pb-3 border-b border-line"><Skeleton width={16} height={16} /><SkLine width={150} size={14} /></div>;
  if (tab === 'notifications') {
    return <SkeletonRegion label="notification settings">{card(<>{title}<SkLine width="80%" size={12} />{[0, 1, 2, 3, 4].map(i => <SkListItem key={i} aside />)}</>)}</SkeletonRegion>;
  }
  if (tab === 'team') {
    return <SkeletonRegion label="your team">{card(<>{title}<SkLine width="70%" size={12} /><SkTableRows columns={['MEMBER', 'EMAIL', 'ROLE', 'JOINED']} rows={3} framed={false} /></>)}</SkeletonRegion>;
  }
  if (tab === 'auth') {
    return <SkeletonRegion label="sign-in security">{card(<>{title}<SkLine width="85%" size={12} /><SkLine width="60%" size={12} />{[0, 1, 2].map(i => <SkListItem key={i} />)}</>)}</SkeletonRegion>;
  }
  return <GeneralSettingsSkeleton card={card} title={title} />;
}

/** The general tab: the company profile, plus billing and closure for owners (the cards the owner will see). */
function GeneralSettingsSkeleton({ card, title }: { card: (c: ReactNode, key?: string) => ReactNode; title: ReactNode }) {
  const { organization } = useAuth();
  const owner = (organization?.membership_role || '').toLowerCase() === 'owner';
  return (
    <SkeletonRegion label="your settings" className="space-y-6">
      <div className="p-6 rounded-lg border border-line bg-raised space-y-4 min-h-[552px] md:min-h-[364px]">{title}<div className="grid grid-cols-1 md:grid-cols-2 gap-4"><SkField /><SkField /><SkField /><SkField /></div><SkControl width={150} height={36} /></div>
      {owner && card(<>{title}<div className="grid grid-cols-2 md:grid-cols-4 gap-2">{[0, 1, 2, 3].map(i => <SkBlock key={i} height={50} />)}</div><div className="flex flex-wrap gap-2"><SkControl width={240} height={34} /><SkControl width={70} height={30} /></div><SkLine width="50%" size={12} /></>, 'billing')}
      {owner && card(<>{title}<SkLine width="80%" size={12} /><SkLine width="60%" size={12} /><SkControl width={206} height={30} /><div className="flex flex-wrap gap-2 pt-3"><SkControl width={181} height={30} /><SkControl width={120} height={30} /></div></>, 'closure')}
    </SkeletonRegion>
  );
}

function SettingsSkeleton({ tab }: { tab: SettingsTabKey }) {
  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12">
      <PageHead title="Settings" note="Company profile, team, billing and sign-in." />
      <div className="flex items-center gap-1 border-b border-line overflow-x-auto pb-px no-scrollbar">
        {[106, 160, 150, 140].map((w, i) => <SkControl key={i} width={w} height={34} />)}
      </div>
      <SettingsPanelSkeleton tab={tab} />
    </div>
  );
}

/* ── Compliance (per section) ───────────────────────────────────────────── */
const CARD = 'rounded-2xl border border-line bg-raised';
const REGISTER_TITLE = 'NDPA 2023 / GAID 2025 readiness register';
const COMPLIANCE_TABS = ['Readiness', 'Answer questions', 'Incidents', 'Packs', 'Documents', 'Reviewer access'];

export function CompliancePanelSkeleton({ section }: { section: string }) {
  if (section === 'questions') {
    return (
      <SkeletonRegion label="questions" className="space-y-4">
        <div className="flex flex-wrap gap-2"><SkActions widths={[120, 120, 120, 120]} /></div>
        {[0, 1, 2].map(i => <SkCard key={i} title={false} lines={2} className={`${CARD} !rounded-2xl`} height={150} />)}
      </SkeletonRegion>
    );
  }
  if (section === 'incidents' || section === 'packs' || section === 'documents' || section === 'reviewers') {
    const label = { incidents: 'incidents', packs: 'packs', documents: 'documents', reviewers: 'reviewer access' }[section]!;
    return (
      <SkeletonRegion label={label} className="space-y-4">
        <SkCard title={false} lines={2} />
        {[0, 1, 2].map(i => <div key={i} className="p-4 rounded-lg border border-line bg-raised"><SkListItem /></div>)}
      </SkeletonRegion>
    );
  }
  return (
    <SkeletonRegion label="your compliance readiness" className="space-y-6">
      <div className="compliance-overview-grid">
        <div className="compliance-coverage space-y-5"><SkLine width="55%" size={11} /><SkLine width="70%" size={36} /><SkLine width="60%" size={12} /><SkBlock height={10} /><SkLine width="80%" size={11} /><div className="grid grid-cols-2 gap-2">{[0, 1, 2, 3].map(i => <SkBlock key={i} height={44} />)}</div></div>
        <div className={`p-5 sm:p-6 ${CARD} space-y-4`}><SkLine width="40%" size={11} /><SkLine width="50%" size={18} />{[0, 1, 2].map(i => <SkListItem key={i} mark aside={false} />)}</div>
      </div>
      <SkBlock height={58} rounded="lg" />
      <SkBlock height={160} rounded="lg" />
    </SkeletonRegion>
  );
}

const TAB_NOTES: Record<string, string> = {
  readiness: 'Review the evidence behind each requirement and decide what to work on next.',
  questions: 'Record what your team does, assign evidence owners and keep answers up to date.',
  incidents: 'Record events and follow the response work through to closure.',
  packs: 'Prepare dated evidence for management and practitioner reviews.',
  documents: 'Draft, review and approve your organisation’s policy documents.',
  reviewers: 'Give a practitioner scoped access to support your review.',
};
const SECTION_TITLES: Record<string, string> = { readiness: 'Readiness', questions: 'Answer questions', incidents: 'Incidents', packs: 'Evidence packs', documents: 'Documents', reviewers: 'Reviewer access' };

export function ComplianceSkeleton({ section = 'readiness' }: { section?: string }) {
  const key = section in TAB_NOTES ? section : 'readiness';
  return (
    <div className="compliance-page space-y-6 max-w-7xl mx-auto pb-12">
      {/* The register title is fixed per register version; the note matches the loaded page's. */}
      <PageHead title="Compliance readiness" note={`${REGISTER_TITLE}. Organise evidence, close gaps and prepare for review.`} actions={<SkActions widths={[98]} />} />
      <div className="p-3.5 rounded border border-accent/30 bg-accent/5 space-y-1.5 min-h-[108px] sm:min-h-[68px] lg:min-h-[50px]"><SkLine width="95%" size={12} /><SkLine width="70%" size={12} /></div>
      <div className="compliance-tabs" aria-hidden="true">
        {COMPLIANCE_TABS.map(t => <span key={t} className="compliance-tab"><Skeleton width={15} height={15} /><span className="opacity-40">{t}</span></span>)}
      </div>
      <div className="compliance-tab-panel space-y-6">
        <div className="compliance-section-heading" aria-hidden="true"><div><p className="compliance-eyebrow">Compliance workspace</p><h2>{SECTION_TITLES[key]}</h2></div><p>{TAB_NOTES[key]}</p></div>
        <CompliancePanelSkeleton section={key} />
      </div>
    </div>
  );
}

/* ── Platform ──────────────────────────────────────────────────────────── */
export function PlatformSkeleton() {
  const card = (children: ReactNode) => <div className="p-6 rounded-lg border border-line bg-raised space-y-3">{children}</div>;
  return (
    <SkeletonRegion label="the platform console" className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* The console header's own line boxes: eyebrow 18px, title 32px (36px from md), note 16px a line (three on phones). */}
      <div>
        <div className="h-[18px] flex items-center"><Skeleton width={220} height={10} /></div>
        <div className="mt-1 h-8 md:h-9 flex items-center"><Skeleton width={240} height={24} /></div>
        <div className="mt-1 h-12 md:h-4 flex flex-col justify-center gap-1"><Skeleton width="80%" height={10} /><Skeleton width="50%" height={10} className="md:hidden" /></div>
      </div>
      {card(<><div className="pb-3 border-b border-line"><SkLine width={140} size={14} /></div><div className="grid grid-cols-2 md:grid-cols-4 gap-2">{[0, 1, 2].map(i => <SkBlock key={i} height={50} />)}</div></>)}
      {card(<><SkLine width={260} size={14} /><SkControl width="100%" height={34} /><div className="flex flex-wrap gap-2 pt-2"><SkControl width={null} className="flex-1 min-w-[160px]" height={30} /><SkControl width={138} height={30} /><SkControl width={123} height={30} /></div></>)}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">{card(<><SkLine width={160} size={14} /><SkControl width="100%" height={34} /><SkControl width={120} height={30} /></>)}{card(<><SkLine width={160} size={14} /><SkLine width="80%" size={12} /><SkControl width={120} height={30} /></>)}</div>
    </SkeletonRegion>
  );
}

/* ── The route fallback ─────────────────────────────────────────────────── */
export function RouteSkeleton({ pathname, search }: { pathname: string; search: string }) {
  const params = new URLSearchParams(search);
  switch (pathname) {
    case '/':
    case '/overview': return <OverviewSkeleton />;
    case '/findings': return <FindingsSkeleton />;
    case '/assets': return <AssetsSkeleton />;
    case '/domains': return <DomainsSkeleton />;
    case '/remediation': return <RemediationSkeleton />;
    case '/reports': return <ReportsSkeleton />;
    case '/scans': return <ScansSkeleton />;
    case '/settings': {
      const tab = params.get('tab');
      return <SettingsSkeleton tab={(['team', 'auth', 'notifications'] as const).find(t => t === tab) || 'general'} />;
    }
    case '/comply': return <ComplianceSkeleton section={params.get('section') || 'readiness'} />;
    case '/platform': return <PlatformSkeleton />;
    default:
      return (
        <SkeletonRegion label="this page" className="space-y-6 max-w-7xl mx-auto pb-12">
          <div className="space-y-2"><SkLine width={180} size={28} /><SkLine width="62%" size={13} /></div>
          <div className="grid gap-4 sm:grid-cols-2"><SkCard lines={3} /><SkCard lines={3} /></div>
          <SkCard lines={6} />
        </SkeletonRegion>
      );
  }
}

export { SettingsSkeleton, FindingsSkeleton, AssetsSkeleton, DomainsSkeleton, RemediationSkeleton, ReportsSkeleton, ScansSkeleton };
