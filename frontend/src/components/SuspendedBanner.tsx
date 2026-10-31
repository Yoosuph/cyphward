import { Link } from 'react-router-dom';
import { CirclePause } from 'lucide-react';
import { SUSPENDED_BODY, SUSPENDED_TITLE } from '../lib/suspension';
import { useOrgSuspended } from '../lib/useOrgSuspended';

/** Shown at the top of every customer page while the organisation is suspended (lib/suspension.ts). */
export default function SuspendedBanner() {
  const suspended = useOrgSuspended();
  if (!suspended) return null;
  return (
    <div
      id="org-suspended-banner"
      role="status"
      data-testid="org-suspended-banner"
      className="mb-5 flex gap-3 rounded-lg border border-accent/40 bg-raised p-4 text-sm"
    >
      <CirclePause size={18} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-medium text-ink">{SUSPENDED_TITLE}</p>
        <p className="text-xs leading-relaxed text-soft">{SUSPENDED_BODY}</p>
        <p className="text-xs leading-relaxed text-soft">
          To ask about it, email{' '}
          <a className="text-accent underline" href="mailto:info@cyphward.com">info@cyphward.com</a> or use the{' '}
          <Link className="text-accent underline" to="/contact">contact page</Link>.
        </p>
      </div>
    </div>
  );
}
