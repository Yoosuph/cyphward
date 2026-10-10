import { useEffect, useState } from 'react';
import {
  Building,
  Users,
  Key,
  RefreshCw,
  Plus,
  Sparkles,
  Check,
} from 'lucide-react';
import { getSettings, updateCompanyProfile, addTeamMember, updateMemberRole, getExecutiveSummary, mfaStatus, mfaEnroll, mfaDisableRequest, mfaDisableConfirm, exportOrganization, closeOrganization, getSubscription, setSubscriptionPlan, renewSubscription, cancelSubscription, listInvoices, deleteOwnAccount, totpEnrollStart, totpEnrollConfirm, totpDisable } from '../lib/api';
import { useAuth } from '../lib/auth';
import type { SettingsData, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';
import { SettingsSkeleton } from '../components/Skeleton';
import Modal from '../components/Modal';
import BoardReportModal from '../components/BoardReportModal';
import { QRCodeSVG } from 'qrcode.react';

type SettingsTab = 'general' | 'team' | 'auth';

export default function Settings() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');

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
  const [delEmail, setDelEmail] = useState('');
  const [delPw, setDelPw] = useState('');
  const [delBusy, setDelBusy] = useState(false);

  const handleDeleteAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!delEmail.trim()) return;
    if (!window.confirm('Permanently delete your account and all its sessions? This cannot be undone.')) return;
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
  const [newPlan, setNewPlan] = useState('growth');
  // MFA (step-up sign-in code): status + enroll/disable flows.
  const [mfa, setMfa] = useState<{ enrolled: boolean; admin_required: boolean; email_verified: boolean; totp_enrolled: boolean; totp_pending: boolean } | null>(null);
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
      setData(res);
      setCompanyName(res.organization.name);
      setCacRc(res.organization.cac_rc || '');
      setSector(res.organization.sector || '');
    } catch {
      toast('Failed to load settings');
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
    if (!window.confirm('This permanently deletes the workspace and all its data. Continue?')) return;
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
      if (sub?.subscription?.plan) setNewPlan(sub.subscription.plan);
    } catch {
      toast('Could not load billing status');
    }
  };

  const handleSetPlan = async () => {
    setBillingBusy(true);
    try {
      const res = await setSubscriptionPlan(newPlan);
      if (res?.subscription) {
        toast(`Plan set to ${newPlan} — manual billing, nothing charged`);
        await refreshBilling();
      } else {
        toast('Could not change the plan');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not change the plan');
    } finally {
      setBillingBusy(false);
    }
  };

  const handleRenew = async () => {
    setBillingBusy(true);
    try {
      const res = await renewSubscription();
      if (res?.subscription) {
        toast('Billing period extended by 30 days');
        await refreshBilling();
      } else {
        toast('Could not renew');
      }
    } catch (e: any) {
      toast(e?.message || 'Could not renew');
    } finally {
      setBillingBusy(false);
    }
  };

  const handleCancelSub = async () => {
    if (!window.confirm('Cancel the subscription at the end of the current period?')) return;
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

  if (loading || !data) {
    return <SettingsSkeleton />;
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-12 content-fade-in">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <p className="eyebrow text-accent">YOUR WORKSPACE</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            Organization Settings
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Company profile, team roles, and sign-in.
          </p>
        </div>

        <button
          onClick={handleOpenExecutiveReport}
          className="btn-tactile flex items-center justify-center gap-2 px-3.5 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink transition-colors w-full sm:w-auto min-h-[38px]"
        >
          <Sparkles size={14} className="text-accent" />
          <span>GENERATE BOARD REPORT</span>
        </button>
      </div>

      <div className="flex items-center gap-1 border-b border-line overflow-x-auto pb-px no-scrollbar">
        <button
          type="button"
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
          onClick={() => setActiveTab('auth')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'auth' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <Key size={14} />
          <span>AUTHENTICATION</span>
        </button>
      </div>

      {activeTab === 'general' && (
        <div className="space-y-6">
          <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-line">
              <Building size={16} className="text-accent" />
              <h3 className="mono font-semibold text-ink text-sm">COMPANY PROFILE</h3>
            </div>

            <form onSubmit={handleSaveCompany} className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="mono text-soft text-[11px]">COMPANY NAME</label>
                  <input
                    type="text"
                    value={companyName}
                    onChange={e => setCompanyName(e.target.value)}
                    required
                    className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="mono text-soft text-[11px]">CORPORATE AFFAIRS COMMISSION (CAC RC)</label>
                  <input
                    type="text"
                    value={cacRc}
                    onChange={e => setCacRc(e.target.value)}
                    placeholder="e.g. RC-1849204"
                    className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="mono text-soft text-[11px]">INDUSTRY SECTOR</label>
                  <input
                    type="text"
                    value={sector}
                    onChange={e => setSector(e.target.value)}
                    placeholder="e.g. Fintech & Digital Commerce"
                    className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="mono text-soft text-[11px]">YOUR ROLE</label>
                  <div className="flex items-center gap-2 p-2 rounded bg-inset border border-line mono">
                    <span className="tag">{myRole.toUpperCase()}</span>
                    <span className="text-soft text-[11px] ml-auto">{data.membership?.user_id ? 'Linked to signed-in user' : ''}</span>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="mono text-soft text-[11px]">YOUR PLAN</label>
                  <div className="flex items-center gap-2 p-2 rounded bg-inset/50 border border-line/60 mono text-soft">
                    <span className="text-ink font-semibold">{data.organization.plan || 'Enterprise Defense'}</span>
                    <span className="tag ml-auto">ALWAYS ON</span>
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  disabled={savingCompany}
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
              <h3 className="mono font-semibold text-ink text-sm">BILLING</h3>
              <span className="tag ml-auto">MANUAL — NOTHING IS CHARGED</span>
            </div>
            {billing ? (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mono">
                  <div className="p-2 rounded bg-inset border border-line">
                    <div className="text-soft text-[10px]">PLAN</div>
                    <div className="text-ink font-semibold capitalize">{billing.entitlements?.plan || '—'}</div>
                  </div>
                  <div className="p-2 rounded bg-inset border border-line">
                    <div className="text-soft text-[10px]">STATUS</div>
                    <div className="text-ink font-semibold uppercase">{billing.effective_status || 'none'}</div>
                  </div>
                  <div className="p-2 rounded bg-inset border border-line col-span-2">
                    <div className="text-soft text-[10px]">CURRENT PERIOD ENDS</div>
                    <div className="text-ink font-semibold">{billing.subscription?.current_period_end ? new Date(billing.subscription.current_period_end).toLocaleDateString() : '—'}</div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={newPlan}
                    onChange={e => setNewPlan(e.target.value)}
                    className="bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="starter">Starter — ₦7,000/mo</option>
                    <option value="growth">Growth — ₦15,000/mo</option>
                  </select>
                  <button
                    type="button"
                    onClick={handleSetPlan}
                    disabled={billingBusy}
                    className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink disabled:opacity-50"
                  >
                    {billingBusy ? 'SAVING…' : 'SET PLAN'}
                  </button>
                  <button
                    type="button"
                    onClick={handleRenew}
                    disabled={billingBusy || !billing.subscription}
                    className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink disabled:opacity-50"
                  >
                    RENEW 30 DAYS
                  </button>
                  <button
                    type="button"
                    onClick={handleCancelSub}
                    disabled={billingBusy || !billing.subscription || billing.subscription?.cancel_at_period_end}
                    className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink disabled:opacity-50"
                  >
                    {billing.subscription?.cancel_at_period_end ? 'CANCELS AT PERIOD END' : 'CANCEL'}
                  </button>
                </div>
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
              <h3 className="mono font-semibold text-ink text-sm">DATA & CLOSURE</h3>
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
                value={closeSlug}
                onChange={e => setCloseSlug(e.target.value)}
                className="bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-red-500"
              />
              <button
                type="submit"
                disabled={closeBusy || !closeSlug.trim()}
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
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-line">
            <div className="flex items-center gap-2">
              <Users size={16} className="text-accent" />
              <h3 className="mono font-semibold text-ink text-sm">TEAM & ROLES</h3>
            </div>
            {canManageRoles && (
              <button
                onClick={() => setMemberModalOpen(true)}
                className="btn-tactile flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 transition-opacity"
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
                          disabled={roleBusyId === m.id}
                          onChange={e => handleRoleChange(m.id, e.target.value)}
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
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-line">
            <Key size={16} className="text-accent" />
            <h3 className="mono font-semibold text-ink text-sm">AUTHENTICATION</h3>
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
              <h4 className="mono font-semibold text-ink text-xs">STEP-UP SIGN-IN CODE</h4>
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
                ? 'Owner and admin accounts always confirm sign-in with a 6-digit code sent to their email.'
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
            {!mfa?.admin_required && mfa?.enrolled && mfaCodeSent && (
              <form onSubmit={handleMfaDisableConfirm} className="flex items-center gap-2">
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="123456"
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
              <h4 className="mono font-semibold text-ink text-xs">AUTHENTICATOR APP</h4>
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
            <h4 className="mono font-semibold text-ink text-xs">DELETE MY ACCOUNT</h4>
            <p className="text-xs text-soft mono leading-relaxed">
              Removes your profile, sessions and memberships. Blocked while you solely own a
              workspace — transfer ownership or close it first.
            </p>
            <form onSubmit={handleDeleteAccount} className="flex flex-wrap items-center gap-2">
              <input
                type="email"
                placeholder={sessionUser?.email || 'you@example.com'}
                value={delEmail}
                onChange={e => setDelEmail(e.target.value)}
                className="flex-1 min-w-[200px] bg-inset border border-line rounded px-3 py-1.5 text-ink mono text-xs focus:outline-none focus:border-red-500"
              />
              {sessionUser?.provider !== 'google' && (
                <input
                  type="password"
                  placeholder="Current password"
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
            <label className="mono text-soft">FULL NAME</label>
            <input
              type="text"
              placeholder="e.g. Fatima Bello"
              value={memberName}
              onChange={e => setMemberName(e.target.value)}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-1.5">
            <label className="mono text-soft">EMAIL (they'll get an invite link)</label>
            <input
              type="email"
              placeholder="name@organization.ng"
              value={memberEmail}
              onChange={e => setMemberEmail(e.target.value)}
              required
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-1.5">
            <label className="mono text-soft">ROLE</label>
            <select
              value={memberRole}
              onChange={e => setMemberRole(e.target.value)}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
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
              disabled={addingMember}
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
