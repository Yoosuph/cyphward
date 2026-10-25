import { useEffect, useRef, useState } from 'react';
import { PageHead } from '../components/ui';
import {
  ShieldAlert,
  AlertTriangle,
  Info,
  CheckCircle2,
  RefreshCw,
  Search,
  Sparkles,
  Terminal,
  Copy,
  Check,
  Code,
  X,
  ArrowUpRight,
  ExternalLink,
  Layers,
} from 'lucide-react';
import { getFindings, updateFindingStatus, explainFinding, getRemediation } from '../lib/api';
import type { Finding, FindingSeverity, FindingStatus, FindingExplanation, RemediationGuide } from '../types';
import { useToast } from '../components/Toast';
import { readPageCache, writePageCache } from '../lib/pageCache';
import { FindingCardSkeleton, Skeleton, SkeletonText, FindingsSkeleton } from '../components/Skeleton';
import Drawer from '../components/Drawer';
import Modal from '../components/Modal';

type FindingsCache = { findings: Finding[]; categories: Record<string, number> };
const FINDINGS_DEFAULT_KEY = 'findings:all:all:';

export default function Findings() {
  // Last-seen list paints at once on a revisit; loadFindings refreshes it.
  const [findings, setFindings] = useState<Finding[]>(() => readPageCache<FindingsCache>(FINDINGS_DEFAULT_KEY)?.findings ?? []);
  const [loading, setLoading] = useState(() => readPageCache(FINDINGS_DEFAULT_KEY) === undefined);
  const shownKey = useRef<string | null>(null); // cache key of the rows on screen
  const [selectedSeverity, setSelectedSeverity] = useState<string>('all');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [statusView, setStatusView] = useState<'open' | 'resolved' | 'all'>('open');
  const [categories, setCategories] = useState<Record<string, number>>(() => readPageCache<FindingsCache>(FINDINGS_DEFAULT_KEY)?.categories ?? {});

  // Active drawer finding
  const [activeFinding, setActiveFinding] = useState<Finding | null>(null);

  // AI Explanation Modal State
  const [explainModalOpen, setExplainModalOpen] = useState(false);
  const [explanation, setExplanation] = useState<FindingExplanation | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState(false);
  const explainRequest = useRef(0);

  // AI Remediation Assistant State
  const [remediationDrawerOpen, setRemediationDrawerOpen] = useState(false);
  const [remediationGuide, setRemediationGuide] = useState<RemediationGuide | null>(null);
  const [remediationFinding, setRemediationFinding] = useState<Finding | null>(null);
  const [remediating, setRemediating] = useState(false);
  const [remediationError, setRemediationError] = useState(false);
  const remediationRequest = useRef(0);
  const [selectedStack, setSelectedStack] = useState<string>('nginx');

  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedCurl, setCopiedCurl] = useState(false);

  const toast = useToast();

  const loadFindings = async () => {
    const cacheKey = `findings:${selectedSeverity}:${selectedCategory}:${search}`;
    const cached = readPageCache<FindingsCache>(cacheKey);
    if (cached) {
      setFindings(cached.findings);
      setCategories(cached.categories);
    }
    // Skeleton only when this view has nothing to show yet (not on a refresh).
    if (cached === undefined && shownKey.current !== cacheKey) setLoading(true);
    else if (cached) setLoading(false);
    shownKey.current = cacheKey;
    try {
      const res = await getFindings({
        severity: selectedSeverity !== 'all' ? selectedSeverity : undefined,
        category: selectedCategory !== 'all' ? selectedCategory : undefined,
        search: search || undefined,
      });
      setFindings(res.findings);
      setCategories(res.categories);
      writePageCache<FindingsCache>(cacheKey, { findings: res.findings, categories: res.categories });
      if (activeFinding) {
        const updated = res.findings.find(f => f.id === activeFinding.id);
        if (updated) setActiveFinding(updated);
      }
    } catch (err) {
      toast('Failed to load issues');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadFindings();
  }, [selectedSeverity, selectedCategory]);

  const handleStatusChange = async (findingId: string, newStatus: FindingStatus) => {
    try {
      const updated = await updateFindingStatus(findingId, newStatus);
      toast(`Issue marked as ${newStatus}`);
      setFindings(prev => prev.map(f => (f.id === findingId ? { ...f, status: newStatus } : f)));
      if (activeFinding && activeFinding.id === findingId) {
        setActiveFinding(prev => (prev ? { ...prev, status: newStatus } : null));
      }
    } catch (e) {
      toast('Status update failed');
    }
  };

  const handleTriggerExplain = async (finding: Finding) => {
    const request = ++explainRequest.current;
    setExplanation(null);
    setExplainError(false);
    setExplainModalOpen(true);
    setExplaining(true);
    try {
      const exp = await explainFinding(finding.id, finding);
      if (request === explainRequest.current) setExplanation(exp);
    } catch (e) {
      if (request === explainRequest.current) {
        setExplainError(true);
        toast('Could not load the explanation. Please try again.');
      }
    } finally {
      if (request === explainRequest.current) setExplaining(false);
    }
  };

  const handleTriggerRemediate = async (finding: Finding, stack: string = selectedStack) => {
    const request = ++remediationRequest.current;
    setRemediationFinding(finding);
    setRemediationGuide(null);
    setRemediationError(false);
    setSelectedStack(stack);
    setRemediationDrawerOpen(true);
    setRemediating(true);
    try {
      const guide = await getRemediation(finding.id, stack, finding);
      if (request === remediationRequest.current) setRemediationGuide(guide);
    } catch (e) {
      if (request === remediationRequest.current) {
        setRemediationError(true);
        toast('Could not build the fix guide. Please try again.');
      }
    } finally {
      if (request === remediationRequest.current) setRemediating(false);
    }
  };

  const copyToClipboard = (text: string, isCurl: boolean = false) => {
    navigator.clipboard.writeText(text);
    if (isCurl) {
      setCopiedCurl(true);
      setTimeout(() => setCopiedCurl(false), 2000);
    } else {
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 2000);
    }
    toast('Copied to clipboard');
  };

  const severities = ['all', 'critical', 'high', 'medium', 'low', 'info'];
  const openCount = findings.filter(f => f.status !== 'resolved').length;
  const visible = findings.filter(f => statusView === 'all' || (statusView === 'resolved' ? f.status === 'resolved' : f.status !== 'resolved'));
  const filtered = selectedSeverity !== 'all' || selectedCategory !== 'all' || !!search;

  if (loading && findings.length === 0) {
    return <FindingsSkeleton />;
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      <PageHead
        title="Findings"
        note="Security issues from your scans, worst first. Open one to see the evidence and how to fix it."
        actions={
          <button
            onClick={loadFindings}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono border border-line bg-raised hover:border-line-strong text-ink transition-colors btn-tactile"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        }
      />

      {/* Open / resolved view: resolved issues no longer mix into the default list */}
      <div className="flex flex-wrap items-center gap-1 p-1 rounded-md border border-line bg-raised w-fit" role="tablist" aria-label="Issue status">
        {([['open', 'Open', openCount], ['resolved', 'Resolved', findings.length - openCount], ['all', 'All', findings.length]] as const).map(([key, label, count]) => (
          <button
            key={key}
            role="tab"
            aria-selected={statusView === key}
            onClick={() => setStatusView(key)}
            className={`px-3 py-1 rounded text-xs mono transition-colors ${statusView === key ? 'bg-ink text-bg font-semibold' : 'text-soft hover:text-ink'}`}
          >
            {label} <span className="opacity-70">{count}</span>
          </button>
        ))}
      </div>

      {/* Severity Filter Tabs */}
      <div className="chip-row flex flex-wrap items-center gap-2">
        {severities.map(sev => (
          <button
            key={sev}
            onClick={() => setSelectedSeverity(sev)}
            className={`px-3 py-1 rounded text-xs mono uppercase transition-all btn-tactile ${
              selectedSeverity === sev
                ? sev === 'critical'
                  ? 'bg-accent text-white font-bold shadow-sm shadow-accent/20'
                  : sev === 'high'
                  ? 'bg-amber-600 text-white font-bold'
                  : 'bg-ink text-bg font-bold'
                : 'bg-raised border border-line text-soft hover:text-ink'
            }`}
          >
            {sev}
          </button>
        ))}

        <div className="ml-auto w-full md:w-64 relative mt-2 md:mt-0">
          <Search size={13} className="absolute left-3 top-2.5 text-soft" />
          <input
            type="text"
            placeholder="Search issues..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadFindings()}
            className="w-full pl-8 pr-3 py-1 rounded bg-raised border border-line text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
          />
        </div>
      </div>

      {/* Findings List */}
      <div className="space-y-3">
        {loading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <FindingCardSkeleton key={i} />
          ))
        ) : visible.length === 0 ? (
          <div className="p-12 text-center border border-line rounded-lg bg-raised">
            <CheckCircle2 size={24} className="text-ok mx-auto mb-2" />
            <p className="text-sm text-ink font-semibold">
              {filtered ? 'Nothing matches these filters.' : statusView === 'resolved' ? 'No resolved issues yet.' : statusView === 'open' ? 'No open issues.' : 'No issues recorded yet.'}
            </p>
            {!filtered && statusView === 'open' && (
              <p className="text-xs text-soft mt-1">New scans add any issues they find here.</p>
            )}
          </div>
        ) : (
          visible.map((finding, idx) => (
            <div
              key={finding.id}
              onClick={() => setActiveFinding(finding)}
              style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
              className={`p-4 rounded-lg border transition-all cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-4 group stagger-row card-hover ${
                activeFinding?.id === finding.id
                  ? 'border-accent bg-raised shadow-md'
                  : finding.status === 'resolved'
                  ? 'border-line/40 bg-raised/40 opacity-70'
                  : 'border-line bg-raised hover:border-line-strong'
              }`}
            >
              <div className="space-y-1.5 flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] mono uppercase font-bold ${
                      finding.severity === 'critical'
                        ? 'bg-accent text-white'
                        : finding.severity === 'high'
                        ? 'bg-amber-600 text-white'
                        : finding.severity === 'medium'
                        ? 'bg-amber-400 text-black'
                        : finding.severity === 'low'
                        ? 'bg-blue-500 text-white'
                        : 'bg-emerald-500 text-white'
                    }`}
                  >
                    {finding.severity}
                  </span>
                  <span className="text-[10px] mono px-2 py-0.5 rounded border border-line bg-inset text-soft">
                    {finding.category}
                  </span>
                  {finding.hostname && (
                    <span className="text-[11px] mono text-soft font-medium">
                      @ {finding.hostname}
                    </span>
                  )}
                  {finding.status === 'resolved' && (
                    <span className="text-[10px] mono text-ok flex items-center gap-1 font-bold">
                      <Check size={11} /> RESOLVED
                    </span>
                  )}
                </div>

                <h3 className="font-semibold text-ink text-sm group-hover:text-accent transition-colors">
                  {finding.title}
                </h3>
                <p className="text-xs text-soft line-clamp-2 leading-relaxed">
                  {finding.description}
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0 self-end md:self-center" onClick={e => e.stopPropagation()}>
                <button
                  onClick={() => handleTriggerExplain(finding)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs mono border border-line bg-inset hover:border-accent text-ink transition-colors"
                  title="Ask CyphBot about this issue"
                >
                  <Sparkles size={12} className="text-accent" />
                  <span className="hidden sm:inline">Ask CyphBot</span>
                </button>

                {finding.status !== 'resolved' && (
                  <button
                    onClick={() => handleTriggerRemediate(finding)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 transition-opacity"
                  >
                    <span>How to fix</span>
                    <ArrowUpRight size={12} />
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Interactive Evidence Drawer */}
      <Drawer
        open={!!activeFinding}
        onClose={() => setActiveFinding(null)}
        size="2xl"
        eyebrow="ISSUE DETAILS"
        title="Issue details"
        icon={<Terminal size={16} />}
      >
        {activeFinding && (
          <div className="space-y-5 pt-2 text-xs content-fade-in">
            {/* Finding Title & Metadata */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded text-[10px] mono uppercase font-bold ${
                    activeFinding.severity === 'critical'
                      ? 'bg-accent text-white'
                      : activeFinding.severity === 'high'
                      ? 'bg-amber-600 text-white'
                      : 'bg-amber-400 text-black'
                  }`}
                >
                  {activeFinding.severity}
                </span>
                <span className="text-[10px] mono px-2 py-0.5 rounded border border-line bg-inset text-soft">
                  {activeFinding.category}
                </span>
              </div>
              <h2 className="text-base font-bold text-ink">{activeFinding.title}</h2>
              <p className="text-soft leading-relaxed">{activeFinding.description}</p>
            </div>

            {/* Target Asset Profile */}
            <div className="p-3 bg-inset rounded border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 mono text-[11px]">
              <div className="truncate">
                <span className="text-soft">HOST:</span>{' '}
                <span className="font-bold text-ink">{activeFinding.hostname || 'All domains'}</span>
              </div>
              <div>
                <span className="text-soft">IP:</span>{' '}
                <span className="text-ink">{activeFinding.ip_address || '—'}</span>
              </div>
            </div>

            {/* Status Action Row */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between p-3 rounded bg-inset/60 border border-line gap-2">
              <span className="mono text-[11px] text-soft">Status:</span>
              <div className="flex flex-wrap items-center gap-1.5 mono text-[10px]">
                <button
                  onClick={() => handleStatusChange(activeFinding.id, 'open')}
                  className={`px-2.5 py-1 rounded border btn-tactile ${
                    activeFinding.status === 'open' ? 'bg-amber-500/20 border-amber-500 text-amber-500 font-bold' : 'border-line text-soft'
                  }`}
                >
                  OPEN
                </button>
                <button
                  onClick={() => handleStatusChange(activeFinding.id, 'resolved')}
                  className={`px-2.5 py-1 rounded border btn-tactile ${
                    activeFinding.status === 'resolved' ? 'bg-ok/20 border-ok text-ok font-bold' : 'border-line text-soft'
                  }`}
                >
                  RESOLVED
                </button>
                <button
                  onClick={() => handleStatusChange(activeFinding.id, 'acknowledged')}
                  className={`px-2.5 py-1 rounded border btn-tactile ${
                    activeFinding.status === 'acknowledged' ? 'bg-raised border-accent text-accent font-bold' : 'border-line text-soft'
                  }`}
                >
                  ACKNOWLEDGED
                </button>
                <button
                  onClick={() => handleStatusChange(activeFinding.id, 'in_progress')}
                  className={`px-2.5 py-1 rounded border btn-tactile ${
                    activeFinding.status === 'in_progress' ? 'bg-raised border-soft text-soft font-bold' : 'border-line text-soft'
                  }`}
                >
                  IN PROGRESS
                </button>
              </div>
            </div>

            {/* Structured Technical Evidence */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="mono text-[11px] font-bold text-ink uppercase tracking-wider flex items-center gap-1.5">
                  <Code size={13} className="text-accent" /> Evidence we collected
                </h4>
                {activeFinding.evidence?.curl_reproduction && (
                  <button
                    onClick={() => copyToClipboard(activeFinding.evidence.curl_reproduction, true)}
                    className="text-[10px] mono text-accent hover:underline flex items-center gap-1"
                  >
                    {copiedCurl ? <Check size={10} /> : <Copy size={10} />} Copy Curl
                  </button>
                )}
              </div>

              <div className="p-3 rounded-lg bg-black text-emerald-400 font-mono text-[11px] overflow-x-auto border border-line">
                <pre>{JSON.stringify(activeFinding.evidence, null, 2)}</pre>
              </div>
            </div>

            {/* Recommended Remediation Blueprint */}
            <div className="space-y-2">
              <h4 className="mono text-[11px] font-bold text-ink uppercase tracking-wider">
                How to fix this
              </h4>
              <div className="p-3.5 rounded bg-inset border border-line text-ink leading-relaxed">
                {activeFinding.remediation}
              </div>
            </div>

            {/* AI Actions Row */}
            <div className="pt-2 flex flex-col sm:flex-row gap-2.5">
              <button
                onClick={() => handleTriggerExplain(activeFinding)}
                className="flex-1 flex items-center justify-center gap-2 py-2 rounded text-xs mono font-medium border border-line bg-raised hover:border-accent text-ink transition-colors btn-tactile"
              >
                <Sparkles size={13} className="text-accent" />
                <span>Ask CyphBot</span>
              </button>

              <button
                onClick={() => handleTriggerRemediate(activeFinding)}
                className="flex-1 flex items-center justify-center gap-2 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 transition-opacity btn-tactile"
              >
                <span>How to fix</span>
                <ArrowUpRight size={13} />
              </button>
            </div>
          </div>
        )}
      </Drawer>

      {/* Feature 1: Explain Finding with AI Modal */}
      <Modal
        open={explainModalOpen}
        onClose={() => setExplainModalOpen(false)}
        title="What this issue means"
        icon={<Sparkles size={16} />}
        maxWidth="max-w-xl"
      >
        {explainError ? (
          <p role="alert" className="text-sm text-soft py-4">The explanation could not be loaded. No new analysis was produced. Close this window and retry; the original finding evidence is still available.</p>
        ) : explaining || !explanation ? (
          <div className="space-y-4 pt-2" aria-busy="true">
            <Skeleton width="45%" height={16} />
            <SkeletonText lines={3} />
            <Skeleton width="50%" height={16} />
            <SkeletonText lines={2} />
            <Skeleton width="40%" height={16} />
            <Skeleton height={70} rounded="md" />
          </div>
        ) : (
          <div className="space-y-4 text-xs max-h-[70vh] overflow-y-auto pr-1 content-fade-in">
            <div>
              <h4 className="mono text-[11px] font-bold text-accent uppercase mb-1">1. What is this?</h4>
              <p className="text-ink leading-relaxed bg-inset/50 p-2.5 rounded border border-line/60">
                {explanation.what_is_this}
              </p>
            </div>

            <div>
              <h4 className="mono text-[11px] font-bold text-accent uppercase mb-1">2. Why does it matter?</h4>
              <p className="text-ink leading-relaxed bg-inset/50 p-2.5 rounded border border-line/60">
                {explanation.why_it_matters}
              </p>
            </div>

            <div>
              <h4 className="mono text-[11px] font-bold text-accent uppercase mb-1">3. What is the evidence?</h4>
              <p className="text-ink leading-relaxed bg-inset/50 p-2.5 rounded border border-line/60">
                {explanation.evidence_analysis}
              </p>
            </div>

            <div>
              <h4 className="mono text-[11px] font-bold text-accent uppercase mb-1">4. What happens if ignored?</h4>
              <p className="text-ink leading-relaxed bg-accent-soft/30 p-2.5 rounded border border-accent/20">
                {explanation.what_happens_if_ignored}
              </p>
            </div>

            {explanation.sovereign_advisory && (
              <p className="text-[11px] mono text-soft italic pt-1">
                * {explanation.sovereign_advisory}
              </p>
            )}
          </div>
        )}

        <div className="flex justify-end pt-2 border-t border-line">
          <button
            onClick={() => setExplainModalOpen(false)}
            className="px-4 py-1.5 rounded text-xs mono bg-accent text-white hover:opacity-90 btn-tactile"
          >
            Close
          </button>
        </div>
      </Modal>

      {/* Feature 2: AI Remediation Assistant Drawer */}
      <Drawer
        open={remediationDrawerOpen}
        onClose={() => setRemediationDrawerOpen(false)}
        size="2xl"
        eyebrow="FIX GUIDE"
        title="How to fix this"
        icon={<Sparkles size={16} />}
      >
        <div className="pt-2 space-y-4 text-xs">
          {/* Stack Selector */}
          <div className="space-y-1.5">
            <span className="mono text-[11px] text-soft">CHOOSE YOUR SETUP:</span>
            <div className="grid grid-cols-4 gap-1.5 mono text-[11px]">
              {['nginx', 'apache', 'cloudflare', 'aws'].map(stack => (
                <button
                  key={stack}
                  onClick={() => remediationFinding && handleTriggerRemediate(remediationFinding, stack)}
                  className={`py-1.5 px-2 rounded uppercase font-medium transition-all border btn-tactile ${
                    selectedStack === stack
                      ? 'bg-accent text-white border-accent shadow-sm shadow-accent/20'
                      : 'bg-inset border-line text-soft hover:text-ink'
                  }`}
                >
                  {stack}
                </button>
              ))}
            </div>
          </div>

          {remediationError ? (
            <p role="alert" className="text-sm text-soft py-4">The guide could not be loaded. No configuration recommendation was produced. Close this panel and retry, or review the original finding guidance.</p>
          ) : remediating || !remediationGuide ? (
            <div className="space-y-4 pt-4" aria-busy="true">
              <div className="p-3 bg-inset rounded border border-line space-y-2">
                <Skeleton width="60%" height={16} />
                <SkeletonText lines={2} />
              </div>
              <div className="space-y-2">
                <Skeleton width={140} height={12} />
                <Skeleton height={32} rounded="md" />
                <Skeleton height={32} rounded="md" />
                <Skeleton height={32} rounded="md" />
              </div>
              <div className="p-4 rounded-lg bg-black border border-line space-y-2">
                <Skeleton width="80%" height={12} />
                <Skeleton width="60%" height={12} />
              </div>
            </div>
          ) : (
            <div className="space-y-5 content-fade-in">
              <div className="p-3 bg-inset rounded border border-line space-y-1">
                <h4 className="font-semibold text-ink">{remediationGuide.title}</h4>
                <p className="text-soft text-[11.5px]">{remediationGuide.summary}</p>
                <span className="inline-block text-[10px] mono text-ok font-semibold mt-1">
                  {remediationGuide.estimated_time_minutes == null ? 'Allow time for staging and observation before enforcement.' : `Est. time: ~${remediationGuide.estimated_time_minutes} minutes`}
                </span>
              </div>

              {remediationGuide.prerequisites?.length > 0 && (
                <div className="space-y-2">
                  <h5 className="mono font-semibold text-soft uppercase text-[11px]">Before you start:</h5>
                  <ul className="list-disc pl-5 space-y-1 text-ink">
                    {remediationGuide.prerequisites.map(item => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}

              {/* Step-by-Step Instructions */}
              <div className="space-y-2">
                <h5 className="mono font-semibold text-soft uppercase text-[11px]">Steps to follow:</h5>
                <ol className="space-y-2">
                  {remediationGuide.steps.map((step, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-ink">
                      <span className="w-5 h-5 rounded-full bg-inset border border-line mono text-[10px] flex items-center justify-center shrink-0 mt-0.5 font-bold">
                        {idx + 1}
                      </span>
                      <span className="leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>

              {/* Code Snippet Box */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="mono text-[11px] font-semibold text-soft uppercase">
                    Configuration notes ({selectedStack.toUpperCase()})
                  </span>
                  <button
                    onClick={() => copyToClipboard(remediationGuide.code_snippet, false)}
                    className="text-[10px] mono text-accent hover:underline flex items-center gap-1 btn-tactile"
                  >
                    {copiedCode ? <Check size={11} /> : <Copy size={11} />}
                    {copiedCode ? 'Copied' : 'Copy'}
                  </button>
                </div>

                <div className="p-3 bg-black text-emerald-400 font-mono text-[11px] rounded-lg border border-line overflow-x-auto relative group">
                  <pre>{remediationGuide.code_snippet}</pre>
                </div>
              </div>

              {/* Verification Command */}
              <div className="space-y-1.5">
                <span className="mono text-[11px] font-semibold text-soft uppercase">
                  Verification and limitations
                </span>
                <div className="p-2.5 bg-inset rounded border border-line font-mono text-[11px] text-ink flex items-center justify-between">
                  <code>{remediationGuide.verification_command}</code>
                  <button
                    onClick={() => copyToClipboard(remediationGuide.verification_command, false)}
                    className="p-1 hover:text-accent btn-tactile"
                  >
                    <Copy size={12} />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </Drawer>
    </div>
  );
}
