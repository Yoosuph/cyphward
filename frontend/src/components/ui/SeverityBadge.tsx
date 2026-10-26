/**
 * The one severity badge (findings list, issue details) and legend dot (overview). Colours live in index.css
 * (.sev-badge / .sev-dot / .sev-bar) so every severity reads at WCAG AA in both themes.
 */
const KNOWN = new Set(['critical', 'high', 'medium', 'low', 'info']);

const tone = (severity: string) => {
  const s = (severity || '').toLowerCase();
  return KNOWN.has(s) ? s : 'info';
};

export function SeverityBadge({ severity, className = '' }: { severity: string; className?: string }) {
  return <span className={`sev-badge sev-${tone(severity)} ${className}`.trim()}>{severity}</span>;
}

export function SeverityDot({ severity }: { severity: string }) {
  return <span className={`sev-dot sev-${tone(severity)}`} aria-hidden="true" />;
}
