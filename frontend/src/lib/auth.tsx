import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { supabase, isSupabaseConfigured } from './supabase';
import { verifyDomain as verifyDomainApi, createOrganization as createOrganizationApi, addDomain } from './api';
import type { Tenant } from '../types';
import type { User, Session } from '@supabase/supabase-js';

const KEY = 'cyphward-tenant';
const SIGNOUT_KEY = 'cyphward-signed-out';
const ONBOARDING_KEY = 'cyphward-onboarding';
const ORG_ID_KEY = 'cyphward-org-id';

const DEFAULT_TENANT: Tenant = {
  id: 'a0000000-0000-0000-0000-000000000001',
  slug: 'datagrid-africa',
  name: 'DataGrid Africa',
  plan: 'Enterprise Defense',
  region: 'ng-lagos',
};

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
  onboardingStep: 'none' | 'create_org' | 'add_domain' | 'verify_domain' | 'complete';
  signIn: (t: Tenant) => void;
  signInWithCredentials: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  signUpWithCredentials: (email: string, password: string, name: string) => Promise<{ ok: boolean; error?: string; needsOnboarding?: boolean }>;
  signOut: () => Promise<void>;
  createOrganization: (name: string, plan: string) => Promise<{ ok: boolean; error?: string }>;
  addPrimaryDomain: (domain: string) => Promise<{ ok: boolean; error?: string }>;
  verifyDomain: () => Promise<{ ok: boolean; verified: boolean; error?: string }>;
  completeOnboarding: () => void;
}

