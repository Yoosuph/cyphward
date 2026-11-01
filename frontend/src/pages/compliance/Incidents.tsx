import { useCallback, useEffect, useRef, useState } from 'react';
import { pageCacheTicket, readPageCache, writePageCache } from '../../lib/pageCache';
import { CompliancePanelSkeleton } from '../../components/skeletons/RouteSkeleton';
import { Info, Pencil, Plus, ShieldAlert } from 'lucide-react';
import StatusChip, { type ChipLevel } from '../../components/StatusChip';
import Dialog, { useDialogClose } from '../../components/ui/Dialog';
import DateTimeField from '../../components/ui/DateTimeField';
import { EmptyPanel } from '../../components/ui/StatePanels';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { localToUtc, resolveZone, utcToLocalInput } from '../../lib/datetime';
import {
  createIncident, listIncidents, updateIncident,
  type Incident, type IncidentChanges, type IncidentList, type IncidentSeverity, type IncidentStatus,
} from '../../lib/api';
import { FIELD_BOX, FIELD_LABEL, GrowthGate, LoadError, ReadOnlyNote, errorText, fmtLocal, isGrowthGate } from './shared';

/**
 * Breach incident log. The 72-hour deadline comes from the API (UTC); this page only counts down to it.
 * It is a reminder date, not a legal conclusion: whether to notify depends on the organisation's circumstances.
 * Times are typed in the organisation's zone with native pickers and sent as UTC.
 */

