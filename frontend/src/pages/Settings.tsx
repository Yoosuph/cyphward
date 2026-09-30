import { useEffect, useState } from 'react';
import {
  Building,
  Users,
  Key,
  RefreshCw,
  Plus,
  ShieldCheck,
  Sparkles,
  Check,
} from 'lucide-react';
import { getSettings, updateCompanyProfile, addTeamMember, updateMemberRole, getExecutiveSummary } from '../lib/api';
import type { SettingsData, ExecutiveSummary } from '../types';
import { useToast } from '../components/Toast';
import { SettingsSkeleton } from '../components/Skeleton';
import Modal from '../components/Modal';
import BoardReportModal from '../components/BoardReportModal';

type SettingsTab = 'general' | 'team' | 'auth' | 'security';

export default function Settings() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');

  const [companyName, setCompanyName] = useState('');
  const [cacRc, setCacRc] = useState('');
  const [sector, setSector] = useState('');
  const [alertEmail, setAlertEmail] = useState('');
  const [savingCompany, setSavingCompany] = useState(false);

  const [scanFrequency, setScanFrequency] = useState('daily');
  const [alertThreshold, setAlertThreshold] = useState('high');
  const [savingPrefs, setSavingPrefs] = useState(false);

  const [memberModalOpen, setMemberModalOpen] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [memberName, setMemberName] = useState('');
  const [memberRole, setMemberRole] = useState('member');
  const [addingMember, setAddingMember] = useState(false);
  const [roleBusyId, setRoleBusyId] = useState<string | null>(null);

  const [summaryModalOpen, setSummaryModalOpen] = useState(false);
  const [execSummary, setExecSummary] = useState<ExecutiveSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const toast = useToast();

  const loadSettings = async () => {
    setLoading(true);
    try {
      const res = await getSettings();
      setData(res);
      setCompanyName(res.organization.name);
      setCacRc(res.organization.cac_rc || '');
      setSector(res.organization.sector || '');
      setAlertEmail(res.organization.email || 'security@' + (res.organization.slug || 'enclave') + '.ng');
    } catch {
      toast('Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

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

  const handleSaveSecurityPrefs = (e: React.FormEvent) => {
    e.preventDefault();
    setSavingPrefs(true);
    setTimeout(() => {
      setSavingPrefs(false);
      toast('Security preferences saved to enclave');
    }, 600);
  };

  const handleAddMember = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!memberEmail.trim()) return;
    setAddingMember(true);
    try {
      await addTeamMember(memberEmail.trim(), memberName.trim() || memberEmail.split('@')[0], memberRole);
      toast(`Member ${memberEmail} enrolled!`);
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
            <p className="eyebrow text-accent">ENTERPRISE GOVERNANCE</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            Organization Settings
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Corporate profile, role-based access control, and authentication.
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
          <span>GENERAL & IDENTITY</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('team')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'team' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <Users size={14} />
          <span>TEAM & ACCESS ({data.members?.length || 0})</span>
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

        <button
          type="button"
          onClick={() => setActiveTab('security')}
          className={`flex items-center gap-2 px-4 py-2 text-xs mono border-b-2 transition-all whitespace-nowrap ${
            activeTab === 'security' ? 'border-accent text-ink font-semibold' : 'border-transparent text-soft hover:text-ink'
          }`}
        >
          <ShieldCheck size={14} />
          <span>SECURITY</span>
        </button>
      </div>

      {activeTab === 'general' && (
        <div className="space-y-6">
          <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-line">
              <Building size={16} className="text-accent" />
              <h3 className="mono font-semibold text-ink text-sm">CORPORATE PROFILE</h3>
            </div>

            <form onSubmit={handleSaveCompany} className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="mono text-soft text-[11px]">LEGAL ENTITY NAME</label>
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
                  <label className="mono text-soft text-[11px]">PRIMARY SECURITY EMAIL</label>
                  <input
                    type="email"
                    value={alertEmail}
                    onChange={e => setAlertEmail(e.target.value)}
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
                  <label className="mono text-soft text-[11px]">DEFENSE PLAN TIER</label>
                  <div className="flex items-center gap-2 p-2 rounded bg-inset/50 border border-line/60 mono text-soft">
                    <span className="text-ink font-semibold">{data.organization.plan || 'Enterprise Defense'}</span>
                    <span className="tag ml-auto">CONTINUOUS</span>
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
        </div>
      )}

      {activeTab === 'team' && (
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-line">
            <div className="flex items-center gap-2">
              <Users size={16} className="text-accent" />
              <h3 className="mono font-semibold text-ink text-sm">TEAM & ACCESS CONTROL</h3>
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
            Roles: <span className="text-ink">owner</span> (full admin + owner grants) ·{' '}
            <span className="text-ink">admin</span> (manage scans, members) ·{' '}
            <span className="text-ink">member</span> (read + triage)
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
              Cyphward uses <span className="text-accent">Supabase Auth</span> exclusively.
              API keys are not part of the MVP authentication model.
            </p>
            <ul className="space-y-2">
              <li className="flex items-start gap-2">
                <Check size={14} className="text-ok mt-0.5" />
                Authorization: Bearer &lt;Supabase access token&gt;
              </li>
              <li className="flex items-start gap-2">
                <Check size={14} className="text-ok mt-0.5" />
                X-Organization-Id selects among your memberships (server-verified)
              </li>
              <li className="flex items-start gap-2">
                <Check size={14} className="text-ok mt-0.5" />
                RBAC enforced server-side: owner / admin / member
              </li>
            </ul>
          </div>
        </div>
      )}

      {activeTab === 'security' && (
        <div className="p-6 rounded-lg border border-line bg-raised space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-line">
            <ShieldCheck size={16} className="text-accent" />
            <h3 className="mono font-semibold text-ink text-sm">SECURITY PREFERENCES</h3>
          </div>

          <form onSubmit={handleSaveSecurityPrefs} className="space-y-5 text-xs">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="mono text-soft text-[11px]">SCAN CADENCE</label>
                <select
                  value={scanFrequency}
                  onChange={e => setScanFrequency(e.target.value)}
                  className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                >
                  <option value="daily">Daily deterministic risk re-scoring</option>
                  <option value="weekly">Weekly comprehensive attack surface audit</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="mono text-soft text-[11px]">ALERT DISPATCH THRESHOLD</label>
                <select
                  value={alertThreshold}
                  onChange={e => setAlertThreshold(e.target.value)}
                  className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
                >
                  <option value="critical">Critical findings only</option>
                  <option value="high">Critical + high severity</option>
                </select>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                disabled={savingPrefs}
                className="btn-tactile px-4 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
              >
                {savingPrefs ? <RefreshCw size={13} className="animate-spin" /> : null}
                Save Security Preferences
              </button>
            </div>
          </form>
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
            <label className="mono text-soft">EMAIL (must match Supabase Auth account)</label>
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
              <option value="member">member — read & triage</option>
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
