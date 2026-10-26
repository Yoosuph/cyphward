import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, ShieldCheck, Radar, Gauge, Wrench, Activity, Check, Terminal, Twitter, Instagram, Linkedin } from 'lucide-react';
import PublicHeader from '../components/PublicHeader';
import PublicFooter from '../components/PublicFooter';
import { usePageMotion } from '../lib/usePageMotion';
import StrataField from '../components/StrataField';
import ScoreRing from '../components/ScoreRing';
import Meter from '../components/Meter';

const STEPS = [
  { idx: '01', name: 'FIND', icon: Radar,
    tagline: 'Find external weaknesses on domains you own',
    summary: 'Verify ownership, then assess public DNS, email authentication, web headers, certificates and exposed services.',
    features: ['DNS ownership verification before scanning', 'Evidence attached to findings', 'Failed and omitted checks stay visible'],
    metric: 'YOUR DOMAIN', metricLabel: 'DEFINED ASSESSMENT SCOPE' },
  { idx: '02', name: 'UNDERSTAND', icon: Gauge,
    tagline: 'Understand the finding and its limits',
    summary: 'Read the observed evidence, why it matters and suggested next steps. A score is shown only when the assessment evidence supports it.',
    features: ['Plain-English findings', 'Prioritised remediation guidance', 'Assessment dates and coverage'],
    metric: 'EVIDENCE', metricLabel: 'BEFORE A SECURITY CLAIM' },
  { idx: '03', name: 'ASSIGN', icon: Wrench,
    tagline: 'Give the fix an owner',
    summary: 'Turn a finding into a remediation task. Growth gives your team a shared workspace to coordinate the work.',
    features: ['Tasks linked to findings', 'Team roles on Growth', 'A visible record of follow-up'],
    metric: 'ONE OWNER', metricLabel: 'FOR THE NEXT ACTION' },
  { idx: '04', name: 'VERIFY', icon: ShieldCheck,
    tagline: 'Recheck supported findings after the change',
    summary: 'A recheck can show whether the original issue is still reproduced. Incomplete checks remain inconclusive rather than certifying a fix.',
    features: ['Detector-aware rechecks where supported', 'Manual task closure stays distinct from verification', 'DNS checks do not prove mail delivery'],
    metric: 'RECHECK', metricLabel: 'SUPPORTED FIX VERIFICATION' },
  { idx: '05', name: 'EXPORT', icon: Activity,
    tagline: 'Prepare dated evidence for the review',
    summary: 'Share assessment reports. Growth adds Nigerian data-protection questionnaires, incident records and evidence packs for preparation and adviser review.',
    features: ['Reports with assessment scope and dates', 'Growth evidence packs from frozen snapshots', 'Source labels for observed and customer-supplied evidence'],
    metric: 'DATED RECORD', metricLabel: 'FOR CUSTOMERS AND ADVISERS' },
];

const CHECKS = [
  {
    check: 'DNS & email authentication',
    detail: 'Published SPF and DMARC records checked; monitoring and enforcement policies explained. Actual mail delivery is not tested',
  },
  {
    check: 'TLS certificates',
    detail: 'Expiry and validity issues surfaced before they break trust',
  },
  {
    check: 'Exposed ports & services',
    detail: 'Open TCP ports on your public addresses (top 100 ports), as an inventory',
  },
  {
    check: 'Web security headers',
    detail: 'HSTS, CSP and X-Frame-Options checked against clickjacking and downgrade attacks',
  },
  {
    check: 'Known vulnerabilities',
    detail: 'Nuclei templates check your web apps for publicly known CVEs. Matches are reported; a clean run is not proof of absence',
  },
  {
    check: 'Exposure hygiene',
    detail: 'Server banners, stack disclosures and robots.txt leaks flagged as findings',
  },
];

