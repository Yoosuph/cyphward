import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowRight, ShieldCheck, Radar, Gauge, Wrench, MessageSquare,
  Activity, Lock, Globe, Check, AlertTriangle, Terminal, ChevronRight,
  Sun, Moon, Laptop, Sparkles, Building2, Zap, Shield, Menu, X,
  Twitter, Instagram, Linkedin
} from 'lucide-react';
import { getTheme, toggleTheme } from '../lib/theme';
import { useAuth } from '../lib/auth';
import { useToast } from '../components/Toast';
import StrataField from '../components/StrataField';
import ScoreRing from '../components/ScoreRing';
import Meter from '../components/Meter';
import CyphwardLogo from '../components/CyphwardLogo';

const LAYERS = [
  {
    idx: '01',
    name: 'COMMAND',
    icon: Activity,
    tagline: 'One clear dashboard of your security health',
    summary: 'A single 0–100 security score, updated after every scan across four areas: Network, Web apps, Encryption, and Exposure.',
    features: [
      'Daily automated scans of your verified domains',
      'Four scored areas with a full breakdown',
      'Board-ready AI summary after each scan',
    ],
    metric: '79 / 100',
    metricLabel: 'EXAMPLE OVERALL SCORE',
  },
  {
    idx: '02',
    name: 'EXPOSE',
    icon: Globe,
    tagline: 'Your external footprint, mapped',
    summary: 'We discover and watch everything the internet can see about you — subdomains, hosts, open ports, certificates and web technologies.',
    features: [
      'Asset discovery across your domains and subdomains',
      'Open port and service inventory for public IPs',
      'Certificate expiry tracking before outages happen',
    ],
    metric: '5',
    metricLabel: 'EXPOSURE SURFACES CHECKED',
  },
  {
    idx: '03',
    name: 'ANALYZE',
    icon: Radar,
    tagline: 'Automated checks that map to real rules',
    summary: 'Every scan validates the controls regulators expect you to have — email authentication, TLS, security headers — and flags what is missing or weak.',
    features: [
      'SPF and DMARC email authentication checks',
      'HSTS, CSP and clickjacking header checks',
      'Known vulnerability scanning with Nuclei templates',
    ],
    metric: 'DAILY',
    metricLabel: 'AUTOMATED CHECK RUNS',
  },
  {
    idx: '04',
    name: 'SCORE',
    icon: Gauge,
    tagline: 'A security rating built for finance',
    summary: 'A clear security score your executives and insurers can read at a glance — built from what is actually exposed online, with history across every scan.',
    features: [
      'Breakdown across network, web apps, encryption and exposure',
      'Score history tracked across every scan',
      'Exportable reports for boards and stakeholders',
    ],
    metric: '+12 PTS',
    metricLabel: 'EXAMPLE SCORE IMPROVEMENT',
  },
  {
    idx: '05',
    name: 'REMEDIATE',
    icon: Wrench,
    tagline: 'From finding to fix, in order',
    summary: 'Every finding arrives with evidence, a plain-English explanation and a step-by-step fix — queued so your team works on what matters first.',
    features: [
      'Prioritized fix queue ordered by severity',
      'Step-by-step remediation guidance per finding',
      'Evidence attached so you can verify every fix',
    ],
    metric: 'STEP-BY-STEP',
    metricLabel: 'REMEDIATION FOR EVERY FINDING',
  },
  {
    idx: '06',
    name: 'CYPHBOT',
    icon: MessageSquare,
    tagline: 'An AI analyst that knows your data',
    summary: 'A conversational AI assistant grounded in your live scan results. Ask about any finding in plain English and get answers from your own telemetry — not generic advice.',
    features: [
      'Answers grounded in your live scan data',
      'Plain-English explanations of every finding',
      'Streams responses right in the dashboard',
    ],
    metric: 'STREAMING',
    metricLabel: 'AI ANSWERS FROM YOUR SCAN DATA',
  },
];

const CHECKS = [
  {
    check: 'DNS & email authentication',
    detail: 'SPF and DMARC records validated; permissive policies flagged before spoofers use them',
  },
  {
    check: 'TLS certificates',
    detail: 'Expiry, chain and cipher issues surfaced weeks before they break trust',
  },
  {
    check: 'Exposed ports & services',
    detail: 'Open ports on your public IPs, listed with the services actually running on them',
  },
  {
    check: 'Web security headers',
    detail: 'HSTS, CSP and X-Frame-Options checked against clickjacking and downgrade attacks',
  },
  {
    check: 'Known vulnerabilities',
    detail: 'Nuclei templates scan your web apps for publicly known CVEs',
  },
  {
    check: 'Exposure hygiene',
    detail: 'Server banners, stack disclosures and robots.txt leaks flagged as findings',
  },
];

