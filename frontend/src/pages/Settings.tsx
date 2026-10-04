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
import { getSettings, updateCompanyProfile, addTeamMember, updateMemberRole, getExecutiveSummary, mfaStatus, mfaEnroll, mfaDisableRequest, mfaDisableConfirm, exportOrganization, closeOrganization } from '../lib/api';
import type { SettingsData, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';
import { SettingsSkeleton } from '../components/Skeleton';
import Modal from '../components/Modal';
import BoardReportModal from '../components/BoardReportModal';

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

  // Workspace export + closure (owner-only danger zone).
  const [exportBusy, setExportBusy] = useState(false);
  const [closeSlug, setCloseSlug] = useState('');
  const [closeBusy, setCloseBusy] = useState(false);
  // MFA (step-up sign-in code): status + enroll/disable flows.
  const [mfa, setMfa] = useState<{ enrolled: boolean; admin_required: boolean; email_verified: boolean } | null>(null);
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
    </div>
  );
}
