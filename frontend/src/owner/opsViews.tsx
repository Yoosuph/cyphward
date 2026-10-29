import { Fragment } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useListParams } from './peopleViews';
import { CancelScanAction } from './actions';
import { ExportButton, FilterBar, ListState, OwnerTable, PagerBar, SelectFilter, SortSelect, type Column } from './table';
import {
  Cell, Empty, FilterChip, PageHead, Pager, Panel, Pill, SearchBox, Table, ViewState,
  fmtAgo, fmtDate, fmtDuration, fmtMoney, statusTone, useOwnerView,
} from './ui';

type Row = Record<string, any>;

const SCAN_STATES: [string, string][] = [
  ['', 'All'],
  ['queued', 'Queued'],
  ['queued_delayed', 'Delayed'],
  ['running', 'Running'],
  ['running_lease_expired', 'Worker stopped'],
  ['completed', 'Completed'],
  ['failed', 'Failed'],
  ['cancelled', 'Cancelled'],
];

const STATE_LABEL: Record<string, string> = Object.fromEntries(SCAN_STATES.filter(([k]) => k));
const ACTIVE_STATES = ['queued', 'queued_delayed', 'running', 'running_lease_expired'];

/* ── Subscriptions ─────────────────────────────────────────────────────── */
// Statuses as the database stores them, plus "lapsed": active or trialing with its period already ended.
const SUB_STATUSES: [string, string][] = [
  ['', 'All'], ['trialing', 'Trialing'], ['active', 'Active'], ['lapsed', 'Lapsed'], ['past_due', 'Past due'], ['canceled', 'Canceled'],
];

const SUB_COLUMNS: Column<Row>[] = [
  { key: 'organization', label: 'Organization', sortKey: 'organization', title: true,
    cell: s => <Link to={`/organizations/${s.org_id}`} className="hover:text-accent break-words">{s.org_name}</Link> },
  { key: 'plan', label: 'Plan', sortKey: 'plan', cell: s => <span className="mono text-xs">{s.plan}</span> },
  { key: 'status', label: 'Status', sortKey: 'status',
    cell: s => <span className="inline-flex flex-wrap items-center gap-1.5"><Pill tone={statusTone(s.effective_status === 'lapsed' ? 'expired' : s.effective_status)}>{(s.effective_status || s.status || '').replace('_', ' ')}</Pill>
      {s.cancel_at_period_end && <span className="text-xs text-soft">cancels at period end</span>}</span> },
  { key: 'period_end', label: 'Period ends', sortKey: 'period_end', firstDir: 'asc', cell: s => fmtDate(s.current_period_end, false) },
  { key: 'trial', label: 'Trial ends', cell: s => fmtDate(s.trial_ends_at, false) },
  { key: 'provider', label: 'Provider', cell: s => <span className="mono text-xs">{s.provider || 'manual'}</span> },
  { key: 'created', label: 'Created', sortKey: 'created', firstDir: 'desc', cell: s => fmtDate(s.created_at, false) },
];

