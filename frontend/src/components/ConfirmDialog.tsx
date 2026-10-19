import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
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
 * - `danger` (delete, remove, revoke): focus starts on Cancel. Otherwise it starts on the confirm button.
 */
export type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** What cannot be undone, in one sentence. */
  irreversible?: string;
  /** Destructive: Cancel is the default focus and the dialog carries a warning icon. */
  danger?: boolean;
};

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
          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
            <button type="button" className="btn btn-ghost justify-center touch-target" data-autofocus={danger ? '' : undefined}
                    data-testid="confirm-cancel" onClick={() => settle(false)}>
              {shown?.cancelLabel || 'Cancel'}
            </button>
            <button type="button" className="btn btn-solid justify-center touch-target" data-autofocus={danger ? undefined : ''}
                    data-testid="confirm-ok" onClick={() => settle(true)}>
              {shown?.confirmLabel}
            </button>
          </div>
        </div>
      </Dialog>
    </ConfirmContext.Provider>
  );
}
