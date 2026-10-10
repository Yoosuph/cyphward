import { useCallback, useEffect, useRef, useState } from 'react';
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
import { useAuth } from '../lib/auth';
import type { OverviewData, Domain, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const requestId = useRef(0);
  const [launching, setLaunching] = useState(false);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string>('');
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [execSummary, setExecSummary] = useState<ExecutiveSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [greeting, setGreeting] = useState<string | null>(null);

  const { user } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  // One friendly, time-aware greeting per browser session (login process).
  useEffect(() => {
    if (!user) return;
    try {
      if (sessionStorage.getItem('cyphward-greeted') === '1') return;
      const first =
        String(user.full_name || '').trim().split(' ')[0] ||
        (user.email || '').split('@')[0] ||
        '';
      if (!first) return;
      const hour = new Date().getHours();
      const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
      setGreeting(`${part}, ${first} — welcome back.`);
      sessionStorage.setItem('cyphward-greeted', '1');
    } catch {
      /* greeting is best-effort */
    }
  }, [user]);

  const loadData = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const [overview, domainResult] = await Promise.allSettled([getOverview(), getDomains()]);
      if (id !== requestId.current) return;
      if (overview.status === 'fulfilled' && overview.value) {
        setData(overview.value);
        setRefreshFailed(false);
        setLastRefreshed(new Date());
      } else {
        setRefreshFailed(true);
      }
      if (domainResult.status === 'fulfilled') {
        setDomains(domainResult.value);
        setSelectedDomain(current => current || domainResult.value[0]?.id || '');
      }
    } catch (e) {
      if (id === requestId.current) setRefreshFailed(true);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    window.addEventListener('focus', loadData);
    window.addEventListener('online', loadData);
    return () => {
      ++requestId.current;
      clearInterval(interval);
      window.removeEventListener('focus', loadData);
      window.removeEventListener('online', loadData);
    };
  }, [loadData]);

  const handleLaunchScan = async () => {
    setLaunching(true);
    try {
      const res = await launchScan(selectedDomain);
      toast(`Scan started for ${res.domain}.`);
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
        // Honest failure — never fabricate board-level findings.
        setSummaryModalOpen(false);
        toast('Executive summary is unavailable right now. Please try again shortly.');
      }
    } catch (err) {
      console.error('Executive summary error:', err);
      setSummaryModalOpen(false);
      toast('Executive summary is unavailable right now. Please try again shortly.');
    } finally {
      setSummaryLoading(false);
    }
  };

  if (loading && !data) {
    return <OverviewSkeleton />;
  }

  if (!data) {
    return (
      <div className="max-w-7xl mx-auto pb-16 content-fade-in">
        <div className="bg-inset border border-line rounded p-10 text-center space-y-3">
          <AlertTriangle size={22} className="mx-auto text-accent" />
          <p className="text-sm mono">We couldn't load your security overview.</p>
          <p className="text-xs mono text-soft max-w-md mx-auto">
            The API didn't respond. Your data is safe — retry below, or this view will
            refresh automatically every few seconds.
          </p>
          <button
            className="btn btn-solid btn-mini hover-lift"
            onClick={() => { setLoading(true); loadData(); }}
          >
            <RefreshCw size={12} className="mr-1" /> RETRY
          </button>
        </div>
      </div>
    );
  }

  const { score, max_score, grade, posture_label, trend, counts, subscores, factors, recent_scans, organization, assessed, assessment } = data;

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      {/* Header Banner & Quick Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          {greeting && (
            <p className="text-xs mono text-soft mb-1.5">{greeting}</p>
          )}
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <p className="eyebrow text-accent">COMMAND WORKSPACE · {organization.cac_rc || 'CAC REGISTERED'}</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            {organization.name}
          </h1>
          <p className="text-xs mono text-soft mt-1">
            We watch what's exposed online and keep your security score up to date.
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
            <span>START SCAN</span>
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-xs mono">
        <p role="status" className={refreshFailed ? 'text-accent' : 'text-soft'}>
          {refreshFailed ? 'Refresh failed — showing previously loaded data.' : 'Overview up to date.'}
          {lastRefreshed && ` Last loaded ${lastRefreshed.toLocaleTimeString()}.`}
        </p>
        <button className="btn btn-mini" onClick={loadData}>
          <RefreshCw size={12} className="mr-1" /> REFRESH
        </button>
      </div>

      {/* Top Grid: Radial Score Ring & High-level Metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Main Score Gauge */}
        <div className="lg:col-span-4 p-6 rounded-lg border border-line bg-raised/70 backdrop-blur flex flex-col items-center justify-center text-center relative overflow-hidden">
          <div className="absolute top-3 left-4 text-[10px] mono text-soft tracking-wider">
            ORGANIZATION SCORE
          </div>
          <div className="absolute top-3 right-4">
            <span className="text-[10px] mono px-2 py-0.5 rounded border border-line bg-inset text-soft">
              {grade ? `${grade} RATING` : 'NOT ASSESSED'}
            </span>
          </div>

          <div className="my-2">
            {score !== null ? (
              <ScoreRing score={score} max={max_score} size={190} />
            ) : (
              <div
                className="flex flex-col items-center justify-center rounded-full border-2 border-dashed border-line-strong"
                style={{ width: 190, height: 190 }}
              >
                <span className="text-4xl font-bold mono text-soft">—</span>
                <span className="text-[10px] mono text-soft tracking-wider mt-1">NO SCORE YET</span>
              </div>
            )}
          </div>

          <div className="mt-1">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-soft text-accent text-xs mono font-semibold tracking-wider">
              {posture_label}
            </div>
            {assessed ? (
              <div className="text-xs mono text-soft mt-2 space-y-2">
                <p title={data.trend_baseline_at ? `Compared with posture recorded ${new Date(data.trend_baseline_at).toLocaleString()}` : undefined}>
                  7-Day Change: {trend == null ? 'Not enough comparable history' : (
                    <span className={trend > 0 ? 'text-ok font-medium' : trend < 0 ? 'text-accent font-medium' : 'text-soft'}>
                      {trend > 0 ? '+' : ''}{trend.toFixed(1)} pts
                    </span>
                  )}
                </p>
                {assessment?.completed_at && (
                  <p>Latest completed scan: {new Date(assessment.completed_at).toLocaleString()}</p>
                )}
                {data.risk_points != null && (
                  <p>{data.risk_points} risk points across {counts.total_findings} open findings</p>
                )}
                <p>Scores change when open risk changes. Scan coverage determines what was checked.</p>
              </div>
            ) : (
              <p className="text-xs mono text-soft mt-2">
                Run your first scan to get a score.
              </p>
            )}
          </div>
        </div>

        {/* 4 Stat Cards */}
        <div className="lg:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div
            onClick={() => navigate('/assets')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-line-strong card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase">Assets Found</span>
              <Server size={15} className="group-hover:text-accent transition-colors" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-ink">{counts.total_assets}</div>
              <p className="text-[11px] text-soft">Across {organization.domains_count || 1} domains</p>
            </div>
            <div className="text-[10px] mono text-accent flex items-center gap-1">
              View assets <ArrowUpRight size={10} />
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
              <p className="text-[11px] text-soft">Confirmed with a DNS TXT record</p>
            </div>
            <div className="text-[10px] mono text-ok flex items-center gap-1">
              Verified and secure <CheckCircle2 size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/findings?severity=critical')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-accent card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase text-accent font-medium">Critical Issues</span>
              <ShieldAlert size={15} className="text-accent" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-accent">{counts.critical}</div>
              <p className="text-[11px] text-soft">Requires immediate fix</p>
            </div>
            <div className="text-[10px] mono text-accent flex items-center gap-1">
              Review issues <ArrowUpRight size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/findings')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-line-strong card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase">Total Issues</span>
              <AlertTriangle size={15} className="group-hover:text-accent transition-colors" />
            </div>
            <div className="my-2">
              <div className="text-3xl font-bold mono text-ink">{counts.total_findings}</div>
              <p className="text-[11px] text-soft">{counts.high} High · {counts.medium} Med</p>
            </div>
            <div className="text-[10px] mono text-soft flex items-center gap-1">
              All issues <ArrowUpRight size={10} />
            </div>
          </div>

          {/* Severity Breakdown Bar across all 4 columns */}
          <div className="col-span-2 md:col-span-4 p-4 rounded-lg border border-line bg-inset/50">
            <div className="flex items-center justify-between mb-2">
              <span className="eyebrow">ISSUES BY SEVERITY</span>
              <span className="text-xs mono text-soft">{counts.total_findings} open issues</span>
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
              CATEGORY HEALTH
            </h3>
            <span className="text-[10px] mono text-soft">
              {assessed && assessment?.completed_at
                ? `OUT OF 100 · ASSESSED ${new Date(assessment.completed_at).toLocaleDateString()}`
                : 'OUT OF 100'}
            </span>
          </div>

          <p className="text-xs text-soft mb-4">
            Each category is rated independently. The organization score accounts for all open findings.
          </p>
          <div className="space-y-4">
            {subscores.length === 0 ? (
              <p className="text-xs mono text-soft py-6 text-center">
                Not assessed yet — complete a scan to see your pillar breakdown.
              </p>
            ) : subscores.map(pillar => (
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
              <span className="text-[10px] mono text-soft">WHAT'S AFFECTING YOUR SCORE</span>
            </div>

            <div className="space-y-2.5">
              {factors.length === 0 ? (
                <p className="text-xs mono text-soft py-4 text-center">
                  Score drivers appear after your first completed scan.
                </p>
              ) : factors.map((f, idx) => (
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
              See all issues <ArrowUpRight size={11} />
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
              RECENT SCANS
            </h3>
          </div>
          <button
            onClick={() => navigate('/scans')}
            className="text-xs mono text-accent hover:underline flex items-center gap-1"
          >
            See all scans <ArrowUpRight size={11} />
          </button>
        </div>

        {recent_scans.length === 0 ? (
          <p className="text-xs mono text-soft py-6 text-center">No scans yet. Click "Start scan" above.</p>
        ) : (
          <div className="overflow-x-auto w-full max-w-full">
            <table className="w-full text-left text-xs mono min-w-[560px]">
              <thead>
                <tr className="border-b border-line text-soft text-[11px]">
                  <th className="pb-2 font-medium">DOMAIN</th>
                  <th className="pb-2 font-medium">STATUS</th>
                  <th className="pb-2 font-medium">PROGRESS</th>
                  <th className="pb-2 font-medium">SCORE</th>
                  <th className="pb-2 font-medium">STARTED</th>
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
                        {['discovery', 'dns', 'http', 'ports', 'tls', 'nuclei', 'security_checks', 'normalization', 'scoring', 'ai_analysis'].map((st, i) => {
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
                      {scan.score != null ? `${scan.score}/100` : '—'}
                      {scan.score != null && (
                        <div className="text-[10px] font-normal text-soft">
                          {scan.stage_progress?.scoring?.scope === 'organization' ? 'Organization at scan completion' : 'Legacy scan score'}
                        </div>
                      )}
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
        title="Start security scan"
        icon={<Play size={16} />}
        maxWidth="max-w-md"
      >
        <p className="text-xs text-soft leading-relaxed">
          This starts an automated security scan: public records → DNS settings → website
          response → open ports → SSL/TLS → security checks → known vulnerabilities → tidy
          up results → security score → AI summary.
        </p>

        <div className="space-y-1.5 pt-2">
          <label className="text-xs mono text-soft">CHOOSE A DOMAIN</label>
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
            <Lock size={12} className="text-ok" /> Only your verified domains
          </div>
          <p>We only scan domains you own and have confirmed with a DNS TXT record.</p>
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
                <Play size={13} fill="currentColor" /> Start scan
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
