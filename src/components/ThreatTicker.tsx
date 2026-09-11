import type { TickerItem } from '../data/mock';

export default function ThreatTicker({ items }: { items: TickerItem[] }) {
  if (!items.length) return null;
  const s = items.map(i => `${i.time} — ${i.label}`).join(' <i>/</i> ') + ' <i>/</i> ';
  return (
    <div className="ticker" aria-hidden="true">
      <span className="ticker-cap"><span className="live-dot" />THREAT FEED</span>
      <div className="ticker-track">
        <span dangerouslySetInnerHTML={{ __html: s }} />
        <span dangerouslySetInnerHTML={{ __html: s }} />
      </div>
    </div>
  );
}
