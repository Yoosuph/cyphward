import { useCallback, useEffect, useRef, useState } from 'react';
import { PageHead } from '../components/ui';
import { SeverityDot } from '../components/ui/SeverityBadge';
import { ErrorPanel } from '../components/ui/StatePanels';
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
import { writeGuard } from '../lib/suspension';
import { useOrgSuspended } from '../lib/useOrgSuspended';
import { useAuth } from '../lib/auth';
import type { OverviewData, Domain, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';
import SetupChecklist from '../components/SetupChecklist';
import { startTour, tourSeen } from '../lib/tour';
import { readPageCache, writePageCache } from '../lib/pageCache';

export default function Overview() {
  // Last-seen overview paints at once on a revisit; loadData refreshes it.
  const [data, setData] = useState<OverviewData | null>(() => readPageCache<OverviewData>('overview') ?? null);
  const [loading, setLoading] = useState(() => readPageCache('overview') === undefined);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const requestId = useRef(0);
  const [launching, setLaunching] = useState(false);
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [domains, setDomains] = useState<Domain[]>(() => readPageCache<Domain[]>('overview:domains') ?? []);
  const [domainsLoaded, setDomainsLoaded] = useState(() => readPageCache('overview:domains') !== undefined);
  const [selectedDomain, setSelectedDomain] = useState<string>(
    () => readPageCache<Domain[]>('overview:domains')?.find(d => d.verification_status === 'verified')?.id || '',
  );
  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [execSummary, setExecSummary] = useState<ExecutiveSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [greeting, setGreeting] = useState<string | null>(null);

  const { user, primaryDomain, organization: activeOrganization } = useAuth();
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
      setGreeting(`${part}, ${first}.`);
      sessionStorage.setItem('cyphward-greeted', '1');
    } catch {
      /* greeting is best-effort */
    }
  }, [user]);

  // First-run tour: only for a workspace that has never completed a scan, once
  // per user. Established workspaces never get it unprompted.
  const tourChecked = useRef(false);
  const [tourDue, setTourDue] = useState(false);
  useEffect(() => {
    if (tourChecked.current || !data || !domainsLoaded || !user?.id) return;
    tourChecked.current = true;
    if (!data.recent_scans.some(scan => scan.status === 'completed') && !tourSeen(user.id)) setTourDue(true);
  }, [data, domainsLoaded, user?.id]);
  useEffect(() => {
    if (!tourDue) return;
    const id = setTimeout(startTour, 900); // Cancelled only if the user leaves Overview first.
    return () => clearTimeout(id);
  }, [tourDue]);

  const loadData = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const [overview, domainResult] = await Promise.allSettled([getOverview(), getDomains()]);
      if (id !== requestId.current) return;
      if (overview.status === 'fulfilled' && overview.value) {
        setData(overview.value);
        writePageCache('overview', overview.value);
        setRefreshFailed(false);
        setLastRefreshed(new Date());
      } else {
        setRefreshFailed(true);
      }
      if (domainResult.status === 'fulfilled') {
        setDomains(domainResult.value);
        writePageCache('overview:domains', domainResult.value);
        setDomainsLoaded(true);
        setSelectedDomain(current => domainResult.value.some(d => d.id === current && d.verification_status === 'verified')
          ? current : domainResult.value.find(d => d.verification_status === 'verified')?.id || '');
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
      if (err.code === 'scan_already_active') {
        toast('A scan is already active for this domain. Opening scan history.');
        setScanModalOpen(false);
        navigate('/scans', { state: { scanId: err.scanId } });
        return;
      }
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
      <div className="max-w-7xl mx-auto pb-16 content-fade-in space-y-6">
        <PageHead title="Overview" note="Your score, open issues and latest scans." />
        <ErrorPanel
          title="We could not load your security overview"
          message="Cyphward did not respond. Try again, or wait: this page checks again every few seconds."
          onRetry={() => { setLoading(true); loadData(); }}
          retrying={loading}
        />
      </div>
    );
  }

  const { score, max_score, grade, posture_label, trend, counts, subscores, factors, recent_scans, organization, assessed, assessment } = data;
  const scopeLabel = data.scope_label?.trim() || null;
  const domainCoverageLine = data.domain_coverage_line?.trim() || null;
  const nucleiLabel = assessment?.coverage?.version === 2 ? assessment.coverage.nuclei?.label?.trim() || null : null;
  const verifiedDomains = domains.filter(d => d.verification_status === 'verified');
  const pendingDomain = domains.find(d => d.verification_status !== 'verified');
  const canManageDomains = ['owner', 'admin'].includes(activeOrganization?.membership_role || 'member');
  const suspended = useOrgSuspended();

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      <PageHead
        title={organization.name}
        note={greeting || 'Your score, open issues and latest scans.'}
        actions={<>
          <button type="button" onClick={loadData} aria-label="Refresh" title="Refresh"
            className="flex items-center justify-center gap-2 px-3 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink transition-colors min-h-[38px] btn-tactile">
            <RefreshCw size={14} /> <span className="sm:hidden">REFRESH</span>
          </button>
          <button
            onClick={handleOpenSummary}
            className="flex items-center justify-center gap-2 px-3.5 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink transition-colors min-h-[38px] btn-tactile"
          >
            <Sparkles size={14} className="text-accent" />
            <span>GENERATE BOARD REPORT</span>
          </button>

          <button
            data-tour="start-scan"
            data-write="scan-launch"
            // Until the domain list loads (or if it fails), never send the user to
            // "add a domain": the Scans page loads its own list and launcher.
            onClick={() => !domainsLoaded ? navigate('/scans') : verifiedDomains.length ? setScanModalOpen(true) : navigate(pendingDomain ? '/domains' : '/onboarding/add-domain')}
            {...writeGuard(suspended, !canManageDomains)}
            className="flex items-center justify-center gap-2 px-4 py-2 rounded text-xs mono font-medium bg-accent text-white disabled:opacity-50 hover:opacity-90 shadow-md shadow-accent/20 transition-all min-h-[38px] btn-tactile"
          >
            <Play size={13} fill="currentColor" />
            <span>{!canManageDomains ? 'WAITING FOR ADMIN' : !domainsLoaded || verifiedDomains.length ? 'START SCAN' : pendingDomain ? 'VERIFY DOMAIN' : 'ADD DOMAIN'}</span>
          </button>
        </>}
      />

      {domainsLoaded && (
        <SetupChecklist
          canManage={canManageDomains}
          onTour={startTour}
          steps={[
            { key: 'workspace', label: 'Create your workspace', hint: '', done: true },
            {
              key: 'domain', label: 'Add a domain', done: domains.length > 0,
              hint: 'Usually your main website, like example.com.',
              action: { label: 'ADD DOMAIN', onClick: () => navigate('/onboarding/add-domain') },
            },
            {
              key: 'verify', label: 'Verify you own it', done: verifiedDomains.length > 0,
              hint: pendingDomain ? `Add one DNS TXT record for ${pendingDomain.domain}. Nothing is scanned before that.` : 'Add one DNS TXT record.',
              action: { label: 'VERIFY DOMAIN', onClick: () => navigate(pendingDomain && primaryDomain?.id === pendingDomain.id ? '/onboarding/verify-domain' : '/domains') },
            },
            {
              key: 'scan', label: 'Run your first scan', done: recent_scans.length > 0,
              hint: 'Usually takes 30–45 minutes. You can leave this page while it runs.',
              action: { label: 'START SCAN', onClick: () => setScanModalOpen(true) },
            },
            {
              key: 'review', label: 'Review your score and findings', done: recent_scans.some(scan => scan.status === 'completed'),
              hint: recent_scans.some(scan => scan.status === 'queued' || scan.status === 'running')
                ? 'Your first scan is running. Results appear here when it finishes.'
                : 'Open the scan to see what was checked and what to fix first.',
              action: { label: 'OPEN SCANS', onClick: () => navigate('/scans') },
            },
          ]}
        />
      )}

      {refreshFailed && (
        <p role="status" className="text-xs text-accent">
          Couldn't refresh. Showing the last loaded data.{' '}
          <button type="button" className="underline" onClick={loadData}>Try again</button>
        </p>
      )}

      {/* Top Grid: Radial Score Ring & High-level Metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Main Score Gauge */}
        <div data-tour="score" className="lg:col-span-4 p-6 rounded-lg border border-line bg-raised/70 flex flex-col items-center text-center">
          <div className="w-full flex items-center justify-between gap-2 text-[11px] mono text-soft">
            <span>SECURITY SCORE</span>
            <span className="px-2 py-0.5 rounded border border-line bg-inset">
              {grade ? `${grade} RATING` : assessment?.coverage?.state === 'partial' ? 'PARTIAL' : 'NO RATING'}
            </span>
          </div>

          <div className="my-3">
            {score !== null ? (
              <ScoreRing score={score} max={max_score} size={176} />
            ) : (
              <div
                className="flex flex-col items-center justify-center rounded-full border-2 border-dashed border-line-strong"
                style={{ width: 176, height: 176 }}
              >
                <span className="text-4xl font-bold mono text-soft">—</span>
                <span className="text-[10px] mono text-soft tracking-wider mt-1">NO SCORE YET</span>
              </div>
            )}
          </div>

          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-soft text-accent text-xs mono font-semibold tracking-wider">
            {posture_label}{grade && scopeLabel ? ' · within declared scope' : ''}
          </div>
          <p className="text-sm text-soft mt-2">
            {assessed
              ? <>
                  {assessment?.completed_at ? `Last scan ${new Date(assessment.completed_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}` : 'Score from your latest scan'}
                  {trend != null && trend !== 0 && (
                    <span className={trend > 0 ? 'text-ok' : 'text-accent'}> · {trend > 0 ? '+' : ''}{trend.toFixed(1)} pts this week</span>
                  )}
                </>
              : assessment ? 'Not enough evidence for a score yet.' : 'Run your first scan to get a score.'}
          </p>
          {!grade && domainCoverageLine && (
            <p className="text-[11px] mono text-soft mt-1.5 max-w-[280px] break-words">{domainCoverageLine}</p>
          )}

          {(assessment || nucleiLabel) && (
            <details className="score-details">
              <summary>What this score covers</summary>
              <div className="space-y-1.5">
                {grade && domainCoverageLine && <p>{domainCoverageLine}</p>}
                {data.risk_points != null && <p>{data.risk_points} risk points across {counts.total_findings} open findings.</p>}
                {grade
                  ? <p>The grade applies to the checks we declare: SPF, DMARC, HTTP headers, TLS certificates and open ports on each verified domain.</p>
                  : <p>Known-risk scores reflect recorded open findings. Partial coverage does not establish whole-organization security.</p>}
                {nucleiLabel && <p>{nucleiLabel}</p>}
              </div>
            </details>
          )}
        </div>

        {/* 4 Stat Cards */}
        <div className="lg:col-span-8 grid grid-cols-2 md:grid-cols-4 gap-4 content-start">
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
              <p className="text-[11px] text-soft">Across {organization.domains_count ?? 0} domains</p>
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
              <div className="text-3xl font-bold mono text-ink">{organization.verified_domains_count ?? 0}</div>
              <p className="text-[11px] text-soft">Confirmed with a DNS TXT record</p>
            </div>
            <div className="text-[10px] mono text-ok flex items-center gap-1">
              {(organization.verified_domains_count ?? 0) > 0 ? 'Verified' : 'Verification needed'} <CheckCircle2 size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/findings?severity=critical')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-accent card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className={`text-[11px] mono uppercase font-medium ${counts.critical ? 'text-accent' : 'text-soft'}`}>Critical Issues</span>
              <ShieldAlert size={15} className={counts.critical ? 'text-accent' : ''} />
            </div>
            <div className="my-2">
              <div className={`text-3xl font-bold mono ${counts.critical ? 'text-accent' : 'text-ink'}`}>{counts.critical}</div>
              <p className="text-[11px] text-soft">{counts.critical ? 'Fix these first' : 'Nothing urgent'}</p>
            </div>
            <div className={`text-[10px] mono flex items-center gap-1 ${counts.critical ? 'text-accent' : 'text-soft'}`}>
              Review issues <ArrowUpRight size={10} />
            </div>
          </div>

          <div
            onClick={() => navigate('/findings')}
            className="p-4 rounded-lg border border-line bg-raised hover:border-line-strong card-hover transition-all cursor-pointer flex flex-col justify-between group"
          >
            <div className="flex items-center justify-between text-soft">
              <span className="text-[11px] mono uppercase">Open Issues</span>
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
                style={{ width: `${(counts.critical / Math.max(1, counts.total_findings)) * 100}%` }}
                className="bg-accent h-full rounded-l-full transition-all"
                title={`Critical: ${counts.critical}`}
              />
              <div
                style={{ width: `${(counts.high / Math.max(1, counts.total_findings)) * 100}%` }}
                className="sev-bar sev-high h-full transition-all"
                title={`High: ${counts.high}`}
              />
              <div
                style={{ width: `${(counts.medium / Math.max(1, counts.total_findings)) * 100}%` }}
                className="sev-bar sev-medium h-full transition-all"
                title={`Medium: ${counts.medium}`}
              />
              <div
                style={{ width: `${(counts.low / Math.max(1, counts.total_findings)) * 100}%` }}
                className="sev-bar sev-low h-full transition-all"
                title={`Low: ${counts.low}`}
              />
              <div
                style={{ width: `${(counts.info / Math.max(1, counts.total_findings)) * 100}%` }}
                className="sev-bar sev-info h-full rounded-r-full transition-all"
                title={`Info: ${counts.info}`}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-[11px] mono text-ink">
              {([['critical', 'Critical', counts.critical], ['high', 'High', counts.high], ['medium', 'Medium', counts.medium], ['low', 'Low', counts.low], ['info', 'Info', counts.info]] as const).map(([key, label, n]) => (
                <span key={key} className="flex items-center gap-1.5">
                  <SeverityDot severity={key} /> {label} ({n ?? 0})
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Middle Grid: 4 Security Pillars Subscores & Factors */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* 4 Pillars Breakdown */}
        <div className="lg:col-span-7 p-5 rounded-lg border border-line bg-raised">
          <div className="flex items-center justify-between pb-3 border-b border-line mb-4">
            <h2 className="mono text-xs font-semibold tracking-wider text-ink">
              CATEGORY HEALTH
            </h2>
            <span className="text-[10px] mono text-soft">
              {assessed && assessment?.completed_at
                ? `OUT OF 100 · ASSESSED ${new Date(assessment.completed_at).toLocaleDateString()}`
                : 'OUT OF 100'}
            </span>
          </div>

          <div className="space-y-4">
            {subscores.length === 0 ? (
              <p className="text-xs mono text-soft py-6 text-center">
                Category ratings require sufficient evaluated evidence. Unchecked areas remain unknown.
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
              <h2 className="mono text-xs font-semibold tracking-wider text-ink">
                TOP ISSUES &amp; STRENGTHS
              </h2>
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
            <h2 className="mono text-xs font-semibold tracking-wider text-ink">
              RECENT SCANS
            </h2>
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
            <table className="table-stack w-full text-left text-xs mono sm:min-w-[560px]">
              <thead>
                <tr className="border-b border-line text-soft text-[11px]">
                  <th className="pb-2 font-medium">DOMAIN</th>
                  <th className="pb-2 font-medium">STATUS</th>
                  <th className="pb-2 font-medium hidden md:table-cell">PROGRESS</th>
                  <th className="pb-2 font-medium">SCORE</th>
                  <th className="pb-2 font-medium hidden md:table-cell">STARTED</th>
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
                    <td className="stack-title py-3 font-semibold text-ink">{scan.domain}</td>
                    <td data-label="Status" className="py-3">
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
                    <td data-label="Progress" className="py-3 hidden md:table-cell">
                      {scan.status === 'queued' || scan.status === 'running' ? (
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
                      ) : (
                        <span className={`text-[11px] ${scan.status === 'failed' ? 'text-accent' : 'text-soft'}`}>
                          {scan.status === 'failed' ? 'Failed' : scan.status === 'cancelled' ? 'Cancelled' : 'Finished'}
                        </span>
                      )}
                    </td>
                    <td data-label="Score" className="py-3 font-bold text-ink">
                      {scan.score != null ? `${scan.score}/100` : '—'}
                      {scan.score != null && scan.stage_progress?.scoring?.scope !== 'organization' && (
                        <div className="text-[10px] font-normal text-soft" title="Scored with an earlier model; not comparable with current scores">
                          Legacy score
                        </div>
                      )}
                    </td>
                    <td data-label="Started" className="py-3 text-soft text-[11px] hidden md:table-cell">
                      {new Date(scan.created_at).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="stack-actions py-3 text-right">
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
          <label htmlFor="scan-domain" className="text-xs mono text-soft">CHOOSE A DOMAIN</label>
          <select
            id="scan-domain"
            value={selectedDomain}
            onChange={e => setSelectedDomain(e.target.value)}
            className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-xs mono text-ink focus:outline-none focus:border-accent"
          >
            {verifiedDomains.map(d => (
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
            {...writeGuard(suspended, launching || !selectedDomain)}
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
