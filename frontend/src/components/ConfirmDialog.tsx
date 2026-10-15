import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import Modal from './Modal';

export type ConfirmOptions = {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive actions start with focus on Cancel and use the accent button. */
  danger?: boolean;
};

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

const ConfirmContext = createContext<(options: ConfirmOptions) => Promise<boolean>>(
  async () => false,
);

/** Branded replacement for window.confirm: `if (!(await confirm({...}))) return;` */
export function useConfirm() {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

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

  useEffect(() => {
    if (!pending) return;
    const id = setTimeout(() => (pending.danger ? cancelRef : confirmRef).current?.focus(), 50);
    return () => clearTimeout(id);
  }, [pending]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Modal
        open={!!pending}
        onClose={() => settle(false)}
        title={pending?.title}
        icon={pending?.danger ? <AlertTriangle size={15} /> : undefined}
        maxWidth="max-w-md"
      >
        <div className="space-y-5">
          <div className="text-sm text-soft leading-relaxed">{pending?.body}</div>
          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
            <button ref={cancelRef} type="button" className="btn btn-ghost justify-center" onClick={() => settle(false)}>
              {pending?.cancelLabel || 'CANCEL'}
            </button>
            <button ref={confirmRef} type="button" className="btn btn-solid justify-center" onClick={() => settle(true)}>
              {pending?.confirmLabel || 'CONFIRM'}
            </button>
          </div>
        </div>
      </Modal>
    </ConfirmContext.Provider>
  );
}
