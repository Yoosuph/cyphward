import { useEffect, useState } from 'react';
import { ScoreRingSkeleton } from './Skeleton';

export { ScoreRingSkeleton };

interface Props {
  score: number;
  max: number;
  size?: number;
  trend?: number;
  loading?: boolean;
}

/** Custom animated gauge — rAF count-up, ink arc, oxide diamond at the leading edge. */
export default function ScoreRing({ score, max, size = 190, trend, loading = false }: Props) {
  const [v, setV] = useState(0);

  useEffect(() => {
    if (loading) return;
    const prefersReducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) {
      setV(score);
      return;
    }

    let raf = 0;
    const t0 = performance.now();
    const dur = 1100;
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      setV(score * e);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [score, loading]);


  if (loading) {
    return <ScoreRingSkeleton size={size} />;
  }

  const stroke = size >= 220 ? 9 : 7;
  const r = (size - stroke * 2 - 10) / 2;
  const cx = size / 2, cy = size / 2;
  const C = 2 * Math.PI * r;
  const frac = Math.min(1, v / max);
  const angle = -90 + 360 * frac;
  const rad = (angle * Math.PI) / 180;
  const dx = cx + r * Math.cos(rad);
  const dy = cy + r * Math.sin(rad);

  return (
    <div className="score-ring content-fade-in" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--line)" strokeWidth={stroke} />
        <circle
          cx={cx} cy={cy} r={r} fill="none" stroke="var(--ink)" strokeWidth={stroke}
          strokeDasharray={C} strokeDashoffset={C * (1 - frac)}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
        <rect
          x={-4.2} y={-4.2} width={8.4} height={8.4} fill="var(--accent)"
          transform={`translate(${dx} ${dy}) rotate(45)`}
        />
      </svg>
      <div className="ring-center">
        <span className="ring-num" style={{ fontSize: Math.round(size * 0.2) }}>{v.toFixed(1)}</span>
        <span className="ring-max mono">/ {max}</span>
        {trend != null && (
          <span className={`ring-trend mono ${trend >= 0 ? 'up' : 'down'}`}>
            {trend >= 0 ? '+' : ''}{trend} THIS MONTH
          </span>
        )}
      </div>
    </div>
  );
}
