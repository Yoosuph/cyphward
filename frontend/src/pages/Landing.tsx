import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowRight, ShieldCheck, Radar, Gauge, GraduationCap, MessageSquare,
  Activity, Lock, Globe, Check, AlertTriangle, Terminal, ChevronRight,
  Sun, Moon, Laptop, Sparkles, Building2, Zap, Shield, Menu, X
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
    summary: 'A single 0–100 security score, updated continuously across four areas: Network, Web apps, Encryption, and Exposure.',
    features: [
      'Live data from cloud, on-premise, and payment switches',
      'Live threat feed for major African financial centres',
      'Instant reports for executives and boards',
    ],
    metric: '74 / 100',
    metricLabel: 'LIVE OVERALL SCORE',
  },
  {
    idx: '02',
    name: 'COMPLY',
    icon: ShieldCheck,
    tagline: 'Automatic NDPA, CBN, and PoPIA checks',
    summary: 'Tracks compliance rules automatically against the Nigeria Data Protection Act (NDPA 2023), the CBN Cybersecurity Framework, and African Union rules.',
    features: [
      'Policy documents drafted for you, with one-click fixes',
      'Evidence collected automatically for NDPC audits',
      'Live scoring of compliance gaps with an estimate of possible fines',
    ],
    metric: '14 / 18 PASS',
    metricLabel: 'NDPA CHECKS PASSED',
  },
  {
    idx: '03',
    name: 'DETECT',
    icon: Radar,
    tagline: 'Threat radar built for Africa',
    summary: 'Built for the problems African businesses actually face: USSD brute-force attacks, SIM-swap fraud, and phishing written in local languages.',
    features: [
      'USSD gateway monitoring for unusual activity (T1566 / T1110)',
      'Live map linking your core switches to payment routes',
      'Automatic SIM-swap checks across telecom APIs',
    ],
    metric: '< 38ms',
    metricLabel: 'TIME TO BLOCK A THREAT',
  },
  {
    idx: '04',
    name: 'SCORE',
    icon: Gauge,
    tagline: 'A security rating built for finance',
    summary: 'A clear security score for insurers, underwriters and regulators. It looks at what is exposed online, live threats, and dark web mentions.',
    features: [
      'Breakdown of your score, refreshed every hour',
      'Compared with others in West and East African finance',
      'Machine-readable REST API for cyber insurance underwriters',
    ],
    metric: '+12 PTS',
    metricLabel: 'MONTHLY SCORE CHANGE',
  },
  {
    idx: '05',
    name: 'ACADEMY',
    icon: GraduationCap,
    tagline: 'Security training in the languages your staff use',
    summary: 'Practice drills in English, Hausa, Yoruba, Pidgin, and Swahili. Your frontline staff become your strongest line of defence.',
    features: [
      'Phishing practice messages over SMS and WhatsApp',
      'Risk heatmaps by department and fun leaderboards',
      'Short lessons made for mobile and branch staff',
    ],
    metric: '92% / 88%',
    metricLabel: 'TRAINING / REPORT RATE',
  },
  {
    idx: '06',
    name: 'COPILOT',
    icon: MessageSquare,
    tagline: 'A security analyst who knows African rules',
    summary: 'An AI assistant trained on African cyber laws, regulations and payment switch systems. It quotes the exact clause every time.',
    features: [
      'Instant NDPA Section 24 and 41 checks, with the clause quoted',
      'Ready-made response steps for NIBSS and payment switches',
      'Run containment steps in one click',
    ],
    metric: '6 SECONDS',
    metricLabel: 'AVERAGE TIME TO ASSESS',
  },
];

const COMPARISON = [
  {
    feature: 'Detection of USSD brute-force and session hijacking',
    global: 'No — assumes HTTP/cloud APIs only',
    cyphward: 'Yes — built for telco and VAS gateways',
  },
  {
    feature: 'Links SIM-swap fraud across telcos',
    global: 'Needs complex custom rules',
    cyphward: 'Automatic — pulls data straight from multiple telco APIs',
  },
  {
    feature: 'Spots social engineering in Hausa, Pidgin and Yoruba',
    global: 'Struggles with local phrasing and slang',
    cyphward: 'Trained on scam messages from West and East Africa',
  },
  {
    feature: 'Continuous NDPA 2023 and CBN security audits',
    global: 'Only covers NIST/SOC2 — you do the gap work by hand',
    cyphward: 'Automated NDPC reports ready from day one',
  },
  {
    feature: 'Payment switch live data (NIBSS, Paystack, M-Pesa)',
    global: 'Generic syslog collection with no transaction context',
    cyphward: 'Reads the protocols African payment switches actually use',
  },
  {
    feature: 'Guarantee that your data stays in your country',
    global: 'Routed through Europe or US data centers',
    cyphward: '100% stored in-region (Lagos, Nairobi, Johannesburg)',
  },
];

