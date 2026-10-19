import { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Pencil } from 'lucide-react';
import StatusChip, { type ChipLevel } from '../../components/StatusChip';
import DateTimeField from '../../components/ui/DateTimeField';
import { useToast } from '../../components/Toast';
import { addDays, endOfDayUtc, resolveZone, todayIn } from '../../lib/datetime';
import { useAuth } from '../../lib/auth';
import {
  listOrgMembers, recordAttestation,
  type OrgMember, type Questionnaire as QuestionnaireData, type QuestionnaireAnswer, type QuestionnaireQuestion,
} from '../../lib/api';
import { FIELD_BOX, FIELD_LABEL, ReadOnlyNote, errorText, fmtDayZone } from './shared';

/**
 * "Answer questions": applicability first, then one register group at a time.
 * A customer answer is evidence labelled "You told us", never shown as observed by Cyphward.
 */

const MAX_EXPIRY_DAYS = 730; // the API's cap; the longest option sends 729 days to stay inside it
const EXPIRY_CHOICES = [
  { label: '12 months (usual)', days: null },
  { label: '3 months', days: 90 },
  { label: '6 months', days: 180 },
  { label: '18 months', days: 545 },
  { label: '24 months (longest)', days: MAX_EXPIRY_DAYS - 1 },
] as const;
const CUSTOM_EXPIRY = 'custom';
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

