import { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import Meter from './Meter';
import { StatCardSkeleton } from './Skeleton';

export { StatCardSkeleton };

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  meter?: { pct: number; variant?: '' | 'ok' | 'warn' | 'bad' };
  note?: ReactNode;
  to?: string;
  loading?: boolean;
}

export default function StatCard({ label, value, unit, meter, note, to, loading = false }: Props) {
  if (loading) {
    return <StatCardSkeleton />;
  }

  return (
    <div className={`stat-card ${to ? 'card-hover cursor-pointer' : ''}`}>
      <p className="eyebrow">{label}</p>
      <p className="stat-val">
        {value}
        {unit && <span className="stat-unit mono">{unit}</span>}
      </p>
      {meter && <Meter pct={meter.pct} variant={meter.variant} tall className="mt-3" />}
      {note && <p className="stat-note">{note}</p>}
      {to && (
        <Link to={to} className="stat-link">
          VIEW <ArrowUpRight size={12} />
        </Link>
      )}
    </div>
  );
}
