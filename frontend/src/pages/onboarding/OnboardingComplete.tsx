import { useNavigate } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Radar } from 'lucide-react';
import { useAuth } from '../../lib/auth';

export default function OnboardingComplete() {
  const { organization, primaryDomain } = useAuth();
  const nav = useNavigate();

  return (
    <div className="space-y-5 text-center">
      <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30">
        <CheckCircle2 size={36} />
      </div>

      <div>
        <h3 className="font-display text-xl font-medium text-ink mb-1">
          You're All Set!
        </h3>
        <p className="text-xs text-soft">
          Your workspace is set up and ready to start monitoring.
        </p>
      </div>

      <div className="p-4 bg-inset rounded border border-line text-left space-y-3">
        {organization && (
          <div>
            <p className="text-[10px] mono text-soft">ORGANIZATION</p>
            <p className="text-xs font-semibold text-ink">{organization.name}</p>
          </div>
        )}
        {primaryDomain && (
          <div>
            <p className="text-[10px] mono text-soft">PRIMARY DOMAIN</p>
            <p className="text-xs font-semibold text-ink">{primaryDomain.domain}</p>
          </div>
        )}
      </div>

      <button
        onClick={() => nav('/scans', { replace: true })}
        className="btn btn-solid w-full justify-center"
      >
        <Radar size={14} className="mr-2" />
        START FIRST SCAN
      </button>

      <button
        onClick={() => nav('/', { replace: true })}
        className="text-xs mono text-soft hover:text-ink transition-colors"
      >
        Go to Dashboard instead →
      </button>
    </div>
  );
}
