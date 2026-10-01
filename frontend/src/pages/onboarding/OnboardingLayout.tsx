import { Navigate, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { ShieldCheck, Building, Globe, CheckCircle2, Radar, MailCheck } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import StrataField from '../../components/StrataField';
import CyphwardLogo from '../../components/CyphwardLogo';

const STEPS = [
  { key: 'verify_email', label: 'Verify Email', icon: MailCheck },
  { key: 'create_org', label: 'Create Organization', icon: Building },
  { key: 'add_domain', label: 'Add Domain', icon: Globe },
  { key: 'verify_domain', label: 'Verify Domain', icon: CheckCircle2 },
  { key: 'complete', label: 'Ready', icon: Radar },
];

export default function OnboardingLayout() {
  const { tenant, user, onboardingStep, loading } = useAuth();
  const nav = useNavigate();
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
    return <Navigate to="/login" replace />;
  }

  if (onboardingStep === 'complete' && !location.pathname.endsWith('/complete')) {
    return <Navigate to="/" replace />;
  }

  if (onboardingStep === 'verify_email' && !location.pathname.endsWith('/verify-email')) {
    return <Navigate to="/onboarding/verify-email" replace />;
  }

  // The index route points at create-org; if state says a later step (fresh
  // load at /onboarding, or a stale URL), bounce to the matching route so the
  // form and the progress stepper never disagree.
  const stepPath = STEPS.find(s => s.key === onboardingStep)?.key;
  const stepRoute = stepPath && stepPath !== 'complete' ? `/onboarding/${stepPath.replace(/_/g, '-')}` : null;
  if (stepRoute && !location.pathname.startsWith(stepRoute)) {
    return <Navigate to={stepRoute} replace />;
  }

  const currentStepIdx = STEPS.findIndex(s => s.key === onboardingStep);

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
          Verify your email, name your workspace, and add a domain to start monitoring.
        </p>

        {/* Progress Steps */}
        <div className="flex items-center justify-center gap-2 mt-6 mb-8">
          {STEPS.map((step, idx) => {
            const Icon = step.icon;
            const isActive = step.key === onboardingStep;
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
