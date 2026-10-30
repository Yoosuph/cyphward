import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { SUSPENDED_EVENT, suspensionSeen } from './suspension';

/** True while the active organisation is suspended: from the bootstrap flag or a refused write this session. */
export function useOrgSuspended(): boolean {
  const { organization } = useAuth();
  const orgId = organization?.id ?? null;
  const [seen, setSeen] = useState(() => suspensionSeen(orgId));
  useEffect(() => {
    setSeen(suspensionSeen(orgId));
    const on = () => setSeen(suspensionSeen(orgId));
    window.addEventListener(SUSPENDED_EVENT, on);
    return () => window.removeEventListener(SUSPENDED_EVENT, on);
  }, [orgId]);
  return Boolean(organization?.suspended) || seen;
}
