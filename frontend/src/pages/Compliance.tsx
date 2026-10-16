import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ChevronDown, ClipboardList, Info, Lock, RefreshCw } from 'lucide-react';
import { PageHead, Loading } from '../components/ui';
import StatusChip, { type ChipLevel } from '../components/StatusChip';
import { useToast } from '../components/Toast';
import {
  createRemediationTask,
  getComplianceOverview,
  getRemediationTasks,
  type ComplianceFindingRef,
  type ComplianceOverview,
  type ComplianceRequirement,
  type ComplianceStatus,
} from '../lib/api';

/**
 * NDPA / GAID readiness evidence. Shows what Cyphward has observed for each
 * requirement, labelled by source. It never states a legal conclusion:
 * missing evidence reads "Not assessed", never as met.
 */

const CHIP: Record<ComplianceStatus, ChipLevel> = { present: 'ok', gap: 'bad', not_assessed: 'warn', not_applicable: 'idle', awaiting_input: 'idle' };

const CARD = 'rounded-lg border border-line bg-raised';

function fmtDay(value?: string | null) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function Chip({ status, label }: { status: ComplianceStatus; label: string }) {
  return <span className="uppercase"><StatusChip level={CHIP[status]}>{label}</StatusChip></span>;
}

function SourceTag({ label }: { label: string | null }) {
  return label
    ? <span className="tag uppercase">{label}</span>
    : <span className="text-[10.5px] mono tracking-[.12em] text-soft uppercase">No evidence yet</span>;
}

function TaskButton({ finding }: { finding: ComplianceFindingRef }) {
  const toast = useToast();
  const [state, setState] = useState<'idle' | 'busy' | 'exists' | 'created'>('idle');
  const run = async () => {
    setState('busy');
    try {
      const existing = await getRemediationTasks({ finding_id: finding.id });
      if (existing.tasks.length > 0) {
        setState('exists');
        return;
      }
      const created = await createRemediationTask({ finding_id: finding.id, title: `Fix: ${finding.title}`.slice(0, 300) });
      if (!created) throw new Error('not created');
      setState('created');
      toast('Remediation task created.');
    } catch {
      setState('idle');
      toast('Could not create the task. Try again from Remediation.');
    }
  };
  if (state === 'exists' || state === 'created') {
    return (
      <Link to="/remediation" className="btn-mini whitespace-nowrap">
        <ClipboardList size={12} /> {state === 'created' ? 'TASK CREATED' : 'VIEW TASK'}
      </Link>
    );
  }
  return (
    <button type="button" className="btn-mini whitespace-nowrap" onClick={() => void run()} disabled={state === 'busy'}>
      <ClipboardList size={12} /> {state === 'busy' ? 'CHECKING…' : 'CREATE TASK'}
    </button>
  );
}