const SEVERITY: IncidentSeverity[] = ['low', 'medium', 'high', 'critical'];
const STATUS: IncidentStatus[] = ['open', 'contained', 'closed'];
const SEV_LEVEL: Record<IncidentSeverity, ChipLevel> = { low: 'idle', medium: 'warn', high: 'bad', critical: 'bad' };
const TICK_MS = 15000;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function countdownText(deadlineAt: string, nowMs: number): string {
  const left = Math.max(0, new Date(deadlineAt).getTime() - nowMs);
  const minutes = Math.floor(left / 60000);
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m left`;
}

function DeadlineBadge({ i, nowMs }: { i: Incident; nowMs: number }) {
  if (i.commission_state === 'notified_late' || i.notified_late) {
    return <span className="tag uppercase text-warn" data-testid="badge-notified-late">Notified late</span>;
  }
  if (i.notified_commission_at) {
    return <span className="tag uppercase" data-testid="badge-notified">Commission notified</span>;
  }
  const past = i.overdue || new Date(i.deadline_at).getTime() <= nowMs;
  if (past) {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-[2px] bg-accent text-[#FCF9F0] mono text-[10px] tracking-[.12em] uppercase" data-testid="badge-overdue">
        Overdue
      </span>
    );
  }
  return <span className="mono text-xs text-ink" data-testid="countdown">{countdownText(i.deadline_at, nowMs)}</span>;
}

interface FormState {
  title: string; severity: IncidentSeverity; status: IncidentStatus;
  detected_at: string; became_aware_at: string; notified_commission_at: string; notified_subjects_at: string; notes: string;
}

function initialState(incident: Incident | null, zone: string): FormState {
  return {
    title: incident?.title || '', severity: incident?.severity || 'medium', status: incident?.status || 'open',
    detected_at: utcToLocalInput(incident?.detected_at, zone), became_aware_at: utcToLocalInput(incident?.became_aware_at, zone),
    notified_commission_at: utcToLocalInput(incident?.notified_commission_at, zone),
    notified_subjects_at: utcToLocalInput(incident?.notified_subjects_at, zone), notes: incident?.notes || '',
  };
}

function FormActions({ busy, editing }: { busy: boolean; editing: boolean }) {
  const close = useDialogClose();
  return (
    <>
      <button type="button" className="btn-mini touch-target" onClick={close} disabled={busy} data-testid="incident-cancel">Cancel</button>
      <button type="submit" form="incident-form" className="btn btn-solid btn-mini touch-target" disabled={busy} data-testid="incident-save">
        {busy ? 'Saving…' : editing ? 'Save changes' : 'Record incident'}
      </button>
    </>
  );
}

function IncidentForm({ zone, incident, onDone, onClose }: {
  zone: string; incident: Incident | null; onDone: () => void; onClose: () => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const editing = incident !== null;
  const initial = useRef(initialState(incident, zone)).current;
  const [f, setF] = useState<FormState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF(prev => ({ ...prev, [k]: v }));
  const dirty = (Object.keys(initial) as (keyof FormState)[]).some(k => f[k] !== initial[k]);

  const timeFields = ['detected_at', 'became_aware_at', 'notified_commission_at', 'notified_subjects_at'] as const;
  const save = async () => {
    setError(null);
    if (!editing && (!f.title.trim() || !f.detected_at || !f.became_aware_at)) {
      setError('Give it a short title, when it was detected and when you became aware of it.');
      return;
    }
    const utc: Partial<Record<(typeof timeFields)[number], string>> = {};
    for (const k of timeFields) {
      if (!f[k] || (editing && (k === 'detected_at' || k === 'became_aware_at'))) continue;
      const r = localToUtc(f[k], zone);
      if (!r.ok) { setError(r.message); return; }
      utc[k] = r.utc;
    }
    const awareUtc = utc.became_aware_at || incident?.became_aware_at;
    if (utc.notified_commission_at && awareUtc && new Date(utc.notified_commission_at) < new Date(awareUtc)) {
      setError('The Commission cannot have been told before you became aware of the incident. Check the times.');
      return;
    }
    const commissionChanged = f.notified_commission_at !== initial.notified_commission_at && !!f.notified_commission_at;
    if (commissionChanged) {
      const ok = await confirm({
        title: 'Record when the Commission was told?',
        body: 'This is the time you say you told the Commission about the incident.',
        irreversible: 'Once it is saved, the 72-hour countdown stops and the time becomes part of the incident record.',
        confirmLabel: 'Record notification time',
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      if (!editing) {
        await createIncident({
          title: f.title.trim(), severity: f.severity, status: f.status,
          detected_at: utc.detected_at as string, became_aware_at: utc.became_aware_at as string,
          ...(utc.notified_commission_at ? { notified_commission_at: utc.notified_commission_at } : {}),
          ...(utc.notified_subjects_at ? { notified_subjects_at: utc.notified_subjects_at } : {}),
          ...(f.notes.trim() ? { notes: f.notes.trim() } : {}),
        });
      } else {
        const changes: Record<string, unknown> = {};
        if (f.status !== initial.status) changes.status = f.status;
        if (f.severity !== initial.severity) changes.severity = f.severity;
        for (const k of ['notified_commission_at', 'notified_subjects_at'] as const) {
          if (f[k] !== initial[k]) changes[k] = f[k] ? utc[k] : null;
        }
        if (f.notes !== initial.notes) changes.notes = f.notes.trim() || null;
        if (Object.keys(changes).length === 0) { onClose(); return; }
        await updateIncident(incident.id, changes as IncidentChanges);
      }
      toast(editing ? 'Incident updated.' : 'Incident recorded.');
      onDone();
    } catch (e) {
      const message = errorText(e, 'We could not save the incident. Try again in a moment.');
      setError(message);
      toast('The incident was not saved.');
    } finally {
      setBusy(false);
    }
  };

  const dialogTitle = editing ? 'Update incident' : 'Record an incident';
  return (
    <Dialog open onClose={onClose} title={dialogTitle} dirty={dirty} maxWidth="max-w-2xl"
            footer={<FormActions busy={busy} editing={editing} />}>
      <form id="incident-form" className="space-y-4" data-testid="incident-form" noValidate
            onSubmit={e => { e.preventDefault(); void save(); }}>
        {editing ? (
          <div className="space-y-1 text-xs">
            <p className="text-sm text-ink break-words">{incident.title}</p>
            <p className="text-soft">Detected {fmtLocal(incident.local.detected_at)} and you became aware {fmtLocal(incident.local.became_aware_at)} ({zone}). These two times cannot be changed.</p>
          </div>
        ) : (
          <div>
            <label htmlFor="inc-title" className={FIELD_LABEL}>Short title</label>
            <input id="inc-title" className={FIELD_BOX} value={f.title} maxLength={200} onChange={e => set('title', e.target.value)} />
          </div>
        )}
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="min-w-0">
            <label htmlFor="inc-severity" className={FIELD_LABEL}>How serious is it?</label>
            <select id="inc-severity" className={FIELD_BOX} value={f.severity} onChange={e => set('severity', e.target.value as IncidentSeverity)}>
              {SEVERITY.map(s => <option key={s} value={s}>{cap(s)}</option>)}
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="inc-status" className={FIELD_LABEL}>Where is it now?</label>
            <select id="inc-status" className={FIELD_BOX} value={f.status} onChange={e => set('status', e.target.value as IncidentStatus)}>
              {STATUS.map(s => <option key={s} value={s}>{cap(s)}</option>)}
            </select>
          </div>
          {!editing && (
            <>
              <DateTimeField id="inc-detected" label="When it was detected" zone={zone} value={f.detected_at} onChange={v => set('detected_at', v)} />
              <DateTimeField id="inc-aware" label="When you became aware" zone={zone} value={f.became_aware_at} onChange={v => set('became_aware_at', v)}
                             hint="The 72 hours count from here" />
            </>
          )}
          <DateTimeField id="inc-commission" label="When the Commission was told" optional zone={zone} value={f.notified_commission_at}
                         onChange={v => set('notified_commission_at', v)} />
          <DateTimeField id="inc-subjects" label="When affected people were told" optional zone={zone} value={f.notified_subjects_at}
                         onChange={v => set('notified_subjects_at', v)} />
        </div>
        <div>
          <label htmlFor="inc-notes" className={FIELD_LABEL}>Notes (optional)</label>
          <textarea id="inc-notes" className={FIELD_BOX} rows={3} maxLength={4000} value={f.notes} onChange={e => set('notes', e.target.value)} />
          <p className="text-[11px] text-soft mt-1.5">Keep names and other personal details out of the notes where you can.</p>
        </div>
        {error && <p role="alert" className="text-xs text-accent break-words" data-testid="incident-error">{error}</p>}
      </form>
    </Dialog>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="mono text-[10px] tracking-[.16em] text-soft uppercase">{label}</dt>
      <dd className="text-sm text-ink mt-0.5 break-words">{children}</dd>
    </div>
  );
}

function IncidentDetails({ i, zone, nowMs, canEdit, onEdit, onClose }: {
  i: Incident; zone: string; nowMs: number; canEdit: boolean; onEdit: () => void; onClose: () => void;
}) {
  const none = 'Not recorded';
  return (
    <Dialog open onClose={onClose} title="Incident details" maxWidth="max-w-xl"
            footer={canEdit ? <button type="button" className="btn-mini touch-target" onClick={onEdit} data-testid="incident-details-edit"><Pencil size={12} /> Update this incident</button> : undefined}>
      <div className="space-y-4" data-testid="incident-details">
        <p className="text-sm text-ink font-medium break-words">{i.title}</p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="uppercase"><StatusChip level={SEV_LEVEL[i.severity]}>{i.severity}</StatusChip></span>
          <span className="tag uppercase">{i.status}</span>
          <DeadlineBadge i={i} nowMs={nowMs} />
        </div>
        <p className="text-xs text-soft">All times are in {zone}.</p>
        <dl className="grid sm:grid-cols-2 gap-4">
          <Detail label="Detected">{fmtLocal(i.local.detected_at)}</Detail>
          <Detail label="You became aware">{fmtLocal(i.local.became_aware_at)}</Detail>
          <Detail label="72-hour mark">{fmtLocal(i.local.deadline_at)}</Detail>
          <Detail label="Commission told">{i.local.notified_commission_at ? fmtLocal(i.local.notified_commission_at) : none}</Detail>
          <Detail label="Affected people told">{i.local.notified_subjects_at ? fmtLocal(i.local.notified_subjects_at) : none}</Detail>
        </dl>
        <Detail label="Notes"><span className="whitespace-pre-wrap">{i.notes || 'No notes.'}</span></Detail>
      </div>
    </Dialog>
  );
}

function IncidentRow({ i, nowMs, canEdit, onDetails, onEdit }: { i: Incident; nowMs: number; canEdit: boolean; onDetails: () => void; onEdit: () => void }) {
  return (
    <li className="px-4 sm:px-5 py-4 space-y-2.5 border-t border-line first:border-t-0" data-testid={`incident-${i.id}`}>
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
        <p className="text-sm text-ink font-medium min-w-0 break-words">{i.title}</p>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <span className="uppercase"><StatusChip level={SEV_LEVEL[i.severity]}>{i.severity}</StatusChip></span>
          <span className="tag uppercase">{i.status}</span>
          <DeadlineBadge i={i} nowMs={nowMs} />
        </div>
      </div>
      <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-1 text-xs text-soft">
        <div><dt className="inline">You became aware: </dt><dd className="inline text-ink">{fmtLocal(i.local.became_aware_at)}</dd></div>
        <div><dt className="inline">72-hour mark: </dt><dd className="inline text-ink">{fmtLocal(i.local.deadline_at)}</dd></div>
        <div><dt className="inline">Commission told: </dt><dd className="inline text-ink">{i.local.notified_commission_at ? fmtLocal(i.local.notified_commission_at) : 'not recorded'}</dd></div>
        <div><dt className="inline">Affected people told: </dt><dd className="inline text-ink">{i.local.notified_subjects_at ? fmtLocal(i.local.notified_subjects_at) : 'not recorded'}</dd></div>
      </dl>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-mini touch-target" onClick={onDetails} data-testid="incident-details-open">Details</button>
        {canEdit && <button type="button" className="btn-mini touch-target" onClick={onEdit} data-testid="incident-edit"><Pencil size={12} /> Edit</button>}
      </div>
    </li>
  );
}

type Open = { kind: 'form'; incident: Incident | null } | { kind: 'details'; incident: Incident } | null;

export default function IncidentsTab({ canEdit }: { canEdit: boolean }) {
  // Last-seen list paints at once on a revisit (lib/queryCache); load() refreshes it.
  const [data, setData] = useState<IncidentList | null>(() => readPageCache<IncidentList>('comply:incidents') ?? null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    setError(null);
    try {
      { const ticket = pageCacheTicket(); const fresh = await listIncidents(); writePageCache('comply:incidents', fresh, ticket); setData(fresh); }
      setGated(false);
    } catch (e) {
      if (isGrowthGate(e)) setGated(true);
      else setError(errorText(e, 'Something went wrong on our side. Try again in a moment.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), TICK_MS);
    return () => window.clearInterval(t);
  }, []);

  if (gated) return <GrowthGate what="The breach incident log" />;
  if (error && !data) return <LoadError title="We could not load your incidents" message={error} onRetry={() => void load()} />;
  if (!data) return <CompliancePanelSkeleton section="incidents" />;
  const zone = resolveZone(data.display_timezone);
  const live = (incident: Incident) => data.incidents.find(x => x.id === incident.id) || incident;

  return (
    <div className="space-y-5" data-testid="incidents">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-accent/30 bg-accent/5 text-xs text-ink leading-relaxed" data-testid="incident-disclaimer">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>{data.disclaimer}</span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-soft">All times are in {zone}. The {data.deadline_hours}-hour mark counts from when you became aware.</p>
        {canEdit ? (
          <button type="button" className="btn-mini touch-target" onClick={() => setOpen({ kind: 'form', incident: null })} data-testid="incident-new"><Plus size={12} /> Record an incident</button>
        ) : <ReadOnlyNote />}
      </div>

      {data.incidents.length === 0 ? (
        <EmptyPanel icon={<ShieldAlert size={26} />} title="No incidents recorded"
                    help="If something goes wrong with personal data, record it here. The 72-hour mark starts from when you became aware of it."
                    action={canEdit ? <button type="button" className="btn-mini touch-target" onClick={() => setOpen({ kind: 'form', incident: null })}><Plus size={12} /> Record an incident</button> : undefined} />
      ) : (
        <section className="rounded-lg border border-line bg-raised" aria-label="Incidents">
          <ul>{data.incidents.map(i => (
            <IncidentRow key={i.id} i={i} nowMs={nowMs} canEdit={canEdit}
                         onDetails={() => setOpen({ kind: 'details', incident: i })}
                         onEdit={() => setOpen({ kind: 'form', incident: i })} />
          ))}</ul>
        </section>
      )}

      <section className="rounded-lg border border-line bg-raised p-4 sm:p-5 space-y-3" aria-label="Checklist" data-testid="incident-checklist">
        <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">Checklist</h2>
        <ol className="space-y-2.5 list-decimal pl-5 text-sm">
          {data.checklist.map(c => (
            <li key={c.key}><span className="text-ink font-medium">{c.title}.</span> <span className="text-soft">{c.text}</span></li>
          ))}
        </ol>
      </section>

      {canEdit && open?.kind === 'form' && (
        <IncidentForm key={open.incident?.id || 'new'} zone={zone} incident={open.incident ? live(open.incident) : null}
                      onClose={() => setOpen(null)} onDone={() => { setOpen(null); void load(); }} />
      )}
      {open?.kind === 'details' && (
        <IncidentDetails i={live(open.incident)} zone={zone} nowMs={nowMs} canEdit={canEdit}
                         onClose={() => setOpen(null)} onEdit={() => setOpen({ kind: 'form', incident: live(open.incident) })} />
      )}
    </div>
  );
}