export default function Landing() {
  const nav = useNavigate();
  const [activeLayer, setActiveLayer] = useState(0);
  const [previewTab, setPreviewTab] = useState<'telemetry' | 'findings' | 'fixes'>('telemetry');

  const motionRef = usePageMotion<HTMLElement>();

  const handleGetStarted = () => {
    // Real flow only: no mock sessions. Send visitors to create a real account.
    nav('/signup', { replace: true });
  };

  return (
    <div className="landing-wrap">
      {/* Background Strata field */}
      <StrataField variant="hero" opacity={0.6} />

      <PublicHeader />

      {/* Hero Section */}
      <main ref={motionRef} className="landing-container relative z-10">
        <section className="hero-sec">
          <div className="inline-block rise-in">
            <div className="telemetry-pill">
              <span>FOR NIGERIAN SOFTWARE TEAMS · SECURITY & EVIDENCE</span>
            </div>
          </div>

          <h1 className="hero-h1 max-w-4xl rise-in rise-in-2">
            Find the weakness. Verify the fix. <em>Show the evidence.</em>
          </h1>

          <p className="hero-desc rise-in rise-in-3">
            Cyphward helps Nigerian software teams assess external security weaknesses,
            coordinate fixes and prepare supporting evidence for customer security and
            data-protection reviews. Start with a domain you own.
          </p>

          <div className="hero-ctas rise-in rise-in-4">
            <button className="btn btn-solid text-sm py-3.5 px-6 hover-lift" onClick={handleGetStarted}>
              START YOUR 30-DAY TRIAL <ArrowRight size={14} />
            </button>
            <a href="#layers" className="btn-mini py-3 text-xs">
              SEE HOW IT WORKS ↓
            </a>
          </div>

          <p className="text-xs mono text-soft mt-4">No card required. Plan limits apply. Paid continuation is arranged manually.</p>

          {/* Interactive example, clearly marked as synthetic. */}
          <div className="preview-card mt-12 hover-lift rise-in rise-in-5">
            <div className="preview-head">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-accent" />
                <span>EXAMPLE WORKSPACE · SAMPLE DATA</span>
              </div>
              <div className="preview-tabs flex gap-2">
                <button
                  type="button"
                  aria-pressed={previewTab === 'telemetry'}
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'telemetry' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('telemetry')}
                >
                  SCORE
                </button>
                <button
                  type="button"
                  aria-pressed={previewTab === 'findings'}
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'findings' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('findings')}
                >
                  FINDINGS
                </button>
                <button
                  type="button"
                  aria-pressed={previewTab === 'fixes'}
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'fixes' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('fixes')}
                >
                  FIX GUIDES
                </button>
              </div>
            </div>

            <div className="p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 bg-raised items-center">
              {previewTab === 'telemetry' && (
                <>
                  <div className="lg:col-span-5 flex flex-col items-center justify-center py-2 border-b lg:border-b-0 lg:border-r border-line pr-0 lg:pr-6">
                    <ScoreRing score={79} max={100} size={200} trend={1} />
                    <p className="ring-note mt-3">SCORE OUT OF 100 · 4 AREAS</p>
                  </div>
                  <div className="lg:col-span-7 space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-line">
                      <span className="eyebrow">SCORE BREAKDOWN</span>
                      <span className="text-xs mono text-soft">SAMPLE</span>
                    </div>
                    <div className="sub-row">
                      <span className="sub-lbl mono">NETWORK &amp; DNS</span>
                      <span className="sub-val text-lg">21</span>
                      <Meter pct={84} variant="ok" />
                      <span className="delta mono up">+2</span>
                    </div>
                    <div className="sub-row">
                      <span className="sub-lbl mono">WEB &amp; APPS</span>
                      <span className="sub-val text-lg">27</span>
                      <Meter pct={77} variant="warn" />
                      <span className="delta mono down">-3</span>
                    </div>
                    <div className="sub-row">
                      <span className="sub-lbl mono">ENCRYPTION</span>
                      <span className="sub-val text-lg">22</span>
                      <Meter pct={88} variant="ok" />
                      <span className="delta mono up">+1</span>
                    </div>
                    <div className="sub-row">
                      <span className="sub-lbl mono">EXPOSURE</span>
                      <span className="sub-val text-lg">9</span>
                      <Meter pct={60} variant="warn" />
                      <span className="delta mono down">-1</span>
                    </div>
                  </div>
                </>
              )}

              {previewTab === 'findings' && (
                <div className="col-span-12 py-3">
                  <div className="flex justify-between items-center mb-4">
                    <div>
                      <h4 className="font-display text-lg font-medium">Findings from your latest scan</h4>
                      <p className="text-xs mono text-soft">Example observations, with their evidence and limitations</p>
                    </div>
                    <span className="tag acc">SAMPLE FINDINGS</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">DNS &amp; EMAIL SECURITY</div>
                      <div className="text-sm font-medium mt-1">Permissive Email DMARC Policy (p=none)</div>
                      <p className="text-[11px] mono text-accent mt-2">Monitoring mode: review reports before enforcement</p>
                    </div>
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">HTTP HEADERS</div>
                      <div className="text-sm font-medium mt-1">Strict-Transport-Security (HSTS) Header Missing</div>
                      <p className="text-[11px] mono text-soft mt-2">Browsers can be downgraded to plain HTTP</p>
                    </div>
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">TLS CERTIFICATES</div>
                      <div className="text-sm font-medium mt-1">SSL/TLS Certificate Expiring within 22 Days</div>
                      <p className="text-[11px] mono text-soft mt-2">Renew before visitors see trust warnings</p>
                    </div>
                  </div>
                </div>
              )}

              {previewTab === 'fixes' && (
                <div className="col-span-12 py-3">
                  <div className="flex justify-between items-center mb-4">
                    <div>
                      <h4 className="font-display text-lg font-medium">Fix guide: roll out DMARC safely</h4>
                      <p className="text-xs mono text-soft">Check your legitimate mail senders before changing enforcement</p>
                    </div>
                    <span className="tag ok">STEP-BY-STEP</span>
                  </div>
                  <div className="p-4 bg-inset border border-line font-mono text-xs leading-relaxed overflow-x-auto">
                    <div className="text-soft">// STEP 1 — Configure SPF/DKIM for every legitimate sender</div>
                    <div className="text-ink mt-1">Start with a monitoring policy: v=DMARC1; p=none</div>
                    <div className="text-soft mt-3">// STEP 2 — Configure reporting, then review normal sending cycles</div>
                    <div className="text-ink mt-1">Fix alignment failures before gradually increasing enforcement</div>
                    <div className="text-ok mt-3">// DNS rechecks confirm records, not successful mail delivery</div>
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-3 border-t border-line bg-inset flex items-center justify-between">
              <span className="text-xs mono text-soft flex items-center gap-2">
                <Terminal size={13} className="text-accent" /> SAMPLE DATA · YOUR WORKSPACE SHOWS YOUR OWN SCANS
              </span>
              <button type="button" className="stat-link tap-row text-xs" onClick={handleGetStarted}>
                GET STARTED <ArrowRight size={12} aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>

        {/* Product scope and trial terms. */}
        <section className="stat-matrix" data-reveal>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val text-accent">0–100</div>
            <div className="stat-matrix-lbl">SCORE WHEN COVERAGE SUPPORTS IT</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val text-ok">30 DAYS</div>
            <div className="stat-matrix-lbl">TRIAL · NO CARD REQUIRED</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val">SCOPE</div>
            <div className="stat-matrix-lbl">SEE WHAT WAS AND WAS NOT ASSESSED</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val">5</div>
            <div className="stat-matrix-lbl">CHECK FAMILIES: DNS, PORTS, TLS, WEB, EMAIL</div>
          </div>
        </section>

        {/* The 6 Strata Defense Layers */}
        <section id="layers" className="py-16" data-reveal>
          <div className="sec-head">
            <p className="eyebrow">FROM ASSESSMENT TO EVIDENCE</p>
            <h2>One workflow your team can finish.</h2>
            <p className="sec-note">
              Find a weakness, understand it, assign the work, recheck supported fixes,
              and export supporting evidence. Choose a step to see the detail.
            </p>
          </div>

          <div className="layer-nav-tabs">
            {STEPS.map((layer, i) => (
              <button
                key={layer.idx}
                type="button"
                className={`layer-tab-btn ${activeLayer === i ? 'active' : ''}`}
                aria-pressed={activeLayer === i}
                onClick={() => setActiveLayer(i)}
              >
                <layer.icon size={13} className="inline mr-1.5" />
                STEP {layer.idx} · {layer.name}
              </button>
            ))}
          </div>

          <div className="panel p-8">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
              <div className="lg:col-span-7">
                <div className="flex items-center gap-3 mb-2">
                  <span className="tag">STEP {STEPS[activeLayer].idx}</span>
                  <span className="eyebrow">{STEPS[activeLayer].name}</span>
                </div>
                <h3 className="font-display text-3xl font-medium mb-3">
                  {STEPS[activeLayer].tagline}
                </h3>
                <p className="text-soft text-sm leading-relaxed mb-6">
                  {STEPS[activeLayer].summary}
                </p>

                <div className="space-y-2.5 mb-6">
                  {STEPS[activeLayer].features.map((feat, fi) => (
                    <div key={fi} className="flex items-start gap-2.5 text-xs mono">
                      <Check size={14} className="text-ok flex-none mt-0.5" />
                      <span>{feat}</span>
                    </div>
                  ))}
                </div>

                <button className="btn btn-solid btn-mini" onClick={handleGetStarted}>
                  START YOUR TRIAL <ArrowRight size={12} />
                </button>
              </div>

              <div className="lg:col-span-5 p-6 bg-inset border border-line rounded flex flex-col items-center justify-center text-center">
                <p className="eyebrow">{STEPS[activeLayer].metricLabel}</p>
                <p className="font-display text-4xl font-medium my-3 text-accent">
                  {STEPS[activeLayer].metric}
                </p>
                <p className="text-xs mono text-soft max-w-xs leading-relaxed">
                  Only verified domains. Scope, limits and incomplete checks stay visible.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* What a scan checks: honest capability table */}
        <section id="checks" className="py-16" data-reveal>
          <div className="sec-head">
            <p className="eyebrow">WHAT WE CHECK</p>
            <h2>Everything a scan puts in front of you.</h2>
            <p className="sec-note">
              Cyphward focuses on what you actually own — your public-facing domains, DNS,
              certificates and web apps — checked automatically on every run.
            </p>
          </div>

          <div className="ledger-wrap panel">
            <table className="ledger">
              <thead>
                <tr>
                  <th style={{ width: '34%' }}>CHECK</th>
                  <th>WHAT YOU GET</th>
                </tr>
              </thead>
              <tbody>
                {CHECKS.map((row, i) => (
                  <tr key={i}>
                    <td className="font-medium">{row.check}</td>
                    <td className="text-soft mono text-xs">
                      <Check size={13} className="inline mr-1 text-ok" />
                      {row.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="ledger-hint">SWIPE THE TABLE FOR THE FULL COLUMN →</p>
        </section>

        <section id="compliance" className="py-16" data-reveal>
          <div className="calc-panel">
            <div className="sec-head mb-6">
              <p className="eyebrow">NIGERIAN DATA-PROTECTION PREPARATION · GROWTH</p>
              <h2 className="text-2xl">Keep the evidence behind your answers.</h2>
              <p className="sec-note">Bring technical observations and your team's records together for a customer review or a conversation with your adviser.</p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <ul className="space-y-3 text-sm text-soft">
                <li>Questionnaires with evidence owners and expiry dates.</li>
                <li>Incident records and reminders.</li>
                <li>Document drafts with customer approval history.</li>
                <li>Dated evidence packs from frozen assessment snapshots.</li>
              </ul>
              <div className="panel p-5 text-sm text-soft leading-relaxed">
                <p>Tool observations, customer answers and reviewer notes keep their own source labels.</p>
                <p className="mt-3">Requirement references are pending professional review. Evidence packs support preparation; they are not legal advice, a compliance determination or a Compliance Audit Return. Ask a qualified adviser about applicability and filing.</p>
                <Link className="btn btn-solid mt-5" to="/pricing">SEE GROWTH <ArrowRight size={14} /></Link>
              </div>
            </div>
          </div>
        </section>

        {/* Teams & roles */}
        <section id="teams" className="py-16" data-reveal>
          <div className="sec-head">
            <p className="eyebrow">TEAM COLLABORATION · GROWTH</p>
            <h2>One workspace, the right access for everyone.</h2>
            <p className="sec-note">
              Invite colleagues by email and give each person a role — security, IT and
              leadership all work from the same scores, findings, fix guides and reports.
            </p>
          </div>

          <div className="teams-grid">
            <div className="panel p-6">
              <span className="tag w-fit mb-3">ROLE 01</span>
              <h3 className="font-display text-xl font-medium mb-2">Owner</h3>
              <p className="text-xs mono text-soft leading-relaxed mb-4">
                Full control of the workspace, including settings and membership.
              </p>
              <ul className="space-y-2.5 text-xs mono text-soft">
                <li className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  Invite people and set their roles
                </li>
                <li className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  Change workspace settings and company profile
                </li>
              </ul>
            </div>

            <div className="panel p-6">
              <span className="tag w-fit mb-3">ROLE 02</span>
              <h3 className="font-display text-xl font-medium mb-2">Admin</h3>
              <p className="text-xs mono text-soft leading-relaxed mb-4">
                You can invite people, change settings, and manage findings.
              </p>
              <ul className="space-y-2.5 text-xs mono text-soft">
                <li className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  Add teammates by email, any role
                </li>
                <li className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  Work through findings and fixes together
                </li>
              </ul>
            </div>

            <div className="panel p-6">
              <span className="tag w-fit mb-3">ROLE 03</span>
              <h3 className="font-display text-xl font-medium mb-2">Member</h3>
              <p className="text-xs mono text-soft leading-relaxed mb-4">
                You can view findings, scans, and reports.
              </p>
              <ul className="space-y-2.5 text-xs mono text-soft">
                <li className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  See scores and step-by-step fix guides
                </li>
                <li className="flex items-start gap-2">
                  <Check size={14} className="text-ok flex-none mt-0.5" />
                  Download board-ready reports
                </li>
              </ul>
            </div>
          </div>

          <div className="teams-foot">
            <p className="text-xs mono text-soft">
              INVITE BY EMAIL · CHANGE ROLES ANYTIME · OWNER, ADMIN OR MEMBER
            </p>
            <button className="btn btn-solid text-sm py-3 px-6" onClick={handleGetStarted}>
              INVITE YOUR TEAM <ArrowRight size={14} />
            </button>
          </div>
        </section>

        {/* Final CTA Banner */}
        <section className="my-20 text-center py-16 panel bg-inset border-line-strong" data-reveal>
          <p className="eyebrow mb-3">30-DAY TRIAL · NO CARD REQUIRED</p>
          <h2 className="font-display text-4xl font-medium mb-4 max-w-xl mx-auto">
            Prepare for your next customer review.
          </h2>
          <p className="text-sm mono text-soft max-w-lg mx-auto mb-8">
            Create a workspace, verify a domain you own, and work through your first assessment. Choose Starter or Growth; included quotas apply during the trial. We confirm payment manually before paid continuation.
          </p>
          <div className="flex justify-center gap-4 flex-wrap">
            <Link to="/signup" className="btn btn-solid py-3 px-8 text-sm">
              START YOUR 30-DAY TRIAL <ArrowRight size={14} />
            </Link>
            <Link to="/login" className="btn btn-ghost py-3 px-8 text-sm">
              SIGN IN
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <PublicFooter anchorPrefix="" />

      {/* Fixed side social buttons — stacked, small gap */}
      <div className="social-float" aria-label="Cyphward on social media">
        <a
          href="https://x.com/cyphward"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Cyphward on X"
          title="Cyphward on X"
          className="social-float-btn"
        >
          <Twitter size={14} />
        </a>
        <a
          href="https://www.instagram.com/cyphward_/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Cyphward on Instagram"
          title="Cyphward on Instagram"
          className="social-float-btn"
        >
          <Instagram size={14} />
        </a>
        <a
          href="https://www.linkedin.com/company/cyphward/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Cyphward on LinkedIn"
          title="Cyphward on LinkedIn"
          className="social-float-btn"
        >
          <Linkedin size={14} />
        </a>
      </div>
    </div>
  );
}
