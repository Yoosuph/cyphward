import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { supabase, isSupabaseConfigured } from './supabase';
import { verifyDomain as verifyDomainApi, createOrganization as createOrganizationApi, addDomain, sendWelcomeEmail, getVerificationStatus } from './api';

type OnboardingStepValue = 'none' | 'verify_email' | 'create_org' | 'add_domain' | 'verify_domain' | 'complete';
import type { Tenant } from '../types';
import type { User, Session } from '@supabase/supabase-js';

const KEY = 'cyphward-tenant';
const SIGNOUT_KEY = 'cyphward-signed-out';
const ONBOARDING_KEY = 'cyphward-onboarding';
const ORG_ID_KEY = 'cyphward-org-id';
const WELCOME_SENT_KEY = 'cyphward-welcome-sent';

// Fire-and-forget: queue one welcome email per account (server enforces its
// own cooldown too). Only safe once a real Supabase session exists.
function maybeSendWelcome(userId?: string) {
  if (!isSupabaseConfigured || !userId) return;
  try {
    if (localStorage.getItem(WELCOME_SENT_KEY) === userId) return;
    localStorage.setItem(WELCOME_SENT_KEY, userId);
    sendWelcomeEmail().then((ok) => {
      if (!ok) localStorage.removeItem(WELCOME_SENT_KEY);
    });
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
  user: User | null;
  session: Session | null;
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
  ) => Promise<{ ok: boolean; error?: string; needsOnboarding?: boolean; needsVerification?: boolean }>;
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
  session: null,
  loading: true,
  organization: null,
  primaryDomain: null,
  onboardingStep: 'none',
  signInWithCredentials: async () => ({ ok: false, error: 'Authentication is not configured.' }),
  signUpWithCredentials: async () => ({ ok: false, error: 'Authentication is not configured.' }),
  signOut: async () => {},
  createOrganization: async () => ({ ok: false }),
  addPrimaryDomain: async () => ({ ok: false }),
  verifyDomain: async () => ({ ok: false, verified: false }),
  completeOnboarding: () => {},
  refreshOnboarding: async () => 'none',
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
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

  // Load active Supabase session
  useEffect(() => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      return;
    }

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

    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      if (session?.user) {
        checkOrganization(session.user.id, session.user);
      } else {
        // No live Supabase session → drop any persisted tenant so the app
        // cannot render authenticated UI and hammer the API with 401s.
        clearAuthState();
        setLoading(false);
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      setUser(session?.user ?? null);
      if (session?.user) {
        checkOrganization(session.user.id, session.user);
      } else {
        clearAuthState();
        setLoading(false);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  type OnboardingStep = OnboardingStepValue;

  const savedOnboardingStep = (): OnboardingStep => {
    const saved = localStorage.getItem(ONBOARDING_KEY);
    return saved && ['create_org', 'add_domain', 'verify_domain', 'complete'].includes(saved)
      ? (saved as OnboardingStep)
      : 'create_org';
  };

  // Resolves the caller's real state from the database and returns which
  // onboarding step they are on (so login/signup can navigate without stale
  // component state).
  const checkOrganization = async (userId: string, authUser?: User | null): Promise<OnboardingStep> => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      return 'none';
    }

    try {
      const userEmail = authUser?.email || user?.email || '';

      // Email verification (Brevo OTP) gates all other routing. Fail-open on
      // network errors: the create-org endpoint enforces the same rule
      // server-side (403), so a flaky status call can't grant access.
      const verification = await getVerificationStatus().catch(() => null);
      if (verification && !verification.verified) {
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
        setLoading(false);
        return 'verify_email';
      }

      // memberships were renamed to organization_members in the MVP migration
      const { data: membership, error: membershipError } = await supabase
        .from('organization_members')
        .select('org_id, role')
        .eq('user_id', userId)
        .order('created_at', { ascending: true })
        .limit(1)
        .maybeSingle();

      if (membershipError || !membership?.org_id) {
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
        setLoading(false);
        return step;
      }

      const { data: org, error: orgError } = await supabase
        .from('organizations')
        .select('*')
        .eq('id', membership.org_id)
        .single();

      if (orgError || !org) {
        setLoading(false);
        return 'none';
      }

      setOrganization(org as Organization);

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

      const { data: domains } = await supabase
        .from('domains')
        .select('*')
        .eq('org_id', org.id)
        .order('created_at', { ascending: false })
        .limit(1);

      let step: OnboardingStep;
      if (domains && domains.length > 0) {
        setPrimaryDomain(domains[0]);
        if (domains[0].verification_status === 'verified') {
          step = 'complete';
          localStorage.removeItem(ONBOARDING_KEY);
        } else {
          step = 'verify_domain';
        }
      } else {
        setPrimaryDomain(null);
        step = 'add_domain';
      }
      setOnboardingStep(step);
      return step;
    } catch (e) {
      console.warn('Failed to check organization:', e);
      // Transient lookup failure: report 'none' so callers don't route into
      // onboarding (or the dashboard) based on guessed state.
      return 'none';
    } finally {
      setLoading(false);
    }
  };

  // Re-resolves the onboarding state after a step completes (e.g. email OTP
  // verified) so callers get the next route instead of stale step state.
  const refreshOnboarding = async (): Promise<OnboardingStep> => {
    if (!user?.id) return 'none';
    return checkOrganization(user.id, user);
  };

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

  const signOut = async () => {
    try {
      localStorage.setItem(SIGNOUT_KEY, 'true');
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
      localStorage.removeItem(ORG_ID_KEY);
      sessionStorage.removeItem(ORG_ID_KEY);
      localStorage.removeItem(ONBOARDING_KEY);
      if (isSupabaseConfigured) {
        await supabase.auth.signOut();
      }
    } catch {}
    setUser(null);
    setSession(null);
    setTenant(null);
    setOrganization(null);
    setPrimaryDomain(null);
    setOnboardingStep('none');
  };

  const signInWithCredentials = async (email: string, password: string): Promise<{ ok: boolean; error?: string; name?: string; onboarding?: OnboardingStepValue }> => {
    const cleanEmail = (email || '').trim().toLowerCase();

    localStorage.removeItem(SIGNOUT_KEY);

    if (isSupabaseConfigured) {
      const { data, error } = await supabase.auth.signInWithPassword({ email: cleanEmail, password });
      if (!error && data.user) {
        setUser(data.user);
        setSession(data.session);
        const onboarding = await checkOrganization(data.user.id, data.user);
        maybeSendWelcome(data.user.id);
        const meta = (data.user.user_metadata || {}) as Record<string, unknown>;
        const name =
          String(meta.full_name || meta.name || '').trim() ||
          (data.user.email || '').split('@')[0] ||
          '';
        return { ok: true, name, onboarding };
      }
      return { ok: false, error: error?.message || 'Invalid credentials. Please try again.' };
    }

    return { ok: false, error: 'Authentication is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.' };
  };

  const signUpWithCredentials = async (
    email: string,
    password: string,
    name: string
  ): Promise<{ ok: boolean; error?: string; needsOnboarding?: boolean; needsVerification?: boolean }> => {
    if (!isSupabaseConfigured) {
      return { ok: false, error: 'Authentication is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.' };
    }

    localStorage.removeItem(SIGNOUT_KEY);

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: name,
        },
      },
    });

    if (error) {
      return { ok: false, error: error.message };
    }

    if (data.user && !data.session) {
      // Email confirmations are enabled on the Supabase project: the account
      // exists but there is NO session yet. Never fake a login — tell the
      // caller to verify first.
      return { ok: true, needsVerification: true };
    }

    if (data.user && data.session) {
      setUser(data.user);
      setSession(data.session);
      maybeSendWelcome(data.user.id);

      // Backend creates the profile row on first authenticated request.
      // Keep a light local profile upsert for immediate display name.
      try {
        await supabase.from('profiles').upsert({
          id: data.user.id,
          email: email,
          full_name: name,
          updated_at: new Date().toISOString(),
        });
      } catch (err) {
        console.warn('Profile sync note:', err);
      }

      const tempTenant: Tenant = {
        name: name ? `${name}'s Org` : 'New Organization',
        plan: 'Growth',
        region: 'ng-lagos',
        email,
      };
      setTenant(tempTenant);
      persistTenant(tempTenant);

      setOnboardingStep('create_org');
      localStorage.setItem(ONBOARDING_KEY, 'create_org');
      return { ok: true, needsOnboarding: true };
    }

    return { ok: true };
  };

  const createOrganization = async (name: string, plan: string): Promise<{ ok: boolean; error?: string }> => {
    if (!isSupabaseConfigured || !session) {
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
    if (!isSupabaseConfigured || !organization) {
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
        session,
        loading,
        organization,
        primaryDomain,
        onboardingStep,
        signInWithCredentials,
        signUpWithCredentials,
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