const CALCULATOR_SECTORS = [
  { name: 'Commercial Banking & Merchant Banks', baseExposure: '₦450M', controls: 24, recommended: 'Private Plan' },
  { name: 'Fintech & Payment Gateway Switches', baseExposure: '₦180M', controls: 18, recommended: 'Scale Plan' },
  { name: 'Telco VAS & Mobile Money Providers', baseExposure: '₦320M', controls: 22, recommended: 'Private Plan' },
  { name: 'Logistics & Supply Chain Conglomerates', baseExposure: '₦65M', controls: 14, recommended: 'Growth Plan' },
  { name: 'Healthcare & Healthtech Networks', baseExposure: '₦95M', controls: 16, recommended: 'Growth Plan' },
];

export default function Landing() {
  const nav = useNavigate();
  const toast = useToast();
  const [theme, setTheme] = useState(getTheme());
  const [activeLayer, setActiveLayer] = useState(0);
  const [calcSector, setCalcSector] = useState(0);
  const [calcCountry, setCalcCountry] = useState('Nigeria');
  const [previewTab, setPreviewTab] = useState<'telemetry' | 'ndpa' | 'ussd'>('telemetry');

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
          <Link to="/landing" className="landing-brand" onClick={() => setMobileMenuOpen(false)}>
            <CyphwardLogo variant="compact" size={19} />
            <span className="!hidden lg:!inline-block tag text-[9px] ml-1">STRATA 2.0</span>
          </Link>

          <nav className="landing-links">
            <a href="#layers" className="landing-link">LAYERS</a>
            <a href="#threat-matrix" className="landing-link">COMPARE</a>
            <a href="#compliance" className="landing-link">REGULATION</a>
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
                href="#threat-matrix"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>HOW WE COMPARE</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
              <a
                href="#compliance"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>NDPA / CBN REGULATION</span>
                <ChevronRight size={13} className="text-soft" />
              </a>
              <a
                href="#pricing"
                className="py-2 px-2.5 rounded text-xs font-mono tracking-wider text-soft hover:text-ink flex items-center justify-between hover:bg-inset transition-colors"
                onClick={() => setMobileMenuOpen(false)}
              >
                <span>PLANS & PRICING</span>
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
              <span>LIVE DATA · 48 SENSORS · LAGOS · NAIROBI · JOHANNESBURG · KANO</span>
            </div>
          </div>

          <h1 className="hero-h1 max-w-4xl">
            Cyber defense built in Africa for <em>African businesses.</em>
          </h1>

          <p className="hero-desc">
            Big global security tools weren't built for African networks. CYPHWARD keeps you
            on top of NDPA and CBN rules, watches for USSD and SIM-swap fraud, and gives you
            AI that understands local languages — all in one clear dashboard.
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
              <div className="flex gap-2">
                <button
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'telemetry' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('telemetry')}
                >
                  LIVE DATA
                </button>
                <button
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'ndpa' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('ndpa')}
                >
                  NDPA AUDIT
                </button>
                <button
                  className={`chip text-[10px] py-0.5 px-2 ${previewTab === 'ussd' ? 'on' : ''}`}
                  onClick={() => setPreviewTab('ussd')}
                >
                  USSD THREATS
                </button>
              </div>
            </div>

            <div className="p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 bg-raised items-center">
              {previewTab === 'telemetry' && (
                <>
                  <div className="lg:col-span-5 flex flex-col items-center justify-center py-2 border-b lg:border-b-0 lg:border-r border-line pr-0 lg:pr-6">
                    <ScoreRing score={74} max={100} size={200} trend={1} />
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
                      <span className="sub-lbl mono">EXPOSED ONLINE</span>
                      <span className="sub-val text-lg">9</span>
                      <Meter pct={60} variant="bad" />
                      <span className="delta mono down">-1</span>
                    </div>
                    <div className="sub-row">
                      <span className="sub-lbl mono">EMAIL SECURITY</span>
                      <span className="sub-val text-lg">7</span>
                      <Meter pct={70} variant="ok" />
                      <span className="delta mono up">+2</span>
                    </div>
                  </div>
                </>
              )}

              {previewTab === 'ndpa' && (
                <div className="col-span-12 py-3">
                  <div className="flex justify-between items-center mb-4">
                    <div>
                      <h4 className="font-display text-lg font-medium">NDPA 2023 compliance check</h4>
                      <p className="text-xs mono text-soft">Automatic tracking against the Nigeria Data Protection Act</p>
                    </div>
                    <span className="tag ok">14 OF 18 COMPLIANT</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">SEC 24(1) · DATA MINIMIZATION</div>
                      <div className="text-sm font-medium mt-1">FAILED — ACTION REQUIRED</div>
                      <p className="text-[11px] mono text-accent mt-2">Customer logs kept beyond 90 days</p>
                    </div>
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">SEC 41 · CROSS-BORDER TRANSFERS</div>
                      <div className="text-sm font-medium mt-1 text-ok">COMPLIANT — VERIFIED</div>
                      <p className="text-[11px] mono text-soft mt-2">All personal data stored in a Nigerian AWS Local Zone</p>
                    </div>
                    <div className="p-3 bg-inset border border-line rounded">
                      <div className="text-[10px] mono text-soft">SEC 34 · BREACH NOTIFICATION</div>
                      <div className="text-sm font-medium mt-1 text-ok">COMPLIANT — AUTO-REPORTING</div>
                      <p className="text-[11px] mono text-soft mt-2">NDPC notified automatically in under 72 hours</p>
                    </div>
                  </div>
                </div>
              )}

              {previewTab === 'ussd' && (
                <div className="col-span-12 py-3">
                  <div className="flex justify-between items-center mb-4">
                    <div>
                      <h4 className="font-display text-lg font-medium">Unusual activity on USSD and payment gateways</h4>
                      <p className="text-xs mono text-soft">Live detection of session hijacking and rapid PIN guessing</p>
                    </div>
                    <span className="tag acc">THREAT BLOCKED</span>
                  </div>
                  <div className="p-4 bg-inset border border-line font-mono text-xs leading-relaxed overflow-x-auto">
                    <div className="text-soft">// EVENT_ID: EVT_KAN_98412 — GATEWAY: ussd-gw-02.kano</div>
                    <div className="text-ink mt-1">ANOMALY: Rapid PIN guessing against the core banking USSD switch (*901#)</div>
                    <div className="text-accent mt-1">DETAIL: 1,420 session requests in 9.2s from 3 SIM-swap fraud groups</div>
                    <div className="text-ok mt-1">ACTION: Rate limiter engaged · Telco fraud API notified · IP blocked</div>
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-3 border-t border-line bg-inset flex items-center justify-between">
              <span className="text-xs mono text-soft flex items-center gap-2">
                <Terminal size={13} className="text-accent" /> ENTERPRISE HARDWARE WORKSPACE · READY FOR AUDIT
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
            <div className="stat-matrix-val text-accent">₦4.8B+</div>
            <div className="stat-matrix-lbl">FRAUD STOPPED AT PAYMENT SWITCHES</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val text-ok">99.8%</div>
            <div className="stat-matrix-lbl">NDPA & CBN AUDIT PASS RATE</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val">&lt; 38ms</div>
            <div className="stat-matrix-lbl">TIME TO DETECT AND BLOCK A THREAT</div>
          </div>
          <div className="stat-matrix-cell">
            <div className="stat-matrix-val">100%</div>
            <div className="stat-matrix-lbl">DATA STORED IN-COUNTRY</div>
          </div>
        </section>

        {/* The 6 Strata Defense Layers */}
        <section id="layers" className="py-16">
          <div className="sec-head">
            <p className="eyebrow">THE DEFENSE ARCHITECTURE</p>
            <h2>The 6 Layers of Strata Defense.</h2>
            <p className="sec-note">
              Complete security coverage for African businesses — from a boardroom security score
              to frontline staff training in local languages. Click through each layer to see what it does.
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
                  Live data sampled from servers in Nigeria, Kenya, and South Africa.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* African Threat Matrix: Cyphward vs Global SIEMs */}
        <section id="threat-matrix" className="py-16">
          <div className="sec-head">
            <p className="eyebrow">REGIONAL ADVANTAGE</p>
            <h2>Why global security tools leave African businesses exposed.</h2>
            <p className="sec-note">
              Western tools are built for US and EU payment systems and English messages.
              They miss the threats behind 84% of financial fraud in Africa.
            </p>
          </div>

          <div className="ledger-wrap panel">
            <table className="ledger">
              <thead>
                <tr>
                  <th style={{ width: '40%' }}>THREATS & CAPABILITIES</th>
                  <th style={{ width: '30%' }}>TYPICAL GLOBAL TOOLS</th>
                  <th style={{ width: '30%' }}>CYPHWARD STRATA DEFENSE</th>
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row, i) => (
                  <tr key={i}>
                    <td className="font-medium">{row.feature}</td>
                    <td className="text-soft mono text-xs">{row.global}</td>
                    <td className="text-ok mono text-xs font-medium">
                      <Check size={13} className="inline mr-1 text-ok" />
                      {row.cyphward}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Interactive Regulatory Exposure Calculator */}
        <section id="compliance" className="py-16">
          <div className="calc-panel">
            <div className="sec-head mb-6">
              <p className="eyebrow">WHAT NON-COMPLIANCE COSTS</p>
              <h2 className="text-2xl">See what breaking the rules could cost you</h2>
              <p className="sec-note">
                Pick your industry and country to see what you could owe if you don't meet NDPA and CBN rules.
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
                    <option value="Egypt">Egypt (Law 151 / CBE Cybersecurity)</option>
                  </select>
                </div>
              </div>

              <div className="lg:col-span-6 p-6 bg-inset border border-line rounded">
                <div className="flex justify-between items-center mb-4">
                  <span className="eyebrow">ESTIMATED FINE IF YOU'RE NON-COMPLIANT</span>
                  <span className="tag acc">MAXIMUM FINE</span>
                </div>
                <div className="font-display text-4xl text-accent font-medium mb-1">
                  {CALCULATOR_SECTORS[calcSector].baseExposure}
                </div>
                <p className="text-xs mono text-soft mb-4">
                  The law allows fines of up to 2% of annual turnover or ₦10M (NDPA Sec 48).
                </p>

                <div className="space-y-2 border-t border-line pt-3 text-xs mono">
                  <div className="flex justify-between">
                    <span className="text-soft">REQUIRED CHECKS:</span>
                    <span>{CALCULATOR_SECTORS[calcSector].controls} technical and organisational checks</span>
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
                  RUN A REAL COMPLIANCE SCAN <ArrowRight size={13} />
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Enterprise Enclaves & Pricing */}
        <section id="pricing" className="py-16">
          <div className="sec-head">
            <p className="eyebrow">SIMPLE PLANS</p>
            <h2>Transparent pricing for every scale.</h2>
            <p className="sec-note">
              From fast-growing African startups to central banks and critical payment networks.
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
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Up to 500 employee devices</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Continuous NDPA 2023 audit</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Continuous scanning of what's exposed online</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Daily threat updates</li>
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
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Unlimited devices and switches</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> USSD and SIM-swap monitoring built in</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> NDPA, CBN & ISO 27001 full suite</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Support for all 5 African languages</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Dedicated security officer, reply in under 15 min</li>
              </ul>
              <button className="btn btn-solid w-full justify-center" onClick={handleGetStarted}>
                START WITH SCALE
              </button>
            </div>

            {/* Tier 3 */}
            <div className="pricing-card">
              <span className="tag w-fit mb-3">PRIVATE</span>
              <h3 className="font-display text-2xl font-medium mb-1">Fully Air-Gapped</h3>
              <p className="text-xs mono text-soft mb-4">For central banks and critical national infrastructure.</p>
              <div className="font-display text-3xl font-medium my-2">CUSTOM <span className="text-xs font-mono text-soft">/ annual</span></div>
              <ul className="space-y-2.5 my-6 text-xs mono text-soft flex-1">
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Runs on your own servers — fully air-gapped</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Connects to national payment switches</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> Threat monitoring tuned for state-sponsored attacks</li>
                <li className="flex items-center gap-2"><Check size={14} className="text-ok" /> 24/7 security team in Lagos and Abuja</li>
              </ul>
              <Link to="/signup" className="btn btn-ghost w-full justify-center">
                CONTACT OUR TEAM
              </Link>
            </div>
          </div>
        </section>

        {/* CISO Testimonial Banner */}
        <section className="my-16 p-8 panel border-accent/40 bg-raised relative overflow-hidden">
          <div className="max-w-3xl">
            <p className="eyebrow mb-2">CUSTOMER STORY</p>
            <blockquote className="font-display text-2xl font-normal italic leading-relaxed mb-4">
              "When our USSD gateways were hit with coordinated brute-force attacks during the Eid holiday,
              our previous tool sent us nothing. CYPHWARD's Layer 03 pinpointed the SIM-swap fraud and alerted our security team in under 40 seconds."
            </blockquote>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-inset border border-line flex items-center justify-center font-display font-medium text-accent">
                AK
              </div>
              <div>
                <p className="font-medium text-sm">Alhaji Kabir Danbaba</p>
                <p className="text-xs mono text-soft">Chief Information Security Officer · Commercial Merchant Bank of West Africa</p>
              </div>
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
            Create your account, add your domain, and run a real scan — you get a security score, compliance reports, and clear steps to fix any issues.
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
              <p className="eyebrow mb-3">REGULATIONS WE TRACK</p>
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
              © 2026 CYPHWARD TECHNOLOGIES LTD · ALL RIGHTS RESERVED · PLATFORM v0.2.0
            </div>
            <div className="flex items-center gap-2">
              <span className="live-dot" /> SYSTEM STATUS: OPERATIONAL
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
