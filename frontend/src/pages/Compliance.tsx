import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowUpRight, CheckCheck, ChevronDown, ClipboardList, FileCheck2, FolderOpen, Info, ListChecks, Lock, Search, ShieldCheck, Siren, Users, RefreshCw } from 'lucide-react';
import './compliance/compliance.css';
import { PageHead, Skeleton, SkeletonText } from '../components/ui';
import { ErrorPanel, LoadingPanel } from '../components/ui/StatePanels';
import { resolveZone } from '../lib/datetime';
import { useOrgZone } from '../lib/orgZone';
import StatusChip, { type ChipLevel } from '../components/StatusChip';
import { useToast } from '../components/Toast';
import { useAuth } from '../lib/auth';
import {
  createRemediationTask,
  getComplianceOverview,
  getQuestionnaire,
  getRemediationTasks,
  type ComplianceFindingRef,
  type ComplianceOverview,
  type ComplianceRequirement,
  type ComplianceStatus,
  type Questionnaire,
  type QuestionnaireQuestion,
} from '../lib/api';
import QuestionnaireTab, { ToldUs } from './compliance/Questionnaire';
import IncidentsTab from './compliance/Incidents';
import PacksTab from './compliance/Packs';
import DocumentsTab from './compliance/Documents';
import ReviewerAccessTab from './compliance/ReviewerAccess';
import { GrowthGate, LoadError, errorText, fmtDayZone, isGrowthGate } from './compliance/shared';

/**
 * NDPA / GAID readiness evidence. Shows what Cyphward has observed for each
 * requirement, labelled by source. It never states a legal conclusion:
 * missing evidence reads "Not assessed", never as met.
 */

const CHIP: Record<ComplianceStatus, ChipLevel> = { present: 'ok', gap: 'bad', not_assessed: 'warn', not_applicable: 'idle', awaiting_input: 'idle' };

const CARD = 'rounded-2xl border border-line bg-raised';
const TAB_ICONS = [ShieldCheck, ListChecks, Siren, FolderOpen, FileCheck2, Users];
const TAB_NOTES: Record<string, string> = { readiness: 'Review the evidence behind each requirement and decide what to work on next.', questions: 'Record what your team does, assign evidence owners and keep answers up to date.', incidents: 'Record events and follow the response work through to closure.', packs: 'Prepare dated evidence for management and practitioner reviews.', documents: 'Draft, review and approve your organisation’s policy documents.', reviewers: 'Give a practitioner scoped access to support your review.' };

function ComplianceLoading() {
  return <div className="compliance-page space-y-6 pb-12" data-testid="state-loading" role="status" aria-busy="true" aria-label="Loading compliance workspace">
    <PageHead title="Compliance readiness" note="Organise evidence, close gaps and prepare for review." />
    <p className="text-xs mono text-soft">Loading your compliance workspace…</p>
    <Skeleton height={68} rounded="lg" />
    <Skeleton height={58} rounded="lg" />
    <div className="compliance-overview-grid" aria-hidden="true">
      {[0, 1].map(key => <div key={key} className={`${CARD} p-6 space-y-5`}><Skeleton width="55%" height={15}/><Skeleton width="70%" height={35}/><SkeletonText lines={3}/><Skeleton height={68}/></div>)}
    </div>
    <Skeleton height={160} rounded="lg" />
  </div>;
}

/** What every tab panel receives. Add a field here when a new tab needs more from the page. */
interface TabContext {
  canEdit: boolean;
  isOwner: boolean;
  /** The organisation's display zone (default Africa/Lagos). */
  zone: string;
  readiness: ReactNode;
  questions: ReactNode;
}

/**
 * The tabs of this page, in order. To add a tab (for example evidence files or reviewer access), append one entry
 * here with a `render` that returns its panel; the tab bar, keyboard handling and ARIA wiring come for free.
 */
