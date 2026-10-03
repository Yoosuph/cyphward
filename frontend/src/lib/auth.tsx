import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import {
  verifyDomain as verifyDomainApi,
  createOrganization as createOrganizationApi,
  addDomain,
  sendWelcomeEmail,
  getBootstrap,
  loginRequest,
  registerRequest,
  logoutRequest,
  type BootstrapData,
} from './api';
import {
  loadSession,
  saveSession,
  clearSession,
  refreshSession,
  type AuthTokens,
  type SessionUser,
} from './session';

type OnboardingStepValue = 'none' | 'verify_email' | 'create_org' | 'add_domain' | 'verify_domain' | 'complete';
import type { Tenant } from '../types';

const KEY = 'cyphward-tenant';
const SIGNOUT_KEY = 'cyphward-signed-out';
const ONBOARDING_KEY = 'cyphward-onboarding';
const ORG_ID_KEY = 'cyphward-org-id';
const WELCOME_SENT_KEY = 'cyphward-welcome-sent';

// Fire-and-forget: queue one welcome email per account. The server is the
// authority — it only welcomes brand-new accounts, once, ever — so a
// "sent: false" answer keeps the local guard (don't retry on every login).
// Only a network failure clears it so the next login can try again.
function maybeSendWelcome(userId?: string) {
  if (!userId) return;
  try {
    if (localStorage.getItem(WELCOME_SENT_KEY) === userId) return;
    localStorage.setItem(WELCOME_SENT_KEY, userId);
    sendWelcomeEmail().catch(() => localStorage.removeItem(WELCOME_SENT_KEY));
  } catch {
    /* never block auth flow on welcome mail */
  }
}

interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
}

interface Domain {
  id: string;
  domain: string;
  org_id: string;
  organization_id?: string;
  verification_status: 'pending' | 'verified' | 'failed' | 'expired' | 'revoked';
  verification_token?: string;
  verified_at?: string;
  created_at: string;
}

interface Auth {
  tenant: Tenant | null;
  user: SessionUser | null;
  loading: boolean;
  organization: Organization | null;
  primaryDomain: Domain | null;
  onboardingStep: OnboardingStepValue;
  signInWithCredentials: (
    email: string,
    password: string
  ) => Promise<{ ok: boolean; error?: string; name?: string; onboarding?: OnboardingStepValue }>;
  signUpWithCredentials: (
    email: string,
    password: string,
    name: string
  ) => Promise<{ ok: boolean; error?: string; needsOnboarding?: boolean; onboarding?: OnboardingStepValue }>;
  completeExternalLogin: (tokens: AuthTokens) => Promise<OnboardingStepValue>;
  signOut: () => Promise<void>;
  createOrganization: (name: string, plan: string) => Promise<{ ok: boolean; error?: string }>;
  addPrimaryDomain: (domain: string) => Promise<{ ok: boolean; error?: string }>;
  verifyDomain: () => Promise<{ ok: boolean; verified: boolean; error?: string }>;
  completeOnboarding: () => void;
  refreshOnboarding: () => Promise<OnboardingStepValue>;
}

