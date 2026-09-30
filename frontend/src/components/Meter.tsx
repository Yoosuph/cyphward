import { useEffect, useState } from 'react';

interface Props {
  pct: number;
  variant?: '' | 'ok' | 'warn' | 'bad';
  tall?: boolean;
  className?: string;
}

export default function Meter({ pct, variant = '', tall = false, className = '' }: Props) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const r = requestAnimationFrame(() => setOn(true));
    return () => cancelAnimationFrame(r);
  }, []);
  const width = Math.min(100, Math.max(0, pct));
  return (
    <span className={`meter ${tall ? 'tall' : ''} ${className}`}>
      <i className={variant} style={{ width: on ? `${width}%` : '0%' }} />
    </span>
  );
}
