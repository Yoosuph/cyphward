import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { getAlerts, getAlertDetail, getDetectionLayers } from '../lib/api';
import { useAsync } from '../lib/hooks';
import { FIRST_ALERT_ID } from '../data/mock';
import DataTable from '../components/DataTable';
import StatusChip from '../components/StatusChip';
import Meter from '../components/Meter';
import { PageHead, Loading, sevLevel, statusLevel } from '../components/ui';
import { useToast } from '../components/Toast';
import type { Alert } from '../data/mock';

import TopologyGraph from '../components/TopologyGraph';

export default function Detect() {
  const location = useLocation();
  const state = location.state as { alertId?: string } | null;
  const [sel, setSel] = useState<string>(state?.alertId ?? FIRST_ALERT_ID);
  const alerts = useAsync(getAlerts);
  const layers = useAsync(getDetectionLayers);
  const detail = useAsync(() => getAlertDetail(sel), [sel]);
  const toast = useToast();

  return (
    <>
      <PageHead
        eyebrow="LAYER 03 · DETECT"
        title="Signals, triaged live."
        note="Five detection layers, one alert ledger. Select a signal to see the L5 LLM triage, its confidence, and the recommended actions."
        meta={
          <dl className="meta-row">
            <div><dt>ACTIVE LAYERS</dt><dd>{layers.data?.length ?? 5} / 5</dd></div>
            <div><dt>OPEN SIGNALS</dt><dd>{alerts.data?.filter(a => a.status === 'OPEN').length ?? 0}</dd></div>
          </dl>
        }
      />

      <div className="layers">
        {layers.data?.map(l => (
          <div className="layer" key={l.id}>
            <p className="layer-id mono"><span className={`dm ${l.hits > 0 ? 'bad' : ''}`} />{l.id}</p>
            <p className="layer-name mono">{l.name}</p>
            <p className="layer-meta mono"><span className="live-dot" />{l.hits} HITS · {l.detail}</p>
          </div>
        ))}
        {!layers.data && <div className="layer"><Loading label="LAYERS" /></div>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
        <div className="panel lg:col-span-7">
          <header className="panel-head">
            <p className="eyebrow">ALERT LEDGER</p>
            <span className="ph-hint mono">UTC · TODAY</span>
          </header>
          {alerts.data ? (
            <DataTable<Alert>
              rows={alerts.data}
              rowId={r => r.id}
              minWidth={560}
              onRowClick={r => setSel(r.id)}
              selectedId={sel}
              columns={[
                { key: 'time', label: 'TIME' },
                { key: 'title', label: 'ALERT' },
                { key: 'technique', label: 'TECHNIQUE', hide: 'md' },
                { key: 'severity', label: 'SEVERITY', render: r => <StatusChip level={sevLevel(r.severity)}>{r.severity}</StatusChip> },
                { key: 'status', label: 'STATUS', render: r => <StatusChip level={statusLevel(r.status)}>{r.status}</StatusChip> },
              ]}
            />
          ) : (
            <div className="panel-body"><Loading label="ALERTS" /></div>
          )}
        </div>

        <div className="panel lg:col-span-5">
          <header className="panel-head">
            <p className="eyebrow">SIGNAL DETAIL</p>
            {alerts.data && (
              <StatusChip level={statusLevel(alerts.data.find(a => a.id === sel)?.status ?? 'OPEN')}>
                {alerts.data.find(a => a.id === sel)?.status}
              </StatusChip>
            )}
          </header>
          <div className="panel-body">
            {!detail.data ? (
              <Loading label="TRIAGE" />
            ) : (
              <>
                <h3 className="detail-title">{alerts.data?.find(a => a.id === sel)?.title}</h3>
                <div className="chips-row">
                  <span className="tag">{alerts.data?.find(a => a.id === sel)?.technique}</span>
                  <span className="tag">{alerts.data?.find(a => a.id === sel)?.entity}</span>
                </div>

                <div className="conf-block">
                  <span className="conf-num">{detail.data.confidence.toFixed(2)}</span>
                  <span className="conf-lbl mono">AI CONFIDENCE</span>
                  <Meter pct={detail.data.confidence * 100} tall className="mt-3" />
                  <p className="conf-src mono">L5 LLM TRIAGE · GROUNDED ON RAW EVENTS</p>
                </div>

                <p className="detail-sum">{detail.data.summary}</p>

                <p className="label">RECOMMENDED ACTIONS</p>
                <div className="act-row">
                  {detail.data.actions.map((a, i) => (
                    <button
                      key={a.label}
                      className={`btn ${i === 0 ? 'btn-solid' : 'btn-ghost'}`}
                      onClick={() => toast(a.toast)}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>

                <p className="label">TIMELINE</p>
                <ol className="tl">
                  {detail.data.timeline.map(t => (
                    <li key={t.t}><span className="tl-t">{t.t}</span><span>{t.label}</span></li>
                  ))}
                </ol>

                {detail.data.related.length > 0 && (
                  <>
                    <p className="label">RELATED</p>
                    <div className="flex flex-col gap-2">
                      {detail.data.related.map(rel => (
                        <button key={rel.id} className="rel-link" onClick={() => setSel(rel.id)}>
                          {rel.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}

                <p className="label">RAW EVIDENCE</p>
                <pre
                  className="codebox"
                  dangerouslySetInnerHTML={{
                    __html: detail.data.evidence
                      .map(l => l.replace(/^(\d{2}:\d{2}:\d{2})/, '<span class="pk">$1</span>'))
                      .join('\n'),
                  }}
                />
              </>
            )}
          </div>
        </div>
      </div>

      <div className="panel mt-6 overflow-hidden hover-lift">
        <header className="panel-head">
          <div className="flex items-center gap-2">
            <p className="eyebrow">TOPOLOGY — KANO EDGE</p>
            <span className="tag text-[9px] acc">OBSIDIAN FORCE GRAPH</span>
          </div>
          <p className="ph-hint mono"><span className="dm bad" /> ACTIVE BEACON · <span className="dm" /> NODE · DRAG & ZOOM</p>
        </header>
        <TopologyGraph />
      </div>
    </>
  );
}