function valueOptions(q: QuestionnaireQuestion): { value: string; label: string }[] {
  let opts: { value: string; label: string }[];
  if (q.type === 'date') opts = [{ value: 'date', label: 'I know the date' }];
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
  const [expiry, setExpiry] = useState<number | typeof CUSTOM_EXPIRY | null>(null);
  const [expiryDate, setExpiryDate] = useState('');
  const [link, setLink] = useState(prior?.evidence_link || '');
  const [notes, setNotes] = useState(prior?.notes || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const followsDate = q.expiry_days_from_date != null && value === 'date';
  const takesDate = value === 'date' || (q.allows_date && q.type !== 'date' && (value === 'yes' || value === 'no'));
  const idBase = `q-${q.key.replace(/[^a-z0-9]/gi, '-')}`;

  const today = todayIn(zone);
  const validate = (): string | null => {
    if (!value) return 'Choose an answer.';
    if (value === 'date' && !date) return 'Choose the date.';
    if (date && date > today) return 'The date cannot be in the future.';
    if (q.allows_text && text && LONG_DIGITS.test(text)) return 'Do not enter personal ID numbers.';
    if (!owner) return 'Choose who owns this answer.';
    if (!followsDate && expiry === CUSTOM_EXPIRY) {
      if (!expiryDate) return 'Choose the date to ask you again.';
      if (expiryDate < addDays(today, 1) || expiryDate > addDays(today, MAX_EXPIRY_DAYS - 1)) return 'Choose a date between tomorrow and 24 months from now.';
    }
    if (link.trim() && (!HTTPS_LINK.test(link.trim()) || link.trim().length > 500)) return 'The evidence link must be an https:// address.';
    if (notes.length > 1000) return 'Notes can be up to 1000 characters.';
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
    let expiresAt: string | undefined;
    if (!followsDate && expiry === CUSTOM_EXPIRY) {
      const end = endOfDayUtc(expiryDate, zone);
      if (!end.ok) { setError(end.message); setBusy(false); return; }
      // Stay inside the API's cap even where a clock change makes the last day a little longer.
      expiresAt = new Date(Math.min(Date.parse(end.utc), Date.now() + MAX_EXPIRY_DAYS * 86400000 - 60000)).toISOString();
    } else if (!followsDate && typeof expiry === 'number') {
      expiresAt = new Date(Date.now() + expiry * 86400000).toISOString();
    }
    const body = {
      question_key: q.key, answer, owner_user_id: owner,
      ...(expiresAt ? { expires_at: expiresAt } : {}),
      ...(link.trim() ? { evidence_link: link.trim() } : {}),
      ...(notes.trim() ? { notes: notes.trim() } : {}),
    };
    try {
      await recordAttestation(body);
      toast('Answer saved.');
      onDone();
    } catch (e) {
      const status = (e as { status?: number }).status;
      setError(status === 409 ? 'Someone else changed this answer while you were editing. Reload the questions and try again.'
        : errorText(e, 'We could not save the answer. Try again in a moment.'));
      toast('The answer was not saved.');
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
            <label key={o.value} className={`flex items-center gap-2 px-3 py-2 min-h-[44px] rounded border text-xs mono cursor-pointer ${value === o.value ? 'border-ink text-ink' : 'border-line text-soft'}`}>
              <input type="radio" name={`${idBase}-value`} value={o.value} checked={value === o.value}
                     onChange={() => setValue(o.value)} className="accent-[var(--accent)]" />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>

      {takesDate && (
        <DateTimeField mode="date" id={`${idBase}-date`} label={q.date_label || 'Date'} optional={value !== 'date'} zone={zone}
                       value={date} max={today} onChange={setDate} />
      )}
      {q.allows_text && value && value !== 'not_sure' && (
        <div>
          <label htmlFor={`${idBase}-text`} className={FIELD_LABEL}>{q.text_label || 'Details'} (optional)</label>
          <input id={`${idBase}-text`} type="text" className={FIELD_BOX} value={text} maxLength={q.text_max || 120} onChange={e => setText(e.target.value)} />
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        <div className="min-w-0">
          <label htmlFor={`${idBase}-owner`} className={FIELD_LABEL}>Who owns this answer?</label>
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
                {q.expiry_days_from_date} days after the date you give. You do not need to set a renewal date.
              </p>
            </>
          ) : (
            <>
              <label htmlFor={`${idBase}-expiry`} className={FIELD_LABEL}>Ask me to confirm again after</label>
              <select id={`${idBase}-expiry`} className={FIELD_BOX} value={expiry ?? ''}
                      onChange={e => setExpiry(e.target.value === CUSTOM_EXPIRY ? CUSTOM_EXPIRY : e.target.value ? Number(e.target.value) : null)}>
                {EXPIRY_CHOICES.map(c => <option key={c.label} value={c.days ?? ''}>{c.label}</option>)}
                <option value={CUSTOM_EXPIRY}>A date I choose</option>
              </select>
            </>
          )}
        </div>
      </div>

      {!followsDate && expiry === CUSTOM_EXPIRY && (
        <DateTimeField mode="date" id={`${idBase}-expiry-date`} label="Ask me again on" zone={zone} value={expiryDate}
                       min={addDays(today, 1)} max={addDays(today, MAX_EXPIRY_DAYS - 1)} onChange={setExpiryDate}
                       hint="Up to 24 months from today" />
      )}

      <div>
        <label htmlFor={`${idBase}-link`} className={FIELD_LABEL}>Link to proof (optional)</label>
        <input id={`${idBase}-link`} type="url" inputMode="url" className={FIELD_BOX} value={link} maxLength={500}
               placeholder="https://" onChange={e => setLink(e.target.value)} />
        <p className="text-[11px] text-soft mt-1.5">The link must start with https://. Cyphward does not open it.</p>
      </div>
      <div>
        <label htmlFor={`${idBase}-notes`} className={FIELD_LABEL}>Notes (optional)</label>
        <textarea id={`${idBase}-notes`} className={FIELD_BOX} rows={2} maxLength={1000} value={notes} onChange={e => setNotes(e.target.value)} />
      </div>

      {error && <p role="alert" className="text-xs text-accent break-words" data-testid="form-error">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn btn-solid btn-mini touch-target" disabled={busy}>{busy ? 'Saving…' : 'Save answer'}</button>
        <button type="button" className="btn-mini touch-target" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </form>
  );
}

function QuestionCard({ q, zone, canEdit, members, onSaved }: {
  q: QuestionnaireQuestion; zone: string; canEdit: boolean; members: OrgMember[]; onSaved: () => void;
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
      {canEdit && !editing && (
        <button type="button" className="btn-mini touch-target" onClick={() => setEditing(true)}>
          <Pencil size={12} /> {q.current ? 'Update answer' : 'Answer'}
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
  const steps = useMemo(() => buildSteps(data), [data]);
  const zone = resolveZone(data.display_timezone);

  useEffect(() => {
    if (!canEdit) return;
    let live = true;
    listOrgMembers().then(m => { if (live) setMembers(m || []); })
      .catch(e => { if (live) setMembersError(errorText(e, 'We could not load your team members, so the owner list is empty. Reload the page to try again.')); });
    return () => { live = false; };
  }, [canEdit]);

  const index = Math.max(0, steps.findIndex(s => s.key === stepKey));
  const step = steps[index];
  if (!step) return <p className="text-sm text-soft">There are no questions to show yet.</p>;

  return (
    <div className="space-y-4" data-testid="questionnaire">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-soft">
          {data.answered} of {data.questions.filter(q => q.shown).length} questions answered · dates are in {zone}
        </p>
        {!canEdit && <ReadOnlyNote />}
      </div>

      <nav aria-label="Question groups" className="flex flex-wrap gap-2">
        {steps.map((s, i) => (
          <button key={s.key} type="button" onClick={() => setStepKey(s.key)} aria-current={i === index ? 'step' : undefined}
                  className={`btn-mini touch-target ${i === index ? '!border-ink !text-ink' : ''}`}>
            {i + 1}. {s.title}
          </button>
        ))}
      </nav>

      {membersError && <p role="alert" className="text-xs text-accent">{membersError}</p>}

      <section className="rounded-lg border border-line bg-raised" aria-label={step.title}>
        <div className="px-4 sm:px-5 py-3.5 border-b border-line">
          <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">{step.title}</h2>
          {step.key === 'applicability' && (
            <p className="text-xs text-soft mt-1.5 leading-relaxed">
              These answers decide which requirements apply to you. If a requirement does not apply, it moves to
              the Excluded list with the reason.
            </p>
          )}
        </div>
        <ul>{step.questions.map(q => (
          <QuestionCard key={q.key} q={q} zone={zone} canEdit={canEdit} members={members} onSaved={onSaved} />
        ))}</ul>
      </section>

      <div className="flex justify-between gap-2">
        <button type="button" className="btn-mini touch-target" disabled={index === 0} onClick={() => setStepKey(steps[index - 1].key)}>
          <ChevronLeft size={12} /> Back
        </button>
        <button type="button" className="btn-mini touch-target" disabled={index === steps.length - 1} onClick={() => setStepKey(steps[index + 1].key)}>
          Next <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}