interface TabDef { key: string; label: string; ownerOnly?: boolean; render: (ctx: TabContext) => ReactNode }
const TABS: TabDef[] = [
  { key: 'readiness', label: 'Readiness', render: c => c.readiness },
  { key: 'questions', label: 'Answer questions', render: c => c.questions },
  { key: 'incidents', label: 'Incidents', render: c => <IncidentsTab canEdit={c.canEdit} /> },
  { key: 'packs', label: 'Packs', render: c => <PacksTab canEdit={c.canEdit} zone={c.zone} /> },
  { key: 'documents', label: 'Documents', render: c => <DocumentsTab canEdit={c.canEdit} zone={c.zone} /> },
  { key: 'reviewers', label: 'Reviewer access', ownerOnly: true, render: c => <ReviewerAccessTab zone={c.zone} /> },
];

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
      toast('Task created. You will find it under Remediation.');
    } catch {
      setState('idle');
      toast('The task was not created. You can add it from the Remediation page.');
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

function RequirementRow({ req, zone, told }: { req: ComplianceRequirement; zone: string; told: QuestionnaireQuestion[] }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const fmtDay = (value?: string | null) => fmtDayZone(value, zone);
  const renewalDue = told.some(q => q.current?.expired);
  return (
    <li data-requirement-row className="border-t border-line first:border-t-0">
      <button type="button" id={`${detailId}-trigger`} onClick={() => setOpen(o => !o)} aria-expanded={open} aria-controls={open ? detailId : undefined}
              className="w-full text-left px-4 sm:px-5 py-3.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 hover:bg-inset/60 transition-colors">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-ink font-medium flex items-start justify-between gap-3">{req.title}<ChevronDown size={15} aria-hidden="true" className={`sm:hidden shrink-0 mt-0.5 text-soft transition-transform ${open ? 'rotate-180' : ''}`} /></p>
          <p className={`text-[11px] mono mt-0.5 ${req.clause_verified || req.clause_review?.verified ? 'text-soft' : 'text-warn'}`}>{req.clause_label}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end shrink-0">
          <Chip status={req.status} label={req.status_label} />
          {renewalDue && <span className="tag uppercase text-warn" data-testid="renewal-due">Renewal due</span>}
          <SourceTag label={req.source_label} />
          <ChevronDown size={14} className={`hidden sm:block text-soft transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {open && (
        <div id={detailId} role="region" aria-labelledby={`${detailId}-trigger`} className="px-4 sm:px-5 pb-5 space-y-4 text-sm content-fade-in">
          <p className="text-soft leading-relaxed">{req.summary}</p>
          <p className="text-xs mono text-ink">{req.reason_text}</p>
          {(req.practitioner_review || req.clause_review) && (
            <div className="p-3 rounded border border-line bg-inset/50 space-y-1.5" data-testid="practitioner-note">
              <p className="mono text-[10px] tracking-[.16em] text-soft">PRACTITIONER NOTE · DOES NOT CHANGE THE STATUS</p>
              {req.practitioner_review && (
                <p className="text-xs text-ink break-words">
                  {req.practitioner_review.label}: {req.practitioner_review.outcome_label}.
                  {req.practitioner_review.comment && <> “{req.practitioner_review.comment}”</>}
                </p>
              )}
              {req.clause_review && (
                <p className="text-xs text-ink break-words">
                  Clause reference: {req.clause_review.label}.
                  {req.clause_review.note && <> “{req.clause_review.note}”</>}
                </p>
              )}
            </div>
          )}
          {req.sources && req.sources.length > 1 && (
            <p className="text-xs text-soft" data-testid="other-sources">
              The status above comes from {req.sources[0].source_label.toLowerCase()} evidence. Also on this requirement:{' '}
              {req.sources.slice(1).map(s => `${s.source_label}: ${s.status_label}`).join('; ')}.
            </p>
          )}
          {told.some(q => q.current) && (
            <div className="p-3 rounded border border-line bg-inset/50 space-y-2">
              <p className="mono text-[10px] tracking-[.16em] text-soft">YOUR ANSWER · CUSTOMER ATTESTED</p>
              {told.filter(q => q.current).map(q => <ToldUs key={q.key} q={q} zone={zone} />)}
            </div>
          )}

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
  const { organization } = useAuth();
  const canEdit = ['owner', 'admin'].includes(organization?.membership_role || 'member');
  const isOwner = organization?.membership_role === 'owner';
  const tabs = TABS.filter(t => !t.ownerOnly || isOwner);
  const toast = useToast();
  const orgZone = useOrgZone();
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get('section');
  const tab = tabs.some(t => t.key === requestedTab) ? requestedTab! : 'readiness';
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [groupFilter, setGroupFilter] = useState('all');
  const requirementsRef = useRef<HTMLDivElement>(null);
  const selectTab = (key: string) => {
    setParams(previous => { const next = new URLSearchParams(previous); if (key === 'readiness') next.delete('section'); else next.set('section', key); return next; });
    requestAnimationFrame(() => tabRefs.current[key]?.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
  };
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [data, setData] = useState<ComplianceOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [qn, setQn] = useState<Questionnaire | null>(null);
  const [qnGated, setQnGated] = useState(false);
  const [qnError, setQnError] = useState<string | null>(null);

  const loadQuestionnaire = useCallback(async () => {
    setQnError(null);
    try {
      setQn(await getQuestionnaire());
      setQnGated(false);
    } catch (e) {
      if (isGrowthGate(e)) setQnGated(true);
      else setQnError(errorText(e, 'Something went wrong on our side. Try again in a moment.'));
    }
  }, []);

  const load = useCallback(async (manual = false) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getComplianceOverview());
    } catch (e) {
      const message = errorText(e, 'Something went wrong on our side. Try again in a moment.');
      setError(message);
      if (manual) toast('The page was not refreshed.');
    } finally {
      setLoading(false);
    }
    void loadQuestionnaire();
  }, [loadQuestionnaire, toast]);

  useEffect(() => { void load(); }, [load]);

  if (loading && !data) return <ComplianceLoading />;
  if (error && !data) {
    return (
      <div className="max-w-7xl mx-auto pb-16 content-fade-in">
        <ErrorPanel title="We could not load your compliance readiness" message={error} onRetry={() => void load()} retrying={loading} />
      </div>
    );
  }
  if (!data) return null;
  const r = data.readiness;
  const total = data.groups.reduce((n, g) => n + g.requirement_count, 0);
  const zone = qn?.display_timezone ? resolveZone(qn.display_timezone) : orgZone;
  const answersFor = (key: string) => (qn?.questions || []).filter(q => q.evidences.some(e => e.key === key));
  const excluded = data.groups.flatMap(g => g.requirements.filter(q => q.status === 'not_applicable'));
  const filtering = Boolean(search.trim()) || statusFilter !== 'all' || groupFilter !== 'all';
  const clearFilters = () => { setSearch(''); setStatusFilter('all'); setGroupFilter('all'); };
  const visibleGroups = data.groups.filter(g => groupFilter === 'all' || g.key === groupFilter).map(group => ({
    ...group,
    requirements: group.requirements.filter(req => req.status !== 'not_applicable'
      && (statusFilter === 'all' || req.status === statusFilter)
      && (!search.trim() || `${req.title} ${req.summary} ${req.clause_label} ${req.source_label || ''}`.toLowerCase().includes(search.trim().toLowerCase()))),
  })).filter(group => group.requirements.length > 0 || (!filtering && groupFilter === 'all') || (group.locked && !search.trim() && statusFilter === 'all'));
  const visibleCount = visibleGroups.reduce((n, group) => n + group.requirements.length, 0);
  const coverage = r.applicable > 0 ? Math.min(100, Math.max(0, Math.round(r.with_evidence / r.applicable * 100))) : 0;
  const renewals = (qn?.questions || []).filter(q => q.answer_state === 'expired').length;
  const focusStatus = (status: string) => {
    setSearch(''); setGroupFilter('all'); setStatusFilter(status);
    requestAnimationFrame(() => requirementsRef.current?.scrollIntoView({ block: 'start' }));
  };

  const questions = qnGated ? <GrowthGate what="The questionnaire" />
    : qnError && !qn ? <LoadError title="We could not load the questions" message={qnError} onRetry={() => void loadQuestionnaire()} />
    : !qn ? <LoadingPanel label="questions" />
    : <>{qnError && <LoadError title="Your questions were not refreshed" message={qnError} onRetry={() => void loadQuestionnaire()} />}<QuestionnaireTab data={qn} canEdit={canEdit} onSaved={() => void load()} /></>;

  const readiness = (
    <>
      <div className="compliance-overview-grid">
        <section className="compliance-coverage" aria-label="Evidence coverage">
          <div className="flex items-center justify-between gap-3"><span className="compliance-eyebrow">Your evidence at a glance</span><ShieldCheck size={19} className="text-accent" /></div>
          <p className="text-base text-ink mt-4 leading-snug" data-testid="readiness-line">
            <span className="text-4xl font-semibold tracking-tight">{r.with_evidence}</span> of {r.applicable} have evidence
            <span className="block text-xs text-soft mt-2"> · {r.awaiting_input} awaiting input or upcoming checks</span>
          </p>
          <div className="compliance-coverage-track" role="progressbar" aria-label="Requirements with recorded evidence" aria-valuenow={r.with_evidence} aria-valuemin={0} aria-valuemax={Math.max(r.applicable, r.with_evidence, 1)}><span style={{ width: `${coverage}%` }} /></div>
          <p className="text-[11px] text-soft">Evidence coverage includes recorded gaps. It is not a legal verdict.</p>
          <div className="compliance-status-grid">
            {([
              ['present', r.present, 'PRESENT', 'ok'], ['gap', r.gap, 'GAPS', 'bad'],
              ['not_assessed', r.not_assessed, 'NOT ASSESSED', 'warn'], ['awaiting_input', r.awaiting_input, 'AWAITING INPUT', 'idle'],
            ] as const).map(([status, count, label, level]) => <button key={status} type="button" aria-label={`Filter requirements: ${label.toLowerCase()}`} aria-pressed={statusFilter === status}
              onClick={() => focusStatus(statusFilter === status ? 'all' : status)}><StatusChip level={level}>{count} {label}</StatusChip><ArrowUpRight size={12} aria-hidden="true" /></button>)}
          </div>
        </section>
        <section className={`p-5 sm:p-6 ${CARD}`} aria-label="Next steps">
          <p className="compliance-eyebrow">Keep your review moving</p>
          <h2 className="text-lg font-semibold mt-2 mb-4">A clear next step</h2>
          <div className="compliance-next-actions">
            {data.domains.length === 0 && <Link to="/domains" className="inline-flex items-center gap-2 text-sm text-accent min-h-[44px]">Verify a domain to start collecting evidence <ArrowUpRight size={15}/></Link>}
            <button type="button" onClick={() => focusStatus('gap')}>
              <span className="compliance-action-icon"><CheckCheck size={17}/></span><span><strong>Review the gaps</strong><small>{r.gap} {r.gap === 1 ? 'requirement' : 'requirements'} with recorded gaps</small></span><ArrowUpRight size={15}/>
            </button>
            <button type="button" onClick={() => selectTab('questions')}><span className="compliance-action-icon"><ListChecks size={17}/></span><span><strong>{canEdit ? 'Complete your evidence' : 'Review your evidence'}</strong><small>{renewals > 0 ? `${renewals} ${renewals === 1 ? 'answer needs' : 'answers need'} renewal` : 'Answer questions and review renewals'}</small></span><ArrowUpRight size={15}/></button>
            <button type="button" onClick={() => selectTab('packs')}><span className="compliance-action-icon"><FolderOpen size={17}/></span><span><strong>Prepare a review pack</strong><small>Keep a dated snapshot of your evidence</small></span><ArrowUpRight size={15}/></button>
          </div>
        </section>
      </div>
      <details className={`p-4 sm:p-5 ${CARD} text-sm`}>
        <summary className="cursor-pointer font-medium flex items-center gap-2"><Info size={15} className="text-accent"/> Understand your evidence <ChevronDown size={14} className="ml-auto text-soft"/></summary>
        <div className="space-y-3 mt-4">
          <p className="text-soft leading-relaxed">{data.note}</p>
          <p className="text-soft leading-relaxed">
            Evidence present means every check finished and nothing linked to it is open. A gap means an open finding is
            linked to it. Not assessed means a check could have run but did not finish. Awaiting input means Cyphward has
            no source for it yet. Clause references marked “pending review” have not been checked against the official texts yet
            ({data.register.references_pending_review} of {total} in register {data.register.version}).
          </p>
          {data.domains.length === 0 && (
            <p className="text-xs text-ink">You have no verified domain yet. <Link to="/domains" className="text-accent underline">Verify a domain</Link> to start collecting evidence.</p>
          )}
        </div>
      </details>

      <div className="space-y-5 scroll-mt-5" ref={requirementsRef}>
        <div className="compliance-register-toolbar">
          <div><p className="compliance-eyebrow">Requirement register</p><h2 className="text-lg font-semibold mt-1">Find the evidence you need</h2></div>
          <label className="compliance-search"><Search size={15} aria-hidden="true"/><input aria-label="Search requirements" placeholder="Search requirements…" value={search} onChange={e => setSearch(e.target.value)} /></label>
          <div className="compliance-filter-row">
            <select aria-label="Filter by evidence status" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="all">All evidence statuses</option><option value="gap">Gaps</option><option value="not_assessed">Not assessed</option><option value="awaiting_input">Awaiting input</option><option value="present">Evidence present</option></select>
            <select aria-label="Filter by requirement group" value={groupFilter} onChange={e => setGroupFilter(e.target.value)}><option value="all">All requirement groups</option>{data.groups.map(g => <option key={g.key} value={g.key}>{g.title}</option>)}</select>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-soft"><span role="status">{visibleCount} visible requirements{filtering ? ' matching your filters' : ''}</span>{filtering && <button type="button" data-testid="clear-requirement-filters" onClick={clearFilters} className="text-accent min-h-[44px] px-2">Clear filters</button>}</div>
        </div>
        {!visibleGroups.length && <div data-testid="requirements-empty" className={`${CARD} p-8 text-center`}><Search size={22} className="mx-auto text-soft mb-3"/><h3 className="font-medium">No requirements match</h3><p className="text-sm text-soft mt-2">Try another search or clear your filters to see the register.</p></div>}
        {visibleGroups.map(group => (
          <section key={group.key} className={CARD} aria-label={group.title} data-requirement-group>
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
                <span>{group.requirement_count} requirements. The detail is part of the Growth plan. They still count in the readiness figure above.</span>
                <Link to="/settings" className="btn-mini whitespace-nowrap self-start">SEE PLANS</Link>
              </div>
            ) : (
              <ul>{!group.requirements.length && <li className="p-5 text-xs text-soft">No applicable requirements in this group. See the exclusions below.</li>}{group.requirements.filter(req => req.status !== 'not_applicable').map(req => (
                <RequirementRow key={req.key} req={req} zone={zone} told={answersFor(req.key)} />
              ))}</ul>
            )}
          </section>
        ))}

        {excluded.length > 0 && (
          <section className={CARD} aria-label="Excluded" data-testid="excluded-section">
            <div className="px-4 sm:px-5 py-3.5 border-b border-line">
              <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">Excluded · does not apply to you</h2>
              <p className="text-xs text-soft mt-1.5">These left the count above because of your answers. If you change an answer, they come back.</p>
            </div>
            <ul>{excluded.map(req => (
              <li key={req.key} className="px-4 sm:px-5 py-3.5 border-t border-line first:border-t-0 space-y-1" data-testid={`excluded-${req.key}`}>
                <p className="text-sm text-ink font-medium break-words">{req.title}</p>
                <p className="text-xs text-soft break-words">{req.reason_text}</p>
              </li>
            ))}</ul>
          </section>
        )}
      </div>
    </>
  );

  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = tabs.map(t => t.key);
    // URL navigation may still be committing when a second key arrives.
    // Move from the focused tab so rapid arrow presses never repeat a step.
    const focused = (e.target as HTMLElement).closest('[role="tab"]')?.id.replace('tab-', '');
    const at = keys.indexOf(focused || tab);
    const next = e.key === 'ArrowRight' ? (at + 1) % keys.length : e.key === 'ArrowLeft' ? (at - 1 + keys.length) % keys.length
      : e.key === 'Home' ? 0 : e.key === 'End' ? keys.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    selectTab(keys[next]);
    tabRefs.current[keys[next]]?.focus();
  };

  return (
    <div className="compliance-page space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      <PageHead
        title="Compliance readiness"
        note={`${data.register.title}. Organise evidence, close gaps and prepare for review.`}
        actions={
          <>
          {!canEdit && <span className="compliance-access-label"><Lock size={12} aria-hidden="true"/> View only</span>}
          <button type="button" onClick={() => void load(true)} aria-label="Refresh" title="Refresh" disabled={loading}
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink transition-colors min-h-[44px] btn-tactile">
            <RefreshCw size={14} className={loading ? 'animate-spin motion-reduce:animate-none' : ''} /> <span>Refresh</span>
          </button>
          </>
        }
      />

      {error && <ErrorPanel title="Your latest refresh did not finish" message={error} onRetry={() => void load(true)} retrying={loading} />}

      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-accent/30 bg-accent/5 text-xs text-ink leading-relaxed" data-testid="compliance-disclaimer">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>{data.disclaimer}</span>
      </div>

      <div role="tablist" aria-label="Compliance sections" className="compliance-tabs" onKeyDown={onTabKey}>
        {tabs.map(t => { const Icon = TAB_ICONS[TABS.indexOf(t)]; return (
          <button key={t.key} type="button" role="tab" id={`tab-${t.key}`} aria-label={t.label} aria-selected={tab === t.key}
                  aria-describedby={t.key === 'questions' && renewals > 0 ? 'compliance-renewal-count' : undefined}
                  aria-controls={tab === t.key ? `panel-${t.key}` : undefined} tabIndex={tab === t.key ? 0 : -1}
                  ref={el => { tabRefs.current[t.key] = el; }}
                  onClick={() => selectTab(t.key)}
                  className={`compliance-tab ${tab === t.key ? 'compliance-tab-active' : ''}`}>
            <Icon size={15} aria-hidden="true"/><span>{t.label}</span>{t.key === 'questions' && renewals > 0 && <span id="compliance-renewal-count" className="compliance-tab-count"><span aria-hidden="true">{renewals}</span><span className="sr-only">{renewals} {renewals === 1 ? 'answer needs' : 'answers need'} renewal</span></span>}
          </button>
        ); })}
      </div>

      {tabs.filter(t => t.key === tab).map(t => (
        <div key={t.key} role="tabpanel" id={`panel-${t.key}`} aria-labelledby={`tab-${t.key}`} className="compliance-tab-panel space-y-6">
          <div className="compliance-section-heading"><div><p className="compliance-eyebrow">Compliance workspace</p><h2>{t.label === 'Packs' ? 'Evidence packs' : t.label}</h2></div><p>{TAB_NOTES[t.key]}</p></div>
          {t.render({ canEdit, isOwner, zone, readiness, questions })}
        </div>
      ))}
    </div>
  );
}
