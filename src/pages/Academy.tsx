import { useState } from 'react';
import { getAcademy } from '../lib/api';
import { useAsync, useMounted } from '../lib/hooks';
import { useThemeState } from '../lib/theme';
import Meter from '../components/Meter';
import { PageHead, Loading } from '../components/ui';
import { useToast } from '../components/Toast';
import type { Academy as AcademyData } from '../data/mock';

function SimRing({ reported, clicked }: { reported: number; clicked: number }) {
  const on = useMounted();
  const size = 170, cx = 85, cy = 85;
  const R1 = 66, R2 = 47;
  const C1 = 2 * Math.PI * R1, C2 = 2 * Math.PI * R2;
  const t = 'stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1)';
  return (
    <div className="sim-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={cx} cy={cy} r={R1} fill="none" stroke="var(--line)" strokeWidth={9} />
        <circle cx={cx} cy={cy} r={R1} fill="none" stroke="var(--ok)" strokeWidth={9}
          strokeDasharray={C1} strokeDashoffset={on ? C1 * (1 - reported / 100) : C1}
          transform={`rotate(-90 ${cx} ${cy})`} style={{ transition: t }} />
        <circle cx={cx} cy={cy} r={R2} fill="none" stroke="var(--line)" strokeWidth={7} />
        <circle cx={cx} cy={cy} r={R2} fill="none" stroke="var(--accent)" strokeWidth={7}
          strokeDasharray={C2} strokeDashoffset={on ? C2 * (1 - clicked / 100) : C2}
          transform={`rotate(-90 ${cx} ${cy})`} style={{ transition: t }} />
      </svg>
      <div className="ring-center">
        <span className="sim-rep">{reported}%</span>
        <span className="sim-sub mono">REPORTED</span>
        <span className="sim-click mono">{clicked}% CLICKED</span>
      </div>
    </div>
  );
}

function Heatmap({ depts, months, cells }: { depts: string[]; months: string[]; cells: number[][] }) {
  const theme = useThemeState();
  const rgb = theme === 'dark' ? [224, 82, 44] : [193, 59, 22];
  return (
    <div className="overflow-x-auto">
      <div className="heat">
        <div className="heat-row">
          <span />
          {months.map(m => <span key={m} className="hm-h">{m}</span>)}
        </div>
        {depts.map((d, di) => (
          <div className="heat-row" key={d}>
            <span className="hm-dept">{d.toUpperCase()}</span>
            {cells[di].map((v, mi) => (
              <span
                key={mi}
                className="hm-cell"
                style={{
                  background: `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${(v / 100) * 0.6})`,
                  animationDelay: `${(di * 6 + mi) * 35}ms`,
                }}
                title={`${d} · ${months[mi]} — risk ${v}`}
              >
                {v}
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Academy() {
  const { data, loading } = useAsync(getAcademy);
  const toast = useToast();
  const [resuming, setResuming] = useState<string | null>(null);

  if (loading || !data) return <Loading label="ACADEMY" />;
  const a: AcademyData = data;

  return (
    <>
      <PageHead
        eyebrow="LAYER 05 · ACADEMY"
        title="Training that lands."
        note="Courses in English, Hausa and Nigerian Pidgin — because your people defend in the language they think in."
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="panel lg:col-span-7">
          <header className="panel-head">
            <p className="eyebrow">COURSES</p>
            <span className="ph-hint mono">EN · HA · PCM</span>
          </header>
          <div className="panel-body pt-1">
            {a.courses.map(c => (
              <div className="course-row" key={c.id}>
                <p className="course-title">{c.title} <span className="tag">{c.lang}</span></p>
                <div className="course-meta">
                  <Meter pct={c.progress} variant="ok" />
                  <span className="pct mono">{c.progress}%</span>
                  <span className="mins">{c.minutes} MIN</span>
                  <button
                    className="btn-mini"
                    disabled={resuming === c.id}
                    onClick={() => { setResuming(c.id); setTimeout(() => setResuming(null), 700); toast(`Resuming — ${c.title} (${c.lang})`); }}
                  >
                    {resuming === c.id ? 'OPENING…' : 'RESUME'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel lg:col-span-5">
          <header className="panel-head">
            <p className="eyebrow">SIMULATION — {a.sim.name.toUpperCase()}</p>
            <span className="ph-hint mono">{a.sim.window}</span>
          </header>
          <div className="panel-body flex flex-col items-center">
            <SimRing reported={a.sim.reported} clicked={a.sim.clicked} />
            <div className="sim-legend mono">
              <span><i className="ok" />REPORTED {a.sim.reported}%</span>
              <span><i className="bad" />CLICKED {a.sim.clicked}%</span>
            </div>
            <p className="ring-note">SENT {a.sim.sent} LURES · REPORT BEAT CLICK 7:1</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
        <div className="panel lg:col-span-4">
          <header className="panel-head">
            <p className="eyebrow">TOP DEFENDERS</p>
            <span className="ph-hint mono">SEP</span>
          </header>
          <div className="panel-body pt-1">
            {a.leaderboard.map(l => (
              <div className="lb-row" key={l.rank}>
                <span className="lb-rank">{l.rank}</span>
                <div>
                  <p className="lb-name">{l.name}</p>
                  <p className="lb-dept">{l.dept}</p>
                </div>
                <span className="lb-pts">{l.points.toLocaleString('en-US')}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel lg:col-span-8">
          <header className="panel-head">
            <p className="eyebrow">RISK BY DEPARTMENT</p>
            <span className="ph-hint mono">TRAINING RISK · 0–100</span>
          </header>
          <div className="panel-body">
            <Heatmap depts={a.heatmap.depts} months={a.heatmap.months} cells={a.heatmap.cells} />
            <p className="ring-note mt-4">HR RUNS HOT ALL QUARTER — ASSIGN "PASSWORD HYGIENE (PCM)" FIRST.</p>
          </div>
        </div>
      </div>
    </>
  );
}
