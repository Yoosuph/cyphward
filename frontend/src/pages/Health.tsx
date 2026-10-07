import { useCallback, useEffect, useState } from 'react';
import { Activity, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';
import PublicShell from '../components/PublicShell';
import { useToast } from '../components/Toast';

const HEALTH_URL = import.meta.env.DEV
  ? 'http://localhost:8000/health'
  : '/api/health';

interface HealthState {
  status: string;
  database: string;
  service: string;
  version: string;
}

/**
 * Public system status — no sign-in required. Reads the unauthenticated
 * /health endpoint (liveness + database reachability + build version).
 * Scanner internals stay behind the staff platform console.
 */
export default function Status() {
  const toast = useToast();
  const [health, setHealth] = useState<HealthState | null>(null);
  const [roundtripMs, setRoundtripMs] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [failureDetail, setFailureDetail] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    setFailureDetail('');
    const t0 = performance.now();
    try {
      const res = await fetch(HEALTH_URL, { cache: 'no-store' });
      if (!res.ok) throw new Error(`API answered HTTP ${res.status}`);
      setHealth(await res.json());
      setRoundtripMs(Math.round(performance.now() - t0));
    } catch (e: any) {
      setHealth(null);
      setFailed(true);
      const detail = e?.message || 'network error';
      setFailureDetail(`${HEALTH_URL} — ${detail}`);
      toast(`Could not reach the API (${detail})`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const ok = !failed && health?.status === 'healthy' && health?.database === 'connected';

  return (
    <PublicShell
      eyebrow="SYSTEM STATUS"
      title={<>All systems <em>nominal.</em></>}
      lede="Live, unauthenticated view of the Cyphward API. No sign-in needed — this page reads the public health endpoint."
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="p-5 rounded-lg border border-line bg-raised">
          <div className="flex items-center gap-2 mb-2">
            <Activity size={14} className="text-accent" />
            <span className="mono text-[11px] text-soft tracking-wider">API</span>
          </div>
          {loading ? (
            <span className="mono text-xs text-soft">Checking…</span>
          ) : (
            <div className="flex items-center gap-2">
              {ok ? <CheckCircle2 size={16} className="text-ok" /> : <AlertTriangle size={16} className="text-accent" />}
              <span className={`mono text-sm font-semibold ${ok ? 'text-ok' : 'text-accent'}`}>
                {ok ? 'OPERATIONAL' : 'UNREACHABLE'}
              </span>
            </div>
          )}
        </div>
        <div className="p-5 rounded-lg border border-line bg-raised">
          <div className="mono text-[11px] text-soft tracking-wider mb-2">DATABASE</div>
          <span className={`mono text-sm font-semibold ${health?.database === 'connected' ? 'text-ok' : 'text-soft'}`}>
            {loading ? '…' : (health?.database || 'unknown').toUpperCase()}
          </span>
        </div>
        <div className="p-5 rounded-lg border border-line bg-raised">
          <div className="mono text-[11px] text-soft tracking-wider mb-2">VERSION</div>
          <span className="mono text-sm font-semibold text-ink">
            {loading ? '…' : health ? `${health.service} ${health.version}` : '—'}
          </span>
          {roundtripMs !== null && (
            <div className="mono text-[11px] text-soft mt-1">{roundtripMs}ms round trip</div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 mt-6">
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50 flex items-center gap-1.5"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          {loading ? 'CHECKING…' : 'CHECK AGAIN'}
        </button>
        {failed ? (
          <span className="mono text-[11px] text-accent">
            {failureDetail || 'Unreachable — check your connection, then try again.'}
          </span>
        ) : (
          <span className="mono text-[11px] text-soft">Scanner internals live in the staff platform console.</span>
        )}
      </div>
    </PublicShell>
  );
}