function RequirementRow({ req }: { req: ComplianceRequirement }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-t border-line first:border-t-0">
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
              className="w-full text-left px-4 sm:px-5 py-3.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 hover:bg-inset/60 transition-colors">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-ink font-medium">{req.title}</p>
          <p className={`text-[11px] mono mt-0.5 ${req.clause_verified ? 'text-soft' : 'text-warn'}`}>{req.clause_label}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end shrink-0">
          <Chip status={req.status} label={req.status_label} />
          <SourceTag label={req.source_label} />
          <ChevronDown size={14} className={`hidden sm:block text-soft transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {open && (
        <div className="px-4 sm:px-5 pb-5 space-y-4 text-sm content-fade-in">
          <p className="text-soft leading-relaxed">{req.summary}</p>
          <p className="text-xs mono text-ink">{req.reason_text}</p>

          {req.checks_performed && (
            <dl className="grid sm:grid-cols-2 gap-3 text-xs">
              <div className="p-3 rounded border border-line bg-inset/50">
                <dt className="mono text-[10px] tracking-[.16em] text-soft mb-1">CHECKED</dt>
                <dd className="text-ink leading-relaxed">{req.checks_performed}</dd>
              </div>
              <div className="p-3 rounded border border-line bg-inset/50">
                <dt className="mono text-[10px] tracking-[.16em] text-soft mb-1">NOT CHECKED</dt>
                <dd className="text-ink leading-relaxed">{req.not_checked}</dd>
              </div>
            </dl>
          )}
          {!req.checks_performed && (
            <p className="text-xs text-soft">Evidence type: {req.evidence_type_labels.join(', ')}.</p>
          )}

          {req.domains.length > 0 && (
            <ul className="space-y-2">
              {req.domains.map(d => (
                <li key={d.domain_id} className="p-3 rounded border border-line">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="mono text-xs text-ink break-all">{d.domain}</span>
                    <span className="flex flex-wrap items-center gap-2">
                      <Chip status={d.status} label={d.status_label} />
                      <SourceTag label={d.source_label} />
                    </span>
                  </div>
                  <p className="text-xs text-soft mt-1.5">
                    {d.reason_text}
                    {d.observed_at && <> · observed {fmtDay(d.observed_at)}</>}
                    {d.expires_at && d.status === 'present' && <> · current until {fmtDay(d.expires_at)}</>}
                  </p>
                  {d.details.open_ports && Object.keys(d.details.open_ports).length > 0 && (
                    <p className="text-xs mono text-ink mt-1.5 break-words">
                      Open ports: {Object.entries(d.details.open_ports).map(([h, ports]) => `${h} ${ports.join(', ')}`).join(' · ')}
                    </p>
                  )}
                  {typeof d.details.url === 'string' && (
                    <p className="text-xs mono text-ink mt-1.5 break-all">
                      {d.details.off_domain ? 'Linked, hosted elsewhere (not fetched): ' : 'Page: '}{d.details.url}
                      {d.details.changed_since_last_scan === true && <span className="text-warn"> · changed since last scan</span>}
                    </p>
                  )}
                  {Array.isArray(d.details.observed) && d.details.observed.length > 0 && (
                    <p className="text-xs mono text-accent mt-1.5 break-words">
                      Observed: {(d.details.observed as { vendor: string; how: string; host: string }[])
                        .map(o => `${String(o.vendor).replace(/_/g, ' ')} (${o.how.replace(/_/g, ' ')}, ${o.host})`).join(' · ')}
                    </p>
                  )}
                  {Array.isArray(d.details.cookies) && d.details.cookies.length > 0 && (
                    <p className="text-xs mono text-soft mt-1.5 break-words">
                      First-visit cookies: {(d.details.cookies as { name: string; category: string }[])
                        .map(c => `${c.name} (${c.category})`).join(', ')}
                    </p>
                  )}
                  {Array.isArray(d.details.consent_managers) && d.details.consent_managers.length > 0 && (
                    <p className="text-xs mono text-soft mt-1.5">Consent manager: {(d.details.consent_managers as string[]).join(', ')}</p>
                  )}
                  {(d.details.missing || []).length > 0 && (
                    <p className="text-xs mono text-soft mt-1.5 break-words">
                      Not finished: {(d.details.missing || []).map(m => `${m.hostname} ${m.check} (${m.reason.replace(/_/g, ' ')})`).join(' · ')}
                    </p>
                  )}
                  {d.details.complete_scans && (
                    <p className="text-xs mono text-soft mt-1.5">
                      {d.details.complete_scans.length} complete scan{d.details.complete_scans.length === 1 ? '' : 's'} in {d.details.window_days} days
                      {d.details.complete_scans.length > 0 && <> · latest {fmtDay(d.details.complete_scans[0].completed_at)}</>}
                      {(d.details.not_counted || []).length > 0 && <> · {(d.details.not_counted || []).length} partial or unknown not counted</>}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}

          {req.findings.length > 0 && (
            <div>
              <p className="mono text-[10px] tracking-[.16em] text-soft mb-2">OPEN FINDINGS BEHIND THIS GAP</p>
              <ul className="space-y-2">
                {req.findings.map(f => (
                  <li key={f.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded border border-line">
                    <Link to="/findings" className="text-xs text-ink hover:text-accent min-w-0 break-words">
                      <span className="mono uppercase text-accent mr-2">{f.severity}</span>{f.title}
                    </Link>
                    <TaskButton finding={f} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(req.policy_mentions || []).length > 0 && (
            <p className="text-xs text-soft">
              Your published privacy policy (heuristic, not a review):{' '}
              {(req.policy_mentions || []).map(pm => `${pm.state === 'mentioned' ? 'mentions this' : 'does not mention this'} (${pm.domain})`).join(' · ')}
            </p>
          )}
          {req.informational_findings.length > 0 && (
            <p className="text-xs text-soft">
              Also observed (informational): {req.informational_findings.map(f => f.title).join(' · ')}
            </p>
          )}

          {req.status !== 'present' && <p className="text-xs text-soft"><span className="mono text-ink">Next step:</span> {req.remediation_hint}</p>}
        </div>
      )}
    </li>
  );
}

export default function Compliance() {
  const [data, setData] = useState<ComplianceOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getComplianceOverview());
    } catch (e) {
      setError((e as Error).message || 'Could not load compliance readiness.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading && !data) return <Loading label="COMPLIANCE READINESS" />;
  if (error && !data) {
    return (
      <div className="max-w-7xl mx-auto pb-16 content-fade-in">
        <div className="bg-inset border border-line rounded p-10 text-center space-y-3">
          <AlertTriangle size={22} className="mx-auto text-accent" />
          <p className="text-sm mono">We couldn't load compliance readiness.</p>
          <p className="text-xs mono text-soft max-w-md mx-auto">{error}</p>
          <button type="button" className="btn btn-solid btn-mini hover-lift" onClick={() => void load()}>
            <RefreshCw size={12} className="mr-1" /> RETRY
          </button>
        </div>
      </div>
    );
  }
  if (!data) return null;
  const r = data.readiness;
  const total = data.groups.reduce((n, g) => n + g.requirement_count, 0);

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      <PageHead
        title="Compliance readiness"
        note={`${data.register.title}. Evidence Cyphward has observed, labelled by source.`}
        actions={
          <button type="button" onClick={() => void load()} aria-label="Refresh" title="Refresh"
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink transition-colors min-h-[38px] btn-tactile">
            <RefreshCw size={14} /> <span className="sm:hidden">REFRESH</span>
          </button>
        }
      />

      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-accent/30 bg-accent/5 text-xs text-ink leading-relaxed" data-testid="compliance-disclaimer">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>{data.disclaimer}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className={`lg:col-span-4 p-6 ${CARD}`}>
          <p className="text-[11px] mono uppercase text-soft">Readiness evidence</p>
          <p className="text-base text-ink mt-3 leading-snug" data-testid="readiness-line">
            <span className="text-3xl font-bold mono">{r.with_evidence}</span> of {r.applicable} have evidence
            <span className="text-soft"> · {r.awaiting_input} awaiting input or upcoming checks</span>
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-2 mt-4">
            <StatusChip level="ok">{r.present} PRESENT</StatusChip>
            <StatusChip level="bad">{r.gap} GAPS</StatusChip>
            <StatusChip level="warn">{r.not_assessed} NOT ASSESSED</StatusChip>
            <StatusChip level="idle">{r.awaiting_input} AWAITING INPUT</StatusChip>
          </div>
        </div>
        <div className={`lg:col-span-8 p-6 ${CARD} space-y-3 text-sm`}>
          <p className="text-[11px] mono uppercase text-soft">How to read this</p>
          <p className="text-soft leading-relaxed">{data.note}</p>
          <p className="text-soft leading-relaxed">
            Evidence present means the checks finished with nothing linked open; a gap means an open finding is
            linked. Not assessed means a check could have run but did not finish. Awaiting input means Cyphward has
            no source for it yet. Clause references marked “pending review” have not yet been checked against the official texts
            ({data.register.references_pending_review} of {total} in register {data.register.version}).
          </p>
          {data.domains.length === 0 && (
            <p className="text-xs mono text-ink">No verified domain yet. <Link to="/domains" className="text-accent underline">Verify a domain</Link> to start collecting evidence.</p>
          )}
        </div>
      </div>

      <div className="space-y-5">
        {data.groups.map(group => (
          <section key={group.key} className={CARD} aria-label={group.title}>
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 sm:px-5 py-3.5 border-b border-line">
              <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">{group.title}</h2>
              {group.locked ? (
                <span className="tag uppercase flex items-center gap-1.5"><Lock size={10} /> Growth plan</span>
              ) : (
                <span className="text-[10.5px] mono text-soft">
                  {group.counts.present} present · {group.counts.gap} gaps · {group.counts.not_assessed} not assessed · {group.counts.awaiting_input} awaiting
                </span>
              )}
            </div>
            {group.locked ? (
              <div className="px-4 sm:px-5 py-5 text-sm text-soft flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <span>{group.requirement_count} requirements. Their detail is part of the Growth plan; they still count in the readiness figure above.</span>
                <Link to="/settings" className="btn-mini whitespace-nowrap self-start">SEE PLANS</Link>
              </div>
            ) : (
              <ul>{group.requirements.map(req => <RequirementRow key={req.key} req={req} />)}</ul>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
