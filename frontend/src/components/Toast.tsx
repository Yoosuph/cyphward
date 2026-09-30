import { createContext, useCallback, useContext, useState, ReactNode } from 'react';

const Ctx = createContext<(msg: string) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msgs, setMsgs] = useState<{ id: number; m: string }[]>([]);

  const push = useCallback((m: string) => {
    const id = Date.now() + Math.random();
    setMsgs(prev => [...prev.slice(-2), { id, m }]);
    setTimeout(() => setMsgs(prev => prev.filter(t => t.id !== id)), 3600);
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toasts">
        {msgs.map(t => <div key={t.id} className="toast">{t.m}</div>)}
      </div>
    </Ctx.Provider>
  );
}
