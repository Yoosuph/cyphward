import { useEffect, useState } from 'react';
import {
  Globe,
  Plus,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Copy,
  Check,
  RefreshCw,
  Trash2,
  Lock,
  ExternalLink,
  ShieldCheck,
  Server,
  X,
} from 'lucide-react';
import { getDomains, addDomain, verifyDomain, deleteDomain } from '../lib/api';
import type { Domain } from '../types';
import { useToast } from '../components/Toast';
import { DomainsSkeleton, TableRowSkeleton } from '../components/Skeleton';
import Modal from '../components/Modal';

const STATUS_LABEL: Record<string, string> = {
  verified: 'Verified',
  pending: 'Waiting for DNS',
  expired: 'Expired',
  revoked: 'Revoked',
  failed: 'Waiting for DNS',
};

const statusLabel = (status: string) => STATUS_LABEL[status] || status;

export default function Domains() {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(true);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newDomainInput, setNewDomainInput] = useState('');
  const [adding, setAdding] = useState(false);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // "How to verify" modal — DNS steps + inline check result
  const [instructionModal, setInstructionModal] = useState<Domain | null>(null);
  const [modalCheck, setModalCheck] = useState<'idle' | 'checking' | 'failed' | 'verified'>('idle');

  const toast = useToast();

  const loadDomains = async () => {
    setLoading(true);
    try {
      const list = await getDomains();
      setDomains(list);
    } catch (e) {
      toast('Failed to load domains');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDomains();
  }, []);

  const handleAddDomain = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDomainInput.trim()) return;

    setAdding(true);
    try {
      const res = await addDomain(newDomainInput.trim());
      toast('Domain added. Follow the steps to verify it.');
      setAddModalOpen(false);
      setNewDomainInput('');
      setModalCheck('idle');
      setInstructionModal(res.domain);
      await loadDomains();
    } catch (err: any) {
      toast(err.message || 'Failed to add domain');
    } finally {
      setAdding(false);
    }
  };

  const openInstructions = (dom: Domain) => {
    setModalCheck('idle');
    setInstructionModal(dom);
  };

  const handleVerify = async (domain: Domain, fromModal = false) => {
    setVerifyingId(domain.id);
    if (fromModal) setModalCheck('checking');
    try {
      const res = await verifyDomain(domain.id);
      if (res.status === 'verified') {
        toast(`${domain.domain} is verified.`);
        if (fromModal) {
          setModalCheck('verified');
          window.setTimeout(() => {
            setInstructionModal(null);
            loadDomains();
          }, 900);
        } else {
          await loadDomains();
        }
      } else {
        if (fromModal) {
          setModalCheck('failed');
        } else {
          // Record not visible yet — send the user straight to the setup steps.
          toast(`We can't find the DNS record for ${domain.domain} yet.`);
          setModalCheck('failed');
          setInstructionModal(domain);
        }
        await loadDomains();
      }
    } catch (err: any) {
      toast(err.message || 'Could not check right now. Please try again.');
      if (fromModal) setModalCheck('failed');
    } finally {
      setVerifyingId(null);
    }
  };

  const handleDelete = async (domainId: string, name: string) => {
    if (!confirm(`Remove ${name}? We will stop scanning it.`)) return;
    try {
      await deleteDomain(domainId);
      toast(`${name} removed.`);
      await loadDomains();
    } catch (e) {
      toast('Failed to delete domain');
    }
  };

  const copyText = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedToken(id);
    setTimeout(() => setCopiedToken(null), 2000);
    toast('Record value copied.');
  };

  if (loading && domains.length === 0) {
    return <DomainsSkeleton />;
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <p className="eyebrow text-accent">YOUR DOMAINS</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            Domains
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Add the domains you want to monitor, prove they're yours, and we'll start scanning them.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-2.5 w-full sm:w-auto">
          <button
            onClick={loadDomains}
            className="btn-tactile flex items-center justify-center gap-1.5 px-3 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong text-ink transition-colors min-h-[38px]"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>

          <button
            onClick={() => setAddModalOpen(true)}
            className="btn-tactile flex items-center justify-center gap-2 px-4 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 shadow-md shadow-accent/20 transition-all min-h-[38px]"
          >
            <Plus size={14} />
            <span>ADD DOMAIN</span>
          </button>
        </div>
      </div>

      {/* Security Scope Banner */}
      <div className="p-4 rounded-lg bg-inset/40 border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs mono">
        <div className="flex items-center gap-3">
          <ShieldCheck size={20} className="text-ok shrink-0" />
          <div>
            <span className="font-bold text-ink">We only scan domains you own.</span>
            <p className="text-soft text-[11.5px] mt-0.5">
              Before we scan a site, you add a one-time DNS record to prove it's yours. This stops anyone — including us — from scanning domains you don't control.
            </p>
          </div>
        </div>
        <span className="text-[11px] text-accent bg-accent-soft px-2.5 py-1 rounded border border-accent/20 shrink-0 self-start sm:self-center">
          Ownership-verified scanning
        </span>
      </div>

      {/* Domains Table */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="p-4 border-b border-line bg-inset/30 flex items-center justify-between">
          <h3 className="mono text-xs font-bold text-ink uppercase tracking-wider">
            YOUR DOMAINS
          </h3>
          <span className="text-[11px] mono text-soft">{domains.length} domains</span>
        </div>

        <div className="overflow-x-auto w-full max-w-full">
          <table className="w-full text-left text-xs mono min-w-[620px]">
            <thead>
              <tr className="border-b border-line bg-inset/40 text-soft text-[11px]">
                <th className="py-3 px-4 font-medium">DOMAIN NAME</th>
                <th className="py-3 px-4 font-medium">STATUS</th>
                <th className="py-3 px-4 font-medium">VERIFICATION RECORD</th>
                <th className="py-3 px-4 font-medium">VERIFIED ON</th>
                <th className="py-3 px-4 font-medium">ASSETS FOUND</th>
                <th className="py-3 px-4 font-medium text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <TableRowSkeleton
                    key={i}
                    cols={[150, 95, 220, 90, 60, 110]}
                  />
                ))
              ) : domains.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-soft mono">
                    No domains yet. Click 'Add domain' to get started.
                  </td>
                </tr>
              ) : (
                domains.map((dom, idx) => (
                  <tr
                    key={dom.id}
                    style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
                    className="stagger-row hover:bg-inset/40 transition-colors"
                  >
                    <td className="py-3 px-4 font-bold text-ink">
                      <div className="flex items-center gap-2">
                        <Globe size={14} className="text-accent" />
                        <span>{dom.domain}</span>
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold inline-flex items-center gap-1 ${
                          dom.verification_status === 'verified'
                            ? 'bg-ok/15 text-ok border border-ok/30'
                            : dom.verification_status === 'failed'
                            ? 'bg-accent/15 text-accent border border-accent/30'
                            : 'bg-amber-500/15 text-amber-500 border border-amber-500/30'
                        }`}
                      >
                        {dom.verification_status === 'verified' ? (
                          <CheckCircle2 size={11} />
                        ) : (
                          <Clock size={11} />
                        )}
                        {statusLabel(dom.verification_status)}
                      </span>
                    </td>

                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5 max-w-xs">
                        <code className="text-[11px] text-soft bg-inset px-2 py-0.5 rounded border border-line truncate">
                          cyphward-verification={dom.verification_token}
                        </code>
                        <button
                          onClick={() => copyText(`cyphward-verification=${dom.verification_token}`, dom.id)}
                          className="btn-tactile p-1 hover:text-accent text-soft shrink-0"
                          title="Copy verification TXT value"
                        >
                          {copiedToken === dom.id ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                        </button>
                      </div>
                    </td>

                    <td className="py-3 px-4 text-soft text-[11px]">
                      {dom.verified_at
                        ? new Date(dom.verified_at).toLocaleDateString([], {
                            day: 'numeric',
                            month: 'short',
                            year: 'numeric',
                          })
                        : 'Not yet'}
                    </td>

                    <td className="py-3 px-4 font-semibold text-ink">
                      {dom.asset_count !== undefined ? `${dom.asset_count} assets` : '—'}
                    </td>

                    <td className="py-3 px-4 text-right space-x-2">
                      <button
                        disabled={verifyingId === dom.id}
                        onClick={() => handleVerify(dom)}
                        className={`btn-tactile px-2.5 py-1 rounded text-[11px] border font-medium transition-colors ${
                          dom.verification_status === 'verified'
                            ? 'border-line bg-raised hover:bg-inset text-soft'
                            : 'bg-ok/20 border-ok text-ok hover:bg-ok/30'
                        }`}
                      >
                        {verifyingId === dom.id ? (
                          <span className="flex items-center gap-1">
                            <RefreshCw size={10} className="animate-spin" /> Checking…
                          </span>
                        ) : dom.verification_status === 'verified' ? (
                          'Check again'
                        ) : (
                          'Check now'
                        )}
                      </button>

                      <button
                        onClick={() => openInstructions(dom)}
                        className="btn-tactile p-1 rounded hover:bg-inset text-soft hover:text-ink"
                        title="How to verify"
                      >
                        <ExternalLink size={13} />
                      </button>

                      <button
                        onClick={() => handleDelete(dom.id, dom.domain)}
                        className="btn-tactile p-1 rounded hover:bg-accent-soft text-soft hover:text-accent"
                        title="Remove domain"
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Domain Modal */}
      <Modal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        title="ADD A DOMAIN"
        icon={<Globe size={16} className="text-accent" />}
        maxWidth="max-w-md"
      >
        <form onSubmit={handleAddDomain} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs mono text-soft">DOMAIN NAME</label>
            <input
              type="text"
              placeholder="e.g. acmetraders.ng or corp.company.com"
              value={newDomainInput}
              onChange={e => setNewDomainInput(e.target.value)}
              autoFocus
              required
              className="w-full bg-inset border border-line rounded px-3 py-2 text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
            />
          </div>

          <div className="p-3 bg-inset/50 rounded border border-line text-[11px] mono text-soft space-y-1">
            <span className="font-semibold text-ink block">You'll verify it next</span>
            <p>
              After adding the domain, we'll show you a one-time DNS record to publish. This proves the domain is yours before scanning starts.
            </p>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={() => setAddModalOpen(false)}
              className="btn-tactile px-3.5 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={adding || !newDomainInput.trim()}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            >
              {adding ? (
                <>
                  <RefreshCw size={13} className="animate-spin" /> Adding...
                </>
              ) : (
                'Add domain'
              )}
            </button>
          </div>
        </form>
      </Modal>

      {/* How to verify — DNS steps + inline check */}
      <Modal
        open={Boolean(instructionModal)}
        onClose={() => setInstructionModal(null)}
        title="HOW TO VERIFY YOUR DOMAIN"
        icon={<ShieldCheck size={16} className="text-ok" />}
        maxWidth="max-w-lg"
      >
        {instructionModal && (
          <div className="space-y-4">
            <p className="text-xs text-soft leading-relaxed">
              Prove you own <strong className="text-ink">{instructionModal.domain}</strong> by adding
              a TXT record in your DNS settings (Cloudflare, GoDaddy, Namecheap, etc.):
            </p>

            <ol className="space-y-1.5 text-xs text-soft list-decimal list-inside">
              <li>Open the DNS settings for {instructionModal.domain}.</li>
              <li>Add a new TXT record with the values below.</li>
              <li>Save, then give it a few minutes to go live.</li>
            </ol>

            <div className="p-3.5 rounded bg-inset border border-line font-mono text-[11px] space-y-2">
              <div className="flex justify-between">
                <span className="text-soft">Record type</span>
                <span className="text-ink font-bold">TXT</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-soft">Name / Host</span>
                <span className="text-ink font-bold break-all">_cyphward</span>
              </div>
              <div className="flex flex-col gap-1 pt-1 border-t border-line">
                <span className="text-soft">Value</span>
                <div className="p-2 bg-raised rounded border border-line flex items-center justify-between gap-2 text-ink">
                  <code className="text-accent break-all">
                    cyphward-verification={instructionModal.verification_token}
                  </code>
                  <button
                    onClick={() =>
                      copyText(
                        `cyphward-verification=${instructionModal.verification_token}`,
                        'modal'
                      )
                    }
                    className="btn-tactile p-1 hover:text-accent text-soft shrink-0"
                  >
                    {copiedToken === 'modal' ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                  </button>
                </div>
              </div>
              <p className="text-soft text-[10px] pt-1 border-t border-line">
                Enter only "_cyphward" in the Name/Host field — your DNS panel adds the domain
                itself, so the record resolves at _cyphward.{instructionModal.domain}.
              </p>
            </div>

            {modalCheck === 'failed' && (
              <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-500 flex items-start gap-2">
                <AlertTriangle size={14} className="flex-none mt-0.5" />
                <span>
                  We can't see the record yet. If you just added it, wait a few minutes and check
                  again — DNS changes sometimes take up to an hour.
                </span>
              </div>
            )}

            {modalCheck === 'verified' && (
              <div className="p-3 bg-ok/10 border border-ok/30 rounded text-xs text-ok flex items-center gap-2">
                <CheckCircle2 size={14} className="flex-none" />
                <span>Domain verified! Updating your dashboard…</span>
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setInstructionModal(null)}
                className="btn-tactile px-4 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft"
              >
                Close
              </button>
              <button
                onClick={() => handleVerify(instructionModal, true)}
                disabled={modalCheck === 'checking' || modalCheck === 'verified'}
                className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
              >
                {modalCheck === 'checking' ? (
                  <>
                    <RefreshCw size={13} className="animate-spin" /> Checking…
                  </>
                ) : (
                  'Check now'
                )}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
