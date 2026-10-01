import { useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { TrendingUp, ShieldAlert, Clock, Zap, CheckCircle2, Eye, EyeOff } from 'lucide-react';

interface DataPoint {
  date: string;
  score: number;
  threats: number;
  mttr: number; // in minutes
}

const DATA_7D: DataPoint[] = [
  { date: 'Sep 13', score: 77, threats: 28, mttr: 34 },
  { date: 'Sep 14', score: 77, threats: 32, mttr: 31 },
  { date: 'Sep 15', score: 78, threats: 19, mttr: 28 },
  { date: 'Sep 16', score: 80, threats: 41, mttr: 24 },
  { date: 'Sep 17', score: 81, threats: 36, mttr: 22 },
  { date: 'Sep 18', score: 83, threats: 48, mttr: 19 },
  { date: 'Sep 19', score: 84, threats: 35, mttr: 18.4 },
];

const DATA_30D: DataPoint[] = [
  { date: 'Aug 21', score: 68, threats: 52, mttr: 58 },
  { date: 'Aug 25', score: 70, threats: 44, mttr: 52 },
  { date: 'Aug 29', score: 71, threats: 41, mttr: 46 },
  { date: 'Sep 02', score: 73, threats: 38, mttr: 41 },
  { date: 'Sep 06', score: 76, threats: 33, mttr: 35 },
  { date: 'Sep 10', score: 78, threats: 29, mttr: 28 },
  { date: 'Sep 14', score: 80, threats: 35, mttr: 23 },
  { date: 'Sep 19', score: 84, threats: 35, mttr: 18.4 },
];

const DATA_90D: DataPoint[] = [
  { date: 'Jul W1', score: 580, threats: 68, mttr: 95 },
  { date: 'Jul W3', score: 615, threats: 62, mttr: 84 },
  { date: 'Aug W1', score: 660, threats: 54, mttr: 68 },
  { date: 'Aug W3', score: 710, threats: 45, mttr: 50 },
  { date: 'Sep W1', score: 770, threats: 38, mttr: 32 },
  { date: 'Sep W3', score: 842, threats: 35, mttr: 18.4 },
];

const DATA_1Y: DataPoint[] = [
  { date: 'Oct 23', score: 490, threats: 88, mttr: 140 },
  { date: 'Dec 23', score: 540, threats: 76, mttr: 115 },
  { date: 'Feb 24', score: 605, threats: 65, mttr: 90 },
  { date: 'Apr 24', score: 670, threats: 52, mttr: 65 },
  { date: 'Jun 24', score: 735, threats: 44, mttr: 42 },
  { date: 'Aug 24', score: 800, threats: 38, mttr: 26 },
  { date: 'Sep 24', score: 842, threats: 35, mttr: 18.4 },
];

type Timeframe = '7D' | '30D' | '90D' | '1Y';

export default function SecurityVelocityChart() {
  const [timeframe, setTimeframe] = useState<Timeframe>('7D');
  const [showScore, setShowScore] = useState(true);
  const [showThreats, setShowThreats] = useState(true);

  const dataMap: Record<Timeframe, DataPoint[]> = {
    '7D': DATA_7D,
    '30D': DATA_30D,
    '90D': DATA_90D,
    '1Y': DATA_1Y,
  };

  const currentData = dataMap[timeframe];
  const latestPoint = currentData[currentData.length - 1];
  const firstPoint = currentData[0];
  const scoreDelta = latestPoint.score - firstPoint.score;
  const threatDelta = latestPoint.threats - firstPoint.threats;

  return (
    <div className="rounded-lg border border-line bg-raised overflow-hidden shadow-sm">
      {/* Top Header Strip */}
      <div className="p-4 sm:p-5 border-b border-line flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-raised">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span className="eyebrow text-[10.5px]">SECURITY HEALTH</span>
          </div>
          <h2 className="text-base sm:text-lg font-bold tracking-tight text-ink flex items-center gap-2">
            <span>Security score over time</span>
            <span className="text-soft font-normal text-xs sm:text-sm">vs. blocked threats</span>
          </h2>
          <p className="text-xs text-soft mt-0.5 max-w-xl">
            How your security score, blocked threats, and fix times have changed.
          </p>
        </div>

        {/* Action Controls: Timeframe + Series Visibility */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Series Toggles */}
          <div className="hidden sm:flex items-center gap-1.5 mr-2 pr-3 border-r border-line">
            <button
              onClick={() => setShowScore(!showScore)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] mono border transition-all ${
                showScore
                  ? 'bg-accent/15 border-accent/40 text-accent font-medium'
                  : 'bg-inset border-line text-soft opacity-60'
              }`}
              title="Toggle score line"
            >
              {showScore ? <Eye size={11} /> : <EyeOff size={11} />}
              <span>Score</span>
            </button>
            <button
              onClick={() => setShowThreats(!showThreats)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] mono border transition-all ${
                showThreats
                  ? 'bg-emerald-500/15 border-emerald-500/40 text-ok font-medium'
                  : 'bg-inset border-line text-soft opacity-60'
              }`}
              title="Toggle threats line"
            >
              {showThreats ? <Eye size={11} /> : <EyeOff size={11} />}
              <span>Threats</span>
            </button>
          </div>

          {/* Timeframe Selector */}
          <div className="flex items-center gap-1 bg-inset p-1 rounded-md border border-line">
            {(['7D', '30D', '90D', '1Y'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded text-[11px] mono font-semibold transition-all btn-tactile ${
                  timeframe === tf
                    ? 'bg-accent text-white shadow-xs'
                    : 'text-soft hover:text-ink hover:bg-raised/60'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* KPI Metric Strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 border-b border-line bg-inset/40 text-xs mono divide-x divide-y lg:divide-y-0 divide-line">
        <div className="p-3.5 sm:p-4 space-y-1">
          <div className="flex items-center justify-between text-soft text-[10.5px]">
            <span>SECURITY SCORE</span>
            <TrendingUp size={13} className="text-accent" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-xl sm:text-2xl font-bold tracking-tight text-ink font-mono">
              {latestPoint.score}
            </span>
            <span className="text-[11px] font-bold text-ok flex items-center">
              +{scoreDelta > 0 ? scoreDelta : 14} pts
            </span>
          </div>
          <div className="text-[10px] text-soft">
            Top 4% of African fintech companies we monitor
          </div>
        </div>

        <div className="p-3.5 sm:p-4 space-y-1">
          <div className="flex items-center justify-between text-soft text-[10.5px]">
            <span>THREATS BLOCKED</span>
            <ShieldAlert size={13} className="text-ok" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-xl sm:text-2xl font-bold tracking-tight text-ink font-mono">
              {latestPoint.threats}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-ok/15 text-ok font-semibold border border-ok/30">
              100% BLOCKED
            </span>
          </div>
          <div className="text-[10px] text-soft">
            Every one blocked before it could reach you
          </div>
        </div>

        <div className="p-3.5 sm:p-4 space-y-1">
          <div className="flex items-center justify-between text-soft text-[10.5px]">
            <span>FIX SPEED</span>
            <Clock size={13} className="text-amber-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-xl sm:text-2xl font-bold tracking-tight text-ink font-mono">
              {latestPoint.mttr}m
            </span>
            <span className="text-[11px] text-ok font-bold">-64% faster</span>
          </div>
          <div className="text-[10px] text-soft">
            CyphBot guidance helps you fix faster
          </div>
        </div>

        <div className="p-3.5 sm:p-4 space-y-1">
          <div className="flex items-center justify-between text-soft text-[10.5px]">
            <span>EXPOSURE RISK</span>
            <Zap size={13} className="text-accent" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-xl sm:text-2xl font-bold tracking-tight text-ink font-mono">
              2.4%
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent font-semibold border border-accent/30">
              LOW
            </span>
          </div>
          <div className="text-[10px] text-soft">
            18 subdomains monitored, no unexpected open ports
          </div>
        </div>
      </div>

      {/* Recharts Area / Line Canvas */}
      <div className="p-3 sm:p-5 pt-6 bg-raised">
        <div className="w-full h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={currentData} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="scoreVelocityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="var(--accent)" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="threatSignalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--ok)" stopOpacity={0.28} />
                  <stop offset="95%" stopColor="var(--ok)" stopOpacity={0.0} />
                </linearGradient>
              </defs>

              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--line)"
                opacity={0.7}
                vertical={false}
              />

              <XAxis
                dataKey="date"
                stroke="var(--soft)"
                tick={{ fill: 'var(--soft)', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--line)' }}
              />

              {/* Left Y Axis: Posture Score */}
              <YAxis
                yAxisId="left"
                domain={[50, 95]}
                stroke="var(--soft)"
                tick={{ fill: 'var(--soft)', fontSize: 10, fontFamily: 'IBM Plex Mono' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(val) => `${val}`}
              />

              {/* Right Y Axis: Threat Signals */}
              <YAxis
                yAxisId="right"
                orientation="right"
                domain={[0, 80]}
                stroke="var(--soft)"
                tick={{ fill: 'var(--soft)', fontSize: 9.5, fontFamily: 'IBM Plex Mono' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(val) => `${val}`}
              />

              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload || !payload.length) return null;
                  const scoreVal = payload.find((p) => p.dataKey === 'score')?.value;
                  const threatsVal = payload.find((p) => p.dataKey === 'threats')?.value;
                  const dataPoint = currentData.find((d) => d.date === label);

                  return (
                    <div className="p-3 rounded-lg border border-line bg-raised shadow-xl text-xs mono space-y-2 min-w-[200px]">
                      <div className="flex items-center justify-between border-b border-line pb-1.5">
                        <span className="font-bold text-ink">{label}</span>
                        <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-ok/15 text-ok border border-ok/30 font-semibold">
                          UP TO DATE
                        </span>
                      </div>

                      <div className="space-y-1.5 pt-0.5">
                        {scoreVal !== undefined && (
                          <div className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-soft">
                              <span className="w-2 h-2 rounded-full bg-accent" />
                              <span>Score:</span>
                            </span>
                            <span className="font-bold text-accent">{scoreVal} / 100</span>
                          </div>
                        )}

                        {threatsVal !== undefined && (
                          <div className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-soft">
                              <span className="w-2 h-2 rounded-full bg-ok" />
                              <span>Blocked threats:</span>
                            </span>
                            <span className="font-bold text-ok">{threatsVal}</span>
                          </div>
                        )}

                        {dataPoint?.mttr && (
                          <div className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5 text-soft">
                              <span className="w-2 h-2 rounded-full bg-amber-500" />
                              <span>Avg fix time:</span>
                            </span>
                            <span className="font-semibold text-ink">{dataPoint.mttr} mins</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                }}
              />

              {/* Primary Posture Score Curve */}
              {showScore && (
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="score"
                  name="Security score"
                  stroke="var(--accent)"
                  strokeWidth={2.5}
                  fill="url(#scoreVelocityGrad)"
                  dot={false}
                  activeDot={{
                    r: 5,
                    fill: 'var(--accent)',
                    stroke: 'var(--raised)',
                    strokeWidth: 2.5,
                  }}
                  isAnimationActive
                  animationDuration={900}
                />
              )}

              {/* Secondary Threat Signals Curve */}
              {showThreats && (
                <Area
                  yAxisId="right"
                  type="monotone"
                  dataKey="threats"
                  name="Blocked threats"
                  stroke="var(--ok)"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  fill="url(#threatSignalGrad)"
                  dot={false}
                  activeDot={{
                    r: 4,
                    fill: 'var(--ok)',
                    stroke: 'var(--raised)',
                    strokeWidth: 2,
                  }}
                  isAnimationActive
                  animationDuration={1100}
                />
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Legend Footer */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 mt-1 border-t border-line text-[11px] mono text-soft">
          <div className="flex flex-wrap items-center gap-2 sm:gap-4">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-accent inline-block rounded-full" />
              <span className="text-ink font-medium">Security score</span>
              <span className="text-[10px] text-soft hidden xs:inline">(left axis: 50-95)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-ok inline-block rounded-full border-t border-dashed" />
              <span className="text-ink font-medium">Blocked threats</span>
              <span className="text-[10px] text-soft hidden xs:inline">(right axis: 0-80)</span>
            </div>
          </div>

          <div className="flex items-center gap-1.5 text-ok text-[10.5px]">
            <CheckCircle2 size={12} />
            <span>Live score updates from your latest scans</span>
          </div>
        </div>
      </div>
    </div>
  );
}
