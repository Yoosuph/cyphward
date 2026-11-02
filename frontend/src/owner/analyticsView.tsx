import { useContext, useEffect, useState } from 'react';
import { AnalyticsKpiSkeleton, ChartSkeleton } from './skeletons';
import { SkLine } from '../components/ui/Skeleton';
import { useSearchParams } from 'react-router-dom';
import { OwnerApiError, newsletterStats, type NewsletterStats } from './ownerApi';
import { Empty, PageHead, Panel, Pill, SessionEndedContext, statusTone, useOwnerView } from './ui';
import { KpiStrip, ListState, RANGES, RangeSelector, type Range } from './table';

/**
 * Platform analytics (phase 1): counts only, from GET /owner/analytics/summary and /timeseries, plus the
 * newsletter's own subscriber counts. No customer address, finding title or other content is ever returned.
 */

type Summary = {
  range_days: number;
  organizations: { total: number; new_in_range: number; suspended: number };
  billing: { paid: number; trialing: number; free: number };
  subscription_status: { status: string; count: number }[];
  scans: { total: number; completed: number; failed: number; cancelled: number; queued: number; running: number;
           success_rate: number | null; failure_rate: number | null };
  users: { total: number; new_in_range: number };
};
type ScanDay = { day: string; total: number; completed: number; failed: number; cancelled: number; queued: number; running: number };
type FindingDay = { day: string; critical: number; high: number; medium: number; low: number; info: number };
type Series = { scans_per_day: ScanDay[]; findings_per_day: FindingDay[]; truncated: boolean };

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'] as const;
const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 1000) / 10}%`);
const n = (v: number | undefined) => (v ?? 0).toLocaleString();

function useRange(): [Range, (r: Range) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get('range');
  const value: Range = (RANGES as readonly string[]).includes(raw || '') ? (raw as Range) : '30';
  return [value, r => { const p = new URLSearchParams(params); if (r === '30') p.delete('range'); else p.set('range', r); setParams(p, { replace: true }); }];
}

/** Daily bars, stacked; heights scale to the busiest day. Phones get thinner bars, never a scrolling page. */
function StackedDays<T extends { day: string }>({ days, parts, label, testId }: {
  days: T[]; parts: { key: keyof T & string; className: string; name: string }[]; label: string; testId: string;
}) {
  const totals = days.map(d => parts.reduce((s, p) => s + Number(d[p.key] || 0), 0));
  const max = Math.max(1, ...totals);
  const sum = totals.reduce((a, b) => a + b, 0);
  const busiest = days[totals.indexOf(Math.max(...totals))];
  return (
    <figure className="m-0" data-testid={testId}>
      <div className="flex items-end gap-px h-36 min-w-0" role="img"
           aria-label={`${label}: ${sum.toLocaleString()} in ${days.length} days${sum && busiest ? `, busiest ${busiest.day} with ${Math.max(...totals)}` : ''}.`}>
        {days.map((d, i) => (
          <div key={d.day} className="flex-1 min-w-0 h-full flex flex-col justify-end" title={`${d.day}: ${totals[i]}`}>
            {totals[i] === 0 ? <div className="w-full bg-line" style={{ height: 2 }} /> : parts.map(p => {
              const v = Number(d[p.key] || 0);
              return v ? <div key={p.key} className={`w-full ${p.className}`} style={{ height: `${(v / max) * 100}%` }} /> : null;
            })}
          </div>
        ))}
      </div>
      <figcaption className="flex flex-wrap justify-between gap-2 mt-2 text-[10px] mono text-soft">
        <span>{days[0]?.day}</span>
        <span className="flex flex-wrap gap-3">
          {parts.map(p => <span key={p.key} className="inline-flex items-center gap-1"><span className={`inline-block w-2 h-2 rounded-sm ${p.className}`} aria-hidden="true" />{p.name}</span>)}
        </span>
        <span>{days[days.length - 1]?.day}</span>
      </figcaption>
    </figure>
  );
}

function NewsletterPanel() {
  const onSessionEnded = useContext(SessionEndedContext);
  const [state, setState] = useState<{ stats?: NewsletterStats; off?: boolean; error?: string }>({});
  useEffect(() => {
    let live = true;
    newsletterStats().then(stats => live && setState({ stats })).catch((e: OwnerApiError) => {
      if (!live) return;
      if (e.status === 401) onSessionEnded();
      else if (e.status === 404) setState({ off: true });
      else setState({ error: e.message });
    });
    return () => { live = false; };
  }, [onSessionEnded]);
  return (
    <Panel title="Newsletter subscribers">
      {state.off ? <Empty>The newsletter is switched off.</Empty>
        : state.error ? <p className="text-xs text-soft" role="alert">{state.error}</p>
        : !state.stats ? <div className="grid grid-cols-3 gap-3" aria-hidden="true">{[0, 1, 2].map(i => <div key={i} className="space-y-1"><SkLine width="70%" size={11} /><SkLine width="50%" size={20} /></div>)}</div>
        : (
          <dl className="grid grid-cols-3 gap-3 text-sm" data-testid="newsletter-counts">
            <div><dt className="text-[11px] mono uppercase text-soft">Confirmed</dt><dd className="text-xl font-bold mono">{n(state.stats.confirmed)}</dd></div>
            <div><dt className="text-[11px] mono uppercase text-soft">Unsubscribed</dt><dd className="text-xl font-bold mono">{n(state.stats.unsubscribed)}</dd></div>
            <div><dt className="text-[11px] mono uppercase text-soft">Pending</dt><dd className="text-xl font-bold mono">{n(state.stats.pending)}</dd></div>
          </dl>
        )}
    </Panel>
  );
}

export function AnalyticsView() {
  const [range, setRange] = useRange();
  const summary = useOwnerView<Summary>('/analytics/summary', { range });
  const series = useOwnerView<Series>('/analytics/timeseries', { range });
  const s = summary.data;
  const t = series.data;
  return (
    <>
      <PageHead title="Analytics" subtitle="Counts across the platform. No customer addresses or content."
                actions={<RangeSelector value={range} onChange={setRange} />} />
      <ListState loading={summary.loading} error={summary.error} onRetry={summary.reload} hasData={!!s} count={1} label="analytics" skeleton={<AnalyticsKpiSkeleton />} placeholder={summary.placeholder}
                 empty={{ title: '', help: '' }}>
        {s && (
          <>
            <KpiStrip label="Organizations and billing" items={[
              { label: 'Organizations', value: n(s.organizations.total), hint: `+${n(s.organizations.new_in_range)} in ${s.range_days} days · ${n(s.organizations.suspended)} suspended`, to: '/organizations' },
              { label: 'Paid', value: n(s.billing.paid), hint: 'active, period not ended', to: '/organizations?billing=paid' },
              { label: 'Trialing', value: n(s.billing.trialing), hint: 'trial, period not ended', to: '/organizations?billing=trialing' },
              { label: 'Free', value: n(s.billing.free), hint: 'no live subscription', to: '/organizations?billing=free' },
            ]} />
            <KpiStrip label="Scans and users" items={[
              { label: `Scans (${s.range_days} d)`, value: n(s.scans.total), hint: `${n(s.scans.queued + s.scans.running)} queued or running`, to: '/scans' },
              { label: 'Completed share', value: pct(s.scans.success_rate), hint: `${n(s.scans.completed)} completed of finished scans` },
              { label: 'Failed share', value: pct(s.scans.failure_rate), hint: `${n(s.scans.failed)} failed`, tone: s.scans.failed ? 'warn' : undefined, to: '/scans?state=failed' },
              { label: 'Users', value: n(s.users.total), hint: `+${n(s.users.new_in_range)} in ${s.range_days} days`, to: '/users' },
            ]} />
          </>
        )}
      </ListState>
      <div className="grid lg:grid-cols-2 gap-5 mt-1">
        <Panel title={`Scans per day, last ${range} days`} className={`lg:col-span-2 transition-opacity ${series.placeholder ? 'opacity-70' : ''}`}>
          {series.error ? <p className="text-xs text-soft" role="alert">{series.error}</p> : !t ? <ChartSkeleton /> : (
            <StackedDays days={t.scans_per_day} label="Scans per day" testId="scans-chart" parts={[
              { key: 'completed', className: 'bg-[var(--ok)]', name: 'completed' },
              { key: 'failed', className: 'bg-[var(--accent)]', name: 'failed' },
              { key: 'cancelled', className: 'bg-[var(--line-strong)]', name: 'cancelled' },
              { key: 'running', className: 'bg-[var(--warn)]', name: 'running' },
              { key: 'queued', className: 'bg-[var(--soft)]', name: 'queued' },
            ]} />
          )}
        </Panel>
        <Panel title={`New findings per day by severity, last ${range} days`} className={`lg:col-span-2 transition-opacity ${series.placeholder ? 'opacity-70' : ''}`}>
          {series.error ? <p className="text-xs text-soft" role="alert">{series.error}</p> : !t ? <ChartSkeleton /> : (
            <StackedDays days={t.findings_per_day} label="New findings per day" testId="findings-chart"
                         parts={SEVERITIES.map(sev => ({ key: sev, className: `sev-bar sev-${sev}`, name: sev }))} />
          )}
        </Panel>
        <Panel title="Subscriptions by status">
          {!s ? <div className="space-y-2" aria-hidden="true">{[0, 1, 2].map(i => <SkLine key={i} width="100%" size={14} />)}</div> : s.subscription_status.length === 0 ? <Empty>No subscriptions recorded.</Empty> : (
            <ul className="space-y-2" data-testid="subscription-status-counts">
              {s.subscription_status.map(r => (
                <li key={r.status} className="flex items-center justify-between gap-3 text-sm">
                  <Pill tone={statusTone(r.status === 'lapsed' ? 'expired' : r.status)}>{r.status.replace('_', ' ')}</Pill>
                  <span className="mono">{n(r.count)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <NewsletterPanel />
      </div>
    </>
  );
}
