import { z } from 'zod';

// A closed intermediate representation. Host code alone builds Vega-Lite;
// payloads cannot contain URLs, expressions, HTML, handlers or Vega config.
const point = z.object({ label: z.string().max(200), value: z.number().finite().min(0).max(1e9) }).strict();
const metric = z.enum(['assessment_scores', 'scan_volume', 'findings_discovered', 'findings_resolved', 'severity', 'finding_status', 'categories', 'remediation_status']);
const chartKind = z.enum(['line', 'bar', 'area', 'donut']);
export const reportChartSchema = z.object({
  id: z.string().max(100), title: z.string().max(250), kind: chartKind,
  metric, x_type: z.enum(['temporal', 'ordinal']),
  unit: z.string().max(100), note: z.string().max(1000), points: z.array(point).max(100),
}).strict();
const table = z.object({
  title: z.string().max(250), columns: z.array(z.string().max(100)).min(1).max(8),
  rows: z.array(z.array(z.union([z.string().max(2000), z.number().finite(), z.null()])).max(8)).max(100),
}).strict().refine(t => t.rows.every(row => row.length === t.columns.length), 'Row/column mismatch');
export const reportArtifactSchema = z.object({
  schema_version: z.literal(1), id: z.string().uuid(), version: z.number().int().min(1).max(101), org_id: z.string().uuid(),
  title: z.string().max(300), generated_at: z.string().datetime({ offset: true }),
  days: z.number().int().min(1).max(365), chart_style: z.enum(['line', 'bar', 'area']),
  severities: z.array(z.enum(['critical', 'high', 'medium', 'low', 'info'])).max(5),
  sample: z.boolean(), summary: z.string().max(3000),
  metrics: z.array(z.object({ label: z.string().max(100), value: z.string().max(100) }).strict()).max(8),
  charts: z.array(reportChartSchema).max(8), tables: z.array(table).max(4),
  limitations: z.array(z.string().max(1000)).max(12), sources: z.array(z.string().max(1000)).max(12),
}).strict();
export type ReportArtifact = z.infer<typeof reportArtifactSchema>;
export type ReportChart = z.infer<typeof reportChartSchema>;
export type ArtifactContext = Pick<ReportArtifact, 'id' | 'version' | 'days' | 'chart_style' | 'severities'> & {
  charts: Array<Pick<ReportChart, 'metric' | 'kind'>>;
  include_metrics: boolean; include_tables: boolean; heading: string;
};

export function reportReference(a: ReportArtifact): ArtifactContext {
  return { id: a.id, version: a.version, days: a.days, chart_style: a.chart_style, severities: a.severities,
    charts: a.charts.map(({ metric, kind }) => ({ metric, kind })),
    include_metrics: a.metrics.length > 0, include_tables: a.tables.length > 0, heading: a.title };
}

export function downloadBlob(value: Blob, filename: string) {
  const url = URL.createObjectURL(value);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function csvCell(value: unknown): string {
  let text = String(value ?? '');
  // Prevent a spreadsheet opening a text cell as a formula.
  if (/^[\s]*[=+@-]|^[\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export function tableCSV(columns: string[], rows: unknown[][]): string {
  return [columns, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n');
}

export function chartSpec(chart: ReportChart, width: number) {
  const data = chart.points.map(p => ({ label: p.label, value: p.value }));
  const common = {
    width: Math.max(120, Math.floor(width) - 65), height: 185,
    background: 'transparent', data: { values: data },
    config: {
      font: 'Inter, system-ui, sans-serif', view: { stroke: null },
      axis: { labelColor: '#777b89', titleColor: '#777b89', gridColor: '#88888818', domain: false, ticks: false, labelFontSize: 10, labelLimit: 90, titlePadding: 12 },
      legend: { labelColor: '#777b89', title: null, orient: 'bottom' },
      range: { category: ['#e57b36', '#6992cf', '#74ad92', '#bba1d9', '#dfb55a'] },
    },
  };
  if (chart.kind === 'donut') return {
    ...common, mark: { type: 'arc', innerRadius: 55, cornerRadius: 3 },
    encoding: { theta: { field: 'value', type: 'quantitative' }, color: { field: 'label', type: 'nominal' }, tooltip: [{ field: 'label' }, { field: 'value', title: chart.unit }] },
  };
  return {
    ...common,
    mark: chart.kind === 'line' || chart.kind === 'area' ? {
      type: 'area', color: '#e57b36', fillOpacity: chart.kind === 'area' ? .25 : .12,
      line: { color: '#e57b36', strokeWidth: 2.5 }, point: { filled: true, color: '#e57b36', size: 65 },
    }
      : { type: 'bar', color: '#e57b36', cornerRadiusEnd: 4 },
    encoding: {
      x: { field: 'label', type: chart.x_type, title: null, sort: null,
        axis: chart.x_type === 'temporal' ? { format: '%d %b', labelAngle: 0, tickCount: 5, labelOverlap: true } : { labelAngle: -20 } },
      y: { field: 'value', type: 'quantitative', title: chart.unit, scale: chart.metric === 'assessment_scores' ? { domain: [0, 100] } : { zero: true }, axis: { tickMinStep: 1 } },
      tooltip: [{ field: 'label', title: 'Observation' }, { field: 'value', title: chart.unit }],
    },
  };
}
