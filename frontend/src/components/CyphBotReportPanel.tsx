import { useEffect, useRef, useState, useId } from 'react';
import { ArrowLeft, Download, BarChart3, FileJson, Table2, X } from 'lucide-react';
import { compile } from 'vega-lite';
import { parse, View } from 'vega';
import { expressionInterpreter } from 'vega-interpreter';
import { createPortal } from 'react-dom';
import { chartSpec, downloadBlob, tableCSV, type ReportArtifact, type ReportChart } from '../lib/reportArtifacts';

function Chart({ chart }: { chart: ReportChart }) {
  const container = useRef<HTMLDivElement>(null);
  const view = useRef<View>();
  const [error, setError] = useState('');
  const [hover, setHover] = useState<{ x: number; y: number; label: string; value: string } | null>(null);
  const [exporting, setExporting] = useState(false);
  const hasData = chart.points.length > 0 && (chart.kind !== 'donut' || chart.points.some(p => p.value > 0));
  useEffect(() => {
    if (!container.current || !hasData) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let renderSequence = 0;
    const element = container.current;
    const showPoint = (event: MouseEvent, datum: { label?: unknown; value?: unknown }) => {
      if (disposed || datum.label === undefined || datum.value === undefined) return;
      const label = String(datum.label);
      const date = new Date(typeof datum.label === 'number' ? datum.label : label);
      setHover({ x: Math.max(8, Math.min(event.clientX + 14, window.innerWidth - 230)),
        y: Math.max(8, Math.min(event.clientY + 14, window.innerHeight - 95)),
        label: chart.x_type === 'temporal' && !isNaN(date.getTime()) ? date.toLocaleString() : label,
        value: `${Number(datum.value).toLocaleString()} ${chart.unit}` });
    };
    const draw = async () => {
      const sequence = ++renderSequence;
      view.current?.finalize();
      view.current = undefined;
      element.replaceChildren();
      try {
        // Only host-generated specs are compiled. No resource or plugin loading.
        const spec = compile(chartSpec(chart, element.clientWidth) as Parameters<typeof compile>[0]).spec;
        const next = new View(parse(spec, undefined, { ast: true }), {
          expr: expressionInterpreter, renderer: 'svg', container: element, hover: true,
          loader: {
            load: () => Promise.reject(new Error('External chart data is disabled')),
            sanitize: () => Promise.reject(new Error('External chart resources are disabled')),
            http: () => Promise.reject(new Error('External chart HTTP is disabled')),
            file: () => Promise.reject(new Error('External chart files are disabled')),
          },
          tooltip: (_handler: unknown, event: MouseEvent, item: { datum?: { label?: unknown; value?: unknown } }, value: unknown) => {
            if (disposed) return;
            if (value && item?.datum) showPoint(event, item.datum);
            else setHover(null);
          },
        } as ConstructorParameters<typeof View>[1]);
        view.current = next;
        // Tap a mark to keep its value visible on touch screens.
        next.addEventListener('click', (event, item) => {
          if (item?.datum) showPoint(event as MouseEvent, item.datum);
        });
        await next.runAsync();
        if (disposed || sequence !== renderSequence) next.finalize();
        else setError('');
      } catch {
        if (!disposed && sequence === renderSequence) setError('Chart unavailable. Recorded values remain available in Data.');
      }
    };
    const observer = new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(draw, 60); });
    const hideTooltip = () => setHover(null);
    window.addEventListener('resize', hideTooltip);
    observer.observe(element);
    return () => {
      disposed = true; renderSequence++; clearTimeout(timer); observer.disconnect(); view.current?.finalize();
      window.removeEventListener('resize', hideTooltip);
    };
  }, [chart, hasData]);
  const savePNG = async () => {
    if (!view.current) return;
    setExporting(true);
    try {
      const url = await view.current.toImageURL('png', 2);
      const a = document.createElement('a'); a.href = url; a.download = `${chart.id}.png`; a.click();
    } catch { setError('PNG export failed. You can still download the report data.'); }
    finally { setExporting(false); }
  };
  return <section className="rounded-xl border border-line bg-raised p-4 min-w-0" data-chart-id={chart.id}>
    <div className="flex items-center justify-between gap-2 mb-1">
      <h3 className="text-sm font-semibold text-ink">{chart.title}</h3>
      <button onClick={savePNG} disabled={!hasData || exporting} title={`Download ${chart.title} as PNG`} className="text-soft hover:text-accent disabled:opacity-30 p-1"><Download size={14}/></button>
    </div>
    <p className="text-[10px] text-soft min-h-4">{chart.unit} · Hover or tap to inspect</p>
    {hasData ? <div ref={container} onPointerLeave={() => setHover(null)} onWheelCapture={() => setHover(null)} onBlur={() => setHover(null)} className="w-full min-w-0 min-h-[230px] overflow-hidden" aria-label={chart.title} /> : <div className="h-44 flex items-center justify-center text-sm text-soft">{chart.points.length ? 'All recorded values are zero.' : 'No observations for this chart.'}</div>}
    {hover && createPortal(<div role="tooltip" className="cyphbot-chart-tooltip fixed z-[1200] pointer-events-none rounded-lg border border-line bg-raised px-3 py-2 shadow-xl max-w-[220px] text-xs" style={{ left: hover.x, top: hover.y }}>
      <p className="text-soft text-[10px] mb-1 break-words">{hover.label}</p><p className="font-semibold text-ink">{hover.value}</p>
    </div>, document.body)}
    {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    <p className="text-[11px] text-soft leading-relaxed mt-2">{chart.note}</p>
  </section>;
}

