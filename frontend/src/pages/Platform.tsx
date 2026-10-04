import { useEffect, useState } from 'react';
import { Activity, Building, ShieldAlert, Search, Clock } from 'lucide-react';
import {
  platformHealth,
  platformTenantLookup,
  platformOverdueScans,
  type PlatformHealth,
  type PlatformTenant,
  type PlatformOverdueScan,
} from '../lib/api';
import { useToast } from '../components/Toast';

export default function Platform() {
  const toast = useToast();
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [denied, setDenied] = useState(false);
  const [reason, setReason] = useState('');
  const [orgId, setOrgId] = useState('');
  const [tenant, setTenant] = useState<PlatformTenant | null>(null);
  const [overdue, setOverdue] = useState<PlatformOverdueScan[]>([]);
  const [busy, setBusy] = useState<'health' | 'tenant' | 'overdue' | null>(null);

  useEffect(() => {
    setBusy('health');
    platformHealth()
      .then(setHealth)
      .catch(() => setDenied(true))
      .finally(() => setBusy(null));
  }, []);

  const needReason = () => {
    if (reason.trim().length < 8) {
      toast('Enter a support reason (min 8 characters) — it is recorded in audit.');
      return null;
    }
    return reason.trim();
  };

  const lookupTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = needReason();
    if (!r || !orgId.trim()) return;
    setBusy('tenant');
    try {
      setTenant(await platformTenantLookup(orgId.trim(), r));
    } catch (err: any) {
      toast(err?.message || 'Lookup failed');
    } finally {
      setBusy(null);
    }
  };

  const loadOverdue = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = needReason();
    if (!r) return;
    setBusy('overdue');
    try {
      const res = await platformOverdueScans(r);
      setOverdue(res.scans);
      toast(res.count === 0 ? 'No stuck scans.' : `${res.count} stuck scan(s) found.`);
    } catch (err: any) {
      toast(err?.message || 'Lookup failed');
    } finally {
      setBusy(null);
    }
  };

  if (denied) {
    return (
      <div className="space-y-6 max-w-3xl mx-auto pb-12 content-fade-in">
        <p className="eyebrow text-accent">INTERNAL · PLATFORM OPERATIONS</p>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">Platform console</h1>
        <div className="p-6 rounded-lg border border-line bg-raised flex items-start gap-3">
          <ShieldAlert size={18} className="text-accent flex-none mt-0.5" />
          <div className="text-xs mono text-soft leading-relaxed">
            <p className="text-ink font-semibold mb-1">No platform grant on this account.</p>
            <p>
              Organization roles never confer platform rights. Access is a separate,
              time-boxed grant recorded with a reason — ask a platform owner to provision it.
              Every lookup here writes an immutable audit event.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      <div>
        <div className="flex items-center gap-2">
          <span className="live-dot" />
          <p className="eyebrow text-accent">INTERNAL · PLATFORM OPERATIONS</p>
        </div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">Platform console</h1>
        <p className="text-xs mono text-soft mt-1">
          Service health, tenant lookup, stuck scans. Counts and identifiers only — never scan evidence or personal data.
        </p>
      </div>

      {/* Health */}
      <div className="p-6 rounded-lg border border-line bg-raised">
        <div className="flex items-center gap-2 pb-3 border-b border-line mb-3">
          <Activity size={15} className="text-accent" />
          <h3 className="mono font-semibold text-ink text-sm">SERVICE HEALTH</h3>
        </div>
        {health ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mono">
            <div className="p-2 rounded bg-inset border border-line">
              <div className="text-soft text-[10px]">DATABASE</div>
              <div className="text-ok font-semibold">{health.database.connected ? `UP · ${health.database.roundtrip_ms}ms` : 'DOWN'}</div>
            </div>
            <div className="p-2 rounded bg-inset border border-line">
              <div className="text-soft text-[10px]">DAILY SWEEP</div>
              <div className="text-ink font-semibold">{health.daily_scans_last_completed || 'never'}</div>
            </div>
            <div className="p-2 rounded bg-inset border border-line">
              <div className="text-soft text-[10px]">ACTIVE SCANS</div>
              <div className="text-ink font-semibold">{health.scans_active}</div>
            </div>
          </div>
        ) : (
          <p className="text-xs mono text-soft">{busy === 'health' ? 'Loading…' : '—'}</p>
        )}
      </div>

      {/* Support reason (shared, audited) */}
      <div className="p-6 rounded-lg border border-line bg-raised space-y-3">
        <h3 className="mono font-semibold text-ink text-sm">SUPPORT REASON (RECORDED IN AUDIT)</h3>
        <input
          type="text"
          placeholder="e.g. customer ticket #1234 — stuck scan triage"
          value={reason}
          onChange={e => setReason(e.target.value)}
          className="w-full bg-inset border border-line rounded px-3 py-2 text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
        />

        {/* Tenant lookup */}
        <form onSubmit={lookupTenant} className="flex flex-wrap items-center gap-2 pt-2">
          <div className="flex items-center gap-2 flex-1 min-w-[220px]">
            <Building size={14} className="text-soft flex-none" />
            <input
              type="text"
              placeholder="Organization ID"
              value={orgId}
              onChange={e => setOrgId(e.target.value)}
              className="flex-1 bg-inset border border-line rounded px-3 py-1.5 text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
            />
          </div>
          <button
            type="submit"
            disabled={busy === 'tenant'}
            className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50 flex items-center gap-1.5"
          >
            <Search size={12} /> {busy === 'tenant' ? 'LOOKING UP…' : 'LOOKUP TENANT'}
          </button>
          <button
            type="button"
            onClick={loadOverdue}
            disabled={busy === 'overdue'}
            className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50 flex items-center gap-1.5"
          >
            <Clock size={12} /> {busy === 'overdue' ? 'LOADING…' : 'STUCK SCANS'}
          </button>
        </form>

        {tenant && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mono pt-1">
            <div className="p-2 rounded bg-inset border border-line col-span-2">
              <div className="text-soft text-[10px]">ORGANIZATION</div>
              <div className="text-ink font-semibold">{tenant.name}</div>
              <div className="text-soft text-[10px]">{tenant.slug} · {tenant.plan}</div>
            </div>
            <div className="p-2 rounded bg-inset border border-line">
              <div className="text-soft text-[10px]">MEMBERS / DOMAINS</div>
              <div className="text-ink font-semibold">{tenant.member_count} / {tenant.domain_count}</div>
            </div>
            <div className="p-2 rounded bg-inset border border-line">
              <div className="text-soft text-[10px]">ACTIVE SCANS</div>
              <div className="text-ink font-semibold">{tenant.active_scan_count}</div>
            </div>
          </div>
        )}

        {overdue.length > 0 && (
          <table className="w-full text-left text-xs mono mt-1">
            <thead>
              <tr className="border-b border-line text-soft text-[11px]">
                <th className="pb-2 font-medium">SCAN</th>
                <th className="pb-2 font-medium">ORGANIZATION</th>
                <th className="pb-2 font-medium">STATUS</th>
                <th className="pb-2 font-medium">STUCK SINCE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {overdue.map(s => (
                <tr key={s.id}>
                  <td className="py-2 text-soft">{s.id.slice(0, 8)}</td>
                  <td className="py-2 text-ink">{s.org_name}</td>
                  <td className="py-2 text-soft uppercase">{s.status}</td>
                  <td className="py-2 text-soft">{s.lease_expires_at || s.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
