import { ArrowUpRight, FileText } from 'lucide-react';
import type { ReportArtifact, ReportChart } from '../lib/reportArtifacts';

function Thumbnail({ chart }: { chart: ReportChart }) {
  const values = chart.points;
  const max = chart.metric === 'assessment_scores' ? 100 : Math.max(1, ...values.map(p => p.value));
  const dates = values.map(p => Date.parse(p.label));
  const temporal = chart.x_type === 'temporal' && dates.every(Number.isFinite);
  const start = Math.min(...dates), end = Math.max(...dates);
  const x = (i: number) => temporal && end > start ? 10 + (dates[i] - start) / (end - start) * 260
    : 10 + (values.length < 2 ? 130 : i / (values.length - 1) * 260);
  const y = (value: number) => 70 - value / max * 58;
  const path = values.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join(' ');
  const total = values.reduce((sum, p) => sum + p.value, 0);
  let offset = 0;
  return <svg viewBox="0 0 280 80" className="w-full h-20" aria-hidden="true" data-report-thumbnail>
    {!values.length ? <text x="140" y="44" textAnchor="middle" fill="currentColor" fontSize="10">No recorded observations</text>
      : chart.kind === 'donut' ? <g transform="rotate(-90 140 40)">{!total && <circle cx="140" cy="40" r="26" fill="none" stroke="currentColor" strokeOpacity=".15" strokeWidth="10"/>}{values.map((p, i) => {
        const share = total ? p.value / total * 100 : 0;
        const before = offset; offset += share;
        return <circle key={i} cx="140" cy="40" r="26" fill="none" stroke={['#e57b36', '#6992cf', '#74ad92', '#bba1d9', '#dfb55a'][i % 5]} strokeWidth="10" pathLength="100" strokeDasharray={`${share} ${100 - share}`} strokeDashoffset={-before}/>;
      })}</g>
      : chart.kind === 'bar' ? <g fill="#e57b36">{values.map((p, i) => <rect key={i} x={10 + i * 260 / values.length} y={y(p.value)} width={Math.max(1, 260 / values.length - 4)} height={70 - y(p.value)} rx="2"/>)}</g>
      : <>
        <path d={`${path} L${x(values.length - 1)},70 L${x(0)},70 Z`} fill="#e57b36" fillOpacity=".12"/>
        <path d={path} fill="none" stroke="#e57b36" strokeWidth="2" strokeLinejoin="round"/>
        {values.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.value)} r="2.5" fill="#e57b36"/>)}</>}
  </svg>;
}

export default function CyphBotReportPreview({ artifact, onOpen }: { artifact: ReportArtifact; onOpen: () => void }) {
  return <button type="button" onClick={onOpen} data-open-report data-report-version={artifact.version}
    aria-label={`Open ${artifact.title}, version ${artifact.version}`}
    className="cyphbot-preview-card w-full min-w-0 p-3.5 rounded-2xl border border-line text-left">
    <div className="flex items-center gap-2 min-w-0">
      <span className="p-1.5 rounded-lg bg-accent/10 text-accent"><FileText size={13}/></span>
      <p className="flex-1 text-xs font-semibold truncate">{artifact.title}</p><ArrowUpRight size={14} className="shrink-0 text-accent"/>
    </div>
    {artifact.charts[0] && <div className="my-2 rounded-lg border border-line bg-raised px-2 pt-2 text-soft">
      <div className="flex items-center gap-2"><p className="text-[10px] truncate flex-1">{artifact.charts[0].title} · {artifact.charts[0].unit}</p>{artifact.charts.length > 1 && <span className="text-[9px] shrink-0">+{artifact.charts.length - 1} more</span>}</div>
      <Thumbnail chart={artifact.charts[0]}/>
    </div>}
    <div className="flex flex-wrap items-center justify-between gap-1 text-[9px] text-soft">
      <span>{artifact.charts.length ? `${artifact.charts.length} ${artifact.charts.length === 1 ? 'chart' : 'charts'}` : `${artifact.tables.length} ${artifact.tables.length === 1 ? 'table' : 'tables'}`} · v{artifact.version} · {artifact.days} days{artifact.sample ? ' · Sample' : ''}</span>
      <span className="text-accent">Open report</span>
    </div>
  </button>;
}
