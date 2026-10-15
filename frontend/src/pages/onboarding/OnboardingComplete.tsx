import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Radar } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { launchScan } from '../../lib/api';

export default function OnboardingComplete() {
  const { organization, primaryDomain } = useAuth();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const canScan = primaryDomain?.verification_status === 'verified';
  const canManage = ['owner', 'admin'].includes(organization?.membership_role || 'member');

  const handleScan = async () => {
    if (!canManage || !canScan || !primaryDomain || busy) return;
    setBusy(true);
    setError('');
    try {
      await launchScan(primaryDomain.id);
      nav('/scans', { replace: true });
    } catch (e: any) {
      if (e?.code === 'scan_already_active') {
        nav('/scans', { replace: true, state: { scanId: e.scanId } });
        return;
      }
      setError(e instanceof Error ? e.message : 'Could not start the scan. Please try again.');
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5 text-center">
      <div className="inline-block p-4 rounded-full bg-ok/10 text-ok border border-ok/30">
        <CheckCircle2 size={36} />
      </div>

      <div>
        <h3 className="font-display text-xl font-medium text-ink mb-1">
          {canScan ? 'Ready for your first scan' : 'Your workspace is ready'}
        </h3>
        <p className="text-xs text-soft">
          {canScan ? `${primaryDomain?.domain} is verified.` : 'Verify a domain when you are ready to scan.'}
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

      {canScan && (
        <div className="text-left">
          <p className="text-[10px] mono text-soft mb-2">WHAT THE FIRST SCAN DOES</p>
          <ul className="space-y-1.5 text-xs text-soft">
            <li>· Finds public subdomains of {primaryDomain?.domain}</li>
            <li>· Checks SPF and DMARC email protection</li>
            <li>· Checks HTTP headers, the TLS certificate and open ports on each public host</li>
            <li>· Scores the result and writes a fix for every finding</li>
          </ul>
          <p className="text-xs text-soft mt-3">It usually takes 30–45 minutes. You can leave this page: results appear on Scans and Overview, and you'll get a notification.</p>
        </div>
      )}

      {error && <p role="alert" className="text-xs text-red-500">{error}</p>}
      {canManage && <button
        onClick={canScan ? handleScan : () => nav(primaryDomain ? '/onboarding/verify-domain' : '/onboarding/add-domain')}
        disabled={busy}
        className="btn btn-solid w-full justify-center"
      >
        <Radar size={14} className="mr-2" />
        {busy ? 'STARTING SCAN…' : canScan ? 'START FIRST SCAN' : primaryDomain ? 'VERIFY DOMAIN' : 'ADD DOMAIN'}
      </button>}
      {canManage && canScan && <p className="text-xs text-soft">Starting a scan uses one scan from your workspace's monthly allowance. Results will appear on the Scans page.</p>}

      <button
        onClick={() => nav('/', { replace: true })}
        className="text-xs mono text-soft hover:text-ink transition-colors"
      >
        Go to Dashboard instead →
      </button>
    </div>
  );
}