const Ctx = createContext<Auth>({
  tenant: null,
  user: null,
  session: null,
  loading: true,
  organization: null,
  primaryDomain: null,
  onboardingStep: 'none',
  signIn: () => {},
  signInWithCredentials: async () => ({ ok: false }),
  signUpWithCredentials: async () => ({ ok: false }),
  signOut: async () => {},
  createOrganization: async () => ({ ok: false }),
  addPrimaryDomain: async () => ({ ok: false }),
  verifyDomain: async () => ({ ok: false, verified: false }),
  completeOnboarding: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [primaryDomain, setPrimaryDomain] = useState<Domain | null>(null);
  const [onboardingStep, setOnboardingStep] = useState<'none' | 'create_org' | 'add_domain' | 'verify_domain' | 'complete'>('none');

  const [tenant, setTenant] = useState<Tenant | null>(() => {
    try {
      if (typeof window !== 'undefined' && localStorage.getItem(SIGNOUT_KEY) === 'true') {
        return null;
      }
      // When Supabase is configured, only use persisted tenant from a real session
      if (isSupabaseConfigured) {
        const raw = localStorage.getItem(KEY) || sessionStorage.getItem(KEY);
        return raw ? (JSON.parse(raw) as Tenant) : null;
      }
      // Demo mode: use DEFAULT_TENANT
      const raw = localStorage.getItem(KEY) || sessionStorage.getItem(KEY);
      if (raw) return JSON.parse(raw) as Tenant;
      return DEFAULT_TENANT;
    } catch {
      return isSupabaseConfigured ? null : DEFAULT_TENANT;
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

  const checkOrganization = async (userId: string, authUser?: User | null) => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      return;
    }

    try {
      const userEmail = authUser?.email || user?.email || '';

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
        const savedStep = localStorage.getItem(ONBOARDING_KEY);
        if (savedStep && ['create_org', 'add_domain', 'verify_domain', 'complete'].includes(savedStep)) {
          setOnboardingStep(savedStep as any);
        } else {
          setOnboardingStep('create_org');
        }
        const tempTenant: Tenant = {
          name: 'New Organization',
          plan: 'Growth',
          region: 'ng-lagos',
          email: userEmail,
        };
        setTenant(tempTenant);
        persistTenant(tempTenant);
        setLoading(false);
        return;
      }

      const { data: org, error: orgError } = await supabase
        .from('organizations')
        .select('*')
        .eq('id', membership.org_id)
        .single();

      if (orgError || !org) {
        setLoading(false);
        return;
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

      if (domains && domains.length > 0) {
        setPrimaryDomain(domains[0]);
        if (domains[0].verification_status === 'verified') {
          setOnboardingStep('complete');
          localStorage.removeItem(ONBOARDING_KEY);
        } else {
          setOnboardingStep('verify_domain');
        }
      } else {
        setPrimaryDomain(null);
        setOnboardingStep('add_domain');
      }
    } catch (e) {
      console.warn('Failed to check organization:', e);
    } finally {
      setLoading(false);
    }
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

  const signIn = (t: Tenant) => {
    persistTenant(t, t.id);
    setTenant(t);
  };

  const signInWithCredentials = async (email: string, password: string): Promise<{ ok: boolean; error?: string }> => {
    const cleanEmail = (email || '').trim().toLowerCase();

    localStorage.removeItem(SIGNOUT_KEY);

    if (isSupabaseConfigured) {
      const { data, error } = await supabase.auth.signInWithPassword({ email: cleanEmail, password });
      if (!error && data.user) {
        setUser(data.user);
        setSession(data.session);
        await checkOrganization(data.user.id, data.user);
        return { ok: true };
      }
      return { ok: false, error: error?.message || 'Invalid credentials. Please try again.' };
    }

    // Demo mode without Supabase (local development only)
    const t: Tenant = {
      name: email.split('@')[0] || 'Sovereign Enclave',
      plan: 'Scale',
      region: 'ng-lagos',
      email: cleanEmail,
    };
    setTenant(t);
    persistTenant(t);
    setOnboardingStep('complete');
    return { ok: true };
  };

  const signUpWithCredentials = async (
    email: string,
    password: string,
    name: string
  ): Promise<{ ok: boolean; error?: string; needsOnboarding?: boolean }> => {
    if (!isSupabaseConfigured) {
      // Demo mode - create local session
      const newTenant: Tenant = {
        name: name || 'New Organization',
        plan: 'Growth',
        region: 'ng-lagos',
        email,
      };
      setTenant(newTenant);
      persistTenant(newTenant);
      setOnboardingStep('create_org');
      localStorage.setItem(ONBOARDING_KEY, 'create_org');
      localStorage.removeItem(SIGNOUT_KEY);
      return { ok: true, needsOnboarding: true };
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

    if (data.user) {
      setUser(data.user);
      setSession(data.session);

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
    if (!isSupabaseConfigured) {
      // Demo mode
      const org: Organization = {
        id: 'org_demo_' + Date.now(),
        name,
        slug: name.toLowerCase().replace(/\s+/g, '-'),
        plan,
        created_at: new Date().toISOString(),
      };
      setOrganization(org);
      const t: Tenant = { name, plan, region: 'ng-lagos', email: user?.email };
      setTenant(t);
      persistTenant(t, org.id);
      setOnboardingStep('add_domain');
      localStorage.setItem(ONBOARDING_KEY, 'add_domain');
      return { ok: true };
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
      // Demo / offline mode
      const tokenBytes = new Uint8Array(8);
      crypto.getRandomValues(tokenBytes);
      const tokenHex = Array.from(tokenBytes).map(b => b.toString(16).padStart(2, '0')).join('');
      const dom: Domain = {
        id: 'dom_demo_' + Date.now(),
        domain,
        org_id: organization?.id || 'a0000000-0000-0000-0000-000000000001',
        verification_status: 'pending',
        verification_token: `cyphward-verify-${tokenHex}`,
        created_at: new Date().toISOString(),
      };
      setPrimaryDomain(dom);
      setOnboardingStep('verify_domain');
      localStorage.setItem(ONBOARDING_KEY, 'verify_domain');
      return { ok: true };
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
      const apiResult = await verifyDomainApi(primaryDomain.id, false);
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
        signIn,
        signInWithCredentials,
        signUpWithCredentials,
        signOut,
        createOrganization,
        addPrimaryDomain,
        verifyDomain,
        completeOnboarding,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