const CALCULATOR_SECTORS = [
  { name: 'Commercial Banking & Merchant Banks', baseExposure: '₦450M', recommended: 'Enterprise' },
  { name: 'Fintech & Payment Gateway Switches', baseExposure: '₦180M', recommended: 'Scale' },
  { name: 'Telco VAS & Mobile Money Providers', baseExposure: '₦320M', recommended: 'Enterprise' },
  { name: 'Logistics & Supply Chain Conglomerates', baseExposure: '₦65M', recommended: 'Growth' },
  { name: 'Healthcare & Healthtech Networks', baseExposure: '₦95M', recommended: 'Growth' },
];

const COUNTRY_REGULATION: Record<string, string> = {
  Nigeria: 'NDPA 2023 · CBN Cybersecurity Framework',
  Kenya: 'Kenya DPA 2019 · CBK Cybersecurity Guidance',
  'South Africa': 'PoPIA · FSCA Cyber Resilience Rules',
  Ghana: 'Ghana DPA 2012 · BoG Cyber & Information Security Directive',
  Egypt: 'Law 151 of 2020 · CBE Cybersecurity Framework',
};

export default function Landing() {
  const nav = useNavigate();
  const toast = useToast();
  const [theme, setTheme] = useState(getTheme());
  const [activeLayer, setActiveLayer] = useState(0);
  const [calcSector, setCalcSector] = useState(0);
  const [calcCountry, setCalcCountry] = useState('Nigeria');
  const [previewTab, setPreviewTab] = useState<'telemetry' | 'findings' | 'fixes'>('telemetry');

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const onToggleTheme = () => {
    toggleTheme();
    setTheme(getTheme());
  };

  const handleGetStarted = () => {
    // Real flow only: no mock sessions. Send visitors to create a real account.
    nav('/signup', { replace: true });
  };

  return (
    <div className="landing-wrap">
      {/* Background Strata field */}
      <StrataField variant="hero" opacity={0.6} />

      {/* Fixed Floating Navigation Header */}
      <header className={`landing-nav ${mobileMenuOpen ? 'menu-open' : ''}`}>
        <div className="landing-nav-inner">
          <Link to="/" className="landing-brand" onClick={() => setMobileMenuOpen(false)}>
            <CyphwardLogo variant="compact" size={19} />
            <span className="!hidden lg:!inline-block tag text-[9px] ml-1">STRATA 2.0</span>
          </Link>

          <nav className="landing-links">
            <a href="#layers" className="landing-link">LAYERS</a>
            <a href="#checks" className="landing-link">WHAT WE CHECK</a>
            <a href="#compliance" className="landing-link">REGULATION</a>
            <a href="#teams" className="landing-link">TEAMS</a>
            <a href="#pricing" className="landing-link">PRICING</a>
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            <button
              className="icon-btn"
              onClick={onToggleTheme}
              aria-label="Toggle visual theme"
              title="Switch light/dark theme"
            >
              {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            </button>

            <Link to="/login" className="btn-mini !hidden sm:!inline-flex">
              SIGN IN
            </Link>

            <button className="btn btn-solid btn-mini hover-lift text-[11px] py-1.5 px-3 flex-none" onClick={handleGetStarted}>
              <span className="hidden sm:inline">GET </span>STARTED <ArrowRight size={11} className="ml-1 inline" />
            </button>

            <button
              className="icon-btn md:hidden"
              onClick={() => setMobileMenuOpen(o => !o)}
              aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
            >
              {mobileMenuOpen ? <X size={15} /> : <Menu size={15} />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown Menu Panel */}
        {mobileMenuOpen && (
          <div className="landing-mobile-menu md:hidden border-t border-line px-4 py-3 flex flex-col gap-2.5 bg-raised/95 backdrop-blur-md rounded-b-2xl">
            <nav className="flex flex-col gap-1 pt-1">
              <a
                href="#layers"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>01–06 · DEFENSE LAYERS</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
              <a
                href="#checks"
                className="py-2 px-2.5 rounded text-xs mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>WHAT WE CHECK</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
              <a
                href="#compliance"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>PENALTY CALCULATOR</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
              <a
                href="#teams"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>TEAMS &amp; ROLES</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
              <a
                href="#pricing"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>PLANS &amp; PRICING</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
            </nav>

            <div className="grid grid-cols-2 gap-2 pt-2 border-t border-line/60">
              <Link
                to="/login"
                className="btn btn-ghost text-xs justify-center py-2"
                onClick={() => setMobileMenuOpen(false)}
              >
                SIGN IN
              </Link>
              <button
                className="btn btn-solid text-xs justify-center py-2"
                onClick={() => {
                  setMobileMenuOpen(false);
                  handleGetStarted();
                }}
              >
                GET STARTED ↗
              </button>
            </div>
          </div>
        )}
      </header>

      {/* Hero Section */}
      <main className="landing-container relative z-10">
        <section className="hero-sec">
          <div className="inline-block">
            <div className="telemetry-pill">
              <span className="live-dot" />
              <span>LIVE DATA · DAILY SCANS · DNS · PORTS · TLS · WEB · EMAIL</span>
            </div>
          </div>

          <h1 className="hero-h1 max-w-4xl">
            Cyber defense built in Africa for <em>African businesses.</em>
          </h1>

          <p className="hero-desc">
            Big global security tools weren't built for African networks. CYPHWARD checks
            what the internet can see about you — DNS, ports, TLS certificates, web apps and
            email security — and turns it into a clear 0–100 score with plain-English findings,
            fix guides and board-ready reports. Built with NDPA 2023 in mind.
          </p>

          <div className="hero-ctas">
            <button className="btn btn-solid text-sm py-3.5 px-6 hover-lift" onClick={handleGetStarted}>
              CREATE YOUR ACCOUNT <ArrowRight size={14} />
            </button>
            <Link to="/signup" className="btn btn-ghost text-sm py-3.5 px-6 hover-lift">
              SET UP A BUSINESS ACCOUNT
            </Link>
            <a href="#layers" className="btn-mini py-3 text-xs">
              EXPLORE THE 6 LAYERS ↓
            </a>
          </div>

          {/* Interactive Live Preview Terminal */}
          <div className="preview-card mt-12 hover-lift">
            <div className="preview-head">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-accent" />
                <span>CYPHWARD DEFENSE OS — LIVE WORKSPACE PREVIEW</span>
              </div>
              <div className="preview-tabs flex gap-2">
                <button
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'telemetry' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('telemetry')}
                >
                  LIVE DATA
                </button>
                <button
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'findings' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('findings')}
                >
                  FINDINGS
                </button>
                <button
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
                      <span className="text-xs mono text-ok flex items-center gap-1">
                        <span className="live-dot" /> UPDATING LIVE
                      </span>
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
                      <p className="text-xs mono text-soft">Severity-ranked, with evidence attached to every item</p>
                    </div>
                    <span className="tag acc">3 HIGH</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">DNS &amp; EMAIL SECURITY</div>
                      <div className="text-sm font-medium mt-1">Permissive Email DMARC Policy (p=none)</div>
                      <p className="text-[11px] mono text-accent mt-2">Spoofed mail from your domain is accepted today</p>
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
                      <h4 className="font-display text-lg font-medium">Fix guide: enforce DMARC</h4>
                      <p className="text-xs mono text-soft">Step-by-step remediation, copy-paste ready</p>
                    </div>
                    <span className="tag ok">STEP-BY-STEP</span>
                  </div>
                  <div className="p-4 bg-inset border border-line font-mono text-xs leading-relaxed overflow-x-auto">
                    <div className="text-soft">// STEP 1 — Publish a restrictive DMARC record</div>
                    <div className="text-ink mt-1">_dmarc.yourdomain.com  TXT  "v=DMARC1; p=quarantine; pct=100"</div>
                    <div className="text-soft mt-3">// STEP 2 — Point reports at a mailbox you read</div>
                    <div className="text-ink mt-1">rua=mailto:dmarc-reports@yourdomain.com</div>
                    <div className="text-ok mt-3">// After publishing: re-run the scan to verify the fix</div>
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-3 border-t border-line bg-inset flex items-center justify-between">
              <span className="text-xs mono text-soft flex items-center gap-2">
                <Terminal size={13} className="text-accent" /> REAL SCAN WORKSPACE · EVIDENCE IN EVERY FINDING
              </span>
              <button className="stat-link text-xs" onClick={handleGetStarted}>
                GET STARTED <ArrowRight size={12} />
              </button>
            </div>
          </div>
        </section>

        {/* Pan-African Metrics Strip */}
        <section className="stat-matrix">
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val text-accent">0–100</div>
            <div className="stat-matrix-lbl">ONE SCORE ACROSS FOUR AREAS</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val text-ok">DAILY</div>
            <div className="stat-matrix-lbl">AUTOMATED SCANS PER VERIFIED DOMAIN</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val">100%</div>
            <div className="stat-matrix-lbl">OF FINDINGS SHIP WITH EVIDENCE &amp; A FIX</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val">5</div>
            <div className="stat-matrix-lbl">CHECK FAMILIES: DNS, PORTS, TLS, WEB, EMAIL</div>
          </div>
        </section>

        {/* The 6 Strata Defense Layers */}
        <section id="layers" className="py-16">
          <div className="sec-head">
            <p className="eyebrow">THE DEFENSE ARCHITECTURE</p>
            <h2>The 6 Layers of Strata Defense.</h2>
            <p className="sec-note">
              Complete security coverage for African businesses — from your public perimeter
              to a prioritized fix queue, with an AI analyst on call. Click through each layer
              to see what it does.
            </p>
          </div>

          <div className="layer-nav-tabs">
            {LAYERS.map((layer, i) => (
              <button
                key={layer.idx}
                type="button"
                className={`layer-tab-btn ${activeLayer === i ? 'active' : ''}`}
                onClick={() => setActiveLayer(i)}
              >
                <layer.icon size={13} className="inline mr-1.5" />
                LAYER {layer.idx} · {layer.name}
              </button>
            ))}
          </div>

          <div className="panel p-8">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
              <div className="lg:col-span-7">
                <div className="flex items-center gap-3 mb-2">
                  <span className="tag">LAYER {LAYERS[activeLayer].idx}</span>
                  <span className="eyebrow">{LAYERS[activeLayer].name} DEFENSE LAYER</span>
                </div>
                <h3 className="font-display text-3xl font-medium mb-3">
                  {LAYERS[activeLayer].tagline}
                </h3>
                <p className="text-soft text-sm leading-relaxed mb-6">
                  {LAYERS[activeLayer].summary}
                </p>

                <div className="space-y-2.5 mb-6">
                  {LAYERS[activeLayer].features.map((feat, fi) => (
                    <div key={fi} className="flex items-start gap-2.5 text-xs mono">
                      <Check size={14} className="text-ok flex-none mt-0.5" />
                      <span>{feat}</span>
                    </div>
                  ))}
                </div>

                <button className="btn btn-solid btn-mini" onClick={handleGetStarted}>
                  TEST LAYER {LAYERS[activeLayer].idx} ON YOUR DOMAIN <ArrowRight size={12} />
                </button>
              </div>

              <div className="lg:col-span-5 p-6 bg-inset border border-line rounded flex flex-col items-center justify-center text-center">
                <p className="eyebrow">{LAYERS[activeLayer].metricLabel}</p>
                <p className="font-display text-4xl font-medium my-3 text-accent">
                  {LAYERS[activeLayer].metric}
                </p>
                <p className="text-xs mono text-soft max-w-xs leading-relaxed">
                  Scans run from the internet edge — the same view an attacker has of your public surface.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* What a scan checks: honest capability table */}
        <section id="checks" className="py-16">
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

        {/* Interactive Regulatory Exposure Calculator */}
        <section id="compliance" className="py-16">
          <div className="calc-panel">
            <div className="sec-head mb-6">
              <p className="eyebrow">WHAT NON-COMPLIANCE COSTS</p>
              <h2 className="text-2xl">See what breaking the rules could cost you</h2>
              <p className="sec-note">
                Pick your industry and country to see what non-compliance could cost you under
                the data-protection rules that apply where you operate.
              </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
              <div className="lg:col-span-6 space-y-4">
                <div className="field">
                  <label>YOUR INDUSTRY</label>
                  <select
                    value={calcSector}
                    onChange={e => setCalcSector(Number(e.target.value))}
                  >
                    {CALCULATOR_SECTORS.map((s, i) => (
                      <option key={i} value={i}>{s.name}</option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>YOUR COUNTRY</label>
                  <select
                    value={calcCountry}
                    onChange={e => setCalcCountry(e.target.value)}
                  >
                    <option value="Nigeria">Nigeria (NDPA 2023 / CBN Framework)</option>
                    <option value="Kenya">Kenya (Kenya DPA 2019 / CBK Guideline)</option>
                    <option value="South Africa">South Africa (PoPIA / FSCA)</option>
                    <option value="Ghana">Ghana (Ghana DPA 2012 / BoG Directives)</option>
                    <option value="Egypt">Egypt (Law 151 of 2020 / CBE Cybersecurity)</option>
                  </select>
                </div>
              </div>

              <div className="lg:col-span-6 p-6 bg-inset border border-line rounded">
                <div className="flex justify-between items-center mb-4">
                  <span className="eyebrow">ESTIMATED FINE IF YOU'RE NON-COMPLIANT</span>
                  <span className="tag acc">ILLUSTRATIVE</span>
                </div>
                <div className="font-display text-4xl text-accent font-medium mb-1">
                  {CALCULATOR_SECTORS[calcSector].baseExposure}
                </div>
                <p className="text-xs mono text-soft mb-4">
                  Penalties are typically tied to turnover — NDPA 2023 Sec 48, for example,
                  allows up to 2% of annual turnover or ₦10M. Figures shown assume a typical
                  annual turnover for the selected sector.
                </p>

                <div className="space-y-2 border-t border-line pt-3 text-xs mono">
                  <div className="flex justify-between">
                    <span className="text-soft">APPLIES TO YOU:</span>
                    <span>{COUNTRY_REGULATION[calcCountry]}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-soft">RECOMMENDED PLAN:</span>
                    <span className="font-medium text-ok">{CALCULATOR_SECTORS[calcSector].recommended}</span>
                  </div>
                </div>

                <button
                  className="btn btn-solid w-full justify-center mt-5 text-xs py-2.5"
                  onClick={handleGetStarted}
                >
                  RUN A REAL SCAN ON YOUR DOMAIN <ArrowRight size={13} />
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Teams & roles */}
        <section id="teams" className="py-16">
          <div className="sec-head">
            <p className="eyebrow">BUILT FOR TEAMS</p>
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

        {/* Enterprise Enclaves & Pricing */}
        <section id="pricing" className="py-16">
          <div className="sec-head">
            <p className="eyebrow">SIMPLE PLANS</p>
            <h2>Transparent pricing for every scale.</h2>
            <p className="sec-note">
              For growing fintechs, banks, telcos and payment providers across Africa.
            </p>
          </div>

          <div className="pricing-grid">
            {/* Tier 1 */}
            <div className="pricing-card">
              <span className="tag w-fit mb-3">GROWTH</span>
              <h3 className="font-display text-2xl font-medium mb-1">Standard Cloud</h3>
              <p className="text-xs mono text-soft mb-4">For growing fintechs, logistics and tech ventures.</p>
              <div className="font-display text-3xl font-medium my-2">₦450,000 <span className="text-xs font-mono text-soft">/ month</span></div>
              <ul className="space-y-2.5 my-6 text-xs mono text-soft flex-1">
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Daily automated scans of your domains</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Email &amp; TLS hardening checks (DMARC, SPF, HSTS)</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Findings prioritized with step-by-step fixes</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Board-ready AI report after every scan</li>
              </ul>
              <button className="btn btn-ghost w-full justify-center" onClick={handleGetStarted}>
                START WITH GROWTH
              </button>
            </div>

            {/* Tier 2 */}
            <div className="pricing-card featured">
              <div className="flex justify-between items-center mb-3">
                <span className="tag w-fit">SCALE</span>
                <span className="tag acc text-[9px]">MOST POPULAR</span>
              </div>
              <h3 className="font-display text-2xl font-medium mb-1">Dedicated Cloud</h3>
              <p className="text-xs mono text-soft mb-4">For national banks, telcos and payment switches.</p>
              <div className="font-display text-3xl font-medium my-2">₦1,850,000 <span className="text-xs font-mono text-soft">/ month</span></div>
              <ul className="space-y-2.5 my-6 text-xs mono text-soft flex-1">
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Everything in Growth, plus:</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Unlimited verified domains</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Dedicated onboarding with our team</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Priority support</li>
              </ul>
              <button className="btn btn-solid w-full justify-center" onClick={handleGetStarted}>
                START WITH SCALE
              </button>
            </div>

            {/* Tier 3 */}
            <div className="pricing-card">
              <span className="tag w-fit mb-3">ENTERPRISE</span>
              <h3 className="font-display text-2xl font-medium mb-1">Custom Plan</h3>
              <p className="text-xs mono text-soft mb-4">For large institutions with bespoke requirements.</p>
              <div className="font-display text-3xl font-medium my-2">CUSTOM <span className="text-xs font-mono text-soft">/ annual</span></div>
              <ul className="space-y-2.5 my-6 text-xs mono text-soft flex-1">
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Everything in Scale, plus:</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Multi-domain portfolios under one roof</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Reports formatted for regulators and boards</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Personalized rollout with our team</li>
              </ul>
              <Link to="/signup" className="btn btn-ghost w-full justify-center">
                CONTACT OUR TEAM
              </Link>
            </div>
          </div>
        </section>

        {/* Final CTA Banner */}
        <section className="my-20 text-center py-16 panel bg-inset border-line-strong">
          <p className="eyebrow mb-3">TRY IT WITH NO COMMITMENT</p>
          <h2 className="font-display text-4xl font-medium mb-4 max-w-xl mx-auto">
            Check how secure you are right now.
          </h2>
          <p className="text-sm mono text-soft max-w-lg mx-auto mb-8">
            Create your account, add your domain, and run a real scan — you get a security score, board-ready reports, and clear steps to fix any issues.
          </p>
          <div className="flex justify-center gap-4 flex-wrap">
            <Link to="/signup" className="btn btn-solid py-3 px-8 text-sm">
              CREATE YOUR ACCOUNT <ArrowRight size={14} />
            </Link>
            <Link to="/login" className="btn btn-ghost py-3 px-8 text-sm">
              SIGN IN
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-container">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 pb-12 border-b border-line">
            <div>
              <div className="mb-3">
                <CyphwardLogo variant="full" size={20} />
              </div>
              <p className="text-xs mono text-soft leading-relaxed">
                African-built cyber security and compliance platform.
                Layer by layer defense for the continent.
              </p>
              <div className="flex items-center gap-2.5 mt-4">
                <a
                  href="https://x.com/cyphward"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Cyphward on X"
                  className="w-8 h-8 rounded border border-line bg-inset flex items-center justify-center text-soft hover:text-ink hover:border-accent transition-colors"
                >
                  <Twitter size={14} />
                </a>
                <a
                  href="https://www.instagram.com/cyphward_/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Cyphward on Instagram"
                  className="w-8 h-8 rounded border border-line bg-inset flex items-center justify-center text-soft hover:text-ink hover:border-accent transition-colors"
                >
                  <Instagram size={14} />
                </a>
                <a
                  href="https://www.linkedin.com/company/cyphward/"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Cyphward on LinkedIn"
                  className="w-8 h-8 rounded border border-line bg-inset flex items-center justify-center text-soft hover:text-ink hover:border-accent transition-colors"
                >
                  <Linkedin size={14} />
                </a>
              </div>
            </div>

            <div>
              <p className="eyebrow mb-3">DEFENSE LAYERS</p>
              <ul className="space-y-2 text-xs mono text-soft">
                <li><a href="#layers" className="hover:text-ink">Overview &amp; Score</a></li>
                <li><a href="#layers" className="hover:text-ink">Assets &amp; Domains</a></li>
                <li><a href="#layers" className="hover:text-ink">Findings &amp; Evidence</a></li>
                <li><a href="#layers" className="hover:text-ink">Scans &amp; Reports</a></li>
                <li><a href="#layers" className="hover:text-ink">Fixes</a></li>
              </ul>
            </div>

            <div>
              <p className="eyebrow mb-3">ACCESS</p>
              <ul className="space-y-2 text-xs mono text-soft">
                <li><Link to="/login" className="hover:text-ink">Sign In</Link></li>
                <li><Link to="/signup" className="hover:text-ink">Create a Business Account</Link></li>
                <li><Link to="/forgot-password" className="hover:text-ink">Reset Password</Link></li>
              </ul>
            </div>

            <div>
              <p className="eyebrow mb-3">REGULATIONS WE BUILD FOR</p>
              <ul className="space-y-2 text-xs mono text-soft">
                <li>NDPA 2023 (Nigeria)</li>
                <li>CBN Cybersecurity Guidelines</li>
                <li>Kenya DPA 2019 / PoPIA ZA</li>
                <li>AU Malabo Convention</li>
              </ul>
            </div>
          </div>

          <div className="pt-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs mono text-soft">
            <div>
              © 2026 CYPHWARD TECHNOLOGIES LTD · ALL RIGHTS RESERVED · PLATFORM v0.1.0
            </div>
            <div className="flex items-center gap-4">
              <Link to="/terms" className="hover:text-ink transition-colors">TERMS</Link>
              <Link to="/privacy" className="hover:text-ink transition-colors">PRIVACY</Link>
              <span className="flex items-center gap-2">
                <span className="live-dot" /> SYSTEM STATUS: OPERATIONAL
              </span>
            </div>
          </div>
        </div>
      </footer>

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
