import { useEffect, useState } from 'react';
import {
  Radar,
  Play,
  CheckCircle2,
  Clock,
  AlertCircle,
  RefreshCw,
  Search,
  ArrowRight,
  ShieldAlert,
  Server,
  Layers,
  Code,
  Lock,
  Sparkles,
  FileText,
  X,
} from 'lucide-react';
import { getScans, getScanDetail, launchScan, getDomains } from '../lib/api';
import type { Scan, Domain } from '../types';
import { useToast } from '../components/Toast';
import { ScansSkeleton, ScanStepperSkeleton, TableRowSkeleton, ScanDrawerSkeleton } from '../components/Skeleton';
import Modal from '../components/Modal';
import Drawer from '../components/Drawer';

export default function Scans() {
  const [scans, setScans] = useState<Scan[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const [selectedScanDetail, setSelectedScanDetail] = useState<{ scan: Scan; raw_results: any[] } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Launch modal state
  const [launchModalOpen, setLaunchModalOpen] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [selectedDomainId, setSelectedDomainId] = useState<string>('');
  const [launching, setLaunching] = useState(false);

  // Scan detail modal state
  const [scanDetailModalOpen, setScanDetailModalOpen] = useState(false);
  const [scanDetailForModal, setScanDetailForModal] = useState<{ scan: Scan; raw_results: any[] } | null>(null);
  const [detailModalLoading, setDetailModalLoading] = useState(false);

  const toast = useToast();

  const loadScans = async () => {
    try {
      const list = await getScans();
      setScans(list);
      if (list.length > 0 && !selectedScanId) {
        setSelectedScanId(list[0].id);
      }
    } catch (e) {
      // Keep last known list on transient errors — do not blank the UI during polling.
      if (scans.length === 0) toast('Failed to load scans');
    } finally {
      setLoading(false);
    }
  };

  const loadScanDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const detail = await getScanDetail(id);
      setSelectedScanDetail(detail);
    } catch (err) {
      // Keep last known detail on transient errors — do not blank the tracker during polling.
      if (!selectedScanDetail) toast('Failed to load scan tracker');
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    loadScans();
    getDomains().then(d => {
      setDomains(d);
      if (d.length > 0) setSelectedDomainId(d[0].id);
    });
  }, []);

  useEffect(() => {
    if (selectedScanId) {
      loadScanDetail(selectedScanId);
    }
  }, [selectedScanId]);

  // Polling if selected scan is running
  useEffect(() => {
    const isRunning = selectedScanDetail?.scan.status === 'running' || selectedScanDetail?.scan.status === 'queued';
    if (!isRunning) return;

    const interval = setInterval(() => {
      if (selectedScanId) loadScanDetail(selectedScanId);
      loadScans();
    }, 3000);

    return () => clearInterval(interval);
  }, [selectedScanId, selectedScanDetail?.scan.status]);

  const handleLaunch = async () => {
    setLaunching(true);
    try {
      const res = await launchScan(selectedDomainId);
      toast(`Workflow started for ${res.domain}! Inngest pipeline initialized.`);
      setLaunchModalOpen(false);
      await loadScans();
      if (res.scan?.id) {
        setSelectedScanId(res.scan.id);
      }
    } catch (err: any) {
      toast(err.message || 'Failed to start scan');
    } finally {
      setLaunching(false);
    }
  };

  const handleOpenScanDetail = async (scanId: string) => {
    setScanDetailModalOpen(true);
    setDetailModalLoading(true);
    try {
      const detail = await getScanDetail(scanId);
      setScanDetailForModal(detail);
    } catch (err) {
      toast('Failed to load scan details');
    } finally {
      setDetailModalLoading(false);
    }
  };

  const STAGES = [
    { key: 'discovery', label: '1. Discovery', desc: 'Subfinder & Passive CT Logs' },
    { key: 'dns', label: '2. DNS Resolution', desc: 'A, MX, TXT, SPF, DMARC' },
    { key: 'http', label: '3. HTTP Probing', desc: 'Go httpx / Python httpx' },
    { key: 'security_checks', label: '4. Security Checks', desc: 'Headers, DMARC, TLS Certs' },
    { key: 'nuclei', label: '5. Nuclei Scan', desc: '9000+ Vulnerability Templates' },
    { key: 'normalization', label: '6. Normalization', desc: 'Evidence Standardization' },
    { key: 'scoring', label: '7. Security Score', desc: 'Simple 0–100 score' },
    { key: 'ai_analysis', label: '8. AI Analysis', desc: 'Explanations & Executive Report' },
  ];

  if (loading && scans.length === 0) {
    return <ScansSkeleton />;
  }

  const activeScan = selectedScanDetail?.scan || scans[0];

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <p className="eyebrow text-accent">MULTI-STAGE INNGEST WORKFLOW PIPELINE</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            Security Scans & Live Execution Tracker
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Asynchronous orchestration: Discovery → DNS → HTTP → Security Checks → Nuclei → Normalization → Score → AI Analysis
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => {
              loadScans();
              if (selectedScanId) loadScanDetail(selectedScanId);
            }}
            className="flex items-center gap-1.5 px-3 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong text-ink transition-colors btn-tactile"
          >
            <RefreshCw size={12} className={loading || detailLoading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>

          <button
            onClick={() => setLaunchModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 shadow-md shadow-accent/20 transition-all btn-tactile"
          >
            <Play size={13} fill="currentColor" />
            <span>NEW SCAN</span>
          </button>
        </div>
      </div>

      {/* Live Workflow Stepper Tracker for Selected Scan */}
      {detailLoading && !selectedScanDetail ? (
        <ScanStepperSkeleton />
      ) : activeScan ? (
        <div className="p-6 rounded-lg border border-line bg-raised shadow-sm space-y-6 content-fade-in">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-line">
            <div>
              <div className="flex items-center gap-2 flex-wrap min-w-0">
                <span className="mono text-xs text-soft uppercase tracking-wider">ACTIVE WORKFLOW:</span>
                <span className="mono text-sm font-bold text-ink">{activeScan.domain}</span>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] mono uppercase font-bold ${
                    activeScan.status === 'completed'
                      ? 'bg-ok/15 text-ok border border-ok/30'
                      : activeScan.status === 'running'
                      ? 'bg-amber-500/15 text-amber-500 border border-amber-500/30 animate-pulse'
                      : 'bg-inset text-soft border border-line'
                  }`}
                >
                  {activeScan.status}
                </span>
              </div>
              <p className="text-[11px] mono text-soft mt-1 break-all">
                Scan ID: {activeScan.id} · Initiated: {new Date(activeScan.created_at).toLocaleString()}
              </p>
            </div>

            {activeScan.score !== null && activeScan.score !== undefined && (
              <div className="text-right">
                <span className="text-xs mono text-soft">SCORE</span>
                <div className="text-2xl font-bold mono text-accent">{activeScan.score}/100</div>
              </div>
            )}
          </div>

          {/* Stepper Pipeline Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-3">
            {STAGES.map((stage, idx) => {
              const stageData = (activeScan.stage_progress as any)?.[stage.key];
              const isCompleted = stageData?.status === 'completed';
              const isRunning = stageData?.status === 'running';
              const isQueued = stageData?.status === 'queued' || stageData?.status === 'pending';

              return (
                <div
                  key={stage.key}
                  className={`p-3.5 rounded-lg border transition-all flex flex-col justify-between min-h-[120px] ${
                    isRunning
                      ? 'border-accent bg-accent-soft/20 shadow-md ring-1 ring-accent'
                      : isCompleted
                      ? 'border-ok/30 bg-ok/5'
                      : 'border-line/70 bg-inset/40 opacity-70'
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] mono text-soft font-bold">STAGE 0{idx + 1}</span>
                      {isCompleted ? (
                        <CheckCircle2 size={14} className="text-ok" />
                      ) : isRunning ? (
                        <span className="w-2.5 h-2.5 rounded-full bg-accent animate-ping" />
                      ) : (
                        <Clock size={13} className="text-soft" />
                      )}
                    </div>

                    <h4 className="mono text-xs font-semibold text-ink leading-tight">{stage.label}</h4>
                    <p className="text-[10.5px] text-soft mt-1 leading-snug">{stage.desc}</p>
                  </div>

                  <div className="pt-2 border-t border-line/50 mt-2 flex items-center justify-between text-[10px] mono">
                    <span className="text-soft">
                      {stageData?.duration_ms ? `${stageData.duration_ms}ms` : '—'}
                    </span>
                    <span className="font-semibold text-ink">
                      {stageData?.items !== undefined ? `${stageData.items} items` : isCompleted ? 'Done' : 'Pending'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Raw Results Inspector Accordion */}
          {selectedScanDetail?.raw_results && selectedScanDetail.raw_results.length > 0 && (
            <div className="pt-2">
              <details className="group border border-line rounded-lg bg-inset/30 overflow-hidden">
                <summary className="px-4 py-2.5 text-xs mono text-soft font-semibold cursor-pointer hover:text-ink flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <Code size={13} className="text-accent" />
                    Inspect Raw Inngest Execution Telemetry & Observations ({selectedScanDetail.raw_results.length} stages recorded)
                  </span>
                  <span className="text-[10px] mono text-accent group-open:rotate-90 transition-transform">▸</span>
                </summary>
                <div className="p-4 bg-black text-emerald-400 font-mono text-[11px] overflow-x-auto border-t border-line max-h-72">
                  <pre>{JSON.stringify(selectedScanDetail.raw_results, null, 2)}</pre>
                </div>
              </details>
            </div>
          )}
        </div>
      ) : null}

      {/* Historical Scans Ledger Table */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="p-4 border-b border-line bg-inset/30 flex items-center justify-between">
          <h3 className="mono text-xs font-bold text-ink uppercase tracking-wider">
            HISTORICAL SCAN LEDGER
          </h3>
          <span className="text-[11px] mono text-soft">{scans.length} total workflow runs</span>
        </div>

        <div className="overflow-x-auto w-full max-w-full">
          <table className="w-full text-left text-xs mono min-w-[620px]">
            <thead>
              <tr className="border-b border-line bg-inset/40 text-soft text-[11px]">
                <th className="py-3 px-4 font-medium">DOMAIN ZONE</th>
                <th className="py-3 px-4 font-medium">RUN STATUS</th>
                <th className="py-3 px-4 font-medium">STAGE PROGRESSION</th>
                <th className="py-3 px-4 font-medium">SCORE</th>
                <th className="py-3 px-4 font-medium">FINDINGS</th>
                <th className="py-3 px-4 font-medium">TIMESTAMP</th>
                <th className="py-3 px-4 font-medium text-right">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRowSkeleton
                    key={i}
                    cols={[140, 80, 160, 70, 70, 100, 50]}
                  />
                ))
              ) : scans.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-soft mono">
                    No scans found. Click "NEW SCAN" to launch your first Inngest workflow.
                  </td>
                </tr>
              ) : (
                scans.map((scan, idx) => (
                  <tr
                    key={scan.id}
                    onClick={() => handleOpenScanDetail(scan.id)}
                    style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
                    className={`stagger-row hover:bg-inset/50 transition-colors cursor-pointer ${
                      selectedScanId === scan.id ? 'bg-inset/60 font-semibold' : ''
                    }`}
                  >
                    <td className="py-3 px-4 font-bold text-ink">
                      {scan.domain}
                    </td>

                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                          scan.status === 'completed'
                            ? 'bg-ok/10 text-ok border border-ok/30'
                            : scan.status === 'running'
                            ? 'bg-amber-500/10 text-amber-500 border border-amber-500/30 animate-pulse'
                            : 'bg-inset text-soft border border-line'
                        }`}
                      >
                        {scan.status}
                      </span>
                    </td>

                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1">
                        {['discovery', 'dns', 'http', 'security_checks', 'nuclei', 'normalization', 'scoring', 'ai_analysis'].map(st => {
                          const sData = (scan.stage_progress as any)?.[st];
                          const isDone = sData?.status === 'completed';
                          const isRunning = sData?.status === 'running';
                          return (
                            <div
                              key={st}
                              title={`${st}: ${sData?.status || 'queued'}`}
                              className={`w-3 h-1.5 rounded-full ${
                                isDone ? 'bg-ok' : isRunning ? 'bg-accent animate-pulse' : 'bg-inset border border-line'
                              }`}
                            />
                          );
                        })}
                        <span className="text-[10px] text-soft ml-2 capitalize">
                          {scan.current_stage || 'Done'}
                        </span>
                      </div>
                    </td>

                    <td className="py-3 px-4 font-bold text-ink">
                      {scan.score ? `${scan.score}/100` : '—'}
                    </td>

                    <td className="py-3 px-4 text-soft">
                      {scan.findings_discovered !== undefined ? `${scan.findings_discovered} risks` : '—'}
                    </td>

                    <td className="py-3 px-4 text-soft text-[11px]">
                      {new Date(scan.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                    </td>

                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={e => {
                          e.stopPropagation();
                          setSelectedScanId(scan.id);
                        }}
                        className="btn-tactile px-2.5 py-1 rounded text-[11px] border border-line bg-raised hover:border-line-strong text-ink"
                      >
                        Select
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Scan Detail Drawer */}
      <Drawer
        open={scanDetailModalOpen}
        onClose={() => {
          setScanDetailModalOpen(false);
          setScanDetailForModal(null);
        }}
        size="2xl"
        eyebrow="SCAN INTELLIGENCE"
        title="WORKFLOW EXECUTION DETAILS"
        icon={<Radar size={16} className="text-accent" />}
      >
        {detailModalLoading || !scanDetailForModal ? (
          <ScanDrawerSkeleton />
        ) : scanDetailForModal ? (
          <div className="space-y-5 content-fade-in">
            {/* Scan Header */}
            <div className="p-4 bg-inset rounded border border-line flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="mono text-xs text-soft uppercase">DOMAIN:</span>
                  <span className="mono text-sm font-bold text-ink">{scanDetailForModal.scan.domain}</span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] mono uppercase font-bold ${
                      scanDetailForModal.scan.status === 'completed'
                        ? 'bg-ok/15 text-ok border border-ok/30'
                        : scanDetailForModal.scan.status === 'running'
                        ? 'bg-amber-500/15 text-amber-500 border border-amber-500/30 animate-pulse'
                        : 'bg-inset text-soft border border-line'
                    }`}
                  >
                    {scanDetailForModal.scan.status}
                  </span>
                </div>
                <p className="text-[11px] mono text-soft mt-1">
                  Scan ID: {scanDetailForModal.scan.id} · {new Date(scanDetailForModal.scan.created_at).toLocaleString()}
                </p>
              </div>
              {scanDetailForModal.scan.score !== null && scanDetailForModal.scan.score !== undefined && (
                <div className="text-right">
                  <span className="text-xs mono text-soft">SCORE</span>
                  <div className="text-2xl font-bold mono text-accent">{scanDetailForModal.scan.score}/100</div>
                </div>
              )}
            </div>

            {/* Stage Progress Grid */}
            <div>
              <h4 className="mono text-xs font-semibold text-soft uppercase tracking-wider mb-3">PIPELINE STAGES</h4>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {STAGES.map((stage, idx) => {
                  const stageData = (scanDetailForModal.scan.stage_progress as any)?.[stage.key];
                  const isCompleted = stageData?.status === 'completed';
                  const isRunning = stageData?.status === 'running';
                  return (
                    <div
                      key={stage.key}
                      className={`p-2.5 rounded border text-[11px] mono ${
                        isCompleted
                          ? 'border-ok/30 bg-ok/5'
                          : isRunning
                          ? 'border-accent bg-accent-soft/20'
                          : 'border-line/50 bg-inset/30'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-soft font-bold">0{idx + 1}</span>
                        {isCompleted ? (
                          <CheckCircle2 size={12} className="text-ok" />
                        ) : isRunning ? (
                          <span className="w-2 h-2 rounded-full bg-accent animate-ping" />
                        ) : (
                          <Clock size={11} className="text-soft" />
                        )}
                      </div>
                      <div className="text-ink font-medium">{stage.label.replace(/^\d+\.\s*/, '')}</div>
                      <div className="text-soft text-[10px] mt-0.5">
                        {stageData?.duration_ms ? `${stageData.duration_ms}ms` : '—'} · {stageData?.items ?? 0} items
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* AI Analysis Section */}
            {scanDetailForModal.raw_results.some((r: any) => r.stage === 'ai_analysis' || r.stage === 'ai_explanations') && (
              <div className="p-4 bg-accent-soft/20 rounded border border-accent/30">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles size={14} className="text-accent" />
                  <h4 className="mono text-xs font-semibold text-accent uppercase tracking-wider">AI SECURITY ANALYSIS</h4>
                </div>
                {(() => {
                  const aiResult = scanDetailForModal.raw_results.find((r: any) => r.stage === 'ai_analysis');
                  if (!aiResult) return null;
                  return (
                    <div className="space-y-2 text-[11px]">
                      {aiResult.raw_data?.executive_summary && (
                        <div className="p-3 bg-inset rounded border border-line">
                          <h5 className="mono font-semibold text-soft text-[10px] uppercase mb-1">Executive Summary</h5>
                          <p className="text-ink leading-relaxed">{aiResult.raw_data.executive_summary.board_summary}</p>
                          {aiResult.raw_data.executive_summary.critical_action_items?.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {aiResult.raw_data.executive_summary.critical_action_items.map((item: any, i: number) => (
                                <div key={i} className="flex items-start gap-2 text-[10px]">
                                  <span className="px-1 py-0.5 rounded bg-accent/10 text-accent font-bold">{item.priority}</span>
                                  <span className="text-ink">{item.title}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      <div className="text-soft">
                        Analyzed {aiResult.raw_data?.explanations_count || 0} critical/high findings
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}

            {/* Raw Telemetry */}
            {scanDetailForModal.raw_results.length > 0 && (
              <details className="group border border-line rounded-lg bg-inset/30 overflow-hidden">
                <summary className="px-4 py-2.5 text-xs mono text-soft font-semibold cursor-pointer hover:text-ink flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <Code size={13} className="text-accent" />
                    Raw Telemetry ({scanDetailForModal.raw_results.length} stages)
                  </span>
                  <span className="text-[10px] mono text-accent group-open:rotate-90 transition-transform">▸</span>
                </summary>
                <div className="p-4 bg-black text-emerald-400 font-mono text-[10px] overflow-x-auto border-t border-line max-h-64">
                  <pre>{JSON.stringify(scanDetailForModal.raw_results, null, 2)}</pre>
                </div>
              </details>
            )}
          </div>
        ) : (
          <div className="py-12 text-center text-soft mono text-xs">No scan data available</div>
        )}
      </Drawer>

      {/* Launch Scan Modal */}
      <Modal
        open={launchModalOpen}
        onClose={() => setLaunchModalOpen(false)}
        title="LAUNCH SECURITY WORKFLOW"
        icon={<Play size={16} className="text-accent" />}
        maxWidth="max-w-md"
      >
        <div className="space-y-4">
          <p className="text-xs text-soft leading-relaxed">
            Select verified domain to scan. The Inngest orchestrator will execute passive discovery, DNS resolution, HTTP inspection, security checks, Nuclei vulnerability scanning, finding normalization, risk scoring, and AI analysis.
          </p>

          <div className="space-y-1.5">
            <label className="text-xs mono text-soft">TARGET DOMAIN</label>
            <select
              value={selectedDomainId}
              onChange={e => setSelectedDomainId(e.target.value)}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-xs mono text-ink focus:outline-none focus:border-accent"
            >
              {domains.map(d => (
                <option key={d.id} value={d.id}>
                  {d.domain} ({d.verification_status.toUpperCase()})
                </option>
              ))}
            </select>
          </div>

          <div className="p-3 bg-inset/50 rounded border border-line text-[11px] mono text-soft flex items-center gap-2">
            <Lock size={12} className="text-ok" />
            <span>Restricted to verified sovereign domains.</span>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setLaunchModalOpen(false)}
              className="btn-tactile px-3.5 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft"
            >
              Cancel
            </button>
            <button
              disabled={launching}
              onClick={handleLaunch}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            >
              {launching ? (
                <>
                  <RefreshCw size={13} className="animate-spin" /> Starting...
                </>
              ) : (
                <>
                  <Play size={13} fill="currentColor" /> Start Pipeline
                </>
              )}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
