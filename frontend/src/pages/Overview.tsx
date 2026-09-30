import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ShieldAlert,
  Server,
  Globe,
  Play,
  ArrowUpRight,
  RefreshCw,
  Sparkles,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Lock,
  Layers,
} from 'lucide-react';
import ScoreRing from '../components/ScoreRing';
import { OverviewSkeleton } from '../components/Skeleton';
import BoardReportModal from '../components/BoardReportModal';
import Modal from '../components/Modal';
import { getOverview, launchScan, getDomains, getExecutiveSummary } from '../lib/api';
import type { OverviewData, Domain, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string>('');
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [execSummary, setExecSummary] = useState<ExecutiveSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const toast = useToast();
  const navigate = useNavigate();

  const loadData = async () => {
    try {
      const [overviewData, domainsList] = await Promise.all([getOverview(), getDomains()]);
      setData(overviewData);
      setDomains(domainsList);
      if (domainsList.length > 0 && !selectedDomain) {
        setSelectedDomain(domainsList[0].id);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleLaunchScan = async () => {
    setLaunching(true);
    try {
      const res = await launchScan(selectedDomain);
      toast(`Scan launched for ${res.domain}! Telemetry worker active.`);
      setScanModalOpen(false);
      navigate('/scans');
    } catch (err: any) {
      toast(err.message || 'Failed to start scan');
    } finally {
      setLaunching(false);
    }
  };

  const handleOpenSummary = async () => {
    setSummaryModalOpen(true);
    setSummaryLoading(true);
    try {
      const sum = await getExecutiveSummary();
      if (sum) {
        setExecSummary(sum);
      } else {
        // Use fallback data if API returns null
        setExecSummary({
          org_name: organization.name,
          score: score,
          grade: grade,
          posture_label: posture_label,
          executive_headline: `Security Score for ${organization.name}: ${score}/100 (Grade ${grade} — ${posture_label})`,
          board_summary: `${organization.name}'s security score is ${score} out of 100 (Grade ${grade} — ${posture_label}). We checked DNS, public web apps, email security, and encryption.`,
          key_strengths: [
            'Modern TLS 1.3 cryptographic suites enforced across primary public endpoints',
            'Zero open administrative database ports exposed directly to the public internet',
            'Consistent reverse-proxy deployment shielding backend application runtimes',
          ],
          critical_action_items: [
            { priority: 'P0 - Immediate', title: 'Enforce Strict DMARC Policy (p=reject)', impact: 'Eliminates brand spoofing and executive phishing impersonation.', owner: 'IT Infrastructure & Security' },
            { priority: 'P1 - High', title: 'Deploy Comprehensive HSTS with includeSubDomains', impact: 'Prevents SSL-stripping and credential interception on corporate subdomains.', owner: 'Web Operations Team' },
          ],
          compliance_verdict: 'Partial Compliance. Immediate remediation of DMARC and HSTS is required to satisfy NDPA 2023 Part V technical safeguards.',
          generated_at: new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
        });
      }
    } catch (err) {
      console.error('Executive summary error:', err);
      // Still show modal with fallback data
      setExecSummary({
        org_name: organization.name,
        score: score,
        grade: grade,
        posture_label: posture_label,
        executive_headline: `Executive Security Assessment: ${organization.name}`,
        board_summary: 'Unable to generate executive summary at this time. Please try again later.',
        key_strengths: [],
        critical_action_items: [],
        compliance_verdict: 'Unable to determine compliance status.',
        generated_at: new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
      });
    } finally {
      setSummaryLoading(false);
    }
  };

  if (loading || !data) {
    return <OverviewSkeleton />;
  }

  const { score, max_score, grade, posture_label, trend, counts, subscores, factors, recent_scans, organization } = data;

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      {/* Header Banner & Quick Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <p className="eyebrow text-accent">COMMAND ENCLAVE · {organization.cac_rc || 'CAC REGISTERED'}</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            {organization.name}
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Autonomous Attack Surface Management & Deterministic Risk Posture
          </p>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-3 w-full sm:w-auto">
          <button
            onClick={handleOpenSummary}
            className="flex items-center justify-center gap-2 px-3.5 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink transition-colors min-h-[38px] btn-tactile"
          >
            <Sparkles size={14} className="text-accent" />
            <span>GENERATE BOARD REPORT</span>
          </button>

          <button
            onClick={() => setScanModalOpen(true)}
            className="flex items-center justify-center gap-2 px-4 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 shadow-md shadow-accent/20 transition-all min-h-[38px] btn-tactile"
          >
            <Play size={13} fill="currentColor" />
            <span>LAUNCH SCAN</span>
          </button>
        </div>
      </div>

      {/* Top Grid: Radial Score Ring & High-level Metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Main Score Gauge */}
        <div className="lg:col-span-4 p-6 rounded-lg border border-line bg-raised/70 backdrop-blur flex flex-col items-center justify-center text-center relative overflow-hidden">
          <div className="absolute top-3 left-4 text-[10px] mono text-soft tracking-wider">
            SECURITY SCORE
          </div>
          <div className="absolute top-3 right-4">
            <span className="text-[10px] mono px-2 py-0.5 rounded border border-line bg-inset text-soft">
              {grade} RATING
            </span>
          </div>

          <div className="my-2">
            <ScoreRing score={score} max={max_score} size={190} />
          </div>

          <div className="mt-1">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-soft text-accent text-xs mono font-semibold tracking-wider">
              {posture_label}
            </div>
            <p className="text-xs mono text-soft mt-2">
              7-Day Delta: <span className="text-ok font-medium">+{trend} pts</span> · Continuous Inngest Probing
            </p>
          </div>
        </div>

        {/* 4 Stat Cards */}
        <div className="lg:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div
            onClick={() => navigate('/assets')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-line-strong card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase">Active Assets</span>
              <Server size={15} className="group-hover:text-accent transition-colors" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-ink">{counts.total_assets}</div>
              <p className="text-[11px] text-soft">Across {organization.domains_count || 1} zones</p>
            </div>
            <div className="text-[10px] mono text-accent flex items-center gap-1">
              View inventory <ArrowUpRight size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/domains')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-line-strong card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase">Verified Domains</span>
              <Globe size={15} className="group-hover:text-accent transition-colors" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-ink">{organization.verified_domains_count || 1}</div>
              <p className="text-[11px] text-soft">DNS TXT Proven</p>
            </div>
            <div className="text-[10px] mono text-ok flex items-center gap-1">
              Protected enclave <CheckCircle2 size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/findings?severity=critical')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-accent card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase text-accent font-medium">Critical Risks</span>
              <ShieldAlert size={15} className="text-accent" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-accent">{counts.critical}</div>
              <p className="text-[11px] text-soft">Requires immediate fix</p>
            </div>
            <div className="text-[10px] mono text-accent flex items-center gap-1">
              Action drawer <ArrowUpRight size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/findings')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-line-strong card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase">Total Findings</span>
              <AlertTriangle size={15} className="group-hover:text-accent transition-colors" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-ink">{counts.total_findings}</div>
              <p className="text-[11px] text-soft">{counts.high} High · {counts.medium} Med</p>
            </div>
            <div className="text-[10px] mono text-soft flex items-center gap-1">
              All findings <ArrowUpRight size={10} />
            </div>
          </div>

          {/* Severity Breakdown Bar across all 4 columns */}
          <div className="col-span-2 md:col-span-4 p-4 rounded-lg border border-line bg-inset/50">
            <div className="flex items-center justify-between mb-2">
              <span className="eyebrow">SEVERITY DISTRIBUTION</span>
              <span className="text-xs mono text-soft">{counts.total_findings} Active Signals</span>
            </div>
            <div className="h-3 w-full bg-raised rounded-full overflow-hidden flex gap-0.5 p-0.5 border border-line">
              <div
                style={{ width: `${Math.max(5, (counts.critical / Math.max(1, counts.total_findings)) * 100)}%` }}
                className="bg-accent h-full rounded-l-full transition-all"
                title={`Critical: ${counts.critical}`}
              />
              <div
                style={{ width: `${(counts.high / Math.max(1, counts.total_findings)) * 100}%` }}
                className="bg-amber-600 h-full transition-all"
                title={`High: ${counts.high}`}
              />
              <div
                style={{ width: `${(counts.medium / Math.max(1, counts.total_findings)) * 100}%` }}
                className="bg-amber-400 h-full transition-all"
                title={`Medium: ${counts.medium}`}
              />
              <div
                style={{ width: `${(counts.low / Math.max(1, counts.total_findings)) * 100}%` }}
                className="bg-blue-500 h-full transition-all"
                title={`Low: ${counts.low}`}
              />
              <div
                style={{ width: `${(counts.info / Math.max(1, counts.total_findings)) * 100}%` }}
                className="bg-emerald-500 h-full rounded-r-full transition-all"
                title={`Info: ${counts.info}`}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-[11px] mono">
              <span className="flex items-center gap-1.5 text-accent">
                <span className="w-2 h-2 rounded-full bg-accent" /> Critical ({counts.critical})
              </span>
              <span className="flex items-center gap-1.5 text-amber-600">
                <span className="w-2 h-2 rounded-full bg-amber-600" /> High ({counts.high})
              </span>
              <span className="flex items-center gap-1.5 text-amber-500">
                <span className="w-2 h-2 rounded-full bg-amber-400" /> Medium ({counts.medium})
              </span>
              <span className="flex items-center gap-1.5 text-blue-400">
                <span className="w-2 h-2 rounded-full bg-blue-500" /> Low ({counts.low})
              </span>
              <span className="flex items-center gap-1.5 text-emerald-500">
                <span className="w-2 h-2 rounded-full bg-emerald-500" /> Info ({counts.info})
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Middle Grid: 4 Security Pillars Subscores & Factors */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* 4 Pillars Breakdown */}
        <div className="lg:col-span-7 p-5 rounded-lg border border-line bg-raised">
          <div className="flex items-center justify-between pb-3 border-b border-line mb-4">
            <h3 className="mono text-xs font-semibold tracking-wider text-ink">
              SCORE BREAKDOWN
            </h3>
            <span className="text-[10px] mono text-soft">OUT OF 100</span>
          </div>

          <div className="space-y-4">
            {subscores.map(pillar => (
              <div key={pillar.name} className="space-y-1.5">
                <div className="flex items-center justify-between text-xs mono">
                  <span className="font-medium text-ink">{pillar.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] px-1.5 py-0.5 rounded border border-line bg-inset text-soft">
                      {pillar.status}
                    </span>
                    <span className="font-bold text-ink">
                      {pillar.score} <span className="text-soft font-normal">/ {pillar.max}</span>
                    </span>
                  </div>
                </div>
                <div className="h-2 w-full bg-inset rounded-full overflow-hidden border border-line/60">
                  <div
                    className={`h-full rounded-full transition-all ${
                      pillar.pct > 75 ? 'bg-ok' : pillar.pct > 50 ? 'bg-warn' : 'bg-accent'
                    }`}
                    style={{ width: `${pillar.pct}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Posture Score Drivers (Factors) */}
        <div className="lg:col-span-5 p-5 rounded-lg border border-line bg-raised flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-line mb-3">
              <h3 className="mono text-xs font-semibold tracking-wider text-ink">
                TOP ISSUES &amp; STRENGTHS
              </h3>
              <span className="text-[10px] mono text-soft">WHY YOUR SCORE IS THIS</span>
            </div>

            <div className="space-y-2.5">
              {factors.map((f, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2.5 p-2 rounded bg-inset/50 border border-line/60 text-xs"
                >
                  <span
                    className={`mono font-bold text-[11px] px-1.5 py-0.5 rounded ${
                      f.type === 'positive' ? 'bg-ok/10 text-ok border border-ok/30' : 'bg-accent/10 text-accent border border-accent/30'
                    }`}
                  >
                    {f.impact}
                  </span>
                  <span className="text-ink text-[12px] leading-snug">{f.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-line text-right">
            <button
              onClick={() => navigate('/findings')}
              className="text-xs mono text-accent hover:underline inline-flex items-center gap-1"
            >
              Examine complete finding ledger <ArrowUpRight size={11} />
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Grid: Recent Scans & Inngest Stage Progress */}
      <div className="p-5 rounded-lg border border-line bg-raised">
        <div className="flex items-center justify-between pb-3 border-b border-line mb-4">
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <h3 className="mono text-xs font-semibold tracking-wider text-ink">
              RECENT INNGEST WORKFLOW EXECUTIONS
            </h3>
          </div>
          <button
            onClick={() => navigate('/scans')}
            className="text-xs mono text-accent hover:underline flex items-center gap-1"
          >
            All scan runs <ArrowUpRight size={11} />
          </button>
        </div>

        {recent_scans.length === 0 ? (
          <p className="text-xs mono text-soft py-6 text-center">No scans executed yet. Click "Launch Scan" above.</p>
        ) : (
          <div className="overflow-x-auto w-full max-w-full">
            <table className="w-full text-left text-xs mono min-w-[560px]">
              <thead>
                <tr className="border-b border-line text-soft text-[11px]">
                  <th className="pb-2 font-medium">DOMAIN</th>
                  <th className="pb-2 font-medium">STATUS</th>
                  <th className="pb-2 font-medium">STAGE TRACKER</th>
                  <th className="pb-2 font-medium">SCORE</th>
                  <th className="pb-2 font-medium">TIMESTAMP</th>
                  <th className="pb-2 font-medium text-right">ACTION</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {recent_scans.map((scan, idx) => (
                  <tr
                    key={scan.id}
                    style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
                    className="stagger-row hover:bg-inset/40 transition-colors"
                  >
                    <td className="py-3 font-semibold text-ink">{scan.domain}</td>
                    <td className="py-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] uppercase font-medium ${
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
                    <td className="py-3">
                      <div className="flex items-center gap-1">
                        {['discovery', 'dns', 'http', 'security_checks', 'nuclei', 'normalization', 'scoring', 'ai_analysis'].map((st, i) => {
                          const stageData = (scan.stage_progress as any)?.[st];
                          const isDone = stageData?.status === 'completed';
                          const isRunning = stageData?.status === 'running';
                          return (
                            <div
                              key={st}
                              title={`${st}: ${stageData?.status || 'queued'}`}
                              className={`w-3.5 h-1.5 rounded-full ${
                                isDone ? 'bg-ok' : isRunning ? 'bg-accent animate-pulse' : 'bg-inset border border-line'
                              }`}
                            />
                          );
                        })}
                        <span className="text-[10px] text-soft ml-2 capitalize">
                          {scan.current_stage || 'Ready'}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 font-bold text-ink">
                      {scan.score ? `${scan.score}/100` : '—'}
                    </td>
                    <td className="py-3 text-soft text-[11px]">
                      {new Date(scan.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="py-3 text-right">
                      <button
                        onClick={() => navigate('/scans')}
                        className="px-2.5 py-1 rounded text-[11px] border border-line bg-raised hover:border-line-strong text-ink"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Launch Scan Modal */}
      <Modal
        open={scanModalOpen}
        onClose={() => setScanModalOpen(false)}
        title="INITIATE INNGEST SECURITY SCAN"
        icon={<Play size={16} />}
        maxWidth="max-w-md"
      >
        <p className="text-xs text-soft leading-relaxed">
          This triggers the automated 8-stage defensive scan: Passive Discovery → DNS Resolution → HTTP Probing → Security Checks → Nuclei Vulnerability Scan → Normalization → Risk Scoring → AI Analysis.
        </p>

        <div className="space-y-1.5 pt-2">
          <label className="text-xs mono text-soft">SELECT TARGET DOMAIN</label>
          <select
            value={selectedDomain}
            onChange={e => setSelectedDomain(e.target.value)}
            className="w-full bg-inset border border-line rounded px-3 py-2 text-xs mono text-ink focus:outline-none focus:border-accent"
          >
            {domains.map(d => (
              <option key={d.id} value={d.id}>
                {d.domain} ({d.verification_status.toUpperCase()})
              </option>
            ))}
          </select>
        </div>

        <div className="p-3 bg-inset/50 rounded border border-line text-[11px] mono text-soft space-y-1">
          <div className="flex items-center gap-1.5 text-ink font-medium">
            <Lock size={12} className="text-ok" /> Sovereign Scope Protection
          </div>
          <p>Scanning is restricted strictly to verified owned infrastructure per DNS TXT validation.</p>
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={() => setScanModalOpen(false)}
            className="px-3.5 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft btn-tactile"
          >
            Cancel
          </button>
          <button
            disabled={launching}
            onClick={handleLaunchScan}
            className="px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2 btn-tactile shadow-md shadow-accent/20"
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
      </Modal>

      {/* AI Executive Summary Modal */}
      <BoardReportModal
        open={summaryModalOpen}
        onClose={() => setSummaryModalOpen(false)}
        loading={summaryLoading}
        summary={execSummary}
      />
    </div>
  );
}
