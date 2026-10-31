import { useEffect, useState, type KeyboardEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { PageHead } from '../components/ui';
import { useConfirm } from '../components/ConfirmDialog';
import {
  Building,
  Users,
  Key,
  RefreshCw,
  Plus,
  Sparkles,
  Check,
  Bell,
} from 'lucide-react';
import NotificationSettings from '../components/NotificationSettings';
import { getSettings, updateCompanyProfile, addTeamMember, updateMemberRole, getExecutiveSummary, mfaStatus, mfaEnroll, mfaDisableRequest, mfaDisableConfirm, forgetTrustedBrowsers, exportOrganization, closeOrganization, getSubscription, cancelSubscription, listInvoices, deleteOwnAccount, totpEnrollStart, totpEnrollConfirm, totpDisable } from '../lib/api';
import { useAuth } from '../lib/auth';
import type { SettingsData, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';
import { SettingsSkeleton } from '../components/Skeleton';
import { ErrorPanel, humanError } from '../components/ui/StatePanels';
import Modal from '../components/Modal';
import BoardReportModal from '../components/BoardReportModal';
import { QRCodeSVG } from 'qrcode.react';
import { writeGuard } from '../lib/suspension';
import { useOrgSuspended } from '../lib/useOrgSuspended';

type SettingsTab = 'general' | 'team' | 'auth' | 'notifications';
const TAB_ORDER = ['general', 'team', 'auth', 'notifications'] as const;

export default function Settings() {
  const confirmAction = useConfirm();
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchParams] = useSearchParams();
  // ?tab=notifications opens a section directly (the bell's settings button and the email's settings link).
  const [activeTab, setActiveTab] = useState<SettingsTab>(() => {
    const asked = searchParams.get('tab');
    return (TAB_ORDER as readonly string[]).includes(asked || '') ? (asked as SettingsTab) : 'general';
  });
  useEffect(() => {
    const asked = searchParams.get('tab');
    if (asked && (TAB_ORDER as readonly string[]).includes(asked)) setActiveTab(asked as SettingsTab);
  }, [searchParams]);
  const [loadError, setLoadError] = useState<unknown>(null);

  const [companyName, setCompanyName] = useState('');
  const [cacRc, setCacRc] = useState('');
  const [sector, setSector] = useState('');
  const [savingCompany, setSavingCompany] = useState(false);

  const [memberModalOpen, setMemberModalOpen] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [memberName, setMemberName] = useState('');
  const [memberRole, setMemberRole] = useState('member');
  const [addingMember, setAddingMember] = useState(false);
  const [roleBusyId, setRoleBusyId] = useState<string | null>(null);

  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [execSummary, setExecSummary] = useState<ExecutiveSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Account self-service deletion (typed email + password when set).
  const { user: sessionUser, signOut } = useAuth();
  const suspended = useOrgSuspended();
  const [delEmail, setDelEmail] = useState('');
  const [delPw, setDelPw] = useState('');
  const [delBusy, setDelBusy] = useState(false);

  const handleDeleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!delEmail.trim()) return;
    if (!(await confirmAction({
      title: 'Delete your account?',
      body: 'This permanently deletes your account and signs out every session. This cannot be undone.',
      confirmLabel: 'DELETE ACCOUNT', danger: true,
    }))) return;
    setDelBusy(true);
    try {
      const res = await deleteOwnAccount(delEmail.trim(), delPw);
      if (res?.deleted) {
        toast('Account deleted');
        await signOut();
        window.location.href = '/login';
      } else {
        toast('Could not delete the account');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not delete the account');
    } finally {
      setDelBusy(false);
    }
  };
  // Workspace export + closure (owner-only danger zone).
  const [exportBusy, setExportBusy] = useState(false);
  const [closeSlug, setCloseSlug] = useState('');
  const [closeBusy, setCloseBusy] = useState(false);
  // Billing (manual provider — records only, nothing is charged).
  const [billing, setBilling] = useState<any | null>(null);
  const [invoices, setInvoices] = useState<any[]>([]);
  const [billingBusy, setBillingBusy] = useState(false);
  // MFA (step-up sign-in code): status + enroll/disable flows.
  const [mfa, setMfa] = useState<{ enrolled: boolean; admin_required: boolean; email_verified: boolean; totp_enrolled: boolean; totp_pending: boolean; remembered_browsers?: number } | null>(null);
  // Authenticator app (TOTP): enroll/confirm/disable flows.
  const [totpSecret, setTotpSecret] = useState<string | null>(null);
  const [totpUrl, setTotpUrl] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState('');
  const [totpBusy, setTotpBusy] = useState(false);
  const [totpCopied, setTotpCopied] = useState(false);
  // QR modal: fitted (just the code) or moderate.
  const [qrOpen, setQrOpen] = useState(false);
  const [qrSize, setQrSize] = useState<'fitted' | 'moderate'>('fitted');

  const handleTotpStart = async () => {
    setTotpBusy(true);
    try {
      const res = await totpEnrollStart();
      if (res?.secret) {
        setTotpSecret(res.secret);
        setTotpUrl(res.otpauth_url);
        setTotpCode('');
        setTotpCopied(false);
        await refreshMfa();
      } else {
        toast('Could not start authenticator setup');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not start authenticator setup');
    } finally {
      setTotpBusy(false);
    }
  };

  const handleTotpConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setTotpBusy(true);
    try {
      const res = await totpEnrollConfirm(totpCode.trim());
      if (res?.enrolled) {
        toast('Authenticator app switched on');
        setTotpSecret(null);
        setTotpUrl(null);
        setTotpCode('');
        await refreshMfa();
      } else {
        toast('Could not confirm — check the code');
      }
    } catch (e: any) {
      toast(e?.message || 'Invalid code. Please try again.');
    } finally {
      setTotpBusy(false);
    }
  };

  const handleTotpDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    setTotpBusy(true);
    try {
      const res = await totpDisable(totpCode.trim());
      if (res?.disabled) {
        toast('Authenticator app switched off');
        setTotpCode('');
        await refreshMfa();
      } else {
        toast('Could not switch off');
      }
    } catch (e: any) {
      toast(e?.message || 'Invalid code. Please try again.');
    } finally {
      setTotpBusy(false);
    }
  };

  const copyTotpUrl = async () => {
    try {
      await navigator.clipboard.writeText(totpUrl || totpSecret || '');
      setTotpCopied(true);
      setTimeout(() => setTotpCopied(false), 2000);
    } catch {
      toast('Copy failed — select the text manually');
    }
  };
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaCode, setMfaCode] = useState('');
  const [mfaCodeSent, setMfaCodeSent] = useState(false);

  const toast = useToast();

  const loadSettings = async () => {
    setLoading(true);
    try {
      const res = await getSettings();
      setLoadError(null);
      setData(res);
      setCompanyName(res.organization.name);
      setCacRc(res.organization.cac_rc || '');
      setSector(res.organization.sector || '');
    } catch (e) {
      // First load: the page shows an error with a retry. A later refresh keeps the page and says so.
      setLoadError(e);
      if (data) toast('Could not refresh settings. Showing what was loaded before.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  useEffect(() => {
    if (activeTab !== 'auth') return;
    mfaStatus().then(setMfa).catch(() => setMfa(null));
  }, [activeTab]);

  useEffect(() => {
    if (activeTab !== 'general' || billing !== null) return;
    const role = (data?.membership?.role || 'member').toLowerCase();
    if (role !== 'owner') return;
    refreshBilling().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, data, billing]);

  const refreshMfa = async () => {
    try {
      setMfa(await mfaStatus());
    } catch {
      toast('Could not load sign-in security status');
    }
  };

  const handleMfaEnroll = async () => {
    setMfaBusy(true);
    try {
      const res = await mfaEnroll();
      if (res?.enrolled) {
        toast('Step-up sign-in switched on — codes go to your email');
        await refreshMfa();
      } else {
        toast('Could not switch on step-up sign-in');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not switch on step-up sign-in');
    } finally {
      setMfaBusy(false);
    }
  };

  const handleForgetBrowsers = async () => {
    setMfaBusy(true);
    try {
      await forgetTrustedBrowsers();
      setMfa(await mfaStatus());
      toast('Remembered browsers forgotten — the next sign-in asks for a code');
    } catch (e: any) {
      toast(e?.message || 'Could not forget remembered browsers');
    } finally {
      setMfaBusy(false);
    }
  };

  const handleMfaDisableRequest = async () => {
    setMfaBusy(true);
    try {
      const res = await mfaDisableRequest();
      if (res?.sent) {
        setMfaCodeSent(true);
        setMfaCode('');
        toast('Confirmation code sent to your email');
      } else {
        toast('Could not send the confirmation code');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not send the confirmation code');
    } finally {
      setMfaBusy(false);
    }
  };

  const handleMfaDisableConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setMfaBusy(true);
    try {
      const res = await mfaDisableConfirm(mfaCode.trim());
      if (res?.disabled) {
        toast('Step-up sign-in switched off');
        setMfaCodeSent(false);
        setMfaCode('');
        await refreshMfa();
      } else {
        toast('Could not switch off step-up sign-in');
      }
    } catch (e: any) {
      toast(e?.message || 'Invalid code. Please try again.');
    } finally {
      setMfaBusy(false);
    }
  };

  const handleExport = async () => {
    setExportBusy(true);
    try {
      const blob = await exportOrganization();
      if (!blob) {
        toast('Export failed');
        return;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `cyphward-${data?.organization?.slug || 'workspace'}-export.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast('Workspace export downloaded');
    } catch (e: any) {
      toast(e?.message || 'Export failed');
    } finally {
      setExportBusy(false);
    }
  };

  const handleClose = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!closeSlug.trim()) return;
    if (!(await confirmAction({
      title: 'Delete this workspace?',
      body: 'This permanently deletes the workspace and all its data, including domains, scans, findings and reports. This cannot be undone.',
      confirmLabel: 'DELETE WORKSPACE', danger: true,
    }))) return;
    setCloseBusy(true);
    try {
      const res = await closeOrganization(closeSlug.trim());
      if (res?.closed) {
        toast('Workspace closed');
        window.location.href = '/overview';
      } else {
        toast('Could not close the workspace');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not close the workspace');
    } finally {
      setCloseBusy(false);
    }
  };

  const refreshBilling = async () => {
    try {
      const [sub, inv] = await Promise.all([getSubscription(), listInvoices().catch(() => null)]);
      setBilling(sub);
      setInvoices(inv?.invoices || []);
    } catch {
      toast('Could not load billing status');
    }
  };

  const handleCancelSub = async () => {
    if (!(await confirmAction({
      title: 'Cancel your subscription?',
      body: 'Your plan stays active until the end of the current period, then it is not renewed.',
      confirmLabel: 'CANCEL SUBSCRIPTION', cancelLabel: 'KEEP PLAN', danger: true,
    }))) return;
    setBillingBusy(true);
    try {
      const res = await cancelSubscription();
      if (res?.subscription) {
        toast('Subscription will end after the current period');
        await refreshBilling();
      } else {
        toast('Could not cancel');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not cancel');
    } finally {
      setBillingBusy(false);
    }
  };

  const handleSaveCompany = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingCompany(true);
    try {
      await updateCompanyProfile({
        name: companyName,
        cac_rc: cacRc,
        sector: sector,
      });
      toast('Company details updated successfully');
      await loadSettings();
    } catch (err: any) {
      toast(err.message || 'Update failed');
    } finally {
      setSavingCompany(false);
    }
  };

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memberEmail.trim()) return;
    setAddingMember(true);
    try {
      const res = await addTeamMember(memberEmail.trim(), memberName.trim() || memberEmail.split('@')[0], memberRole);
      toast(res?.message || `Invite sent to ${memberEmail}`);
      setMemberModalOpen(false);
      setMemberEmail('');
      setMemberName('');
      setMemberRole('member');
      await loadSettings();
    } catch (err: any) {
      toast(err.message || 'Failed to add member');
    } finally {
      setAddingMember(false);
    }
  };

  const handleRoleChange = async (userId: string, role: string) => {
    setRoleBusyId(userId);
    try {
      await updateMemberRole(userId, role);
      toast(`Role updated to ${role}`);
      await loadSettings();
    } catch (err: any) {
      toast(err.message || 'Failed to update role');
    } finally {
      setRoleBusyId(null);
    }
  };

  const handleOpenExecutiveReport = async () => {
    setSummaryModalOpen(true);
    setSummaryLoading(true);
    try {
      const sum = await getExecutiveSummary();
      setExecSummary(sum);
    } catch {
      toast('Failed to generate executive report');
    } finally {
      setSummaryLoading(false);
    }
  };

  const myRole = (data?.membership?.role || 'member').toLowerCase();
  const isOwner = myRole === 'owner';
  const canManageRoles = myRole === 'owner' || myRole === 'admin';

  // Arrow keys, Home and End move between the section tabs (WAI-ARIA tabs pattern).
  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const order = TAB_ORDER;
    const at = order.indexOf(activeTab);
    const next = e.key === 'ArrowRight' ? order[(at + 1) % order.length]
      : e.key === 'ArrowLeft' ? order[(at + order.length - 1) % order.length]
      : e.key === 'Home' ? order[0] : e.key === 'End' ? order[order.length - 1] : null;
    if (!next) return;
    e.preventDefault();
    setActiveTab(next);
    document.getElementById(`settings-tab-${next}`)?.focus();
  };

  if (!data && loadError && !loading) {
    return (
      <div className="space-y-6 max-w-5xl mx-auto pb-12 content-fade-in">
        <PageHead title="Settings" note="Company profile, team, billing and sign-in." />
        <ErrorPanel title="We could not load your settings" message={humanError(loadError, 'Cyphward did not respond. Try again in a moment.', { passDetail: false })} onRetry={loadSettings} />
      </div>
    );
  }

  if (loading || !data) {
    return <SettingsSkeleton />;
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12 content-fade-in">
      <PageHead title="Settings" note="Company profile, team, billing and sign-in." />

      <div className="flex items-center gap-1 border-b border-line overflow-x-auto pb-px no-scrollbar" role="tablist" aria-label="Settings sections" onKeyDown={onTabKey}>
        <button
          type="button"
          role="tab"
          id="settings-tab-general"
          aria-selected={activeTab === 'general'}
          aria-controls={activeTab === 'general' ? 'settings-panel-general' : undefined}
          tabIndex={activeTab === 'general' ? 0 : -1}
          onClick={() => setActiveTab('general')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'general' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <Building size={14} />
          <span>GENERAL</span>
        </button>

        <button
          type="button"
          role="tab"
          id="settings-tab-team"
          aria-selected={activeTab === 'team'}
          aria-controls={activeTab === 'team' ? 'settings-panel-team' : undefined}
          tabIndex={activeTab === 'team' ? 0 : -1}
          onClick={() => setActiveTab('team')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'team' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <Users size={14} />
          <span>TEAM & ROLES ({data.members?.length || 0})</span>
        </button>

        <button
          type="button"
          role="tab"
          id="settings-tab-auth"
          aria-selected={activeTab === 'auth'}
          aria-controls={activeTab === 'auth' ? 'settings-panel-auth' : undefined}
          tabIndex={activeTab === 'auth' ? 0 : -1}
          onClick={() => setActiveTab('auth')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'auth' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <Key size={14} />
          <span>AUTHENTICATION</span>
        </button>

        <button
          type="button"
          role="tab"
          id="settings-tab-notifications"
          aria-selected={activeTab === 'notifications'}
          aria-controls={activeTab === 'notifications' ? 'settings-panel-notifications' : undefined}
          tabIndex={activeTab === 'notifications' ? 0 : -1}
          onClick={() => setActiveTab('notifications')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'notifications' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <Bell size={14} />
          <span>NOTIFICATIONS</span>
        </button>
      </div>

      {activeTab === 'notifications' && (
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4" role="tabpanel" id="settings-panel-notifications"
             aria-labelledby="settings-tab-notifications">
          <NotificationSettings focusCategory={searchParams.get('category')} />
        </div>
      )}

      {activeTab === 'general' && (
        <div className="space-y-6" role="tabpanel" id="settings-panel-general" aria-labelledby="settings-tab-general">
          <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-line">
              <Building size={16} className="text-accent" />
              <h2 className="mono font-semibold text-ink text-sm">COMPANY PROFILE</h2>
            </div>

            <form onSubmit={handleSaveCompany} className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label htmlFor="settings-company-name" className="mono text-soft text-[11px]">COMPANY NAME</label>
                  <input
                    id="settings-company-name"
                    type="text"
                    value={companyName}
                    onChange={e => setCompanyName(e.target.value)}
                    required
                    className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="settings-cac-rc" className="mono text-soft text-[11px]">CORPORATE AFFAIRS COMMISSION (CAC RC)</label>
                  <input
                    id="settings-cac-rc"
                    type="text"
                    value={cacRc}
                    onChange={e => setCacRc(e.target.value)}
                    placeholder="e.g. RC-1849204"
                    className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="settings-sector" className="mono text-soft text-[11px]">INDUSTRY SECTOR</label>
                  <input
                    id="settings-sector"
                    type="text"
                    value={sector}
                    onChange={e => setSector(e.target.value)}
                    placeholder="e.g. Fintech & Digital Commerce"
                    className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="space-y-1.5">
                  <p className="mono text-soft text-[11px]">YOUR ROLE</p>
                  <div className="flex items-center gap-2 p-2 rounded bg-inset border border-line mono">
                    <span className="tag">{myRole.toUpperCase()}</span>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <p className="mono text-soft text-[11px]">YOUR PLAN</p>
                  <div className="flex items-center gap-2 p-2 rounded bg-inset/50 border border-line/60 mono text-soft">
                    <span className="text-ink font-semibold">{data.organization.plan ? data.organization.plan.charAt(0).toUpperCase() + data.organization.plan.slice(1) : '—'}</span>
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  data-write="settings-save"
                  {...writeGuard(suspended, savingCompany)}
                  className="btn-tactile px-4 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
                >
                  {savingCompany ? <RefreshCw size={13} className="animate-spin" /> : null}
                  Save Organization Profile
                </button>
              </div>
            </form>
          </div>

          {isOwner && (
          <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-line">
              <h2 className="mono font-semibold text-ink text-sm">BILLING</h2>
              <span className="tag ml-auto">MANUAL PAYMENT CONFIRMATION</span>
            </div>
            {billing ? (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mono">
                  <div className="p-2 rounded bg-inset border border-line">
                    <div className="text-soft text-[10px]">PLAN</div>
                    <div className="text-ink font-semibold capitalize">{billing.subscription?.plan || billing.entitlements?.plan || '—'}</div>
                  </div>
                  <div className="p-2 rounded bg-inset border border-line">
                    <div className="text-soft text-[10px]">STATUS</div>
                    <div className="text-ink font-semibold">{({ trialing: 'Trial', active: 'Active period', past_due: 'Period ended', canceled: 'Ended' } as Record<string, string>)[billing.effective_status] || 'Contact us'}</div>
                  </div>
                  <div className="p-2 rounded bg-inset border border-line col-span-2">
                    <div className="text-soft text-[10px]">CURRENT PERIOD ENDS</div>
                    <div className="text-ink font-semibold">{billing.subscription?.current_period_end ? new Date(billing.subscription.current_period_end).toLocaleDateString() : '—'}</div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Link to="/contact" className="btn-tactile px-3 py-2 rounded text-xs mono border border-line hover:border-accent text-ink">
                    ARRANGE PAYMENT OR PLAN CHANGE
                  </Link>
                  <button
                    type="button"
                    onClick={handleCancelSub}
                    // Cancelling stays open while suspended (a customer can always stop paying).
                    disabled={billingBusy || !billing.subscription || billing.subscription?.cancel_at_period_end}
                    className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink disabled:opacity-50"
                  >
                    {billing.subscription?.cancel_at_period_end ? 'CANCELS AT PERIOD END' : 'CANCEL'}
                  </button>
                </div>
                <p className="text-xs text-soft leading-relaxed">
                  New workspaces have a 30-day trial. No automatic charge or paid renewal is made.
                  Payment must be confirmed before another paid period is activated. An open invoice
                  does not confirm payment. New scans and report generation pause after expiry;
                  contact us for payment or an explicit trial extension.
                </p>
                {invoices.length > 0 && (
                  <table className="w-full text-left text-xs mono">
                    <thead>
                      <tr className="border-b border-line text-soft text-[11px]">
                        <th className="pb-2 font-medium">INVOICE</th>
                        <th className="pb-2 font-medium">PLAN</th>
                        <th className="pb-2 font-medium">AMOUNT</th>
                        <th className="pb-2 font-medium">STATUS</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {invoices.map(inv => (
                        <tr key={inv.id}>
                          <td className="py-2 text-soft">{inv.number}</td>
                          <td className="py-2 text-ink capitalize">{inv.plan}</td>
                          <td className="py-2 text-ink">₦{(inv.amount_kobo / 100).toLocaleString()}</td>
                          <td className="py-2 text-soft uppercase">{inv.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            ) : (
              <p className="text-xs text-soft mono">Loading billing status…</p>
            )}
          </div>
          )}
          {isOwner && (
          <div className="p-6 rounded-lg border border-red-500/30 bg-raised space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-line">
              <h2 className="mono font-semibold text-ink text-sm">DATA & CLOSURE</h2>
            </div>
            <p className="text-xs text-soft mono leading-relaxed">
              Download everything in this workspace (members, domains, assets, findings,
              scans, reports) as JSON, or permanently close the workspace. Closure deletes
              all workspace data at once — your account itself stays.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={handleExport}
                disabled={exportBusy}
                className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50"
              >
                {exportBusy ? 'EXPORTING…' : 'DOWNLOAD WORKSPACE EXPORT'}
              </button>
            </div>
            <form onSubmit={handleClose} className="flex flex-wrap items-center gap-2 pt-3 border-t border-line">
              <input
                type="text"
                placeholder={`Type '${data?.organization?.slug || 'slug'}' to confirm`}
                aria-label={`Type the workspace name '${data?.organization?.slug || 'slug'}' to confirm closing it`}
                value={closeSlug}
                onChange={e => setCloseSlug(e.target.value)}
                className="bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-red-500"
              />
              <button
                type="submit"
                {...writeGuard(suspended, closeBusy || !closeSlug.trim())}
                className="btn-tactile px-3 py-1.5 rounded text-xs mono bg-red-600 text-white hover:bg-red-500 disabled:opacity-50"
              >
                {closeBusy ? 'CLOSING…' : 'CLOSE WORKSPACE'}
              </button>
            </form>
          </div>
          )}
        </div>
      )}

      {activeTab === 'team' && (
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4" role="tabpanel" id="settings-panel-team" aria-labelledby="settings-tab-team">
          <div className="flex items-center justify-between pb-3 border-b border-line">
            <div className="flex items-center gap-2">
              <Users size={16} className="text-accent" />
              <h2 className="mono font-semibold text-ink text-sm">TEAM & ROLES</h2>
            </div>
            {canManageRoles && (
              <button
                onClick={() => setMemberModalOpen(true)}
                data-write="member-invite"
                {...writeGuard(suspended)}
                className="btn-tactile flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                <Plus size={13} />
                <span>Invite Member</span>
              </button>
            )}
          </div>

          <div className="overflow-x-auto w-full max-w-full">
            <table className="w-full text-left text-xs mono min-w-[560px]">
              <thead>
                <tr className="border-b border-line text-soft text-[11px]">
                  <th className="pb-2 font-medium">MEMBER</th>
                  <th className="pb-2 font-medium">EMAIL</th>
                  <th className="pb-2 font-medium">ROLE</th>
                  <th className="pb-2 font-medium text-right">JOINED</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {(data.members || []).map((m, idx) => (
                  <tr key={m.id} className="hover:bg-inset/40 transition-colors" style={{ animationDelay: `${idx * 35}ms` }}>
                    <td className="py-2.5 font-semibold text-ink flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-accent/10 border border-accent/30 text-accent font-bold text-[10px] flex items-center justify-center">
                        {(m.full_name || m.email || '?').charAt(0).toUpperCase()}
                      </div>
                      <span>{m.full_name || m.email}</span>
                    </td>
                    <td className="py-2.5 text-soft">{m.email}</td>
                    <td className="py-2.5">
                      {canManageRoles ? (
                        <select
                          value={(m.role || 'member').toLowerCase()}
                          // Lowering a role stays open while suspended; the server refuses a promotion.
                          disabled={roleBusyId === m.id}
                          onChange={e => handleRoleChange(m.id, e.target.value)}
                          aria-label={`Role for ${m.email || m.full_name || 'this member'}`}
                          className="bg-inset border border-line rounded px-2 py-1 text-[11px] text-ink mono focus:outline-none focus:border-accent"
                        >
                          <option value="owner">owner</option>
                          <option value="admin">admin</option>
                          <option value="member">member</option>
                        </select>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-[10px] bg-inset border border-line text-soft font-semibold">
                          {(m.role || 'member').toLowerCase()}
                        </span>
                      )}
                      {roleBusyId === m.id && <RefreshCw size={11} className="inline ml-1 animate-spin text-accent" />}
                    </td>
                    <td className="py-2.5 text-soft text-right text-[11px]">
                      {m.created_at ? new Date(m.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-[11px] text-soft mono">
            Roles: <span className="text-ink">owner</span> (full control) ·{' '}
            <span className="text-ink">admin</span> (manage scans and members) ·{' '}
            <span className="text-ink">member</span> (view and review findings)
          </p>
        </div>
      )}

      {activeTab === 'auth' && (
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4" role="tabpanel" id="settings-panel-auth" aria-labelledby="settings-tab-auth">
          <div className="flex items-center gap-2 pb-3 border-b border-line">
            <Key size={16} className="text-accent" />
            <h2 className="mono font-semibold text-ink text-sm">AUTHENTICATION</h2>
          </div>
          <div className="space-y-3 text-xs text-soft mono leading-relaxed">
            <p className="text-ink">
              Sign-in is handled by <span className="text-accent">Cyphward accounts</span>
              (email + password, or Google). This version does not use API keys.
            </p>
            <ul className="space-y-2">
              <li className="flex items-start gap-2">
                <Check size={14} className="text-ok mt-0.5" />
                Authorization: Bearer &lt;access token&gt;
              </li>
              <li className="flex items-start gap-2">
                <Check size={14} className="text-ok mt-0.5" />
                X-Organization-Id picks which organization to use (checked on the server)
              </li>
              <li className="flex items-start gap-2">
                <Check size={14} className="text-ok mt-0.5" />
                Roles are checked on the server: owner / admin / member
              </li>
            </ul>
          </div>

          {/* Step-up sign-in (email code) */}
          <div className="pt-4 border-t border-line space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="mono font-semibold text-ink text-xs">STEP-UP SIGN-IN CODE</h3>
              {mfa && (
                <span className={`px-2 py-0.5 rounded text-[10px] mono border ${
                  mfa.enrolled || mfa.admin_required
                    ? 'bg-ok/10 text-ok border-ok/30'
                    : 'bg-inset text-soft border-line'
                }`}>
                  {mfa.enrolled ? 'ON' : mfa.admin_required ? 'REQUIRED (ADMIN)' : 'OFF'}
                </span>
              )}
            </div>
            <p className="text-xs text-soft mono leading-relaxed">
              {mfa?.admin_required
                ? 'Owner and admin accounts confirm sign-in with a 6-digit code sent to their email. This can\'t be switched off, but you can tick “Remember this browser” when you enter a code to skip it on that browser for 30 days.'
                : mfa?.enrolled
                  ? 'Your sign-ins ask for a 6-digit email code after your password.'
                  : 'Add a 6-digit email code after your password on every sign-in.'}
            </p>
            {!mfa?.enrolled && !mfa?.admin_required && (
              mfa && !mfa.email_verified ? (
                <p className="text-xs mono text-amber-500">Verify your email first — the code has to reach you.</p>
              ) : (
                <button
                  type="button"
                  onClick={handleMfaEnroll}
                  disabled={mfaBusy}
                  className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50"
                >
                  {mfaBusy ? 'SWITCHING ON…' : 'SWITCH ON STEP-UP SIGN-IN'}
                </button>
              )
            )}
            {!mfa?.admin_required && mfa?.enrolled && !mfaCodeSent && (
              <button
                type="button"
                onClick={handleMfaDisableRequest}
                disabled={mfaBusy}
                className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink disabled:opacity-50"
              >
                {mfaBusy ? 'SENDING…' : 'SWITCH OFF (SEND CONFIRMATION CODE)'}
              </button>
            )}
            {(mfa?.remembered_browsers ?? 0) > 0 && (
              <div className="flex flex-wrap items-center gap-3 text-xs mono text-soft">
                <span>
                  {mfa?.remembered_browsers} remembered browser{mfa?.remembered_browsers === 1 ? '' : 's'} skip the code for now.
                </span>
                <button
                  type="button"
                  onClick={handleForgetBrowsers}
                  disabled={mfaBusy}
                  className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50"
                >
                  FORGET REMEMBERED BROWSERS
                </button>
              </div>
            )}
            {!mfa?.admin_required && mfa?.enrolled && mfaCodeSent && (
              <form onSubmit={handleMfaDisableConfirm} className="flex items-center gap-2">
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="123456"
                  aria-label="Six-digit code from your email"
                  value={mfaCode}
                  onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="w-32 bg-inset border border-line rounded px-3 py-1.5 text-ink mono focus:outline-none focus:border-accent"
                />
                <button
                  type="submit"
                  disabled={mfaBusy || mfaCode.length !== 6}
                  className="btn-tactile px-3 py-1.5 rounded text-xs mono bg-accent text-white disabled:opacity-50"
                >
                  {mfaBusy ? 'CONFIRMING…' : 'CONFIRM SWITCH-OFF'}
                </button>
              </form>
            )}
          </div>

          {/* Authenticator app (TOTP) */}
          <div className="pt-4 border-t border-line space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="mono font-semibold text-ink text-xs">AUTHENTICATOR APP</h3>
              {mfa && (
                <span className={`px-2 py-0.5 rounded text-[10px] mono border ${
                  mfa.totp_enrolled
                    ? 'bg-ok/10 text-ok border-ok/30'
                    : 'bg-inset text-soft border-line'
                }`}>
                  {mfa.totp_enrolled ? 'ON' : mfa.totp_pending ? 'PENDING' : 'OFF'}
                </span>
              )}
            </div>
            <p className="text-xs text-soft mono leading-relaxed">
              Use Google Authenticator, 1Password or any TOTP app instead of waiting for email codes.
              {mfa && !mfa.email_verified && ' Verify your email first.'}
            </p>
            {!mfa?.totp_enrolled && !totpSecret && (
              <button
                type="button"
                onClick={handleTotpStart}
                disabled={totpBusy || (mfa != null && !mfa.email_verified)}
                className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50"
              >
                {totpBusy ? 'PREPARING…' : 'SET UP AUTHENTICATOR APP'}
              </button>
            )}
            {!mfa?.totp_enrolled && totpSecret && (
              <div className="space-y-2">
                <p className="text-xs mono text-soft">
                  Scan this with Google Authenticator (click to enlarge), or enter the secret manually:
                </p>
                <div className="flex flex-wrap items-start gap-3">
                  <button
                    type="button"
                    onClick={() => setQrOpen(true)}
                    title="Enlarge QR code"
                    className="btn-tactile p-2 rounded bg-white border border-line hover:border-line-strong"
                  >
                    <QRCodeSVG value={totpUrl || totpSecret} size={128} />
                  </button>
                  <div className="flex-1 min-w-[200px] space-y-2">
                    <div className="flex items-center gap-2">
                      <code className="flex-1 bg-inset border border-line rounded px-3 py-1.5 text-xs mono text-ink break-all">{totpSecret}</code>
                      <button
                        type="button"
                        onClick={copyTotpUrl}
                        className="btn-tactile px-2.5 py-1.5 rounded text-[11px] mono border border-line text-soft hover:text-ink"
                      >
                        {totpCopied ? 'COPIED' : 'COPY'}
                      </button>
                    </div>
                    <p className="text-[11px] mono text-soft">Then confirm with a code from the app:</p>
                  </div>
                </div>
                <form onSubmit={handleTotpConfirm} className="flex items-center gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="123456"
                    aria-label="Six-digit code from your authenticator app"
                    value={totpCode}
                    onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    className="w-32 bg-inset border border-line rounded px-3 py-1.5 text-ink mono focus:outline-none focus:border-accent"
                  />
                  <button
                    type="submit"
                    disabled={totpBusy || totpCode.length !== 6}
                    className="btn-tactile px-3 py-1.5 rounded text-xs mono bg-accent text-white disabled:opacity-50"
                  >
                    {totpBusy ? 'CONFIRMING…' : 'CONFIRM'}
                  </button>
                </form>
              </div>
            )}
            {mfa?.totp_enrolled && (
              <form onSubmit={handleTotpDisable} className="flex items-center gap-2">
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="Current app code"
                  aria-label="Current code from your authenticator app"
                  value={totpCode}
                  onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="w-40 bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-accent"
                />
                <button
                  type="submit"
                  disabled={totpBusy || totpCode.length !== 6}
                  className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink disabled:opacity-50"
                >
                  {totpBusy ? 'SWITCHING OFF…' : 'SWITCH OFF APP'}
                </button>
              </form>
            )}
          </div>

          {/* Self-service account deletion */}
          <div className="pt-4 border-t border-red-500/20 space-y-3">
            <h3 className="mono font-semibold text-ink text-xs">DELETE MY ACCOUNT</h3>
            <p className="text-xs text-soft mono leading-relaxed">
              Removes your profile, sessions and memberships. Blocked while you solely own a
              workspace — transfer ownership or close it first.
            </p>
            <form onSubmit={handleDeleteAccount} className="flex flex-wrap items-center gap-2">
              <input
                type="email"
                placeholder={sessionUser?.email || 'you@example.com'}
                aria-label="Your email address, to confirm deleting your account"
                value={delEmail}
                onChange={e => setDelEmail(e.target.value)}
                className="flex-1 min-w-[200px] bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-red-500"
              />
              {sessionUser?.provider !== 'google' && (
                <input
                  type="password"
                  placeholder="Current password"
                  aria-label="Current password"
                  value={delPw}
                  onChange={e => setDelPw(e.target.value)}
                  autoComplete="current-password"
                  className="w-48 bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-red-500"
                />
              )}
              <button
                type="submit"
                disabled={delBusy || !delEmail.trim()}
                className="btn-tactile px-3 py-1.5 rounded text-xs mono bg-red-600 text-white hover:bg-red-500 disabled:opacity-50"
              >
                {delBusy ? 'DELETING…' : 'DELETE ACCOUNT'}
              </button>
            </form>
          </div>
        </div>
      )}

      <Modal
        open={memberModalOpen}
        onClose={() => setMemberModalOpen(false)}
        title="INVITE TEAM MEMBER"
        icon={<Users size={16} className="text-accent" />}
        maxWidth="max-w-md"
      >
        <form onSubmit={handleAddMember} className="space-y-3.5 text-xs">
          <div className="space-y-1.5">
            <label htmlFor="invite-name" className="mono text-soft">FULL NAME</label>
            <input
              id="invite-name"
              type="text"
              placeholder="e.g. Fatima Bello"
              value={memberName}
              onChange={e => setMemberName(e.target.value)}
              className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="invite-email" className="mono text-soft">EMAIL (they'll get an invite link)</label>
            <input
              id="invite-email"
              type="email"
              placeholder="name@organization.ng"
              value={memberEmail}
              onChange={e => setMemberEmail(e.target.value)}
              required
              className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="invite-role" className="mono text-soft">ROLE</label>
            <select
              id="invite-role"
              value={memberRole}
              onChange={e => setMemberRole(e.target.value)}
              className="app-form-control w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            >
              <option value="member">member — view & review</option>
              <option value="admin">admin — manage scans & members</option>
              <option value="owner">owner — full control</option>
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-line">
            <button
              type="button"
              onClick={() => setMemberModalOpen(false)}
              className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              {...writeGuard(suspended, addingMember)}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
            >
              {addingMember ? <RefreshCw size={12} className="animate-spin" /> : null}
              Invite Member
            </button>
          </div>
        </form>
      </Modal>

      <BoardReportModal
        open={summaryModalOpen}
        onClose={() => setSummaryModalOpen(false)}
        loading={summaryLoading}
        summary={execSummary}
      />

      {/* TOTP QR code — fitted or moderate */}
      <Modal
        open={qrOpen}
        onClose={() => setQrOpen(false)}
        title="SCAN WITH YOUR AUTHENTICATOR APP"
        maxWidth={qrSize === 'fitted' ? 'max-w-xs' : 'max-w-sm'}
      >
        <div className="flex flex-col items-center gap-3 py-2">
          <div className="flex rounded border border-line overflow-hidden text-[11px] mono">
            {(['fitted', 'moderate'] as const).map(s => (
              <button
                key={s}
                type="button"
                onClick={() => setQrSize(s)}
                className={`px-3 py-1 uppercase tracking-wider transition-colors ${
                  qrSize === s ? 'bg-accent text-white' : 'text-soft hover:text-ink'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
          {totpUrl && (
            <div className="p-3 rounded bg-white border border-line">
              <QRCodeSVG value={totpUrl} size={qrSize === 'fitted' ? 200 : 280} />
            </div>
          )}
          <p className="text-[11px] mono text-soft text-center">
            Point Google Authenticator at this code, then confirm with a 6-digit code.
          </p>
        </div>
      </Modal>
    </div>
  );
}