export function SubscriptionsView() {
  const { q, offset, limit, sort, dir, set, params } = useListParams({ sort: 'period_end', dir: 'asc' });
  const status = params.get('status') || '';
  const plan = params.get('plan') || '';
  const filters = { q, status, plan, sort, dir };
  const { data, error, loading, reload } = useOwnerView<Row>('/subscriptions', { ...filters, offset, limit });
  return (
    <>
      <PageHead title="Subscriptions" subtitle="Plans, renewal dates and invoices on record. Invoices are records, not proof of payment."
                actions={<ExportButton path="/exports/subscriptions.csv" params={filters} />} />
      <FilterBar>
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder="Search organization" />
        <SelectFilter id="sub-status" label="Status" value={status} options={SUB_STATUSES} onChange={v => set({ status: v, offset: 0 })} />
        <SelectFilter id="sub-plan" label="Plan" value={plan}
                      options={[['', 'All'], ['starter', 'Starter'], ['growth', 'Growth'], ['other', 'Other']]} onChange={v => set({ plan: v, offset: 0 })} />
        <SortSelect id="sub-sort" columns={SUB_COLUMNS} sort={sort} dir={dir} onChange={(s, d) => set({ sort: s, dir: d, offset: 0 })} />
      </FilterBar>
      <ListState loading={loading} error={error} onRetry={reload} hasData={!!data} count={data?.items.length || 0} label="subscriptions"
                 empty={{ title: 'No subscriptions match', help: status ? 'No subscription has this status. Choose another status.' : 'Subscriptions appear here once an organization has one.' }}>
        <OwnerTable caption="Subscriptions" columns={SUB_COLUMNS} rows={(data?.items || []) as Row[]} rowKey={s => s.id}
                    sort={sort} dir={dir} onSort={(s, d) => set({ sort: s, dir: d, offset: 0 })} testId="sub-table" />
        {data && <PagerBar offset={offset} limit={limit} total={data.total} count={data.items.length}
                           onPage={o => set({ offset: o })} onLimit={n => set({ limit: n === 50 ? 0 : n, offset: 0 })} />}
      </ListState>
      {data && (
        <div className="mt-5">
          <Panel title="Recent invoices">
            {(data.invoices || []).length === 0 ? <Empty>No invoices recorded.</Empty> : (
              <Table head={['Invoice', 'Organization', 'Amount', 'Status', 'Period', 'Created']}>
                {(data.invoices as Row[]).map(inv => (
                  <tr key={inv.number}>
                    <Cell title><span className="mono text-xs">{inv.number}</span></Cell>
                    <Cell label="Organization"><Link to={`/organizations/${inv.org_id}`} className="hover:text-accent">{inv.org_name}</Link></Cell>
                    <Cell label="Amount">{fmtMoney(inv.amount_kobo, inv.currency)}</Cell>
                    <Cell label="Status"><Pill tone={statusTone(inv.status)}>{inv.status}</Pill></Cell>
                    <Cell label="Period">{fmtDate(inv.period_start, false)} – {fmtDate(inv.period_end, false)}</Cell>
                    <Cell label="Created">{fmtDate(inv.created_at, false)}</Cell>
                  </tr>
                ))}
              </Table>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}

/* ── Scans ──────────────────────────────────────────────────────────────── */
export function ScansView() {
  const { q, offset, params, set } = useListParams();
  const state = params.get('state') || '';
  const limit = 50;
  const { data, error, loading, reload } = useOwnerView<Row>('/scans', { q, state, offset, limit });
  return (
    <>
      <PageHead title="Scans" subtitle={`Every scan across customers. "Delayed" means queued for over ${Math.round((data?.queue_delay_seconds || 600) / 60)} minutes; "Worker stopped" means its claim expired.`} />
      <div className="flex flex-wrap gap-3 mb-3">
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder="Search domain or organization" />
      </div>
      <div className="no-scrollbar flex gap-2 mb-4 overflow-x-auto sm:flex-wrap">
        {SCAN_STATES.map(([k, label]) => (
          <FilterChip key={k || 'all'} active={state === k} onClick={() => set({ state: k, offset: 0 })}>{label}</FilterChip>
        ))}
      </div>
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && data.items.length === 0 ? <Empty>No scans match.</Empty> : (
          <Panel>
            <Table head={['Domain', 'Organization', 'State', 'Coverage', 'Score', 'Duration', 'Created']}>
              {(data?.items || []).map((s: Row) => (
                <tr key={s.id}>
                  <Cell title><Link to={`/scans/${s.id}`} className="mono text-xs hover:text-accent">{s.domain || '—'}</Link></Cell>
                  <Cell label="Organization"><Link to={`/organizations/${s.org_id}`} className="hover:text-accent">{s.org_name}</Link></Cell>
                  <Cell label="State">
                    <Pill tone={statusTone(s.state)}>{STATE_LABEL[s.state] || s.state}</Pill>
                    {s.failed_stages?.length ? <span className="text-xs text-accent ml-1">{s.failed_stages.join(', ')} failed</span> : null}
                  </Cell>
                  <Cell label="Coverage">{s.coverage_state ? <Pill tone={statusTone(s.coverage_state)}>{s.coverage_state}</Pill> : '—'}</Cell>
                  <Cell label="Score">{s.score ?? '—'}</Cell>
                  <Cell label="Duration">{fmtDuration(s.duration_seconds)}</Cell>
                  <Cell label="Created">{fmtDate(s.created_at)}</Cell>
                </tr>
              ))}
            </Table>
            {data && <Pager offset={offset} limit={limit} count={data.items.length} onChange={o => set({ offset: o })} />}
          </Panel>
        )}
      </ViewState>
    </>
  );
}

export function ScanDetailView() {
  const { id = '' } = useParams();
  const { data, error, loading, reload } = useOwnerView<Row>(`/scans/${id}`);
  const s = data?.scan;
  const coverage = s?.coverage || {};
  return (
    <>
      <PageHead title={s?.domain || 'Scan'} subtitle={s ? <span className="mono text-xs">{s.org_name} · {STATE_LABEL[s.state] || s.state} · created {fmtDate(s.created_at)}</span> : undefined}
                actions={<div className="flex flex-wrap gap-2">
                  {s && ACTIVE_STATES.includes(s.state) && <CancelScanAction scanId={s.id} domain={s.domain || 'this domain'} state={s.state} onDone={reload} />}
                  <Link to="/scans" className="btn-mini">← ALL SCANS</Link>
                </div>} />
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && (
          <div className="grid lg:grid-cols-2 gap-5">
            <Panel title="Summary">
              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-soft">State</dt><dd><Pill tone={statusTone(s.state)}>{STATE_LABEL[s.state] || s.state}</Pill></dd>
                <dt className="text-soft">Score</dt><dd>{s.score ?? '—'}</dd>
                <dt className="text-soft">Coverage</dt><dd>{coverage.state ? `${coverage.state} · ${coverage.evaluated_checks ?? '?'} of ${coverage.requested_checks ?? '?'} checks` : '—'}</dd>
                <dt className="text-soft">Duration</dt><dd>{fmtDuration(s.duration_seconds)}</dd>
                <dt className="text-soft">Worker</dt><dd className="mono text-xs">{s.claimed_by || '—'}{s.lease_expires_at ? ` · claim until ${fmtDate(s.lease_expires_at)}` : ''}</dd>
                <dt className="text-soft">Attempt</dt><dd>{s.claim_generation ?? '—'} · phase {s.execution_phase || '—'}</dd>
                {s.error_message && (<><dt className="text-soft">Error</dt><dd className="text-accent">{s.error_message}</dd></>)}
              </dl>
            </Panel>
            <Panel title="Missing checks">
              {(coverage.missing || []).length === 0 ? <Empty>None recorded.</Empty> : (
                <ul className="space-y-1.5 text-xs mono">
                  {(coverage.missing as Row[]).map((m, i) => <li key={i}>{m.hostname} · {m.check} — <span className="text-soft">{m.reason}</span></li>)}
                </ul>
              )}
            </Panel>
            <Panel title="Stages" className="lg:col-span-2">
              <Table head={['Stage', 'Status', 'Time', 'Items', 'Note']}>
                {(data.stages as Row[]).map(st => (
                  <tr key={st.stage}>
                    <Cell title><span className="mono text-xs">{st.stage}</span></Cell>
                    <Cell label="Status"><Pill tone={statusTone(st.status)}>{st.status || '—'}</Pill></Cell>
                    <Cell label="Time">{st.duration_ms != null ? fmtDuration(Math.round(st.duration_ms / 1000)) : '—'}</Cell>
                    <Cell label="Items">{st.items ?? '—'}</Cell>
                    <Cell label="Note"><span className="text-xs">{st.error || ''}</span></Cell>
                  </tr>
                ))}
              </Table>
            </Panel>
            <Panel title="Hosts by stage" className="lg:col-span-2">
              {(data.hosts as Row[]).length === 0 ? <Empty>No stage results stored yet.</Empty> : (
                <div className="space-y-3">
                  {(data.hosts as Row[]).map(h => (
                    <div key={h.stage} className="text-xs">
                      <div className="mono uppercase tracking-[.14em] text-soft mb-1">{h.stage} · {(h.attempted_hosts || []).length} attempted</div>
                      {Object.entries(h.failed_hosts || {}).map(([host, why]) => <div key={host} className="mono"><span className="text-accent">failed</span> {host} — {String(why)}</div>)}
                      {Object.entries(h.omitted_hosts || {}).map(([host, why]) => <div key={host} className="mono"><span className="text-soft">omitted</span> {host} — {String(why)}</div>)}
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        )}
      </ViewState>
    </>
  );
}

/* ── System ─────────────────────────────────────────────────────────────── */
export function SystemView() {
  const { data, error, loading, reload } = useOwnerView<Row>('/system');
  const bg = (data?.background || {}) as Record<string, string>;
  return (
    <>
      <PageHead title="System" subtitle="Live state of the API, database, background jobs and scanner." />
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && (
          <div className="grid lg:grid-cols-2 gap-5">
            <Panel title="API and database">
              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-soft">Database</dt><dd><Pill tone={data.database.ok ? 'good' : 'bad'}>{data.database.ok ? 'connected' : 'down'}</Pill> <span className="text-xs text-soft">{data.database.latency_ms} ms</span></dd>
                <dt className="text-soft">Deployed</dt><dd className="mono text-xs">{data.deploy.commit || 'unknown'}{data.deploy.service ? ` · ${data.deploy.service}` : ''}</dd>
                {Object.entries(bg).map(([k, v]) => (
                  <Fragment key={k}>
                    <dt className="text-soft capitalize">{k}</dt>
                    <dd className="min-w-0">
                      <Pill tone={v === 'running' ? 'good' : 'warn'}>{v.split(' ')[0]}</Pill>
                      {v.includes(' ') && <span className="block text-xs text-soft mono break-all mt-1">{v.slice(v.indexOf(' ') + 1)}</span>}
                    </dd>
                  </Fragment>
                ))}
                <dt className="text-soft">Email</dt><dd><Pill tone={data.integrations.email ? 'good' : 'warn'}>{data.integrations.email ? 'configured' : 'not configured'}</Pill></dd>
                <dt className="text-soft">AI</dt><dd><Pill tone={data.integrations.ai ? 'good' : 'neutral'}>{data.integrations.ai ? 'configured' : 'not configured'}</Pill></dd>
              </dl>
            </Panel>
            <Panel title="Scanner">
              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-soft">Running</dt><dd>{data.scanner.running}</dd>
                <dt className="text-soft">Queued</dt><dd>{data.scanner.queued}</dd>
                <dt className="text-soft">Last scan started</dt><dd>{fmtAgo(data.scanner.last_scan_started_at)}</dd>
                <dt className="text-soft">Last scan finished</dt><dd>{fmtAgo(data.scanner.last_scan_completed_at)}</dd>
              </dl>
              <p className="text-xs text-soft mt-3">Worker liveness is inferred from scan activity; the worker doesn't report a heartbeat while idle.</p>
            </Panel>
            <Panel title="Scheduled runs" className="lg:col-span-2">
              {(data.scheduled_runs as Row[]).length === 0 ? <Empty>No scheduled runs recorded.</Empty> : (
                <Table head={['Job', 'Day', 'Status', 'Started', 'Finished']}>
                  {(data.scheduled_runs as Row[]).map((r, i) => (
                    <tr key={i}>
                      <Cell title><span className="mono text-xs">{r.cron_name}</span></Cell>
                      <Cell label="Day">{fmtDate(r.run_day, false)}</Cell>
                      <Cell label="Status"><Pill tone={statusTone(r.status)}>{r.status}</Pill></Cell>
                      <Cell label="Started">{fmtDate(r.claimed_at)}</Cell>
                      <Cell label="Finished">{fmtDate(r.finished_at)}</Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
          </div>
        )}
      </ViewState>
    </>
  );
}
