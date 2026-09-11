import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import * as mock from '../data/mock';
import type { Tenant } from '../data/mock';

const KEY = 'cyphward-tenant';
const SIGNOUT_KEY = 'cyphward-signed-out';

interface Auth {
  tenant: Tenant | null;
  signIn: (t: Tenant) => void;
  signOut: () => void;
}

const Ctx = createContext<Auth>({ tenant: null, signIn: () => {}, signOut: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [tenant, setTenant] = useState<Tenant | null>(() => {
    try {
      if (typeof window !== 'undefined' && localStorage.getItem(SIGNOUT_KEY) === 'true') {
        return null;
      }
      const raw = localStorage.getItem(KEY) || sessionStorage.getItem(KEY);
      if (raw) return JSON.parse(raw) as Tenant;
      return mock.tenant;
    } catch {
      return mock.tenant;
    }
  });

  useEffect(() => {
    try {
      if (tenant) {
        localStorage.setItem(KEY, JSON.stringify(tenant));
        sessionStorage.setItem(KEY, JSON.stringify(tenant));
        localStorage.removeItem(SIGNOUT_KEY);
      } else {
        localStorage.removeItem(KEY);
        sessionStorage.removeItem(KEY);
      }
    } catch { /* private mode — ignore */ }
  }, [tenant]);

  const signOut = () => {
    try {
      localStorage.setItem(SIGNOUT_KEY, 'true');
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
    } catch {}
    setTenant(null);
  };

  const signIn = (t: Tenant) => {
    try {
      localStorage.removeItem(SIGNOUT_KEY);
      localStorage.setItem(KEY, JSON.stringify(t));
      sessionStorage.setItem(KEY, JSON.stringify(t));
    } catch {}
    setTenant(t);
  };

  return (
    <Ctx.Provider value={{ tenant, signIn, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