const Ctx = createContext<Auth>({
  tenant: null,
  user: null,
  loading: true,
  organization: null,
  primaryDomain: null,
  onboardingStep: 'none',
  signInWithCredentials: async () => ({ ok: false, error: 'Sign in failed. Please try again.' }),
  signUpWithCredentials: async () => ({ ok: false, error: 'Sign up failed. Please try again.' }),
  completeExternalLogin: async () => 'none',
  signOut: async () => {},
  createOrganization: async () => ({ ok: false }),
  addPrimaryDomain: async () => ({ ok: false }),
  verifyDomain: async () => ({ ok: false, verified: false }),
  completeOnboarding: () => {},
  refreshOnboarding: async () => 'none',
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [primaryDomain, setPrimaryDomain] = useState<Domain | null>(null);
  const [onboardingStep, setOnboardingStep] = useState<OnboardingStepValue>('none');

  const [tenant, setTenant] = useState<Tenant | null>(() => {
    try {
      if (typeof window !== 'undefined' && localStorage.getItem(SIGNOUT_KEY) === 'true') {
        return null;
      }
      // Only a previously persisted real-session tenant may bootstrap the UI.
      const raw = localStorage.getItem(KEY) || sessionStorage.getItem(KEY);
      return raw ? (JSON.parse(raw) as Tenant) : null;
    } catch {
      return null;
    }
  });

  const persistTenant = (t: Tenant | null, orgId?: string) => {
    try {
      if (t) {
        localStorage.setItem(KEY, JSON.stringify(t));
        sessionStorage.setItem(KEY, JSON.stringify(t));
        const effectiveOrgId = orgId || t.id || t.slug;
        if (effectiveOrgId) {
          localStorage.setItem(ORG_ID_KEY, effectiveOrgId);
          sessionStorage.setItem(ORG_ID_KEY, effectiveOrgId);
        }
        localStorage.removeItem(SIGNOUT_KEY);
      } else {
        localStorage.removeItem(KEY);
        sessionStorage.removeItem(KEY);
        localStorage.removeItem(ORG_ID_KEY);
        sessionStorage.removeItem(ORG_ID_KEY);
      }
    } catch {}
  };

  const clearAuthState = () => {
    setUser(null);
    setTenant(null);
    setOrganization(null);
    setPrimaryDomain(null);
    setOnboardingStep('none');
    persistTenant(null);
    localStorage.removeItem(SIGNOUT_KEY);
    localStorage.removeItem(ONBOARDING_KEY);
  };

  const savedOnboardingStep = (): OnboardingStepValue => {
    const saved = localStorage.getItem(ONBOARDING_KEY);
    return saved && ['create_org', 'add_domain', 'verify_domain', 'complete'].includes(saved)
      ? (saved as OnboardingStepValue)
      : 'create_org';
  };

  // Maps a backend /auth/bootstrap payload onto tenant/org/domain state and
  // returns which onboarding step the caller is on.
  const applyBootstrap = (boot: BootstrapData): OnboardingStepValue => {
    const userEmail = boot.user?.email || '';

    // Email verification (Brevo OTP) gates all other routing — enforced
    // server-side too (org creation 403s until verified).
    if (!boot.email_verified) {
      setOrganization(null);
      setPrimaryDomain(null);
      const tempTenant: Tenant = {
        name: 'New Organization',
        plan: 'Growth',
        region: 'ng-lagos',
        email: userEmail,
      };
      setTenant(tempTenant);
      persistTenant(tempTenant);
      setOnboardingStep('verify_email');
      return 'verify_email';
    }

    const first = boot.memberships?.[0];
    if (!first?.org?.id) {
      setOrganization(null);
      setPrimaryDomain(null);
      const step = savedOnboardingStep();
      setOnboardingStep(step);
      const tempTenant: Tenant = {
        name: 'New Organization',
        plan: 'Growth',
        region: 'ng-lagos',
        email: userEmail,
      };
      setTenant(tempTenant);
      persistTenant(tempTenant);
      return step;
    }

    const org = first.org as unknown as Organization;
    setOrganization(org);

    const t: Tenant = {
      id: org.id,
      slug: org.slug,
      name: org.name,
      plan: org.plan || 'Scale',
      region: 'ng-lagos',
      email: userEmail,
    };
    setTenant(t);
    persistTenant(t, org.id);

    const domains = [...(first.domains || [])].sort((a, b) =>
      (b.created_at || '').localeCompare(a.created_at || '')
    );
    // Setup is complete once ANY domain is verified. Domains sort newest-first,
    // so a pending domain added after setup used to sit at domains[0] and
    // re-route every login (email or Google) back to the verify screen.
    // Pending domains are managed from the Domains page instead.
    const verified = domains.filter((d) => d.verification_status === 'verified');

    let step: OnboardingStepValue;
    if (domains.length > 0) {
      // Onboarding screens should reference a verified domain when one
      // exists; otherwise the newest pending one (what needs verifying).
      setPrimaryDomain(verified[0] ?? domains[0]);
      if (verified.length > 0) {
        step = 'complete';
        localStorage.removeItem(ONBOARDING_KEY);
      } else {
        step = 'verify_domain';
        // A duplicate/late refresh (e.g. StrictMode's second boot fetch, or a
        // slow response) must not bounce someone who just skipped back to the
        // verify screen — only a fresh load (prev is 'none') may re-derive it.
        setOnboardingStep(prev => (prev === 'complete' ? 'complete' : 'verify_domain'));
        return 'verify_domain';
      }
    } else {
      setPrimaryDomain(null);
      step = 'add_domain';
    }
    setOnboardingStep(step);
    return step;
  };

  // Loads state from the backend for the stored session (refreshing the
  // token once if needed). Returns 'none' when the session is dead.
  const reloadState = async (): Promise<OnboardingStepValue> => {
    try {
      let boot = await getBootstrap().catch(() => null);
      if (!boot) {
        const rotated = await refreshSession();
        if (rotated) boot = await getBootstrap().catch(() => null);
      }
      if (!boot) {
        clearSession();
        clearAuthState();
        return 'none';
      }
      setUser(boot.user);
      return applyBootstrap(boot);
    } catch (e) {
      console.warn('Failed to load account state:', e);
      // Transient lookup failure: report 'none' so callers don't route into
      // onboarding (or the dashboard) based on guessed state.
      return 'none';
    }
  };

  // Boot: restore the stored session (if any) before first render of the app.
  useEffect(() => {
    (async () => {
      try {
        const stored = loadSession();
        if (!stored) {
          clearAuthState();
          return;
        }
        await reloadState();
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Re-resolves the onboarding state after a step completes (e.g. email OTP
  // verified) so callers get the next route instead of stale step state.
  const refreshOnboarding = async (): Promise<OnboardingStepValue> => {
    if (!user?.id) return 'none';
    return reloadState();
  };

  const signOut = async () => {
    try {
      const stored = loadSession();
      localStorage.setItem(SIGNOUT_KEY, 'true');
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
      localStorage.removeItem(ORG_ID_KEY);
      sessionStorage.removeItem(ORG_ID_KEY);
      localStorage.removeItem(ONBOARDING_KEY);
      clearSession();
      if (stored?.refresh_token) {
        // Best-effort server-side revoke; local state clears regardless.
        logoutRequest(stored.refresh_token);
      }
    } catch {}
    setUser(null);
    setTenant(null);
    setOrganization(null);
    setPrimaryDomain(null);
    setOnboardingStep('none');
  };

  const signInWithCredentials = async (
    email: string,
    password: string
  ): Promise<{ ok: boolean; error?: string; name?: string; onboarding?: OnboardingStepValue }> => {
    const cleanEmail = (email || '').trim().toLowerCase();
    localStorage.removeItem(SIGNOUT_KEY);

    try {
      const tokens = await loginRequest(cleanEmail, password);
      saveSession(tokens);
      setUser(tokens.user);
      const onboarding = await reloadState();
      maybeSendWelcome(tokens.user.id);
      const name = (tokens.user.full_name || '').trim() || cleanEmail.split('@')[0] || '';
      return { ok: true, name, onboarding };
    } catch (e) {
      return { ok: false, error: (e as Error).message || 'Invalid email or password.' };
    }
  };

  const signUpWithCredentials = async (
    email: string,
    password: string,
    name: string
  ): Promise<{ ok: boolean; error?: string; needsOnboarding?: boolean; onboarding?: OnboardingStepValue }> => {
    const cleanEmail = (email || '').trim().toLowerCase();
    localStorage.removeItem(SIGNOUT_KEY);

    try {
      // Our backend creates the account AND the session immediately; email
      // verification happens via the Brevo OTP onboarding step (no separate
      // "confirm your email" screen).
      const tokens = await registerRequest(cleanEmail, password, name);
      saveSession(tokens);
      setUser(tokens.user);
      maybeSendWelcome(tokens.user.id);
      const onboarding = await reloadState();
      return { ok: true, needsOnboarding: onboarding !== 'complete', onboarding };
    } catch (e) {
      return { ok: false, error: (e as Error).message || 'Could not create the account.' };
    }
  };

  // Completes a Google sign-in: the AuthCallback page exchanges the one-time
  // redirect code for tokens, then hands them here.
  const completeExternalLogin = async (tokens: AuthTokens): Promise<OnboardingStepValue> => {
    saveSession(tokens);
    setUser(tokens.user);
    localStorage.removeItem(SIGNOUT_KEY);
    maybeSendWelcome(tokens.user.id);
    return reloadState();
  };

  const createOrganization = async (name: string, plan: string): Promise<{ ok: boolean; error?: string }> => {
    if (!user) {
      return { ok: false, error: 'You must be signed in to create an organization.' };
    }

    try {
      // Server creates the org and assigns the caller as owner (RBAC).
      const res = await createOrganizationApi({ name: name.trim(), sector: plan });
      const org = res?.organization;
      if (!org) {
        return { ok: false, error: 'Failed to create organization. Ensure you are signed in.' };
      }

      setOrganization(org);
      const t: Tenant = {
        id: org.id,
        slug: org.slug,
        name: org.name,
        plan: org.plan || plan,
        region: 'ng-lagos',
        email: user?.email,
      };
      setTenant(t);
      persistTenant(t, org.id);
      setOnboardingStep('add_domain');
      localStorage.setItem(ONBOARDING_KEY, 'add_domain');
      return { ok: true };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Failed to create organization' };
    }
  };

  const addPrimaryDomain = async (domain: string): Promise<{ ok: boolean; error?: string }> => {
    if (!organization) {
      return { ok: false, error: 'Create your organization first, then add a domain.' };
    }

    try {
      const result = await addDomain(domain.trim().toLowerCase());
      if (!result?.domain) {
        return { ok: false, error: 'Failed to add domain' };
      }
      setPrimaryDomain(result.domain);
      setOnboardingStep('verify_domain');
      localStorage.setItem(ONBOARDING_KEY, 'verify_domain');
      return { ok: true };
    } catch (e: any) {
      return { ok: false, error: e.message || 'Failed to add domain' };
    }
  };

  const verifyDomain = async (): Promise<{ ok: boolean; verified: boolean; error?: string }> => {
    if (!primaryDomain) {
      return { ok: false, verified: false, error: 'No primary domain to verify' };
    }

    try {
      // 1. Check via real backend DNS TXT verification API
      const apiResult = await verifyDomainApi(primaryDomain.id);
      if (apiResult && apiResult.status === 'verified') {
        const verifiedDom: Domain = {
          ...primaryDomain,
          verification_status: 'verified',
          verified_at: new Date().toISOString(),
        };
        setPrimaryDomain(verifiedDom);
        return { ok: true, verified: true };
      }

      if (apiResult && apiResult.details && !apiResult.details.verified) {
        return {
          ok: false,
          verified: false,
          error: apiResult.message || 'DNS TXT record not found. Please ensure record has propagated and retry.'
        };
      }

      return {
        ok: false,
        verified: false,
        error: 'DNS TXT record could not be verified yet. Propagation may take a few minutes.'
      };
    } catch (e: any) {
      return { ok: false, verified: false, error: e.message || 'Verification request failed' };
    }
  };

  const completeOnboarding = () => {
    setOnboardingStep('complete');
    localStorage.removeItem(ONBOARDING_KEY);
  };

  return (
    <Ctx.Provider
      value={{
        tenant,
        user,
        loading,
        organization,
        primaryDomain,
        onboardingStep,
        signInWithCredentials,
        signUpWithCredentials,
        completeExternalLogin,
        signOut,
        createOrganization,
        addPrimaryDomain,
        verifyDomain,
        completeOnboarding,
        refreshOnboarding,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
