import { Check, Compass } from 'lucide-react';

export type ChecklistStep = {
  key: string;
  label: string;
  hint: string;
  done: boolean;
  action?: { label: string; onClick: () => void };
};

/**
 * First-run checklist on Overview. Every step is derived from real workspace
 * state (domains and scans), never from page views or button clicks, and the
 * card disappears once all steps are done.
 */
export default function SetupChecklist({
  steps,
  canManage,
  onTour,
}: {
  steps: ChecklistStep[];
  canManage: boolean;
  onTour: () => void;
}) {
  const done = steps.filter(step => step.done).length;
  if (done === steps.length) return null;
  const nextKey = steps.find(step => !step.done)?.key;

  return (
    <section className="setup-checklist panel" data-tour="checklist" aria-labelledby="setup-checklist-title">
      <div className="setup-checklist-head">
        <div>
          <p className="eyebrow">GETTING STARTED · {done} OF {steps.length} DONE</p>
          <h2 id="setup-checklist-title" className="font-display text-lg font-medium text-ink mt-1">
            Get your first security score
          </h2>
        </div>
        <button type="button" className="btn-mini" onClick={onTour}>
          <Compass size={12} /> TAKE THE TOUR
        </button>
      </div>
      <div className="setup-checklist-bar" aria-hidden="true">
        <span style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className="setup-checklist-steps">
        {steps.map(step => {
          const isNext = step.key === nextKey;
          return (
            <li key={step.key} className={step.done ? 'is-done' : isNext ? 'is-next' : ''}>
              <span className="setup-checklist-mark" aria-hidden="true">
                {step.done ? <Check size={12} /> : null}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink font-medium">
                  {step.label}
                  <span className="sr-only">{step.done ? ' (done)' : isNext ? ' (next step)' : ''}</span>
                </p>
                {isNext && <p className="text-xs text-soft mt-0.5">{step.hint}</p>}
              </div>
              {isNext && (canManage && step.action
                ? <button type="button" className="btn btn-solid btn-mini shrink-0" onClick={step.action.onClick}>{step.action.label}</button>
                : !canManage && <span className="text-xs mono text-soft shrink-0">ASK A WORKSPACE ADMIN</span>)}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
