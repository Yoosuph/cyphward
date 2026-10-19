import { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Pencil } from 'lucide-react';
import StatusChip, { type ChipLevel } from '../../components/StatusChip';
import { useToast } from '../../components/Toast';
import { useAuth } from '../../lib/auth';
import {
  listEvidenceFiles, listOrgMembers, recordAttestation,
  type EvidenceFileList, type OrgMember, type Questionnaire as QuestionnaireData, type QuestionnaireAnswer, type QuestionnaireQuestion,
} from '../../lib/api';
import EvidenceFiles from './EvidenceFiles';
import { FIELD_BOX, FIELD_LABEL, ReadOnlyNote, errorText, fmtDayZone } from './shared';

/**
 * "Answer questions": applicability first, then one register group at a time.
 * A customer answer is evidence labelled "You told us", never shown as observed by Cyphward.
 */

const MAX_EXPIRY_DAYS = 730; // the API's cap; the longest option sends 729 days to stay inside it
const EXPIRY_CHOICES = [
  { label: '12 months (default)', days: null },
  { label: '3 months', days: 90 },
  { label: '6 months', days: 180 },
  { label: '18 months', days: 545 },
  { label: '24 months (longest)', days: MAX_EXPIRY_DAYS - 1 },
] as const;
const LONG_DIGITS = /\d{7,}/;
const HTTPS_LINK = /^https:\/\/\S+$/;

const STATE_CHIP: Record<QuestionnaireQuestion['answer_state'], { level: ChipLevel; label: string }> = {
  unanswered: { level: 'idle', label: 'NOT ANSWERED' },
  answered: { level: 'ok', label: 'ANSWERED' },
  not_sure: { level: 'warn', label: 'NOT SURE' },
  expired: { level: 'warn', label: 'RENEWAL DUE' },
};

function valueLabel(q: QuestionnaireQuestion, a: QuestionnaireAnswer, zone: string): string {
  if (a.value === 'date') return fmtDayZone(`${a.date}T12:00:00Z`, 'UTC');
  const base = a.value === 'not_sure' ? 'Not sure' : a.value === 'not_applicable' ? 'Not applicable'
    : a.value === 'yes' ? 'Yes' : a.value === 'no' ? 'No' : (a.value || '').toUpperCase();
  const parts = [base];
  if (a.date && q.allows_date) parts.push(fmtDayZone(`${a.date}T12:00:00Z`, 'UTC'));
  if (a.text) parts.push(a.text);
  void zone;
  return parts.join(' · ');
}

/** "You told us … on … (owner …, renews …)", with "renewal due" once the answer has expired. */
export function ToldUs({ q, zone }: { q: QuestionnaireQuestion; zone: string }) {
  const a = q.current;
  if (!a) return null;
  return (
    <p className="text-xs text-ink leading-relaxed break-words" data-testid="told-us">
      You told us: <span className="mono">{valueLabel(q, a, zone)}</span> on {fmtDayZone(a.attested_at, zone)}
      {' '}(owner {a.owner_name || 'not set'}, {a.expired ? 'renewal due since' : 'renews'} {fmtDayZone(a.expires_at, zone)})
      {a.evidence_link && <> · <a href={a.evidence_link} target="_blank" rel="noopener noreferrer" className="text-accent underline break-all">evidence link</a></>}
      {a.notes && <span className="block text-soft mt-1">Notes: {a.notes}</span>}
    </p>
  );
}

function todayIn(zone: string): string {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function valueOptions(q: QuestionnaireQuestion): { value: string; label: string }[] {
  let opts: { value: string; label: string }[];
  if (q.type === 'date') opts = [{ value: 'date', label: 'I have the date' }];
  else if (q.type === 'choice') opts = q.options.map(o => ({ value: o, label: o.toUpperCase() }));
  else opts = [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }];
  if (q.allow_not_applicable) opts.push({ value: 'not_applicable', label: 'Not applicable' });
  opts.push({ value: 'not_sure', label: 'Not sure' });
  return opts;
}

