import { useEffect, useRef } from 'react';

export interface StrataFieldProps {
  variant?: 'hero' | 'ambient' | 'mini' | 'auth';
  opacity?: number;
  interactive?: boolean;
  showCrosshair?: boolean;
  className?: string;
}

/** The STRATA dot-field instrument: drifting strata dots, pointer repulsion,
 *  and the live DEPTH crosshair. Window-level tracking so overlapping
 *  content never blocks it. Supports 'mini' mode for subtle app-wide background. */
export default function StrataField({
  variant = 'hero',
  opacity = 1,
  interactive = true,
  showCrosshair,
  className = '',
}: StrataFieldProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const isMini = variant === 'mini';
  const isAmbient = variant === 'ambient';
  const shouldShowCrosshair = showCrosshair !== undefined ? showCrosshair : (variant === 'hero' || variant === 'auth');

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let inkC: number[] = [26, 24, 18];
    let accC: number[] = [193, 59, 22];
    const col = (c: number[], a: number) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a * opacity))})`;

    const hex2rgb = (h: string) => {
      h = h.trim().replace('#', '');
      if (h.length === 3) h = h.split('').map(c => c + c).join('');
      const n = parseInt(h, 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };

    const readCols = () => {
      const cs = getComputedStyle(document.documentElement);
      const inkVal = cs.getPropertyValue('--ink');
      const accVal = cs.getPropertyValue('--accent');
      if (inkVal) inkC = hex2rgb(inkVal);
      if (accVal) accC = hex2rgb(accVal);
    };
    readCols();

    const onTheme = () => readCols();
    window.addEventListener('cyphward:theme', onTheme);

    let W = 0, H = 0;
    let dots: { x: number; y: number; row: number; alpha: number; acc: boolean; r: number; ph: number }[] = [];

    const hash = (a: number, b: number) => {
      const s = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
      return s - Math.floor(s);
    };

    const build = () => {
      const rect = host.getBoundingClientRect();
      W = rect.width || window.innerWidth;
      H = rect.height || window.innerHeight;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dots = [];

      // Spacing: balanced grid for clear visibility of mini dots
      const gx = isMini ? 28 : (isAmbient ? 34 : 27);
      const gy = isMini ? 26 : (isAmbient ? 30 : 25);
      const cols = Math.ceil(W / gx) + 1;
      const rows = Math.ceil(H / gy) + 1;

      // Alpha: distinctly visible so dots pop gracefully against background
      const bandA = isMini
        ? [0.32, 0.50, 0.68, 0.38]
        : (isAmbient ? [0.18, 0.32, 0.48, 0.24] : [0.22, 0.38, 0.54, 0.30]);

      for (let j = 0; j < rows; j++) {
        for (let i = 0; i < cols; i++) {
          const h = hash(i, j);
          if (h < (isMini ? 0.12 : 0.16)) continue;

          // In mini mode, dot radius is crisp and clearly visible ("small dots")
          const isAcc = h > 0.945;
          let r = 1.4;
          if (isMini) {
            r = isAcc ? 1.85 : 1.25;
          } else if (isAmbient) {
            r = isAcc ? 1.6 : 1.1;
          } else {
            r = isAcc ? 2.2 : 1.5;
          }

          dots.push({
            x: i * gx + (hash(j, i) * 6 - 3),
            y: j * gy + (hash(i + 7, j + 3) * 6 - 3),
            row: j,
            alpha: bandA[Math.floor(j / 3) % 4] * (0.8 + h * 0.4),
            acc: isAcc,
            r,
            ph: h * 6.283,
          });
        }
      }
    };

    build();

    let rsT: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(rsT);
      rsT = setTimeout(build, 150);
    };
    window.addEventListener('resize', onResize);

    const M = { x: -9999, y: -9999, ty: null as number | null, lineY: null as number | null, alpha: 0 };
    const onMove = (e: PointerEvent) => {
      if (!interactive) return;
      const rect = host.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
        M.ty = null;
        M.x = -9999;
        M.y = -9999;
      } else {
        M.x = x;
        M.y = y;
        M.ty = y;
      }
    };

    window.addEventListener('pointermove', onMove);

    let raf = 0;
    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      ctx.clearRect(0, 0, W, H);

      if (shouldShowCrosshair) {
        M.alpha += ((M.ty != null ? 1 : 0) - M.alpha) * 0.12;
        if (M.ty != null) M.lineY = M.lineY == null ? M.ty : M.lineY + (M.ty - M.lineY) * 0.18;
        if (M.alpha > 0.01 && M.lineY != null) {
          ctx.lineWidth = 1;
          ctx.strokeStyle = col(accC, 0.55 * M.alpha);
          ctx.beginPath();
          ctx.moveTo(0, M.lineY + 0.5);
          ctx.lineTo(W, M.lineY + 0.5);
          ctx.stroke();

          ctx.strokeStyle = col(accC, 0.15 * M.alpha);
          ctx.beginPath();
          ctx.moveTo(M.x + 0.5, 0);
          ctx.lineTo(M.x + 0.5, H);
          ctx.stroke();

          ctx.font = '10px "IBM Plex Mono", monospace';
          ctx.fillStyle = col(accC, 0.95 * M.alpha);
          ctx.fillText('DEPTH ' + Math.round((M.lineY / H) * 84 + 6) + 'm', 14, M.lineY - 7);
        }
      }

      const rm = reduced ? 0 : 1;
      const driftSpeedX = isMini ? 0.0002 : 0.0003;
      const driftSpeedY = isMini ? 0.0003 : 0.0005;

      for (const d of dots) {
        let x = d.x + Math.sin(t * driftSpeedX + d.ph) * (isMini ? 0.8 : 1.2) * rm;
        let y = d.y + Math.sin(t * driftSpeedY + d.row * 0.55 + d.ph) * (isMini ? 1.4 : 2.4) * rm;

        if (interactive && (M.ty != null || M.x > -100)) {
          const ddx = x - M.x;
          const ddy = y - M.y;
          const d2 = ddx * ddx + ddy * ddy;
          const radiusLimit = isMini ? 75 : 95;
          if (d2 < radiusLimit * radiusLimit * 2) {
            const f = Math.exp(-d2 / (2 * radiusLimit * radiusLimit)) * (isMini ? 18 : 30);
            const dist = Math.sqrt(d2) + 0.001;
            x += (ddx / dist) * f;
            y += (ddy / dist) * f;
          }
        }

        ctx.fillStyle = d.acc ? col(accC, Math.min(1, d.alpha + 0.25)) : col(inkC, d.alpha);
        ctx.beginPath();
        ctx.arc(x, y, d.r, 0, 6.283);
        ctx.fill();
      }
    };

    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('cyphward:theme', onTheme);
    };
  }, [variant, opacity, interactive, shouldShowCrosshair, isMini, isAmbient]);

  return (
    <div
      ref={hostRef}
      className={`strata-field ${className} ${isMini ? 'strata-mini' : ''}`}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} />
    </div>
  );
}
