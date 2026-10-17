import { useCallback, useEffect, useState } from 'react';
import { Info, Pencil, Plus } from 'lucide-react';
import StatusChip, { type ChipLevel } from '../../components/StatusChip';
import { useToast } from '../../components/Toast';
import {
  createIncident, listIncidents, updateIncident,
  type Incident, type IncidentChanges, type IncidentList, type IncidentSeverity, type IncidentStatus,
} from '../../lib/api';
import { FIELD_BOX, FIELD_LABEL, GrowthGate, LoadError, ReadOnlyNote, errorText, fmtLocal, isGrowthGate, naiveTime, toInputValue } from './shared';

/**
 * Breach incident log. The 72-hour deadline comes from the API (UTC); this page only counts down to it.
 * A reminder date, not a legal conclusion: whether to notify depends on the organisation's circumstances.
 */

const SEVERITY: IncidentSeverity[] = ['low', 'medium', 'high', 'critical'];
const STATUS: IncidentStatus[] = ['open', 'contained', 'closed'];
const SEV_LEVEL: Record<IncidentSeverity, ChipLevel> = { low: 'idle', medium: 'warn', high: 'bad', critical: 'bad' };
const TICK_MS = 15000;

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

function IncidentForm({ zone, incident, onDone, onCancel }: {
  zone: string; incident: Incident | null; onDone: () => void; onCancel: () => void;
}) {
  const toast = useToast();
  const initial: FormState = {
    title: incident?.title || '', severity: incident?.severity || 'medium', status: incident?.status || 'open',
    detected_at: toInputValue(incident?.local.detected_at), became_aware_at: toInputValue(incident?.local.became_aware_at),
    notified_commission_at: toInputValue(incident?.local.notified_commission_at),
    notified_subjects_at: toInputValue(incident?.local.notified_subjects_at), notes: incident?.notes || '',
  };
  const [f, setF] = useState<FormState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF(prev => ({ ...prev, [k]: v }));
  const editing = incident !== null;
  const zoneHint = <span className="block text-[11px] text-soft mt-1.5 normal-case tracking-normal">Time in {zone}</span>;

  const save = async () => {
    setError(null);
    if (!editing && (!f.title.trim() || !f.detected_at || !f.became_aware_at)) {
      setError('Give a title, when it was detected and when you became aware of it.');
      return;
    }
    setBusy(true);
    try {
      if (!editing) {
        await createIncident({
          title: f.title.trim(), severity: f.severity, status: f.status,
          detected_at: naiveTime(f.detected_at), became_aware_at: naiveTime(f.became_aware_at),
          ...(f.notified_commission_at ? { notified_commission_at: naiveTime(f.notified_commission_at) } : {}),
          ...(f.notified_subjects_at ? { notified_subjects_at: naiveTime(f.notified_subjects_at) } : {}),
          ...(f.notes.trim() ? { notes: f.notes.trim() } : {}),
        });
      } else {
        const changes: Record<string, unknown> = {};
        if (f.status !== initial.status) changes.status = f.status;
        if (f.severity !== initial.severity) changes.severity = f.severity;
        for (const k of ['notified_commission_at', 'notified_subjects_at'] as const) {
          if (f[k] !== initial[k]) changes[k] = f[k] ? naiveTime(f[k]) : null;
        }
        if (f.notes !== initial.notes) changes.notes = f.notes.trim() || null;
        if (Object.keys(changes).length === 0) { onCancel(); return; }
        await updateIncident(incident.id, changes as IncidentChanges);
      }
      toast(editing ? 'Incident updated.' : 'Incident recorded.');
      onDone();
    } catch (e) {
      setError(errorText(e, 'Could not save the incident.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="rounded-lg border border-line bg-raised p-4 sm:p-5 space-y-4" data-testid="incident-form"
          onSubmit={e => { e.preventDefault(); void save(); }}>
      <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">{editing ? 'Edit incident' : 'Record an incident'}</h2>
      {editing ? (
        <div className="space-y-1 text-xs">
          <p className="text-sm text-ink break-words">{incident.title}</p>
          <p className="text-soft mono">Detected {fmtLocal(incident.local.detected_at)} · aware {fmtLocal(incident.local.became_aware_at)} ({zone}). These cannot be changed.</p>
        </div>
      ) : (
        <div>
          <label htmlFor="inc-title" className={FIELD_LABEL}>Title</label>
          <input id="inc-title" className={FIELD_BOX} value={f.title} maxLength={200} onChange={e => set('title', e.target.value)} />
        </div>
      )}
      <div className="grid sm:grid-cols-2 gap-4">
        <div className="min-w-0">
          <label htmlFor="inc-severity" className={FIELD_LABEL}>Severity</label>
          <select id="inc-severity" className={FIELD_BOX} value={f.severity} onChange={e => set('severity', e.target.value as IncidentSeverity)}>
            {SEVERITY.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="min-w-0">
          <label htmlFor="inc-status" className={FIELD_LABEL}>Status</label>
          <select id="inc-status" className={FIELD_BOX} value={f.status} onChange={e => set('status', e.target.value as IncidentStatus)}>
            {STATUS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {!editing && (
          <>
            <div className="min-w-0">
              <label htmlFor="inc-detected" className={FIELD_LABEL}>Detected at</label>
              <input id="inc-detected" type="datetime-local" className={FIELD_BOX} value={f.detected_at} onChange={e => set('detected_at', e.target.value)} />
              {zoneHint}
            </div>
            <div className="min-w-0">
              <label htmlFor="inc-aware" className={FIELD_LABEL}>Became aware at</label>
              <input id="inc-aware" type="datetime-local" className={FIELD_BOX} value={f.became_aware_at} onChange={e => set('became_aware_at', e.target.value)} />
              {zoneHint}
            </div>
          </>
        )}
        <div className="min-w-0">
          <label htmlFor="inc-commission" className={FIELD_LABEL}>Commission notified at (optional)</label>
          <input id="inc-commission" type="datetime-local" className={FIELD_BOX} value={f.notified_commission_at} onChange={e => set('notified_commission_at', e.target.value)} />
          {zoneHint}
        </div>
        <div className="min-w-0">
          <label htmlFor="inc-subjects" className={FIELD_LABEL}>Affected people notified at (optional)</label>
          <input id="inc-subjects" type="datetime-local" className={FIELD_BOX} value={f.notified_subjects_at} onChange={e => set('notified_subjects_at', e.target.value)} />
          {zoneHint}
        </div>
      </div>
      <div>
        <label htmlFor="inc-notes" className={FIELD_LABEL}>Notes (optional)</label>
        <textarea id="inc-notes" className={FIELD_BOX} rows={3} maxLength={4000} value={f.notes} onChange={e => set('notes', e.target.value)} />
        <p className="text-[11px] text-soft mt-1.5">Keep personal details out of the notes where you can.</p>
      </div>
      {error && <p role="alert" className="text-xs mono text-accent break-words" data-testid="incident-error">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn btn-solid btn-mini" disabled={busy}>{busy ? 'SAVING…' : editing ? 'SAVE CHANGES' : 'RECORD INCIDENT'}</button>
        <button type="button" className="btn-mini" onClick={onCancel} disabled={busy}>CANCEL</button>
      </div>
    </form>
  );
}

function IncidentRow({ i, nowMs, canEdit, onEdit }: { i: Incident; nowMs: number; canEdit: boolean; onEdit: () => void }) {
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
      <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-1 text-xs mono text-soft">
        <div><dt className="inline">Detected: </dt><dd className="inline text-ink">{fmtLocal(i.local.detected_at)}</dd></div>
        <div><dt className="inline">Became aware: </dt><dd className="inline text-ink">{fmtLocal(i.local.became_aware_at)}</dd></div>
        <div><dt className="inline">72-hour mark: </dt><dd className="inline text-ink">{fmtLocal(i.local.deadline_at)}</dd></div>
        <div><dt className="inline">Commission notified: </dt><dd className="inline text-ink">{i.local.notified_commission_at ? fmtLocal(i.local.notified_commission_at) : 'not recorded'}</dd></div>
        <div><dt className="inline">Affected people notified: </dt><dd className="inline text-ink">{i.local.notified_subjects_at ? fmtLocal(i.local.notified_subjects_at) : 'not recorded'}</dd></div>
      </dl>
      {i.notes && <p className="text-xs text-soft break-words whitespace-pre-wrap">Notes: {i.notes}</p>}
      {canEdit && <button type="button" className="btn-mini" onClick={onEdit}><Pencil size={12} /> EDIT</button>}
    </li>
  );
}

export default function IncidentsTab({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<IncidentList | null>(null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<{ incident: Incident | null } | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await listIncidents());
      setGated(false);
    } catch (e) {
      if (isGrowthGate(e)) setGated(true);
      else setError(errorText(e, 'Could not load incidents.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), TICK_MS);
    return () => window.clearInterval(t);
  }, []);

  if (gated) return <GrowthGate what="The breach incident log" />;
  if (error && !data) return <LoadError message={error} onRetry={() => void load()} />;
  if (!data) return <p className="text-xs mono text-soft">LOADING INCIDENTS…</p>;
  const zone = data.display_timezone;

  return (
    <div className="space-y-5" data-testid="incidents">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-accent/30 bg-accent/5 text-xs text-ink leading-relaxed" data-testid="incident-disclaimer">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>{data.disclaimer}</span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs mono text-soft">All times shown in {zone}. The {data.deadline_hours}-hour mark counts from when you became aware.</p>
        {canEdit && !form && (
          <button type="button" className="btn-mini" onClick={() => setForm({ incident: null })}><Plus size={12} /> RECORD AN INCIDENT</button>
        )}
        {!canEdit && <ReadOnlyNote />}
      </div>

      {canEdit && form && (
        <IncidentForm key={form.incident?.id || 'new'} zone={zone} incident={form.incident}
                      onCancel={() => setForm(null)} onDone={() => { setForm(null); void load(); }} />
      )}

      <section className="rounded-lg border border-line bg-raised" aria-label="Incidents">
        {data.incidents.length === 0 ? (
          <p className="px-4 sm:px-5 py-5 text-sm text-soft">No incidents recorded.</p>
        ) : (
          <ul>{data.incidents.map(i => (
            <IncidentRow key={i.id} i={i} nowMs={nowMs} canEdit={canEdit} onEdit={() => setForm({ incident: i })} />
          ))}</ul>
        )}
      </section>

      <section className="rounded-lg border border-line bg-raised p-4 sm:p-5 space-y-3" aria-label="Checklist" data-testid="incident-checklist">
        <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">Checklist</h2>
        <ol className="space-y-2.5 list-decimal pl-5 text-sm">
          {data.checklist.map(c => (
            <li key={c.key}><span className="text-ink font-medium">{c.title}.</span> <span className="text-soft">{c.text}</span></li>
          ))}
        </ol>
      </section>
    </div>
  );
}
