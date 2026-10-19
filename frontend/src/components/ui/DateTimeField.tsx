import { useId, type ReactNode } from 'react';
import { localToUtc, resolveZone, wallProblem, zoneLabel } from '../../lib/datetime';

/**
 * A native date or date-and-time picker, always read in the organisation's zone and always shown with it.
 *
 *   const [when, setWhen] = useState('');            // '2026-10-15T09:30' (wall clock in `zone`)
 *   <DateTimeField label="Detected at" zone={zone} value={when} onChange={setWhen} />
 *   …on submit:   const r = localToUtc(when, zone);  if (r.ok) send(r.utc);   // UTC ISO string
 *
 * `mode="date"` gives a plain calendar date (`2026-10-15`) for things that are days, not moments.
 * A time the clocks skip or repeat shows an inline message here; `localToUtc` refuses it too, so it is never sent.
 * `error` shows a message from the form itself (for example "Choose when it was detected").
 */
export interface DateTimeFieldProps {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  zone: string;
  mode?: 'datetime' | 'date';
  id?: string;
  min?: string;
  max?: string;
  optional?: boolean;
  disabled?: boolean;
  hint?: ReactNode;
  error?: string | null;
  testId?: string;
}

export const FIELD_CONTROL = 'w-full font-mono text-[12.5px] bg-inset border border-line rounded-[3px] px-3 py-3 min-h-[44px] text-ink min-w-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent focus:border-ink';
export const FIELD_LABEL_CLASS = 'block mono text-[10px] tracking-[.18em] text-soft mb-2 uppercase';

export default function DateTimeField({
  label, value, onChange, zone, mode = 'datetime', id, min, max, optional = false, disabled = false, hint, error, testId,
}: DateTimeFieldProps) {
  const auto = useId();
  const inputId = id || `dt-${auto}`;
  const z = resolveZone(zone);
  const problem = error || (mode === 'datetime' ? wallProblem(value, z) : null);
  const noteId = `${inputId}-note`;
  const zoneNote = mode === 'datetime' ? `Time in ${zoneLabel(z)}` : `Day in ${z}`;
  return (
    <div className="min-w-0">
      <label htmlFor={inputId} className={FIELD_LABEL_CLASS}>{label}{optional ? ' (optional)' : ''}</label>
      <input
        id={inputId}
        type={mode === 'date' ? 'date' : 'datetime-local'}
        className={FIELD_CONTROL}
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? `${noteId} ${noteId}-problem` : noteId}
        data-testid={testId}
        onChange={e => onChange(e.target.value)}
      />
      <p id={noteId} className="text-[11px] text-soft mt-1.5 normal-case tracking-normal" data-testid="zone-note">
        {zoneNote}{hint ? <> · {hint}</> : null}
      </p>
      {problem && <p id={`${noteId}-problem`} role="alert" className="text-xs text-accent mt-1 break-words" data-testid="datetime-problem">{problem}</p>}
    </div>
  );
}

export { localToUtc };
