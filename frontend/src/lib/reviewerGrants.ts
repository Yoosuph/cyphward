import { useEffect, useState } from 'react';
import { getMyReviewGrants, type MyReviewGrant } from './api';
import { useAuth } from './auth';

/**
 * The organisations the signed-in account may review right now (C6). Empty for almost everyone; the
 * "Reviews" link in the header appears only when it is not. The server decides on every request; this is
 * only what to show.
 */
export function useReviewGrants(): MyReviewGrant[] {
  const { user, loading } = useAuth();
  const [grants, setGrants] = useState<MyReviewGrant[]>([]);
  const userId = user?.id;

  useEffect(() => {
    if (loading || !userId) {
      setGrants([]);
      return;
    }
    let cancelled = false;
    void getMyReviewGrants().then(list => { if (!cancelled) setGrants(list); });
    return () => { cancelled = true; };
  }, [userId, loading]);

  return grants;
}
