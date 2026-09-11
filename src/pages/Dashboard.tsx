import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, RefreshCw, Download, Zap, ShieldCheck } from 'lucide-react';
import { getPosture, getScore, getAlerts, getTicker } from '../lib/api';
import { useAsync } from '../lib/hooks';
import BentoCard from '../components/BentoCard';
import ScoreRing from '../components/ScoreRing';
import StatCard from '../components/StatCard';
import StatusChip from '../components/StatusChip';
import Meter from '../components/Meter';
import DataTable from '../components/DataTable';
import ThreatTicker from '../components/ThreatTicker';
import { PageHead, Loading, sevLevel, statusLevel } from '../components/ui';
import { useToast } from '../components/Toast';
import type { Alert } from '../data/mock';

export default function Dashboard() {
  const nav = useNavigate();
  const toast = useToast();
  const posture = useAsync(getPosture);
  const score = useAsync(getScore);
  const alerts = useAsync(getAlerts);
  const ticker = useAsync(getTicker);
  const [signals, setSignals] = useState(0);
  const [timeframe, setTimeframe] = useState<'24H' | '7D' | '30D'>('24H');
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    if (posture.data) setSignals(posture.data.signalsToday);
  }, [posture.data]);

  /* signals counter ticks — the command center stays alive */
  useEffect(() => {
    const iv = setInterval(() => setSignals(s => s + Math.floor(Math.random() * 4) + 1), 2200);
    return () => clearInterval(iv);
  }, []);

  const handleSync = () => {
    if (syncing) return;
    setSyncing(true);
    toast('Synchronizing telemetry across African enclaves (Lagos/Kano/Nairobi)…');
    setTimeout(() => {
      setSyncing(false);
      setSignals(s => s + 342);
      toast('Sync complete: 342 fresh telemetry packets ingested.');
    }, 900);
  };

  const handleExportDossier = () => {
    toast('Compiling NDPA 2023 & CBN continuous audit dossier (PDF)…');
    setTimeout(() => {
      toast('Dossier generated: NDPA-COMPLIANCE-REPORT-2026.pdf ready.');
    }, 700);
  };

  if (posture.loading || !posture.data) return <Loading label="POSTURE" />;
  const p = posture.data;

  return (
    <>
      <div className="ticker-card">
        <ThreatTicker items={ticker.data ?? []} />
      </div>

      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-2">
        <PageHead
          eyebrow="LAYER 01 · COMMAND"
          title="The posture, at a glance."
          note={`${p.tenant} on the ${p.plan} plan — score, compliance, training and the latest signals from the detection stack.`}
          meta={
            <dl className="meta-row">
              <div><dt>SIGNALS TODAY</dt><dd>{signals.toLocaleString('en-US')}</dd></div>
              <div><dt>CRITICAL OPEN</dt><dd className="acc">{p.criticalAlerts}</dd></div>
              <div><dt>LAST SYNC</dt><dd>04:00 UTC</dd></div>
            </dl>
          }
        />

        {/* Quick Action Bar & Timeframe */}
        <div className="flex flex-wrap items-center gap-2.5 mb-6 sm:mb-8">
          <div className="flex items-center gap-1 border border-line rounded p-0.5 bg-inset">
            {(['24H', '7D', '30D'] as const).map(tf => (
              <button
                key={tf}
                type="button"
                className={`chip text-[10px] py-1 px-2.5 border-0 ${timeframe === tf ? 'on' : ''}`}
                onClick={() => setTimeframe(tf)}
              >
                {tf}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              className="btn-mini hover-lift"
              onClick={handleSync}
              disabled={syncing}
              title="Resync telemetry"
            >
              <RefreshCw size={12} className={syncing ? 'animate-spin text-accent' : ''} />
              <span>SYNC</span>
            </button>
            <button
              className="btn-mini hover-lift"
              onClick={handleExportDossier}
              title="Export regulatory dossier"
            >
              <Download size={12} />
              <span>DOSSIER</span>
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <BentoCard className="lg:col-span-5 hover-lift" title="SECURITY POSTURE" right={<StatusChip level="ok">LIVE</StatusChip>}>
          <div className="flex justify-center py-3">
            {score.data && <ScoreRing score={score.data.score} max={score.data.max} size={216} trend={score.data.trend} />}
          </div>
          <p className="ring-note">COMPOSITE OF 5 SUB-SCORES · TARGET 800 BY Q4</p>
        </BentoCard>

        <div className="panel lg:col-span-7 hover-lift">
          <header className="panel-head">
            <p className="eyebrow">SUB-SCORES</p>
            <span className="ph-hint mono">0–1000 WEIGHTED</span>
          </header>
          <div className="panel-body pt-1">
            {score.data ? score.data.subscores.map(s => (
              <div className="sub-row" key={s.key}>
                <span className="sub-lbl mono">{s.label}</span>
                <span className="sub-val">{s.value}</span>
                <Meter pct={(s.value / s.max) * 100} variant={s.delta >= 0 ? 'ok' : 'bad'} />
                <span className={`delta mono ${s.delta >= 0 ? 'up' : 'down'}`}>
                  {s.delta >= 0 ? '+' : ''}{s.delta}
                </span>
              </div>
            )) : <Loading label="SUB-SCORES" />}
          </div>
        </div>
      </div>

      <div className="stat-strip mt-6">
        <StatCard
          label="COMPLIANCE" value={p.compliance.passing} unit={`/ ${p.compliance.total} CONTROLS PASS`}
          meter={{ pct: (p.compliance.passing / p.compliance.total) * 100, variant: 'ok' }}
          note={`FRAMEWORK — ${p.compliance.framework}`} to="/comply"
        />
        <StatCard
          label="TRAINING" value={`${p.trainingCompletion}%`}
          meter={{ pct: p.trainingCompletion, variant: 'ok' }}
          note="ACADEMY COMPLETION — ALL DEPARTMENTS" to="/academy"
        />
        <StatCard
          label="OPEN ALERTS" value={p.openAlerts}
          note={<span>{p.criticalAlerts} CRITICAL — <span className="acc">{p.criticalLabel}</span></span>} to="/detect"
        />
        <StatCard
          label="REMEDIATIONS" value={p.openRemediations}
          note="2 DUE WITHIN 14 DAYS" to="/comply"
        />
      </div>

      <div className="panel mt-6 hover-lift">
        <header className="panel-head">
          <div className="flex items-center gap-2">
            <p className="eyebrow">LATEST SIGNALS</p>
            <span className="tag text-[9px]">REAL-TIME</span>
          </div>
          <button className="stat-link" onClick={() => nav('/detect')}>
            VIEW ALL <ArrowUpRight size={12} />
          </button>
        </header>
        {alerts.data ? (
          <DataTable<Alert>
            rows={alerts.data}
            rowId={r => r.id}
            minWidth={620}
            onRowClick={r => nav('/detect', { state: { alertId: r.id } })}
            columns={[
              { key: 'time', label: 'TIME' },
              { key: 'title', label: 'ALERT' },
              { key: 'technique', label: 'TECHNIQUE', hide: 'sm' },
              { key: 'severity', label: 'SEVERITY', render: r => <StatusChip level={sevLevel(r.severity)}>{r.severity}</StatusChip> },
              { key: 'status', label: 'STATUS', hide: 'md', render: r => <StatusChip level={statusLevel(r.status)}>{r.status}</StatusChip> },
            ]}
          />
        ) : (
          <div className="panel-body"><Loading label="SIGNALS" /></div>
        )}
      </div>
    </>
  );
}
