import { useEffect, useState } from 'react';
import { Bar, BarChart, LabelList, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { getScore } from '../lib/api';
import { useAsync } from '../lib/hooks';
import ScoreRing from '../components/ScoreRing';
import { PageHead, Loading } from '../components/ui';
import { highlightJSON } from '../lib/format';

const SHORT_LABELS: Record<string, string> = {
  exposure: 'EXTERNAL',
  threat: 'THREAT',
  compliance: 'COMPLY',
  human: 'TRAIN',
  darkweb: 'DARKWEB',
};

export default function Score() {
  const { data: s, loading } = useAsync(getScore);
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < 640 : false);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 640);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  if (loading || !s) return <Loading label="SCORE" />;

  const bars = s.subscores.map(x => ({
    name: isMobile ? (SHORT_LABELS[x.key] ?? x.label) : x.label,
    value: x.value,
  }));
  const apiResponse = {
    endpoint: 'GET /v1/score?tenant=acme-traders',
    authorization: 'Bearer <token>',
    tenant: s.tenant,
    score: s.score,
    trend: `+${s.trend} this month`,
    sub_scores: Object.fromEntries(s.subscores.map(x => [x.key, x.value])),
  };

  return (
    <>
      <PageHead
        eyebrow="LAYER 04 · SCORE"
        title="The number behind the number."
        note="One composite out of a thousand, five sub-scores underneath, and the exact factors that moved it this month."
        meta={
          <dl className="meta-row">
            <div><dt>TREND</dt><dd className="up">+{s.trend} THIS MONTH</dd></div>
            <div><dt>COMPUTED</dt><dd>HOURLY · 04:00 UTC</dd></div>
          </dl>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="panel lg:col-span-5">
          <header className="panel-head">
            <p className="eyebrow">COMPOSITE</p>
            <span className="ph-hint mono">NDPA-WEIGHTED</span>
          </header>
          <div className="panel-body flex flex-col items-center py-6">
            <ScoreRing score={s.score} max={s.max} size={252} trend={s.trend} />
            <p className="ring-note">WEIGHTS — COMPLIANCE .30 · EXTERNAL .25 · THREAT .20 · TRAINING .15 · DARKWEB .10</p>
          </div>
        </div>

        <div className="panel lg:col-span-7">
          <header className="panel-head">
            <p className="eyebrow">SUB-SCORES</p>
            <span className="ph-hint mono">0–1000</span>
          </header>
          <div className="panel-body pt-4">
            <ResponsiveContainer width="100%" height={264}>
              <BarChart data={bars} layout="vertical" margin={{ left: 0, right: isMobile ? 32 : 44, top: 4, bottom: 4 }}>
                <XAxis type="number" domain={[0, 1000]} hide />
                <YAxis
                  type="category" dataKey="name" width={isMobile ? 78 : 132}
                  tickLine={false} axisLine={false}
                  tick={{ fontSize: isMobile ? 9 : 10, fill: 'var(--soft)', fontFamily: 'IBM Plex Mono' }}
                />
                <Bar dataKey="value" fill="var(--ink)" barSize={11} isAnimationActive animationDuration={900}>
                  <LabelList dataKey="value" position="right"
                    style={{ fontSize: 10, fill: 'var(--ink)', fontFamily: 'IBM Plex Mono', letterSpacing: '0.05em' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
        <div className="panel lg:col-span-7">
          <header className="panel-head">
            <p className="eyebrow">WHAT MOVED IT</p>
            <span className="ph-hint mono">THIS MONTH</span>
          </header>
          <div className="panel-body pt-1">
            {s.factors.map(f => (
              <div className="factor-row" key={f.label}>
                <p className="factor-lbl">{f.label}</p>
                <span className={`factor-delta ${f.delta >= 0 ? 'up' : 'down'}`}>
                  {f.delta >= 0 ? '+' : ''}{f.delta}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel lg:col-span-5">
          <header className="panel-head">
            <p className="eyebrow">SCORE API</p>
            <span className="ph-hint mono">MOCK RESPONSE</span>
          </header>
          <div className="panel-body">
            <pre className="codebox" dangerouslySetInnerHTML={{ __html: highlightJSON(apiResponse) }} />
          </div>
        </div>
      </div>
    </>
  );
}