export default function CyphBotReportPanel({ artifact, versions, onVersion, onClose }: {
  artifact: ReportArtifact; versions: ReportArtifact[]; onVersion: (version: ReportArtifact) => void; onClose: () => void;
}) {
  const [tab, setTab] = useState<'preview' | 'data'>('preview');
  const viewId = useId();
  const tabKeys = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'preview' : event.key === 'End' ? 'data' : tab === 'preview' ? 'data' : 'preview';
    setTab(next);
    event.currentTarget.closest('[role="tablist"]')?.querySelector<HTMLButtonElement>(`[data-report-tab="${next}"]`)?.focus();
  };
  const tables = [...artifact.charts.map(chart => ({ title: chart.title, columns: ['Observation', chart.unit], rows: chart.points.map(p => [p.label, p.value]) })), ...artifact.tables];
  const exportJSON = () => downloadBlob(new Blob([JSON.stringify(artifact, null, 2)], { type: 'application/json' }), `cyphward-report-v${artifact.version}.json`);
  return <section className="cyphbot-artifact-panel flex-1 min-w-0 flex flex-col bg-base border-l border-line" aria-label="Organization performance report">
    <header className="px-4 py-3 border-b border-line flex items-center justify-between gap-2 bg-raised flex-none">
      <div className="flex items-center gap-2 min-w-0">
        <button onClick={onClose} aria-label="Back to chat" className="p-1.5 rounded hover:bg-inset"><ArrowLeft size={16}/></button>
        <div className="min-w-0"><p className="text-[9px] tracking-widest text-accent">CYPHBOT / ARTIFACT</p><h2 className="font-semibold text-sm truncate">Workspace report</h2></div>
      </div>
      <button onClick={onClose} aria-label="Close report" className="p-1.5 text-soft hover:text-ink"><X size={16}/></button>
    </header>
    <div className="px-4 py-2 border-b border-line flex flex-wrap items-center justify-between gap-2 flex-none">
      <div className="flex items-center gap-1" role="tablist" aria-label="Report view">
        <button role="tab" id={`${viewId}-preview`} data-report-tab="preview" aria-controls={viewId} tabIndex={tab === 'preview' ? 0 : -1} onKeyDown={tabKeys} aria-selected={tab === 'preview'} onClick={() => setTab('preview')} className={`px-3 py-2 rounded-lg text-xs inline-flex gap-1.5 ${tab === 'preview' ? 'bg-accent/10 text-accent' : 'text-soft'}`}><BarChart3 size={14}/> Preview</button>
        <button role="tab" id={`${viewId}-data`} data-report-tab="data" aria-controls={viewId} tabIndex={tab === 'data' ? 0 : -1} onKeyDown={tabKeys} aria-selected={tab === 'data'} onClick={() => setTab('data')} className={`px-3 py-2 rounded-lg text-xs inline-flex gap-1.5 ${tab === 'data' ? 'bg-accent/10 text-accent' : 'text-soft'}`}><Table2 size={14}/> Data</button>
      </div>
      <div className="flex items-center gap-2">
        <select aria-label="Report version" value={artifact.version} onChange={e => { const a = versions.find(v => v.version === Number(e.target.value)); if (a) onVersion(a); }} className="rounded border border-line bg-raised text-xs p-1.5">
          {versions.map(v => <option key={v.version} value={v.version}>Version {v.version}</option>)}
        </select>
        <button onClick={exportJSON} className="flex items-center gap-1 text-xs text-soft hover:text-accent" title="Download complete report JSON"><FileJson size={14}/><span>JSON</span></button>
      </div>
    </div>
    <div className="flex-1 overflow-y-auto overscroll-contain p-4 md:p-6 space-y-5" role="tabpanel" id={viewId} aria-labelledby={`${viewId}-${tab}`} data-report-scroll>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-[10px] mono text-soft"><span className="rounded-full border border-accent/30 bg-accent/10 text-accent px-2 py-0.5">LOCAL PREVIEW</span>{artifact.sample && <span className="rounded-full border border-line px-2 py-0.5">SAMPLE DATA</span>}<span>{artifact.days} DAYS · V{artifact.version}</span></div>
        <h1 className="text-xl font-semibold text-ink leading-tight">{artifact.title}</h1>
        <p className="text-[10px] text-soft">Generated {new Date(artifact.generated_at).toLocaleString()} · Snapshot of recorded telemetry</p>
        {artifact.severities.length > 0 && <p className="text-xs text-accent">Finding filter: {artifact.severities.join(', ')} · Assessment and task metrics retain their full scope.</p>}
        <p className="text-sm leading-relaxed text-soft">{artifact.summary}</p>
      </div>
      {tab === 'preview' ? <>
        {artifact.metrics.length > 0 && <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">{artifact.metrics.map(metric => <div key={metric.label} className="rounded-lg border border-line bg-raised p-3"><p className="text-[10px] text-soft">{metric.label}</p><p className="text-2xl font-semibold text-ink mt-1">{metric.value}</p></div>)}</div>}
        <div className="space-y-4">{artifact.charts.map(chart => <Chart key={`${artifact.version}-${chart.id}`} chart={chart}/>)}</div>
      </> : <div className="space-y-5">{tables.map((table, i) => <section key={i} className="rounded-xl border border-line bg-raised overflow-hidden">
        <div className="flex items-center justify-between p-3 gap-2"><h3 className="text-xs font-semibold">{table.title}</h3><button title={`Download ${table.title} CSV`} onClick={() => downloadBlob(new Blob([tableCSV(table.columns, table.rows)], { type: 'text/csv;charset=utf-8' }), `cyphward-report-v${artifact.version}-table-${i + 1}.csv`)} className="text-xs text-accent shrink-0">CSV ↓</button></div>
        <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead className="bg-inset"><tr>{table.columns.map((col, j) => <th key={j} className="px-3 py-2 font-medium text-soft">{col}</th>)}</tr></thead><tbody>{table.rows.map((row, j) => <tr key={j} className="border-t border-line">{row.map((cell, k) => <td key={k} className="px-3 py-2 max-w-[250px] break-words">{cell ?? 'Not assessed'}</td>)}</tr>)}</tbody></table>{!table.rows.length && <p className="p-3 text-xs text-soft">No records in this period.</p>}</div>
      </section>)}</div>}
      <details className="rounded-xl border border-line p-3 text-xs text-soft"><summary className="font-medium cursor-pointer">Scope & sources</summary><ul className="mt-2 space-y-2 list-disc pl-4">{[...artifact.limitations, ...artifact.sources].map((text, i) => <li key={i}>{text}</li>)}</ul></details>
      <p className="text-[11px] text-soft">Ask in chat: “Only show a line graph”, “Add scan activity”, or “Explain what changed”. Each revision keeps the earlier version.</p>
    </div>
  </section>;
}
