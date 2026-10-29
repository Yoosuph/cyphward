import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import Dialog from './ui/Dialog';

/**
 * Branded confirmation for actions that cannot be undone.
 *
 *   const confirm = useConfirm();
 *   if (!(await confirm({ title: 'Issue this pack?', confirmLabel: 'Issue pack',
 *                         body: 'It freezes your evidence as it is now.', irreversible: 'An issued pack cannot be changed or taken back.' }))) return;
 *
 * - `confirmLabel` names the action ("Issue pack", never "OK").
 * - `irreversible` is the one sentence saying what cannot be undone. It is shown in bold.
 * - Focus always starts on Cancel, so a stray Enter or a key held down never confirms. `danger` only adds the warning icon.
 * - `typedName` adds the typed-name gate: the confirm button stays disabled until that exact text (case and spaces
 *   included) is typed. The same gate is exported as <TypedNameGate> for dialogs that also collect input (the
 *   owner console's actions), so every typed confirmation looks and behaves the same.
 */
export type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** What cannot be undone, in one sentence. */
  irreversible?: string;
  /** Destructive: the dialog carries a warning icon. Focus starts on Cancel for every confirmation. */
  danger?: boolean;
  /** The exact text to type before the confirm button is enabled (for example an organization's name). */
  typedName?: string;
};

/** True only for the exact text: no trimming, no case folding. */
export function typedNameMatches(typed: string, name: string) {
  return name.length > 0 && typed === name;
}

/**
 * The typed-name gate: a labelled field and a line that says what to type. The parent keeps the value and enables
 * its confirm button only when typedNameMatches(value, name).
 */
export function TypedNameGate({ name, value, onChange, id, what = 'the organization name' }: {
  name: string; value: string; onChange: (v: string) => void; id?: string; what?: string;
}) {
  const auto = useId();
  const fieldId = id || `${auto}-typed-name`;
  const helpId = `${fieldId}-help`;
  const matches = typedNameMatches(value, name);
  return (
    <div data-testid="typed-name-gate">
      <label htmlFor={fieldId} className="block mono text-[10px] tracking-[.18em] text-soft mb-2">
        TYPE {what.toUpperCase()} TO CONFIRM
      </label>
      <p id={helpId} className="text-xs text-soft mb-2 break-words">
        Type <span className="mono text-ink select-all" data-testid="typed-name-target">{name}</span> exactly, including capitals and spaces.
      </p>
      <input
        id={fieldId}
        value={value}
        onChange={e => onChange(e.target.value)}
        autoComplete="off"
        spellCheck={false}
        aria-describedby={helpId}
        aria-invalid={value.length > 0 && !matches}
        className="w-full mono text-[12.5px] bg-inset border border-line rounded-[3px] px-3.5 py-3 text-ink outline-none focus:border-[var(--ink)]"
        data-testid="typed-name-input"
      />
      {value.length > 0 && !matches && (
        <p className="text-[11px] mono text-soft mt-1.5" aria-live="polite">Not a match yet.</p>
      )}
    </div>
  );
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

const ConfirmContext = createContext<(options: ConfirmOptions) => Promise<boolean>>(
  async () => false,
);

export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const last = useRef<Pending | null>(null);
  if (pending) last.current = pending;

  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>(resolve => {
    setPending(current => {
      current?.resolve(false); // A newer request supersedes an unanswered one.
      return { ...options, resolve };
    });
  }), []);

  const settle = useCallback((ok: boolean) => {
    setPending(current => {
      current?.resolve(ok);
      return null;
    });
  }, []);

  const shown = pending ?? last.current;
  const danger = !!shown?.danger;
  const [typed, setTyped] = useState('');
  useEffect(() => { setTyped(''); }, [pending]);
  const gated = !!shown?.typedName && !typedNameMatches(typed, shown.typedName);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog
        open={!!pending}
        onClose={() => settle(false)}
        title={shown?.title}
        icon={danger ? <AlertTriangle size={15} /> : undefined}
        maxWidth="max-w-md"
        compact
      >
        <div className="space-y-5" data-testid="confirm-dialog">
          <div className="text-sm text-soft leading-relaxed space-y-2">
            {shown?.body && <div>{shown.body}</div>}
            {shown?.irreversible && <p className="text-ink font-medium" data-testid="confirm-irreversible">{shown.irreversible}</p>}
          </div>
          {shown?.typedName && <TypedNameGate name={shown.typedName} value={typed} onChange={setTyped} />}
          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
            <button type="button" className="btn btn-ghost justify-center touch-target" data-autofocus
                    data-testid="confirm-cancel" onClick={() => settle(false)}>
              {shown?.cancelLabel || 'Cancel'}
            </button>
            <button type="button" className="btn btn-solid justify-center touch-target" disabled={gated}
                    data-testid="confirm-ok" onClick={() => { if (!gated) settle(true); }}>
              {shown?.confirmLabel}
            </button>
          </div>
        </div>
      </Dialog>
    </ConfirmContext.Provider>
  );
}
