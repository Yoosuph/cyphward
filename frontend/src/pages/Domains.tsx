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

export default function Domains() {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(true);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newDomainInput, setNewDomainInput] = useState('');
  const [adding, setAdding] = useState(false);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // Verification instruction modal state
  const [instructionModal, setInstructionModal] = useState<{
    domain: Domain;
    dns_instructions?: any;
  } | null>(null);

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
      toast('Domain added! DNS TXT token generated.');
      setAddModalOpen(false);
      setNewDomainInput('');
      setInstructionModal({
        domain: res.domain,
        dns_instructions: res.dns_instructions,
      });
      await loadDomains();
    } catch (err: any) {
      toast(err.message || 'Failed to add domain');
    } finally {
      setAdding(false);
    }
  };

  const handleVerify = async (domain: Domain) => {
    setVerifyingId(domain.id);
    try {
      const res = await verifyDomain(domain.id);
      if (res.status === 'verified') {
        toast(`Domain ${domain.domain} verified successfully!`);
      } else {
        toast(`DNS TXT verification failed for ${domain.domain}. Expected record cyphward-verification=${domain.verification_token} not yet detected.`);
      }
      await loadDomains();
    } catch (err: any) {
      toast(err.message || 'Verification error');
    } finally {
      setVerifyingId(null);
    }
  };

  const handleDelete = async (domainId: string, name: string) => {
    if (!confirm(`Are you sure you want to remove domain ${name}?`)) return;
    try {
      await deleteDomain(domainId);
      toast(`Domain ${name} removed`);
      await loadDomains();
    } catch (e) {
      toast('Failed to delete domain');
    }
  };

  const copyText = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedToken(id);
    setTimeout(() => setCopiedToken(null), 2000);
    toast('Token copied to clipboard');
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
            <p className="eyebrow text-accent">INFRASTRUCTURE GOVERNANCE</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            Domain Verification & Enclave Assets
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Prove authoritative ownership via DNS TXT cryptographic challenges before enabling attack surface scanning.
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
            <span className="font-bold text-ink">Zero-Trust Perimeter Rule:</span>
            <p className="text-soft text-[11.5px] mt-0.5">
              To prevent unauthorized reconnaissance, scanning is only permitted on domains possessing a validated DNS TXT token.
            </p>
          </div>
        </div>
        <span className="text-[11px] text-accent bg-accent-soft px-2.5 py-1 rounded border border-accent/20 shrink-0 self-start sm:self-center">
          NDPA 2023 Compliant
        </span>
      </div>

      {/* Domains Table */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="p-4 border-b border-line bg-inset/30 flex items-center justify-between">
          <h3 className="mono text-xs font-bold text-ink uppercase tracking-wider">
            REGISTERED DOMAIN LEDGER
          </h3>
          <span className="text-[11px] mono text-soft">{domains.length} domains</span>
        </div>

        <div className="overflow-x-auto w-full max-w-full">
          <table className="w-full text-left text-xs mono min-w-[620px]">
            <thead>
              <tr className="border-b border-line bg-inset/40 text-soft text-[11px]">
                <th className="py-3 px-4 font-medium">DOMAIN NAME</th>
                <th className="py-3 px-4 font-medium">VERIFICATION STATUS</th>
                <th className="py-3 px-4 font-medium">DNS TXT TOKEN</th>
                <th className="py-3 px-4 font-medium">VERIFIED AT</th>
                <th className="py-3 px-4 font-medium">ASSETS</th>
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
                    No domains configured. Click "ADD DOMAIN" above to begin.
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
                        {dom.verification_status}
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
                        : 'Unverified'}
                    </td>

                    <td className="py-3 px-4 font-semibold text-ink">
                      {dom.asset_count !== undefined ? `${dom.asset_count} hosts` : '—'}
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
                            <RefreshCw size={10} className="animate-spin" /> Checking
                          </span>
                        ) : dom.verification_status === 'verified' ? (
                          'Re-verify'
                        ) : (
                          'Verify DNS'
                        )}
                      </button>

                      <button
                        onClick={() =>
                          setInstructionModal({
                            domain: dom,
                            dns_instructions: {
                              record_type: 'TXT',
                              host: `@ or ${dom.domain}`,
                              value: `cyphward-verification=${dom.verification_token}`,
                              ttl: 300,
                            },
                          })
                        }
                        className="btn-tactile p-1 rounded hover:bg-inset text-soft hover:text-ink"
                        title="View Setup Instructions"
                      >
                        <ExternalLink size={13} />
                      </button>

                      <button
                        onClick={() => handleDelete(dom.id, dom.domain)}
                        className="btn-tactile p-1 rounded hover:bg-accent-soft text-soft hover:text-accent"
                        title="Delete Domain"
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
        title="ADD ENTERPRISE DOMAIN"
        icon={<Globe size={16} className="text-accent" />}
        maxWidth="max-w-md"
      >
        <form onSubmit={handleAddDomain} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs mono text-soft">ROOT APEX DOMAIN OR SUBDOMAIN</label>
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
            <span className="font-semibold text-ink block">DNS Verification Required</span>
            <p>
              A unique cryptographic TXT token will be generated. You must publish this record in your authoritative DNS zone to unlock automated scanning.
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
                'Generate Token'
              )}
            </button>
          </div>
        </form>
      </Modal>

      {/* DNS Setup Instructions Modal */}
      <Modal
        open={Boolean(instructionModal)}
        onClose={() => setInstructionModal(null)}
        title="DNS TXT VERIFICATION RECORD"
        icon={<ShieldCheck size={16} className="text-ok" />}
        maxWidth="max-w-lg"
      >
        {instructionModal && (
          <div className="space-y-4">
            <p className="text-xs text-soft leading-relaxed">
              Add the following TXT record to your authoritative DNS zone (Cloudflare, Route 53, Namecheap, etc.) to prove ownership of{' '}
              <strong className="text-ink">{instructionModal.domain.domain}</strong>:
            </p>

            <div className="p-3.5 rounded bg-black text-emerald-400 font-mono text-[11px] space-y-2 border border-line">
              <div className="flex justify-between">
                <span className="text-soft">Record Type:</span>
                <span className="text-white font-bold">TXT</span>
              </div>
              <div className="flex justify-between">
                <span className="text-soft">Host / Name:</span>
                <span className="text-white font-bold">@ (or {instructionModal.domain.domain})</span>
              </div>
              <div className="flex flex-col gap-1 pt-1 border-t border-line/50">
                <span className="text-soft">TXT Value:</span>
                <div className="p-2 bg-inset/80 rounded flex items-center justify-between gap-2 text-ink">
                  <code className="text-emerald-300 break-all">
                    cyphward-verification={instructionModal.domain.verification_token}
                  </code>
                  <button
                    onClick={() =>
                      copyText(
                        `cyphward-verification=${instructionModal.domain.verification_token}`,
                        'modal'
                      )
                    }
                    className="btn-tactile p-1 hover:text-accent text-soft shrink-0"
                  >
                    {copiedToken === 'modal' ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                  </button>
                </div>
              </div>
              <div className="flex justify-between pt-1">
                <span className="text-soft">TTL:</span>
                <span className="text-white font-bold">300 (or Auto)</span>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setInstructionModal(null)}
                className="btn-tactile px-4 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft"
              >
                Close
              </button>
              <button
                onClick={() => {
                  const domToVerify = instructionModal.domain;
                  setInstructionModal(null);
                  handleVerify(domToVerify);
                }}
                className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90"
              >
                Verify Now
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
