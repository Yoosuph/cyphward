import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { ShieldCheck, Building, Globe, CheckCircle2, Radar, MailCheck } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import StrataField from '../../components/StrataField';
import CyphwardLogo from '../../components/CyphwardLogo';

const STEPS = [
  { key: 'verify_email', label: 'Email', icon: MailCheck },
  { key: 'create_org', label: 'Workspace', icon: Building },
  { key: 'add_domain', label: 'Domain', icon: Globe },
  { key: 'verify_domain', label: 'Verify', icon: CheckCircle2 },
  { key: 'complete', label: 'First scan', icon: Radar },
];

export default function OnboardingLayout() {
  const { tenant, user, organization, primaryDomain, onboardingStep, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="auth-wrap">
        <StrataField variant="auth" />
        <div className="login-z w-full max-w-xl mx-auto my-auto px-4 text-center">
          <div className="animate-pulse">
            <ShieldCheck size={48} className="text-accent mx-auto mb-4" />
            <p className="mono text-sm text-soft">Loading your workspace…</p>
          </div>
        </div>
      </div>
    );
  }

  if (!tenant && !user) {
    return <Navigate to={{ pathname: "/login", search: location.search }} replace />;
  }

  if (onboardingStep === 'complete') {
    const path = location.pathname;
    if (!organization || (path.endsWith('/verify-domain') && !primaryDomain)) {
      return <Navigate to="/onboarding/add-domain" replace />;
    }
    if (path.endsWith('/verify-domain') && primaryDomain?.verification_status === 'verified') {
      return <Navigate to="/domains" replace />;
    }
    if (!['/onboarding/add-domain', '/onboarding/verify-domain', '/onboarding/complete'].includes(path)) {
      return <Navigate to={{ pathname: "/overview", search: location.search }} replace />;
    }
  }

  if (onboardingStep === 'verify_email' && !location.pathname.endsWith('/verify-email')) {
    return <Navigate to={{ pathname: "/onboarding/verify-email", search: location.search }} replace />;
  }

  // The index route points at create-org; if state says a later step (fresh
  // load at /onboarding, or a stale URL), bounce to the matching route so the
  // form and the progress stepper never disagree.
  const stepPath = STEPS.find(s => s.key === onboardingStep)?.key;
  const stepRoute = stepPath && stepPath !== 'complete' ? `/onboarding/${stepPath.replace(/_/g, '-')}` : null;
  if (stepRoute && !location.pathname.startsWith(stepRoute)) {
    return <Navigate to={{ pathname: stepRoute, search: location.search }} replace />;
  }

  const visibleStep = onboardingStep === 'complete' && location.pathname.endsWith('/add-domain')
    ? 'add_domain'
    : onboardingStep === 'complete' && location.pathname.endsWith('/verify-domain')
    ? 'verify_domain'
    : onboardingStep;
  const currentStepIdx = STEPS.findIndex(s => s.key === visibleStep);

  return (
    <div className="auth-wrap">
      <StrataField variant="auth" />

      <div className="login-z w-full max-w-2xl mx-auto my-auto px-4">
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-line">
          <CyphwardLogo variant="compact" size={19} />
          <p className="eyebrow flex items-center gap-2">
            <span className="live-dot" /> SETUP
          </p>
        </div>

        <h1 className="display-h text-center">
          Set up your <em>workspace.</em>
        </h1>
        <p className="login-sub text-center">
          About five minutes. You'll need access to your domain's DNS settings, or someone who has it.
        </p>

        {/* Progress Steps */}
        <div className="sm:hidden mt-6 mb-4" aria-label={`Setup step ${Math.max(1, currentStepIdx + 1)} of ${STEPS.length}`}>
          <p className="text-xs mono text-soft text-center">Step {Math.max(1, currentStepIdx + 1)} of {STEPS.length} · {STEPS[Math.max(0, currentStepIdx)].label}</p>
          <div className="h-1.5 rounded-full bg-inset mt-2 overflow-hidden"><div className="h-full bg-accent" style={{ width: `${Math.max(1, currentStepIdx + 1) / STEPS.length * 100}%` }} /></div>
        </div>
        <div className="hidden sm:flex items-center justify-center gap-2 mt-6 mb-8">
          {STEPS.map((step, idx) => {
            const Icon = step.icon;
            const isActive = step.key === visibleStep;
            const isCompleted = idx < currentStepIdx;
            return (
              <div key={step.key} className="flex items-center">
                <div
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs mono transition-all ${
                    isActive
                      ? 'bg-accent text-white font-bold'
                      : isCompleted
                      ? 'bg-ok/15 text-ok border border-ok/30'
                      : 'bg-inset text-soft border border-line'
                  }`}
                >
                  <Icon size={12} />
                  <span className="hidden sm:inline">{step.label}</span>
                </div>
                {idx < STEPS.length - 1 && (
                  <div className={`w-6 h-px mx-1 ${isCompleted ? 'bg-ok' : 'bg-line'}`} />
                )}
              </div>
            );
          })}
        </div>

        {/* Step Content */}
        <div className="auth-card panel">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
