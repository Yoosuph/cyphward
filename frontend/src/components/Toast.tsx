import { createContext, useCallback, useContext, useState, ReactNode } from 'react';
import { createPortal } from 'react-dom';

const Ctx = createContext<(msg: string) => void>(() => {});
/** `const toast = useToast(); toast('Pack issued.')`: one short sentence for every finished or failed action. */
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msgs, setMsgs] = useState<{ id: number; m: string }[]>([]);

  const push = useCallback((m: string) => {
    const id = Date.now() + Math.random();
    setMsgs(prev => [...prev.slice(-2), { id, m }]);
    setTimeout(() => setMsgs(prev => prev.filter(t => t.id !== id)), 5000);
  }, []);

  // Rendered on <body>, outside the app root, so toasts stay readable and announced while a dialog makes the page inert.
  const stack = (
    <div className="toasts" role="status" aria-live="polite" aria-atomic="false">
      {msgs.map(t => <div key={t.id} className="toast">{t.m}</div>)}
    </div>
  );

  return (
    <Ctx.Provider value={push}>
      {children}
      {typeof document === 'undefined' ? stack : createPortal(stack, document.body)}
    </Ctx.Provider>
  );
}
