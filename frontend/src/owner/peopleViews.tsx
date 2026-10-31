import { useContext, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Activity, AlertTriangle, Building2, Clock, CreditCard, Globe, Radar, Users } from 'lucide-react';
import {
  Cell, Empty, OwnerMeContext, PageHead, Panel, Pill, SearchBox, Stat, Table, ViewState,
  fmtAgo, fmtDate, fmtDuration, fmtMoney, statusTone, useOwnerView,
} from './ui';
import { ChangePlanAction, DeleteOrgAction, ExtendTrialAction, PurgeOrgAction, RemoveMemberAction, RestoreMemberAction, RestoreOrgAction, SignOutEverywhereAction, SuspendAction } from './actions';
import {
  ExportButton, FilterBar, ListState, OwnerTable, PagerBar, SelectFilter, SortSelect, useListParams, type Column,
} from './table';

export { useListParams };

type Row = Record<string, any>;

/* ── Overview ───────────────────────────────────────────────────────────── */
export function OverviewView() {
  const { data, error, loading, reload } = useOwnerView<Row>('/overview');
  const c = data?.counts || {};
  // Days without sign-ups aren't returned; draw all 14 so the bars keep a fixed width.
  const signupsByDay = Object.fromEntries(((data?.signups_14d || []) as Row[]).map(r => [String(r.day).slice(0, 10), Number(r.users)]));
  const signupDays = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(((data?.as_of as number) || 0) * 1000 || Date.now());
    d.setUTCDate(d.getUTCDate() - 13 + i);
    const day = d.toISOString().slice(0, 10);
    return { day, users: signupsByDay[day] || 0 };
  });
  const maxSignups = Math.max(1, ...signupDays.map(r => r.users));
  const oldest = c.oldest_queued_seconds;
  return (
    <>
      <PageHead title="Overview" subtitle={data ? `As of ${fmtDate(new Date(data.as_of * 1000).toISOString())}` : 'Everything on the platform, at a glance.'} />
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <Stat label="Users" value={c.users_total ?? '—'} hint={`+${c.users_7d ?? 0} this week · +${c.users_30d ?? 0} in 30 days`} to="/users" icon={Users} />
          <Stat label="Organizations" value={c.orgs_total ?? '—'} hint={`+${c.orgs_7d ?? 0} this week`} to="/organizations" icon={Building2} />
          <Stat label="Domains" value={c.domains_verified ?? '—'} hint={`verified · ${c.domains_pending ?? 0} awaiting DNS`} icon={Globe} />
          <Stat label="Scans (24 h)" value={c.scans_24h ?? '—'} hint={`${c.scans_failed_24h ?? 0} failed`} tone={c.scans_failed_24h ? 'bad' : undefined} to="/scans" icon={Radar} />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
          <Stat label="Queued" value={c.scans_queued ?? 0} hint={oldest ? `oldest waiting ${fmtDuration(oldest)}` : 'nothing waiting'}
                tone={oldest && oldest > (data?.queue_delay_seconds || 600) ? 'warn' : undefined} to="/scans?state=queued_delayed" icon={Clock} />
          <Stat label="Running" value={c.scans_running ?? 0} hint="scans in progress" to="/scans?state=running" icon={Activity} />
          <Stat label="Expired claims" value={c.scans_lease_expired ?? 0} hint="running scans whose worker stopped reporting"
                tone={c.scans_lease_expired ? 'bad' : undefined} to="/scans?state=running_lease_expired" icon={AlertTriangle} />
          <Stat label="Subscriptions" value={((data?.subscriptions || []) as Row[]).reduce((n, r) => n + Number(r.n), 0)} hint="all plans and states" to="/subscriptions" icon={CreditCard} />
        </div>
        <div className="grid lg:grid-cols-2 gap-5">
          <Panel title="Sign-ups, last 14 days">
            {(data?.signups_14d || []).length === 0 ? <Empty>No sign-ups in the last 14 days.</Empty> : (
              <div className="flex items-end gap-1.5 h-32" role="img" aria-label="Daily sign-ups">
                {signupDays.map(r => (
                  <div key={r.day} className="flex-1 min-w-0 flex flex-col items-center gap-1" title={`${r.day}: ${r.users}`}>
                    <span className="text-[10px] mono text-soft">{r.users || ''}</span>
                    <div className={`w-full rounded-t ${r.users ? 'bg-[var(--accent)]' : 'bg-line'}`} style={{ height: `${Math.max(2, (r.users / maxSignups) * 90)}px` }} />
                    <span className="text-[9px] mono text-soft">{r.day.slice(8)}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>
          <Panel title="Invoices recorded" right={<span className="text-[10px] mono text-soft">records, not cash collected</span>}>
            {(data?.invoices || []).length === 0 ? <Empty>No invoices recorded.</Empty> : (
              <ul className="space-y-2">
                {(data!.invoices as Row[]).map(r => (
                  <li key={`${r.currency}-${r.status}`} className="flex items-center justify-between gap-3 text-sm">
                    <span><Pill tone={statusTone(r.status)}>{r.status}</Pill> <span className="text-soft mono text-xs ml-1">{r.n} × {r.currency}</span></span>
                    <span className="mono">{fmtMoney(r.amount_minor, r.currency)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel title="Recent customer activity" className="lg:col-span-2" right={<Link to="/logs" className="tap-row text-[10px] mono text-soft hover:text-accent">ALL LOGS →</Link>}>
            {(data?.recent_activity || []).length === 0 ? <Empty>No activity recorded.</Empty> : (
              <Table head={['Action', 'Organization', 'User', 'When']}>
                {(data!.recent_activity as Row[]).map((r, i) => (
                  <tr key={i}>
                    <Cell title><span className="mono text-xs">{r.action}</span></Cell>
                    <Cell label="Organization">{r.org_name || '—'}</Cell>
                    <Cell label="User">{r.user_email || '—'}</Cell>
                    <Cell label="When">{fmtAgo(r.created_at)}</Cell>
                  </tr>
                ))}
              </Table>
            )}
          </Panel>
        </div>
      </ViewState>
    </>
  );
}

/* ── Organizations ─────────────────────────────────────────────────────── */
const BILLING_OPTIONS: [string, string][] = [['', 'All'], ['paid', 'Paid'], ['trialing', 'Trialing'], ['free', 'Free']];
const PLAN_OPTIONS: [string, string][] = [['', 'All'], ['starter', 'Starter'], ['growth', 'Growth'], ['other', 'Other']];
const BILLING_TONE: Record<string, 'good' | 'warn' | 'neutral'> = { paid: 'good', trialing: 'warn', free: 'neutral' };
// Deleted organizations are left out unless asked for (backend core/owner_lists.py).
const DELETED_OPTIONS: [string, string][] = [['', 'Hide deleted'], ['include', 'Include deleted'], ['only', 'Deleted only']];

const ORG_COLUMNS: Column<Row>[] = [
  { key: 'name', label: 'Organization', sortKey: 'name', title: true,
    cell: o => <><Link to={`/organizations/${o.id}`} className="font-medium hover:text-accent break-words">{o.name}</Link>
      {o.owner_email && <div className="text-xs text-soft break-all">{o.owner_email}</div>}</> },
  { key: 'plan', label: 'Plan', sortKey: 'plan',
    cell: o => <span className="inline-flex flex-wrap items-center gap-1.5"><span className="mono text-xs">{o.plan || '—'}</span><Pill tone={BILLING_TONE[o.billing] || 'neutral'}>{o.billing || '—'}</Pill></span> },
  { key: 'status', label: 'Status',
    cell: o => o.deleted ? <Pill tone="bad">deleted</Pill> : o.suspended ? <Pill tone="bad">suspended</Pill> : <Pill tone="good">active</Pill> },
  { key: 'members', label: 'Members', sortKey: 'members', firstDir: 'desc', cell: o => o.members },
  { key: 'domains', label: 'Domains', sortKey: 'domains', firstDir: 'desc', cell: o => `${o.domains_verified}/${o.domains} verified` },
  { key: 'last_scan', label: 'Last scan', sortKey: 'last_scan', firstDir: 'desc',
    cell: o => o.last_scan_at ? <span className="inline-flex flex-wrap items-center gap-1.5">{fmtAgo(o.last_scan_at)} <Pill tone={statusTone(o.last_scan_status)}>{o.last_scan_status}</Pill></span> : 'never' },
  { key: 'created', label: 'Created', sortKey: 'created', firstDir: 'desc', cell: o => fmtDate(o.created_at, false) },
];

export function OrganizationsView() {
  const { q, offset, limit, sort, dir, set, params } = useListParams({ sort: 'created', dir: 'desc' });
  const billing = params.get('billing') || '';
  const plan = params.get('plan') || '';
  const suspended = params.get('suspended') || '';
  const deleted = params.get('deleted') || '';
  const filters = { q, billing, plan, suspended, deleted, sort, dir };
  const { data, error, loading, reload } = useOwnerView<Row>('/organizations', { ...filters, offset, limit });
  return (
    <>
      <PageHead title="Organizations" subtitle={data ? `${data.total} workspace${data.total === 1 ? '' : 's'} match` : 'Every customer workspace.'}
                actions={<ExportButton path="/exports/organizations.csv" params={filters} />} />
      <FilterBar>
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder="Search name, domain or member email" />
        <SelectFilter id="org-billing" label="Billing" value={billing} options={BILLING_OPTIONS} onChange={v => set({ billing: v, offset: 0 })} />
        <SelectFilter id="org-plan" label="Plan" value={plan} options={PLAN_OPTIONS} onChange={v => set({ plan: v, offset: 0 })} />
        <SelectFilter id="org-suspended" label="Status" value={suspended}
                      options={[['', 'All'], ['no', 'Active'], ['yes', 'Suspended']]} onChange={v => set({ suspended: v, offset: 0 })} />
        <SelectFilter id="org-deleted" label="Deleted" value={deleted}
                      options={DELETED_OPTIONS} onChange={v => set({ deleted: v, offset: 0 })} />
        <SortSelect id="org-sort" columns={ORG_COLUMNS} sort={sort} dir={dir} onChange={(s, d) => set({ sort: s, dir: d, offset: 0 })} />
      </FilterBar>
      <ListState loading={loading} error={error} onRetry={reload} hasData={!!data} count={data?.items.length || 0} label="organizations"
                 empty={{ title: 'No organizations match', help: 'Clear the search or a filter to see more.' }}>
        <OwnerTable caption="Organizations" columns={ORG_COLUMNS} rows={(data?.items || []) as Row[]} rowKey={o => o.id}
                    sort={sort} dir={dir} onSort={(s, d) => set({ sort: s, dir: d, offset: 0 })} testId="org-table" />
        {data && <PagerBar offset={offset} limit={limit} total={data.total} count={data.items.length}
                           onPage={o => set({ offset: o })} onLimit={n => set({ limit: n === 50 ? 0 : n, offset: 0 })} />}
      </ListState>
    </>
  );
}

export function OrganizationDetailView() {
  const { id = '' } = useParams();
  const { data, error, loading, reload } = useOwnerView<Row>(`/organizations/${id}`);
  const org = data?.organization;
  const findings = Object.fromEntries(((data?.open_findings || []) as Row[]).map(r => [r.severity, r.n]));
  const owners = ((data?.members || []) as Row[]).filter(m => m.role === 'owner').length;
  const deleted = !!org?.deleted;
  return (
    <>
      <PageHead title={org?.name || 'Organization'} subtitle={org ? <span className="mono text-xs">{org.slug} · {org.sector || 'no sector'} · created {fmtDate(org.created_at, false)}</span> : undefined}
                actions={<div className="flex flex-wrap gap-2">
                  {org && !deleted && <SuspendAction orgId={org.id} orgName={org.name} suspended={!!org.suspended} onDone={reload} />}
                  <Link to="/organizations" className="btn-mini">← ALL ORGANIZATIONS</Link>
                </div>} />
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && (
          <div className="grid lg:grid-cols-2 gap-5">
            {deleted && (
              <div role="status" data-testid="org-deleted-note" className="lg:col-span-2 p-3 rounded border border-accent/40 bg-accent/10 text-sm text-ink flex flex-wrap items-center gap-2">
                <Pill tone="bad">deleted</Pill>
                <span>
                  Deleted {fmtDate(org.deleted_at)}{org.deleted_by_email ? <> by <span className="break-all">{org.deleted_by_email}</span></> : null}. Its members cannot sign in to it or open any of its pages, its scans are stopped and it is hidden from the owner lists.{' '}
                  {org.restorable
                    ? <>It can be restored until {fmtDate(org.restore_until)}; its data can be purged after that.</>
                    : <>The restore window ended {fmtDate(org.restore_until)}; its data can now be purged from the danger zone below.</>}
                </span>
              </div>
            )}
            {org.suspended && (
              <div role="status" data-testid="org-suspended-note" className="lg:col-span-2 p-3 rounded border border-accent/40 bg-accent/10 text-sm text-ink flex flex-wrap items-center gap-2">
                <Pill tone="bad">suspended</Pill>
                <span>Since {fmtDate(org.suspension_changed_at)}. Members can sign in and read their data; new scans, scheduled scans and changes that add something are paused (cancelling, revoking access and lowering roles stay open), and they see a notice on every page. Owner actions keep working.</span>
              </div>
            )}
            <Panel title={`Members (${(data.members as Row[]).length})`}>
              {(data.members as Row[]).length === 0 ? <Empty>No members.</Empty> : (
                <Table head={['Person', 'Role', 'Last seen', 'Action']}>
                  {(data.members as Row[]).map(m => (
                    <tr key={m.id} data-testid="member-row">
                      <Cell title><Link to={`/users/${m.id}`} className="hover:text-accent">{m.full_name || m.email}</Link><div className="text-xs text-soft break-all">{m.email}</div></Cell>
                      <Cell label="Role"><Pill>{m.role}</Pill></Cell>
                      <Cell label="Last seen">{fmtAgo(m.last_seen_at)}</Cell>
                      <Cell label="Action">
                        {deleted ? <span className="text-xs text-soft">restore the organization first</span>
                          : m.role === 'owner' && owners <= 1
                          ? <span className="text-xs text-soft">last owner</span>
                          : <RemoveMemberAction orgId={org.id} orgName={org.name} userId={m.id} email={m.email} role={m.role} onDone={reload} />}
                      </Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
            {((data.removed_members || []) as Row[]).length > 0 && (
              <Panel title="Removed by an owner action" className="lg:col-span-2">
                <Table head={['Person', 'Role', 'Removed', 'Action']}>
                  {(data.removed_members as Row[]).map(r => (
                    <tr key={r.audit_id} data-testid="removed-member-row">
                      <Cell title><span className="break-all">{r.email}</span></Cell>
                      <Cell label="Role"><Pill>{r.role}</Pill></Cell>
                      <Cell label="Removed">{fmtDate(r.removed_at)}</Cell>
                      <Cell label="Action">
                        {deleted ? <span className="text-xs text-soft">restore the organization first</span>
                          : r.restored ? <span className="text-xs text-soft">restored</span>
                          : r.is_member ? <span className="text-xs text-soft">member again</span>
                          : org.suspended ? <span className="text-xs text-soft">lift the suspension to restore</span>
                          : <RestoreMemberAction orgId={org.id} orgName={org.name} auditId={r.audit_id} email={r.email}
                                                 role={r.role} onDone={reload} />}
                      </Cell>
                    </tr>
                  ))}
                </Table>
              </Panel>
            )}
            <Panel title="Domains">
              {(data.domains as Row[]).length === 0 ? <Empty>No domains added yet.</Empty> : (
                <Table head={['Domain', 'Status', 'Verified']}>
                  {(data.domains as Row[]).map(d => (
                    <tr key={d.id}>
                      <Cell title><span className="mono text-xs">{d.domain}</span></Cell>
                      <Cell label="Status"><Pill tone={d.revoked_at ? 'bad' : statusTone(d.verification_status)}>{d.revoked_at ? 'removed' : d.verification_status}</Pill></Cell>
                      <Cell label="Verified">{fmtDate(d.verified_at, false)}</Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
            <Panel title="Plan and billing" right={deleted ? undefined :
              <div className="flex flex-wrap justify-end gap-2">
                <ChangePlanAction orgId={org.id} orgName={org.name} current={(data.subscriptions as Row[])[0]?.plan || org.plan}
                                  plans={data.plans || []} onDone={reload} />
                {(data.subscriptions as Row[])[0]?.status === 'trialing' && (
                  <ExtendTrialAction orgId={org.id} orgName={org.name} trialEndsAt={(data.subscriptions as Row[])[0]?.trial_ends_at}
                                     onDone={reload} />
                )}
              </div>
            }>
              <p className="text-sm mb-3">Plan on record: <span className="mono">{org.plan || '—'}</span></p>
              {(data.subscriptions as Row[]).map((s, i) => (
                <div key={i} className="text-sm flex flex-wrap gap-2 items-center mb-2">
                  <Pill tone={statusTone(s.status)}>{s.status}</Pill>
                  <span className="mono text-xs">{s.plan}</span>
                  <span className="text-soft text-xs">period ends {fmtDate(s.current_period_end, false)}{s.trial_ends_at ? ` · trial ends ${fmtDate(s.trial_ends_at, false)}` : ''}</span>
                </div>
              ))}
              {(data.invoices as Row[]).length > 0 && (
                <Table head={['Invoice', 'Amount', 'Status', 'Date']}>
                  {(data.invoices as Row[]).map(inv => (
                    <tr key={inv.number}>
                      <Cell title><span className="mono text-xs">{inv.number}</span></Cell>
                      <Cell label="Amount">{fmtMoney(inv.amount_kobo, inv.currency)}</Cell>
                      <Cell label="Status"><Pill tone={statusTone(inv.status)}>{inv.status}</Pill></Cell>
                      <Cell label="Date">{fmtDate(inv.created_at, false)}</Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
            <Panel title="Open findings">
              <div className="flex flex-wrap gap-2">
                {['critical', 'high', 'medium', 'low', 'info'].map(s => (
                  <Pill key={s} tone={s === 'critical' || s === 'high' ? 'bad' : s === 'medium' ? 'warn' : 'neutral'}>{s}: {findings[s] || 0}</Pill>
                ))}
              </div>
            </Panel>
            <Panel title="Recent scans" className="lg:col-span-2">
              {(data.scans as Row[]).length === 0 ? <Empty>No scans yet.</Empty> : (
                <Table head={['Domain', 'Status', 'Coverage', 'Score', 'Started']}>
                  {(data.scans as Row[]).map(s => (
                    <tr key={s.id}>
                      <Cell title><Link to={`/scans/${s.id}`} className="mono text-xs hover:text-accent">{s.domain || '—'}</Link></Cell>
                      <Cell label="Status"><Pill tone={statusTone(s.status)}>{s.status}</Pill></Cell>
                      <Cell label="Coverage">{s.coverage_state ? <Pill tone={statusTone(s.coverage_state)}>{s.coverage_state}</Pill> : '—'}</Cell>
                      <Cell label="Score">{s.score ?? '—'}</Cell>
                      <Cell label="Started">{fmtDate(s.created_at)}</Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
            <Panel title="Owner actions on this organization" className="lg:col-span-2">
              {((data.owner_actions || []) as Row[]).length === 0 ? <Empty>No owner actions recorded.</Empty> : (
                <Table head={['When', 'Action', 'Outcome', 'By', 'Reason']}>
                  {(data.owner_actions as Row[]).map((a, i) => (
                    <tr key={i}>
                      <Cell title>{fmtDate(a.created_at)}</Cell>
                      <Cell label="Action"><span className="mono text-xs">{String(a.action).replace('owner.action.', '')}</span></Cell>
                      <Cell label="Outcome"><Pill tone={statusTone(a.outcome)}>{a.outcome}</Pill></Cell>
                      <Cell label="By"><span className="break-all">{a.actor_email || '—'}</span></Cell>
                      <Cell label="Reason"><span className="text-xs">{a.reason || '—'}</span></Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
            <Panel title="Activity" className="lg:col-span-2">
              {(data.activity as Row[]).length === 0 ? <Empty>No activity recorded.</Empty> : (
                <Table head={['Action', 'By', 'When']}>
                  {(data.activity as Row[]).map((a, i) => (
                    <tr key={i}>
                      <Cell title><span className="mono text-xs">{a.action}</span></Cell>
                      <Cell label="By">{a.user_email || 'system'}</Cell>
                      <Cell label="When">{fmtDate(a.created_at)}</Cell>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
            <DangerZone org={org} onDone={reload} />
          </div>
        )}
      </ViewState>
    </>
  );
}

/* ── Organization: danger zone (docs/admin-delete-org) ───────────────────── */
function DangerZone({ org, onDone }: { org: Row; onDone: () => void }) {
  const days = org.restore_window_days || 30;
  let body: ReactNode;
  if (!org.deleted) {
    const blocked = org.protected
      ? 'This organization is protected (the demo or the InnovaTech workspace), so it cannot be deleted from the console.'
      : org.paid_subscription_active
      ? 'It has an active paid subscription. The subscription must be cancelled first: the customer can cancel it from Settings, also while suspended.'
      : undefined;
    body = (
      <>
        <p className="text-sm text-soft mb-3">Deleting is done in two steps. First the organization is marked deleted: it disappears for its members, its scans stop and nothing is removed, so you can restore it for {days} days. After that, its data can be purged as a separate step.</p>
        <DeleteOrgAction orgId={org.id} orgName={org.name} blockedReason={blocked} onDone={onDone} />
      </>
    );
  } else if (org.restorable) {
    body = (
      <>
        <p className="text-sm text-soft mb-3">Deleted {fmtDate(org.deleted_at)}. You can restore it until {fmtDate(org.restore_until)}. Purging its data becomes possible after that date.</p>
        <RestoreOrgAction orgId={org.id} orgName={org.name} restoreUntil={org.restore_until} onDone={onDone} />
      </>
    );
  } else {
    body = (
      <>
        <p className="text-sm text-soft mb-3">The {days}-day restore window ended {fmtDate(org.restore_until)}. Purging removes its data permanently. It is refused while compliance records are still inside their retention period.</p>
        {org.protected
          ? <p className="text-xs text-soft" data-testid="org-purge-blocked">This organization is protected, so its data cannot be purged from the console.</p>
          : <PurgeOrgAction orgId={org.id} orgName={org.name} onDone={onDone} />}
      </>
    );
  }
  return (
    <section data-testid="org-danger-zone" aria-labelledby="org-danger-title"
             className="lg:col-span-2 min-w-0 rounded border border-accent/50 p-5">
      <h2 id="org-danger-title" className="text-[11px] mono uppercase tracking-[.14em] text-accent mb-3">Danger zone</h2>
      {body}
    </section>
  );
}

/* ── Users ──────────────────────────────────────────────────────────────── */
const MFA_LABEL: Record<string, string> = { authenticator: 'authenticator', email_code: 'email code', none: 'none' };

const USER_COLUMNS: Column<Row>[] = [
  { key: 'email', label: 'Person', sortKey: 'email', title: true,
    cell: u => <><Link to={`/users/${u.id}`} className="font-medium hover:text-accent break-all">{u.email}</Link>
      {u.full_name && <div className="text-xs text-soft">{u.full_name}</div>}</> },
  { key: 'orgs', label: 'Organizations and roles',
    cell: u => {
      const list = (u.memberships || []) as Row[];
      if (list.length === 0) return <span className="text-xs text-soft">{u.organizations || '—'}</span>;
      return <span className="flex flex-col gap-1">{list.map(m => (
        <span key={m.org_id} className="text-xs"><Link to={`/organizations/${m.org_id}`} className="hover:text-accent">{m.name}</Link> <Pill>{m.role}</Pill></span>
      ))}</span>;
    } },
  { key: 'mfa', label: 'Second step',
    cell: u => <span className="inline-flex flex-wrap gap-1">
      <Pill tone={u.mfa && u.mfa !== 'none' ? 'good' : 'warn'}>{MFA_LABEL[u.mfa] || (u.authenticator ? 'authenticator' : 'none')}</Pill>
      {!u.email_verified && <Pill tone="warn">unverified</Pill>}
      {u.platform_owner && <Pill tone="bad">platform owner</Pill>}
    </span> },
  { key: 'last_sign_in', label: 'Last sign-in', sortKey: 'last_sign_in', firstDir: 'desc',
    cell: u => <span>{fmtAgo(u.last_sign_in_at || u.last_seen_at)}{u.active_sessions ? <span className="text-soft"> · {u.active_sessions} active</span> : null}</span> },
  { key: 'created', label: 'Joined', sortKey: 'created', firstDir: 'desc', cell: u => fmtDate(u.created_at, false) },
];

export function UsersView() {
  const { q, offset, limit, sort, dir, set, params } = useListParams({ sort: 'created', dir: 'desc' });
  const mfa = params.get('mfa') || '';
  const verified = params.get('verified') || '';
  const filters = { q, mfa, verified, sort, dir };
  const { data, error, loading, reload } = useOwnerView<Row>('/users', { ...filters, offset, limit });
  return (
    <>
      <PageHead title="Users" subtitle={data ? `${data.total} account${data.total === 1 ? '' : 's'} match` : 'Every account on the platform.'}
                actions={<ExportButton path="/exports/users.csv" params={filters} />} />
      <FilterBar>
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder="Search email or name" />
        <SelectFilter id="user-mfa" label="Second step" value={mfa}
                      options={[['', 'All'], ['authenticator', 'Authenticator'], ['email_code', 'Email code'], ['none', 'None']]}
                      onChange={v => set({ mfa: v, offset: 0 })} />
        <SelectFilter id="user-verified" label="Email" value={verified}
                      options={[['', 'All'], ['yes', 'Verified'], ['no', 'Not verified']]} onChange={v => set({ verified: v, offset: 0 })} />
        <SortSelect id="user-sort" columns={USER_COLUMNS} sort={sort} dir={dir} onChange={(s, d) => set({ sort: s, dir: d, offset: 0 })} />
      </FilterBar>
      <ListState loading={loading} error={error} onRetry={reload} hasData={!!data} count={data?.items.length || 0} label="users"
                 empty={{ title: 'No users match', help: 'Clear the search or a filter to see more.' }}>
        <OwnerTable caption="Users" columns={USER_COLUMNS} rows={(data?.items || []) as Row[]} rowKey={u => u.id}
                    sort={sort} dir={dir} onSort={(s, d) => set({ sort: s, dir: d, offset: 0 })} testId="user-table" />
        {data && <PagerBar offset={offset} limit={limit} total={data.total} count={data.items.length}
                           onPage={o => set({ offset: o })} onLimit={n => set({ limit: n === 50 ? 0 : n, offset: 0 })} />}
      </ListState>
    </>
  );
}

export function UserDetailView() {
  const { id = '' } = useParams();
  const { data, error, loading, reload } = useOwnerView<Row>(`/users/${id}`);
  const u = data?.user;
  const me = useContext(OwnerMeContext);
  return (
    <>
      <PageHead title={u?.full_name || u?.email || 'User'} subtitle={u ? <span className="mono text-xs">{u.email} · joined {fmtDate(u.created_at, false)}</span> : undefined}
                actions={<div className="flex flex-wrap gap-2">
                  {u && u.email !== me?.email && <SignOutEverywhereAction userId={u.id} email={u.email} onDone={reload} />}
                  <Link to="/users" className="btn-mini">← ALL USERS</Link>
                </div>} />
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && (
          <div className="grid lg:grid-cols-2 gap-5">
            <Panel title="Account">
              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-soft">Sign-in</dt><dd className="mono text-xs">{u.provider}</dd>
                <dt className="text-soft">Email</dt><dd>{u.email_verified_at ? `verified ${fmtDate(u.email_verified_at, false)}` : 'not verified'}</dd>
                <dt className="text-soft">Email code</dt><dd>{u.mfa_enrolled_at ? 'opted in' : 'not opted in'}</dd>
                <dt className="text-soft">Authenticator</dt><dd>{u.totp_enrolled_at ? `since ${fmtDate(u.totp_enrolled_at, false)}` : 'not set up'}</dd>
                <dt className="text-soft">Remembered browsers</dt><dd>{data.remembered_browsers}</dd>
                <dt className="text-soft">Platform owner</dt><dd>{u.platform_owner ? 'yes' : 'no'}</dd>
              </dl>
            </Panel>
            <Panel title="Organizations">
              {(data.memberships as Row[]).length === 0 ? <Empty>Not in any organization.</Empty> : (
                <ul className="space-y-2">
                  {(data.memberships as Row[]).map(m => (
                    <li key={m.id} className="flex items-center justify-between gap-2 text-sm">
                      <Link to={`/organizations/${m.id}`} className="hover:text-accent">{m.name}</Link>
                      <span className="inline-flex flex-wrap gap-1">{m.deleted && <Pill tone="bad">deleted</Pill>}<Pill>{m.role}</Pill></span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Sign-in sessions" className="lg:col-span-2">
              {(data.sessions as Row[]).length === 0 ? <Empty>No sessions.</Empty> : (
                <Table head={['Session', 'Started', 'Last used', 'State']}>
                  {(data.sessions as Row[]).map(s => {
                    const live = !s.revoked_at && new Date(s.expires_at).getTime() > Date.now();
                    return (
                      <tr key={s.ref}>
                        <Cell title><span className="mono text-xs">{s.ref}…</span></Cell>
                        <Cell label="Started">{fmtDate(s.created_at)}</Cell>
                        <Cell label="Last used">{fmtAgo(s.last_used_at || s.created_at)}</Cell>
                        <Cell label="State"><Pill tone={live ? 'good' : 'neutral'}>{s.revoked_at ? 'signed out' : live ? 'active' : 'expired'}</Pill></Cell>
                      </tr>
                    );
                  })}
                </Table>
              )}
            </Panel>
            <Panel title="Activity" className="lg:col-span-2">
              {(data.activity as Row[]).length === 0 ? <Empty>No activity recorded.</Empty> : (
                <Table head={['Action', 'Organization', 'When']}>
                  {(data.activity as Row[]).map((a, i) => (
                    <tr key={i}>
                      <Cell title><span className="mono text-xs">{a.action}</span></Cell>
                      <Cell label="Organization">{a.org_name || '—'}</Cell>
                      <Cell label="When">{fmtDate(a.created_at)}</Cell>
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
