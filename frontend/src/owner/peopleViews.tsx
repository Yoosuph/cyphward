import { useCallback } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Activity, AlertTriangle, Building2, Clock, CreditCard, Globe, Radar, Users } from 'lucide-react';
import {
  Cell, Empty, PageHead, Pager, Panel, Pill, SearchBox, Stat, Table, ViewState,
  fmtAgo, fmtDate, fmtDuration, fmtMoney, statusTone, useOwnerView,
} from './ui';

type Row = Record<string, any>;

/** Search text and page offset live in the URL, so back/forward keeps them. */
export function useListParams() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') || '';
  const offset = Number(params.get('offset') || 0) || 0;
  const set = useCallback((next: Record<string, string | number>) => {
    const merged = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v === '' || v === 0 ? merged.delete(k) : merged.set(k, String(v))));
    setParams(merged, { replace: true });
  }, [params, setParams]);
  return { q, offset, set, params };
}

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
          <Panel title="Recent customer activity" className="lg:col-span-2" right={<Link to="/logs" className="text-[10px] mono text-soft hover:text-accent">ALL LOGS →</Link>}>
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
export function OrganizationsView() {
  const { q, offset, set } = useListParams();
  const limit = 50;
  const { data, error, loading, reload } = useOwnerView<Row>('/organizations', { q, offset, limit });
  return (
    <>
      <PageHead title="Organizations" subtitle={data ? `${data.total} workspace${data.total === 1 ? '' : 's'}` : 'Every customer workspace.'} />
      <div className="flex flex-wrap gap-3 mb-4">
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder="Search name, domain or member email" />
      </div>
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && data.items.length === 0 ? <Empty>No organizations match.</Empty> : (
          <Panel>
            <Table head={['Organization', 'Owner', 'Plan', 'Domains', 'Members', 'Last scan', 'Created']}>
              {(data?.items || []).map((o: Row) => (
                <tr key={o.id}>
                  <Cell title><Link to={`/organizations/${o.id}`} className="font-medium hover:text-accent">{o.name}</Link></Cell>
                  <Cell label="Owner">{o.owner_email || '—'}</Cell>
                  <Cell label="Plan"><span className="mono text-xs">{o.plan || '—'}</span> {o.subscription_status && <Pill tone={statusTone(o.subscription_status)}>{o.subscription_status}</Pill>}</Cell>
                  <Cell label="Domains">{o.domains_verified}/{o.domains} verified</Cell>
                  <Cell label="Members">{o.members}</Cell>
                  <Cell label="Last scan">{o.last_scan_at ? <span>{fmtAgo(o.last_scan_at)} <Pill tone={statusTone(o.last_scan_status)}>{o.last_scan_status}</Pill></span> : 'never'}</Cell>
                  <Cell label="Created">{fmtDate(o.created_at, false)}</Cell>
                </tr>
              ))}
            </Table>
            {data && <Pager offset={offset} limit={limit} total={data.total} count={data.items.length} onChange={o => set({ offset: o })} />}
          </Panel>
        )}
      </ViewState>
    </>
  );
}

export function OrganizationDetailView() {
  const { id = '' } = useParams();
  const { data, error, loading, reload } = useOwnerView<Row>(`/organizations/${id}`);
  const org = data?.organization;
  const findings = Object.fromEntries(((data?.open_findings || []) as Row[]).map(r => [r.severity, r.n]));
  return (
    <>
      <PageHead title={org?.name || 'Organization'} subtitle={org ? <span className="mono text-xs">{org.slug} · {org.sector || 'no sector'} · created {fmtDate(org.created_at, false)}</span> : undefined}
                actions={<Link to="/organizations" className="btn-mini">← ALL ORGANIZATIONS</Link>} />
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && (
          <div className="grid lg:grid-cols-2 gap-5">
            <Panel title="Members">
              <Table head={['Person', 'Role', 'Last seen']}>
                {(data.members as Row[]).map(m => (
                  <tr key={m.id}>
                    <Cell title><Link to={`/users/${m.id}`} className="hover:text-accent">{m.full_name || m.email}</Link><div className="text-xs text-soft">{m.email}</div></Cell>
                    <Cell label="Role"><Pill>{m.role}</Pill></Cell>
                    <Cell label="Last seen">{fmtAgo(m.last_seen_at)}</Cell>
                  </tr>
                ))}
              </Table>
            </Panel>
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
            <Panel title="Plan and billing">
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
          </div>
        )}
      </ViewState>
    </>
  );
}

/* ── Users ──────────────────────────────────────────────────────────────── */
export function UsersView() {
  const { q, offset, set } = useListParams();
  const limit = 50;
  const { data, error, loading, reload } = useOwnerView<Row>('/users', { q, offset, limit });
  return (
    <>
      <PageHead title="Users" subtitle={data ? `${data.total} account${data.total === 1 ? '' : 's'}` : 'Every account on the platform.'} />
      <div className="flex flex-wrap gap-3 mb-4">
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder="Search email or name" />
      </div>
      <ViewState loading={loading} error={error} onRetry={reload} empty={!data}>
        {data && data.items.length === 0 ? <Empty>No users match.</Empty> : (
          <Panel>
            <Table head={['Person', 'Organizations', 'Sign-in', 'Security', 'Last seen', 'Joined']}>
              {(data?.items || []).map((u: Row) => (
                <tr key={u.id}>
                  <Cell title>
                    <Link to={`/users/${u.id}`} className="font-medium hover:text-accent">{u.full_name || u.email}</Link>
                    <div className="text-xs text-soft">{u.email}</div>
                  </Cell>
                  <Cell label="Organizations"><span className="text-xs">{u.organizations || '—'}</span></Cell>
                  <Cell label="Sign-in"><span className="mono text-xs">{u.provider}</span></Cell>
                  <Cell label="Security">
                    <span className="flex flex-wrap gap-1">
                      <Pill tone={u.email_verified ? 'good' : 'warn'}>{u.email_verified ? 'email verified' : 'unverified'}</Pill>
                      {u.authenticator && <Pill tone="good">authenticator</Pill>}
                      {u.platform_owner && <Pill tone="bad">platform owner</Pill>}
                    </span>
                  </Cell>
                  <Cell label="Last seen"><span>{fmtAgo(u.last_seen_at)}{u.active_sessions ? <span className="text-soft"> · {u.active_sessions} active</span> : null}</span></Cell>
                  <Cell label="Joined">{fmtDate(u.created_at, false)}</Cell>
                </tr>
              ))}
            </Table>
            {data && <Pager offset={offset} limit={limit} total={data.total} count={data.items.length} onChange={o => set({ offset: o })} />}
          </Panel>
        )}
      </ViewState>
    </>
  );
}

export function UserDetailView() {
  const { id = '' } = useParams();
  const { data, error, loading, reload } = useOwnerView<Row>(`/users/${id}`);
  const u = data?.user;
  return (
    <>
      <PageHead title={u?.full_name || u?.email || 'User'} subtitle={u ? <span className="mono text-xs">{u.email} · joined {fmtDate(u.created_at, false)}</span> : undefined}
                actions={<Link to="/users" className="btn-mini">← ALL USERS</Link>} />
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
                      <Pill>{m.role}</Pill>
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