function AnswerForm({ q, zone, members, onDone, onCancel }: {
  q: QuestionnaireQuestion; zone: string; members: OrgMember[]; onDone: () => void; onCancel: () => void;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const prior = q.current;
  const [value, setValue] = useState<string>(prior && !prior.expired ? prior.value || '' : '');
  const [date, setDate] = useState(prior?.date || '');
  const [text, setText] = useState(prior?.text || '');
  const [owner, setOwner] = useState(prior?.owner_user_id || user?.id || '');
  const [expiry, setExpiry] = useState<number | null>(null);
  const [link, setLink] = useState(prior?.evidence_link || '');
  const [notes, setNotes] = useState(prior?.notes || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const followsDate = q.expiry_days_from_date != null && value === 'date';
  const takesDate = value === 'date' || (q.allows_date && q.type !== 'date' && (value === 'yes' || value === 'no'));
  const idBase = `q-${q.key.replace(/[^a-z0-9]/gi, '-')}`;

  const validate = (): string | null => {
    if (!value) return 'Choose an answer.';
    if (value === 'date' && !date) return 'Give the date.';
    if (date && date > todayIn(zone)) return 'A date cannot be in the future.';
    if (q.allows_text && text && LONG_DIGITS.test(text)) return 'Do not enter personal ID numbers.';
    if (!owner) return 'Choose an owner.';
    if (link.trim() && (!HTTPS_LINK.test(link.trim()) || link.trim().length > 500)) return 'The evidence link must be an https:// address.';
    if (notes.length > 1000) return 'Notes must be at most 1000 characters.';
    return null;
  };

  const save = async () => {
    const problem = validate();
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError(null);
    const answer: { value: string; date?: string; text?: string } = { value };
    if (takesDate && date) answer.date = date;
    if (q.allows_text && text.trim() && value !== 'not_sure') answer.text = text.trim();
    const body = {
      question_key: q.key, answer, owner_user_id: owner,
      ...(!followsDate && expiry ? { expires_at: new Date(Date.now() + expiry * 86400000).toISOString() } : {}),
      ...(link.trim() ? { evidence_link: link.trim() } : {}),
      ...(notes.trim() ? { notes: notes.trim() } : {}),
    };
    try {
      await recordAttestation(body);
      toast('Answer saved.');
      onDone();
    } catch (e) {
      const status = (e as { status?: number }).status;
      setError(status === 409 ? 'This answer changed while you were editing. Reload the questions and try again.'
        : errorText(e, 'Could not save the answer.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="space-y-4 pt-3 border-t border-line" onSubmit={e => { e.preventDefault(); void save(); }} data-testid={`form-${q.key}`}>
      <fieldset className="min-w-0">
        <legend className={FIELD_LABEL}>Your answer</legend>
        <div className="flex flex-wrap gap-2">
          {valueOptions(q).map(o => (
            <label key={o.value} className={`flex items-center gap-2 px-3 py-2 rounded border text-xs mono cursor-pointer ${value === o.value ? 'border-ink text-ink' : 'border-line text-soft'}`}>
              <input type="radio" name={`${idBase}-value`} value={o.value} checked={value === o.value}
                     onChange={() => setValue(o.value)} className="accent-[var(--accent)]" />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>

      {takesDate && (
        <div>
          <label htmlFor={`${idBase}-date`} className={FIELD_LABEL}>{q.date_label || 'Date'}{value !== 'date' ? ' (optional)' : ''}</label>
          <input id={`${idBase}-date`} type="date" className={FIELD_BOX} value={date} max={todayIn(zone)} onChange={e => setDate(e.target.value)} />
        </div>
      )}
      {q.allows_text && value && value !== 'not_sure' && (
        <div>
          <label htmlFor={`${idBase}-text`} className={FIELD_LABEL}>{q.text_label || 'Details'} (optional)</label>
          <input id={`${idBase}-text`} type="text" className={FIELD_BOX} value={text} maxLength={q.text_max || 120} onChange={e => setText(e.target.value)} />
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        <div className="min-w-0">
          <label htmlFor={`${idBase}-owner`} className={FIELD_LABEL}>Owner</label>
          <select id={`${idBase}-owner`} className={FIELD_BOX} value={owner} onChange={e => setOwner(e.target.value)}>
            <option value="" disabled>Choose a member</option>
            {members.map(m => <option key={m.id} value={m.id}>{m.full_name || m.email}</option>)}
          </select>
        </div>
        <div className="min-w-0">
          {followsDate ? (
            <>
              <span className={FIELD_LABEL}>Renews</span>
              <p className="text-xs text-soft leading-relaxed" data-testid="expiry-follows-date">
                {q.expiry_days_from_date} days after the date you give. No expiry to set.
              </p>
            </>
          ) : (
            <>
              <label htmlFor={`${idBase}-expiry`} className={FIELD_LABEL}>Renew after</label>
              <select id={`${idBase}-expiry`} className={FIELD_BOX} value={expiry ?? ''}
                      onChange={e => setExpiry(e.target.value ? Number(e.target.value) : null)}>
                {EXPIRY_CHOICES.map(c => <option key={c.label} value={c.days ?? ''}>{c.label}</option>)}
              </select>
            </>
          )}
        </div>
      </div>

      <div>
        <label htmlFor={`${idBase}-link`} className={FIELD_LABEL}>Evidence link (https only, optional)</label>
        <input id={`${idBase}-link`} type="url" inputMode="url" className={FIELD_BOX} value={link} maxLength={500}
               placeholder="https://" onChange={e => setLink(e.target.value)} />
        <p className="text-[11px] text-soft mt-1.5">Cyphward does not open this link.</p>
      </div>
      <div>
        <label htmlFor={`${idBase}-notes`} className={FIELD_LABEL}>Notes (optional)</label>
        <textarea id={`${idBase}-notes`} className={FIELD_BOX} rows={2} maxLength={1000} value={notes} onChange={e => setNotes(e.target.value)} />
      </div>

      {error && <p role="alert" className="text-xs mono text-accent break-words" data-testid="form-error">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn btn-solid btn-mini" disabled={busy}>{busy ? 'SAVING…' : 'SAVE ANSWER'}</button>
        <button type="button" className="btn-mini" onClick={onCancel} disabled={busy}>CANCEL</button>
      </div>
    </form>
  );
}

function QuestionCard({ q, zone, canEdit, members, onSaved, fileInfo, onFilesChanged }: {
  q: QuestionnaireQuestion; zone: string; canEdit: boolean; members: OrgMember[]; onSaved: () => void;
  fileInfo: EvidenceFileList | null; onFilesChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const chip = STATE_CHIP[q.answer_state];
  return (
    <li className="px-4 sm:px-5 py-4 space-y-3 border-t border-line first:border-t-0" data-testid={`question-${q.key}`}>
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
        <p className="text-sm text-ink font-medium min-w-0 break-words">{q.prompt}</p>
        <span className="uppercase shrink-0"><StatusChip level={chip.level}>{chip.label}</StatusChip></span>
      </div>
      {q.evidences.length > 0 && <p className="text-[11px] mono text-soft break-words">Informs: {q.evidences.map(e => e.title).join(' · ')}</p>}
      <ToldUs q={q} zone={zone} />
      {fileInfo && <EvidenceFiles questionKey={q.key} info={fileInfo} zone={zone} canEdit={canEdit} onChanged={onFilesChanged} />}
      {canEdit && !editing && (
        <button type="button" className="btn-mini" onClick={() => setEditing(true)}>
          <Pencil size={12} /> {q.current ? 'UPDATE ANSWER' : 'ANSWER'}
        </button>
      )}
      {canEdit && editing && (
        <AnswerForm q={q} zone={zone} members={members} onCancel={() => setEditing(false)}
                    onDone={() => { setEditing(false); onSaved(); }} />
      )}
    </li>
  );
}

interface Step { key: string; title: string; questions: QuestionnaireQuestion[] }

function buildSteps(data: QuestionnaireData): Step[] {
  const shown = data.questions.filter(q => q.shown);
  const applicability = shown.filter(q => q.applicability.length > 0);
  const steps: Step[] = [];
  if (applicability.length) steps.push({ key: 'applicability', title: 'What applies to you', questions: applicability });
  const rest = shown.filter(q => q.applicability.length === 0);
  for (const q of rest) {
    let step = steps.find(s => s.key === q.group);
    if (!step) { step = { key: q.group, title: q.group_title, questions: [] }; steps.push(step); }
    step.questions.push(q);
  }
  return steps;
}

export default function QuestionnaireTab({ data, canEdit, onSaved }: {
  data: QuestionnaireData; canEdit: boolean; onSaved: () => void;
}) {
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [membersError, setMembersError] = useState<string | null>(null);
  const [stepKey, setStepKey] = useState('applicability');
  const [fileInfo, setFileInfo] = useState<EvidenceFileList | null>(null);
  const steps = useMemo(() => buildSteps(data), [data]);
  const zone = data.display_timezone;

  useEffect(() => {
    if (!canEdit) return;
    let live = true;
    listOrgMembers().then(m => { if (live) setMembers(m || []); })
      .catch(e => { if (live) setMembersError(errorText(e, 'Could not load the members list.')); });
    return () => { live = false; };
  }, [canEdit]);

  // Attached files load once for the whole page. A failure just hides the file area: the answers still work.
  const loadFiles = useMemo(() => () => {
    listEvidenceFiles().then(r => setFileInfo(r && Array.isArray(r.files) ? r : null)).catch(() => setFileInfo(null));
  }, []);
  useEffect(() => { loadFiles(); }, [loadFiles]);

  const index = Math.max(0, steps.findIndex(s => s.key === stepKey));
  const step = steps[index];
  if (!step) return <p className="text-sm text-soft">There are no questions to show.</p>;

  return (
    <div className="space-y-4" data-testid="questionnaire">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs mono text-soft">
          {data.answered} of {data.questions.filter(q => q.shown).length} questions answered · times shown in {zone}
        </p>
        {!canEdit && <ReadOnlyNote />}
      </div>

      <nav aria-label="Question groups" className="flex flex-wrap gap-2">
        {steps.map((s, i) => (
          <button key={s.key} type="button" onClick={() => setStepKey(s.key)} aria-current={i === index ? 'step' : undefined}
                  className={`btn-mini ${i === index ? '!border-ink !text-ink' : ''}`}>
            {i + 1}. {s.title}
          </button>
        ))}
      </nav>

      {membersError && <p role="alert" className="text-xs mono text-accent">{membersError}</p>}

      <section className="rounded-lg border border-line bg-raised" aria-label={step.title}>
        <div className="px-4 sm:px-5 py-3.5 border-b border-line">
          <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">{step.title}</h2>
          {step.key === 'applicability' && (
            <p className="text-xs text-soft mt-1.5 leading-relaxed">
              These answers decide which requirements apply to you. A requirement that does not apply is listed
              under Excluded, with the reason.
            </p>
          )}
        </div>
        <ul>{step.questions.map(q => (
          <QuestionCard key={q.key} q={q} zone={zone} canEdit={canEdit} members={members} onSaved={onSaved}
                        fileInfo={fileInfo} onFilesChanged={loadFiles} />
        ))}</ul>
      </section>

      <div className="flex justify-between gap-2">
        <button type="button" className="btn-mini" disabled={index === 0} onClick={() => setStepKey(steps[index - 1].key)}>
          <ChevronLeft size={12} /> BACK
        </button>
        <button type="button" className="btn-mini" disabled={index === steps.length - 1} onClick={() => setStepKey(steps[index + 1].key)}>
          NEXT <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}
