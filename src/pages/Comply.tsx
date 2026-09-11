import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts';
import { Search, X, Download } from 'lucide-react';
import { getCompliance, draftPolicy } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { DEFAULT_FRAMEWORK } from '../data/mock';
import DataTable from '../components/DataTable';
import StatusChip from '../components/StatusChip';
import Drawer from '../components/Drawer';
import { PageHead, Loading, ctlLevel } from '../components/ui';
import { useToast } from '../components/Toast';
import type { Control } from '../data/mock';

function GapDonut({ passing, failing, pending }: { passing: number; failing: number; pending: number }) {
  const data = [
    { name: 'PASS', value: passing, fill: 'var(--ok)' },
    { name: 'FAIL', value: failing, fill: 'var(--accent)' },
    { name: 'PENDING', value: pending, fill: 'var(--warn)' },
  ];
  const total = passing + failing + pending;
  const passRate = total > 0 ? Math.round((passing / total) * 100) : 0;

  return (
    <div>
      <div className="donut-wrap min-h-[174px] w-full relative">
        <ResponsiveContainer width="100%" height={174}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="64%" outerRadius="94%"
              startAngle={90} endAngle={-270} stroke="none">
              {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">
          <span className="donut-num">{passRate}%</span>
          <span className="donut-den mono">{passing} / {total} PASS</span>
        </div>
      </div>
      <ul className="donut-legend mono">
        {data.map(d => (
          <li key={d.name}>
            <i style={{ background: d.fill }} />{d.name}<b>{d.value} CONTROLS</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Comply() {
  const toast = useToast();
  const [framework, setFramework] = useState(DEFAULT_FRAMEWORK);
  const { data, loading } = useAsync(() => getCompliance(framework), [framework]);
  const [searchParams] = useSearchParams();
  const [selected, setSelected] = useState<Control | null>(() => {
    try {
      return typeof window !== 'undefined' && window.location.search.includes('open')
        ? {
            id: 'NDPA-2(1)',
            name: 'Lawful basis for processing',
            framework: 'NDPA 2023',
            status: 'PASS' as const,
            lastReviewed: '2025-06-02',
            owner: 'Legal',
            evidence: 'RoPA v3 — lawful basis documented for all 41 datasets.',
          }
        : null;
    } catch {
      return null;
    }
  });
  const [drafting, setDrafting] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'FAIL' | 'PENDING' | 'PASS'>('ALL');
  const [search, setSearch] = useState('');
  const [mobileTab, setMobileTab] = useState<'controls' | 'gaps' | 'remediations'>('controls');

  useEffect(() => {
    const cId = searchParams.get('control');
    if (cId && data) {
      const match = data.controls.find(c => c.id === cId);
      if (match) setSelected(match);
    }
  }, [searchParams, data]);

  const firstFail = data?.controls.find(c => c.status === 'FAIL');
  const failCount = data?.controls.filter(c => c.status === 'FAIL').length ?? 0;
  const pendingCount = data?.controls.filter(c => c.status === 'PENDING').length ?? 0;
  const passCount = data?.controls.filter(c => c.status === 'PASS').length ?? 0;

  const filteredControls = (data?.controls ?? []).filter(c => {
    if (statusFilter !== 'ALL' && c.status !== statusFilter) return false;
    if (search && !c.name.toLowerCase().includes(search.toLowerCase()) && !c.id.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const doDraft = async (control: Control | undefined) => {
    if (!control || drafting) return;
    setDrafting(true);
    const r = await draftPolicy(control.id);
    setDrafting(false);
    if (r.ok) toast(`Policy draft queued — ${control.name} (${control.id})`);
  };

  const handleExportAudit = () => {
    toast(`Compiling official ${framework} continuous audit dossier…`);
    setTimeout(() => {
      toast(`${framework} Regulatory Audit Dossier generated and signed.`);
    }, 700);
  };

  return (
    <>
      <PageHead
        eyebrow="LAYER 02 · COMPLY"
        title="Compliance, control by control."
        note="Every control, every framework, one register. Tap any control to inspect evidence and its linked remediation."
        meta={
          <dl className="meta-row">
            <div><dt>CONTROLS VALIDATED</dt><dd>{passCount} / {data?.controls.length ?? 18}</dd></div>
            <div><dt>CRITICAL GAPS</dt><dd className="acc">{failCount}</dd></div>
            <div><dt>VERDICT</dt><dd className={failCount === 0 ? 'up' : 'acc'}>{failCount === 0 ? 'COMPLIANT' : 'GAPS OPEN'}</dd></div>
          </dl>
        }
      />

      {/* Framework Selector Strip — Horizontal scroll without ugly scrollbars */}
      <div className="flex items-center gap-2 overflow-x-auto max-w-full pb-2 mb-5 no-scrollbar">
        {data?.frameworks.map(f => (
          <button
            key={f.key}
            className={`chip text-xs py-2 px-3.5 flex-none whitespace-nowrap ${framework === f.key ? 'on' : ''}`}
            onClick={() => setFramework(f.key)}
          >
            <span className="font-semibold">{f.key.toUpperCase()}</span>
            <span className="count ml-1.5">{f.passing}/{f.controls}</span>
          </button>
        ))}
      </div>

      {/* ============ EXECUTIVE AUDIT HEALTH SUMMARY (Mobile & Tablet < lg) ============ */}
      {data && (
        <div className="lg:hidden panel p-4 mb-6 hover-lift">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-line">
            <p className="eyebrow flex items-center gap-1.5 text-[10px]">
              <span className="live-dot" /> AUDIT HEALTH PROFILE — {framework.toUpperCase()}
            </p>
            <span className={`tag text-[9px] ${failCount === 0 ? 'text-ok border-ok/30' : 'text-accent border-accent/30'}`}>
              {failCount === 0 ? 'FULLY COMPLIANT' : 'GAPS IDENTIFIED'}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-center">
            <div className="sm:col-span-5 flex justify-center">
              <div className="w-full max-w-[200px]">
                <GapDonut passing={data.passing} failing={failCount} pending={pendingCount} />
              </div>
            </div>
            <div className="sm:col-span-7 flex flex-col justify-center gap-2">
              <div className="grid grid-cols-3 gap-2 text-center p-2 rounded bg-inset border border-line">
                <div>
                  <span className="mono text-xs font-semibold text-ok">{data.passing}</span>
                  <p className="mono text-[8.5px] text-soft mt-0.5">PASS</p>
                </div>
                <div>
                  <span className="mono text-xs font-semibold text-accent">{failCount}</span>
                  <p className="mono text-[8.5px] text-soft mt-0.5">FAIL</p>
                </div>
                <div>
                  <span className="mono text-xs font-semibold text-warn">{pendingCount}</span>
                  <p className="mono text-[8.5px] text-soft mt-0.5">PENDING</p>
                </div>
              </div>
              <button
                className="btn btn-ghost w-full justify-center text-xs py-2 mt-1 hover-lift"
                onClick={handleExportAudit}
              >
                <Download size={13} className="mr-1.5" /> EXPORT AUDIT DOSSIER (PDF)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Mobile & Tablet Section Switcher (Controls Register vs Remediation Queue) */}
      <div className="flex lg:hidden items-center border border-line-strong rounded p-1 bg-inset mb-5">
        <button
          type="button"
          className={`flex-1 py-2 text-xs font-mono tracking-wider rounded transition-all text-center ${
            mobileTab === 'controls' ? 'bg-raised text-ink font-semibold shadow-sm' : 'text-soft hover:text-ink'
          }`}
          onClick={() => setMobileTab('controls')}
        >
          CONTROLS REGISTER ({filteredControls.length})
        </button>
        <button
          type="button"
          className={`flex-1 py-2 text-xs font-mono tracking-wider rounded transition-all text-center ${
            mobileTab === 'remediations' ? 'bg-raised text-ink font-semibold shadow-sm' : 'text-soft hover:text-ink'
          }`}
          onClick={() => setMobileTab('remediations')}
        >
          REMEDIATION QUEUE ({data?.remediations.length ?? 0})
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* ============ CONTROL REGISTER ============ */}
        <div className={`panel lg:col-span-8 hover-lift ${mobileTab !== 'controls' ? 'hidden lg:block' : ''}`}>
          <header className="panel-head flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <p className="eyebrow">CONTROL REGISTER</p>
              <span className="tag text-[9px]">{framework.toUpperCase()}</span>
            </div>
            <span className="ph-hint mono">{data ? `${filteredControls.length} OF ${data.controls.length} CONTROLS` : ''}</span>
          </header>

          {/* Search and Status Filter Controls */}
          <div className="p-3 border-b border-line bg-inset/40 flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
            <div className="relative flex-1">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-soft pointer-events-none" />
              <input
                type="text"
                placeholder="Search controls or ID..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full text-xs mono py-1.5 pl-8 pr-7 bg-raised border border-line-strong rounded focus:outline-none focus:border-ink"
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-soft hover:text-ink text-xs"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            <div className="flex items-center gap-1 border border-line-strong rounded p-0.5 bg-raised overflow-x-auto no-scrollbar flex-none">
              {(['ALL', 'FAIL', 'PENDING', 'PASS'] as const).map(s => {
                const count = s === 'ALL'
                  ? data?.controls.length
                  : data?.controls.filter(c => c.status === s).length;
                return (
                  <button
                    key={s}
                    type="button"
                    className={`chip flex-1 sm:flex-none justify-center text-[10px] py-1 px-2.5 border-0 whitespace-nowrap ${statusFilter === s ? 'on' : ''}`}
                    onClick={() => setStatusFilter(s)}
                  >
                    {s} <span className="count ml-0.5">({count ?? 0})</span>
                  </button>
                );
              })}
            </div>
          </div>

          {loading || !data ? (
            <div className="panel-body"><Loading label="CONTROLS" /></div>
          ) : (
            <>
              {/* Desktop/Tablet Table View */}
              <div className="hidden md:block">
                <DataTable<Control>
                  rows={filteredControls}
                  rowId={r => r.id}
                  minWidth={560}
                  onRowClick={setSelected}
                  selectedId={selected?.id ?? null}
                  columns={[
                    { key: 'id', label: 'ID' },
                    { key: 'name', label: 'CONTROL' },
                    { key: 'status', label: 'STATUS', render: r => <StatusChip level={ctlLevel(r.status)}>{r.status}</StatusChip> },
                    { key: 'lastReviewed', label: 'LAST REVIEWED', hide: 'sm' },
                  ]}
                />
              </div>

              {/* Mobile Card List View (< md) */}
              <div className="md:hidden p-3 flex flex-col gap-2.5">
                {filteredControls.map(c => (
                  <div
                    key={c.id}
                    onClick={() => setSelected(c)}
                    className="p-3.5 bg-raised border border-line hover:border-ink rounded-lg transition-all cursor-pointer shadow-sm active:scale-[0.99]"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <span className="font-mono text-xs font-semibold text-accent tracking-wider">{c.id}</span>
                      <StatusChip level={ctlLevel(c.status)}>{c.status}</StatusChip>
                    </div>
                    <p className="text-[13px] font-medium text-ink leading-snug">{c.name}</p>
                    <div className="flex items-center justify-between text-[10px] mono text-soft pt-2 mt-2 border-t border-line/60">
                      <span>REVIEWED {c.lastReviewed}</span>
                      <span className="text-accent flex items-center gap-1 font-semibold">INSPECT EVIDENCE ↗</span>
                    </div>
                  </div>
                ))}
                {filteredControls.length === 0 && (
                  <div className="p-8 text-center mono text-xs text-soft">
                    NO CONTROLS MATCHING CURRENT FILTER.
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* ============ DESKTOP/MOBILE RIGHT COLUMN ============ */}
        <div className={`lg:col-span-4 flex flex-col gap-6 ${mobileTab !== 'remediations' ? 'hidden lg:flex' : 'flex'}`}>
          {/* GAP PROFILE (Desktop only, since mobile has Executive Summary Card above) */}
          <div className="panel hover-lift hidden lg:block">
            <header className="panel-head">
              <p className="eyebrow">GAP PROFILE</p>
              <span className="ph-hint mono">{framework.toUpperCase()}</span>
            </header>
            <div className="panel-body">
              {data ? (
                <>
                  <GapDonut passing={data.passing} failing={failCount} pending={pendingCount} />
                  <div className="mt-4 pt-4 border-t border-line flex flex-col gap-2.5">
                    <div className="flex items-center justify-between text-xs mono">
                      <span className="text-soft">AUDIT VERDICT</span>
                      <span className={failCount === 0 ? 'text-ok font-semibold' : 'text-accent font-semibold'}>
                        {failCount === 0 ? 'FULLY COMPLIANT' : 'CONDITIONALLY COMPLIANT'}
                      </span>
                    </div>
                    <button
                      className="btn btn-ghost w-full justify-center text-xs py-2 mt-1 hover-lift"
                      onClick={handleExportAudit}
                    >
                      <Download size={13} className="mr-1.5" /> EXPORT AUDIT DOSSIER
                    </button>
                  </div>
                </>
              ) : (
                <Loading label="GAPS" />
              )}
            </div>
          </div>

          {/* REMEDIATION QUEUE */}
          <div className="panel hover-lift">
            <header className="panel-head">
              <div className="flex items-center gap-2">
                <p className="eyebrow">REMEDIATION QUEUE</p>
                {data?.remediations && data.remediations.length > 0 && (
                  <span className="tag text-[9px] text-accent border-accent/30">{data.remediations.length} OPEN</span>
                )}
              </div>
              <span className="ph-hint mono">SEVERITY ORDER</span>
            </header>
            <div className="panel-body">
              <ol className="sev-list">
                {data?.remediations.map(r => (
                  <li key={r.id} className={`sev-item ${r.severity === 'CRITICAL' ? 'crit' : r.severity === 'HIGH' ? 'high' : r.severity === 'MEDIUM' ? 'med' : 'low'}`}>
                    <p className="sev-title">
                      <span className={`sev sev-${r.severity.toLowerCase()}`}>{r.severity}</span>
                      {r.title}
                    </p>
                    <p className="sev-meta">{r.control} · {r.owner} · DUE {r.due}</p>
                  </li>
                ))}
              </ol>
              <button
                className="btn btn-solid w-full justify-center mt-4"
                disabled={drafting || !firstFail}
                onClick={() => doDraft(firstFail)}
              >
                {drafting ? 'DRAFTING REMEDIATION…' : 'AUTO-DRAFT LEGAL POLICY'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Control Detail Inspector Drawer */}
      <Drawer open={!!selected} onClose={() => setSelected(null)} eyebrow="CONTROL DETAIL">
        {selected && (
          <>
            <h3 className="drawer-id mono text-accent">{selected.id}</h3>
            <p className="drawer-name">{selected.name}</p>
            <div className="chips-row">
              <StatusChip level={ctlLevel(selected.status)}>{selected.status}</StatusChip>
              <span className="tag">{selected.framework.toUpperCase()}</span>
            </div>
            <dl className="kv">
              <div><dt>OWNER</dt><dd>{selected.owner}</dd></div>
              <div><dt>LAST REVIEWED</dt><dd>{selected.lastReviewed}</dd></div>
            </dl>
            <p className="label">EVIDENCE</p>
            <p className="drawer-evidence">{selected.evidence}</p>
            {(() => {
              const rem = data?.remediations.find(r => r.control === selected.id);
              if (!rem) return null;
              return (
                <>
                  <p className="label">LINKED REMEDIATION</p>
                  <div className="rem-mini">
                    <span className={`sev sev-${rem.severity.toLowerCase()}`}>{rem.severity}</span>
                    {rem.title}
                    <span className="mono block mt-2" style={{ fontSize: 10, letterSpacing: '.1em', color: 'var(--soft)' }}>
                      {rem.owner} · DUE {rem.due}
                    </span>
                  </div>
                </>
              );
            })()}
            {selected.status !== 'PASS' && (
              <button className="btn btn-solid w-full justify-center" onClick={() => doDraft(selected)}>
                DRAFT POLICY
              </button>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}
