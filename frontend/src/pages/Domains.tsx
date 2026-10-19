import { useEffect, useState } from 'react';
import { PageHead } from '../components/ui';
import { useConfirm } from '../components/ConfirmDialog';
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
import { getDomainsStrict, addDomain, verifyDomain, deleteDomain, listMonitoredHosts, addMonitoredHost, removeMonitoredHost } from '../lib/api';
import type { Domain } from '../types';
import { useToast } from '../components/Toast';
import { readPageCache, writePageCache } from '../lib/pageCache';
import { DomainsSkeleton, TableRowSkeleton } from '../components/Skeleton';
import Dialog, { useDialogClose } from '../components/ui/Dialog';
import { EmptyPanel, ErrorPanel, humanError } from '../components/ui/StatePanels';
import { useOrgZone } from '../lib/orgZone';
import { fmtDayZone } from './compliance/shared';
import DomainDnsInstructions from '../components/DomainDnsInstructions';

const STATUS_LABEL: Record<string, string> = {
  verified: 'Verified',
  pending: 'Waiting for DNS',
  expired: 'Expired',
  revoked: 'Revoked',
  failed: 'Waiting for DNS',
};

const statusLabel = (status: string) => STATUS_LABEL[status] || status;

export default function Domains() {
  const confirmAction = useConfirm();
  const zone = useOrgZone();
  const [loadError, setLoadError] = useState<string | null>(null);
  // Last-seen list paints at once on a revisit; loadDomains refreshes it.
  const [domains, setDomains] = useState<Domain[]>(() => readPageCache<Domain[]>('domains') ?? []);
  const [loading, setLoading] = useState(() => readPageCache('domains') === undefined);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newDomainInput, setNewDomainInput] = useState('');
  const [adding, setAdding] = useState(false);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // "How to verify" modal — DNS steps + inline check result
  const [instructionModal, setInstructionModal] = useState<Domain | null>(null);
  const [modalCheck, setModalCheck] = useState<'idle' | 'checking' | 'failed' | 'verified'>('idle');
  // Manually monitored hosts per domain (probed every scan).
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [hostsByDomain, setHostsByDomain] = useState<Record<string, { id: string; hostname: string }[]>>({});
  const [newHost, setNewHost] = useState('');
  const [hostsBusy, setHostsBusy] = useState(false);

  const toast = useToast();

  const loadDomains = async () => {
    // The skeleton is only for a first visit; refreshes keep the list on screen.
    try {
      const list = await getDomainsStrict();
      setDomains(list);
      writePageCache('domains', list);
      setLoadError(null);
    } catch (e) {
      setLoadError(humanError(e, 'Something went wrong on our side. Try again in a moment.'));
      toast('The domain list was not refreshed.');
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
    } catch (err) {
      toast(humanError(err, 'The domain was not added. Check the name and try again.'));
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
    } catch (err) {
      toast(humanError(err, 'We could not check right now. Try again in a moment.'));
      if (fromModal) setModalCheck('failed');
    } finally {
      setVerifyingId(null);
    }
  };

  const handleDelete = async (domainId: string, name: string) => {
    if (!(await confirmAction({
      title: `Remove ${name}?`,
      body: 'Its past scans and findings stay in your history. You can add it again later, but you will need to verify it again.',
      irreversible: 'Removing it cannot be undone. Scans of this domain stop straight away.',
      confirmLabel: 'Remove domain', danger: true,
    }))) return;
    try {
      await deleteDomain(domainId);
      toast(`${name} removed.`);
      await loadDomains();
    } catch (e) {
      toast(humanError(e, 'The domain was not removed. Try again in a moment.'));
      await loadDomains();
    }
  };

  const toggleHosts = async (domainId: string) => {
    if (expandedId === domainId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(domainId);
    setNewHost('');
    try {
      const res = await listMonitoredHosts(domainId);
      setHostsByDomain(prev => ({ ...prev, [domainId]: res?.hosts || [] }));
    } catch {
      toast('We could not load the extra hosts. Try again.');
    }
  };

  const handleAddHost = async (e: React.FormEvent, domainId: string, domain: string) => {
    e.preventDefault();
    if (!newHost.trim()) return;
    setHostsBusy(true);
    try {
      const res = await addMonitoredHost(domainId, newHost.trim());
      if (res?.host) {
        setHostsByDomain(prev => ({
          ...prev,
          [domainId]: [...(prev[domainId] || []), { id: res.host.id, hostname: res.host.hostname }].sort((a, b) => a.hostname.localeCompare(b.hostname)),
        }));
        setNewHost('');
        toast(`${res.host.hostname} will be probed on every scan of ${domain}.`);
      }
    } catch (err) {
      toast(humanError(err, 'The host was not added. Check the name and try again.'));
    } finally {
      setHostsBusy(false);
    }
  };

  const handleRemoveHost = async (domainId: string, hostId: string, hostname: string) => {
    if (!(await confirmAction({
      title: `Stop checking ${hostname}?`,
      body: 'It will no longer be checked on every scan. Discovery may still find it.',
      irreversible: 'Removing it cannot be undone. You would need to add it again.',
      confirmLabel: 'Remove host', danger: true,
    }))) return;
    try {
      await removeMonitoredHost(domainId, hostId);
      setHostsByDomain(prev => ({
        ...prev,
        [domainId]: (prev[domainId] || []).filter(h => h.id !== hostId),
      }));
      toast(`${hostname} removed from monitoring.`);
    } catch {
      toast('The host was not removed. Try again in a moment.');
    }
  };

  const copyText = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedToken(id);
      setTimeout(() => setCopiedToken(null), 2000);
      toast(id === 'modal-host' ? 'Record host copied.' : 'Record value copied.');
    } catch {
      toast('Could not copy. Select the text and copy it yourself.');
    }
  };

  if (loading && domains.length === 0) {
    return <DomainsSkeleton />;
  }
  if (loadError && domains.length === 0) {
    return (
      <div className="space-y-6 max-w-7xl mx-auto pb-12">
        <PageHead title="Domains" note="Add a domain, prove you own it with one DNS record, and it is scanned every day." />
        <ErrorPanel title="We could not load your domains" message={loadError} onRetry={() => { setLoading(true); void loadDomains(); }} retrying={loading} />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">
      <PageHead
        title="Domains"
        note="Add a domain, prove you own it with one DNS record, and it is scanned every day."
        actions={<>
          <button
            onClick={loadDomains}
            className="btn-tactile flex items-center justify-center gap-1.5 px-3 py-2 rounded text-xs mono border border-line bg-raised hover:border-line-strong text-ink transition-colors min-h-[44px] sm:min-h-[38px]"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
          <button
            onClick={() => setAddModalOpen(true)}
            className="btn-tactile flex items-center justify-center gap-2 px-4 py-2 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 shadow-md shadow-accent/20 transition-all min-h-[44px] sm:min-h-[38px]"
          >
            <Plus size={14} />
            <span>Add domain</span>
          </button>
        </>}
      />

      <p className="flex items-center gap-2 text-xs text-soft">
        <ShieldCheck size={14} className="text-ok shrink-0" />
        We only scan domains you have verified. Nobody, including us, can scan a domain you don't control.
      </p>

      {/* Domains Table */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">

        <div className="overflow-x-auto w-full max-w-full">
          <table className="table-stack w-full text-left text-xs mono sm:min-w-[620px]">
            <thead>
              <tr className="border-b border-line bg-inset/40 text-soft text-[11px]">
                <th className="py-3 px-4 font-medium">DOMAIN NAME</th>
                <th className="py-3 px-4 font-medium">STATUS</th>
                <th className="py-3 px-4 font-medium">VERIFICATION RECORD</th>
                <th className="py-3 px-4 font-medium">VERIFIED ON ({zone})</th>
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
                  <td colSpan={6} className="p-4">
                    <EmptyPanel icon={<Globe size={26} />} title="No domains yet"
                                help="Add the domain you want scanned. You will prove you own it with one DNS record."
                                action={<button type="button" onClick={() => setAddModalOpen(true)} className="btn-tactile flex items-center gap-2 px-4 py-2 rounded text-xs mono bg-accent text-white min-h-[44px]"><Plus size={14} /> Add your first domain</button>} />
                  </td>
                </tr>
              ) : (
                domains.map((dom, idx) => (
                  <>
                  <tr
                    key={dom.id}
                    style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
                    className="stagger-row hover:bg-inset/40 transition-colors"
                  >
                    <td className="stack-title py-3 px-4 font-bold text-ink">
                      <div className="flex items-center gap-2">
                        <Globe size={14} className="text-accent" />
                        <span>{dom.domain}</span>
                      </div>
                    </td>

                    <td data-label="Status" className="py-3 px-4">
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

                    <td data-label="Record" className="py-3 px-4">
                      {dom.verification_status === 'verified' ? (
                        <span className="text-[11px] text-soft">In place</span>
                      ) : (
                      <div className="flex items-center gap-1.5 max-w-xs">
                        <code className="text-[11px] text-soft bg-inset px-2 py-0.5 rounded border border-line truncate">
                          cyphward-verification={dom.verification_token}
                        </code>
                        <button
                          onClick={() => copyText(`cyphward-verification=${dom.verification_token}`, dom.id)}
                          className="btn-tactile p-1 hover:text-accent text-soft shrink-0 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 inline-flex items-center justify-center"
                          title="Copy verification TXT value"
                          aria-label="Copy verification record"
                        >
                          {copiedToken === dom.id ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                        </button>
                      </div>
                      )}
                    </td>

                    <td data-label="Verified" className="py-3 px-4 text-soft text-[11px]">
                      {dom.verified_at ? fmtDayZone(dom.verified_at, zone) : 'Not yet'}
                    </td>

                    <td data-label="Assets" className="py-3 px-4 font-semibold text-ink">
                      {dom.asset_count !== undefined ? `${dom.asset_count} assets` : '—'}
                    </td>

                    <td className="stack-actions py-3 px-4 text-right space-x-2">
                      <button
                        disabled={verifyingId === dom.id}
                        onClick={() => handleVerify(dom)}
                        className={`btn-tactile px-2.5 py-1 rounded text-[11px] border font-medium transition-colors min-h-[44px] sm:min-h-0 ${
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
                        className="btn-tactile p-1 rounded hover:bg-inset text-soft hover:text-ink min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 inline-flex items-center justify-center"
                        title="How to verify"
                        aria-label={`How to verify ${dom.domain}`}
                      >
                        <ExternalLink size={13} />
                      </button>

                      <button
                        onClick={() => handleDelete(dom.id, dom.domain)}
                        className="btn-tactile p-1 rounded hover:bg-accent-soft text-soft hover:text-accent min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 inline-flex items-center justify-center"
                        aria-label={`Remove ${dom.domain}`}
                        title="Remove domain"
                      >
                        <Trash2 size={13} />
                      </button>
                      {dom.verification_status === 'verified' && (
                        <button
                          onClick={() => toggleHosts(dom.id)}
                          className="btn-tactile px-2 py-1 rounded hover:bg-inset text-soft hover:text-ink text-[10px] mono min-h-[44px] sm:min-h-0"
                          title="Hosts probed on every scan"
                        >
                          {expandedId === dom.id ? 'Hide hosts' : 'Extra hosts'}
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedId === dom.id && (
                    <tr key={`${dom.id}-hosts`}>
                      <td colSpan={6} className="py-3 px-4 bg-inset/40">
                        <p className="text-[11px] mono text-soft mb-2">
                          Extra hosts under {dom.domain} that are checked on every scan, even if discovery misses them.
                        </p>
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {(hostsByDomain[dom.id] || []).map(h => (
                            <span key={h.id} className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] mono bg-raised border border-line text-ink">
                              {h.hostname}
                              <button
                                onClick={() => handleRemoveHost(dom.id, h.id, h.hostname)}
                                className="text-soft hover:text-accent min-w-[44px] min-h-[44px]"
                                title="Stop monitoring"
                                aria-label={`Stop monitoring ${h.hostname}`}
                              >
                                ×
                              </button>
                            </span>
                          ))}
                          {(hostsByDomain[dom.id] || []).length === 0 && (
                            <span className="text-[11px] mono text-soft">No extra hosts. Cyphward uses discovery only.</span>
                          )}
                        </div>
                        <form onSubmit={e => handleAddHost(e, dom.id, dom.domain)} className="flex items-center gap-2">
                          <input
                            type="text"
                            placeholder={`e.g. portal.${dom.domain}`}
                            value={expandedId === dom.id ? newHost : ''}
                            onChange={e => setNewHost(e.target.value)}
                            aria-label={`Extra host under ${dom.domain}`}
                            className="w-64 max-w-full bg-raised border border-line rounded px-2.5 py-1 min-h-[44px] sm:min-h-0 text-xs mono text-ink placeholder:text-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus:border-accent"
                          />
                          <button
                            type="submit"
                            disabled={hostsBusy || !newHost.trim()}
                            className="btn-tactile px-2.5 py-1 rounded text-[11px] mono bg-accent text-white disabled:opacity-50 min-h-[44px] sm:min-h-0"
                          >
                            {hostsBusy ? 'Adding…' : 'Add host'}
                          </button>
                        </form>
                      </td>
                    </tr>
                  )}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add domain */}
      <Dialog
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        title="Add a domain"
        icon={<Globe size={16} className="text-accent" />}
        maxWidth="max-w-md"
        dirty={!!newDomainInput.trim()}
        footer={<AddDomainActions adding={adding} disabled={!newDomainInput.trim()} />}
      >
        <form id="add-domain-form" onSubmit={handleAddDomain} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="add-domain-name" className="text-xs mono text-soft block">Domain name</label>
            <input
              id="add-domain-name"
              type="text"
              placeholder="e.g. acmetraders.ng or corp.company.com"
              value={newDomainInput}
              onChange={e => setNewDomainInput(e.target.value)}
              required
              className="w-full bg-inset border border-line rounded px-3 py-2 min-h-[44px] text-xs mono text-ink placeholder:text-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus:border-accent"
            />
          </div>

          <div className="p-3 bg-inset/50 rounded border border-line text-[11px] mono text-soft space-y-1">
            <span className="font-semibold text-ink block">You will verify it next</span>
            <p>
              After you add the domain, we show you a one-time DNS record to publish. This proves the domain is yours before any scanning starts.
            </p>
          </div>
        </form>
      </Dialog>

      {/* How to verify: DNS steps and an inline check */}
      <Dialog
        open={Boolean(instructionModal)}
        onClose={() => setInstructionModal(null)}
        title="How to verify your domain"
        icon={<ShieldCheck size={16} className="text-ok" />}
        maxWidth="max-w-lg"
        footer={instructionModal ? (
          <VerifyActions
            checking={modalCheck === 'checking'}
            disabled={!instructionModal.verification_token || modalCheck === 'checking' || modalCheck === 'verified'}
            onCheck={() => handleVerify(instructionModal, true)}
          />
        ) : undefined}
      >
        {instructionModal && (
          <div className="space-y-4">
            <p className="text-xs text-soft leading-relaxed">
              Prove you own <strong className="text-ink">{instructionModal.domain}</strong> by adding
              a TXT record in your DNS settings (Cloudflare, GoDaddy, Namecheap and so on):
            </p>

            <DomainDnsInstructions key={instructionModal.id} domain={instructionModal.domain} token={instructionModal.verification_token} />

            {modalCheck === 'failed' && (
              <div role="alert" className="p-3 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-500 flex items-start gap-2">
                <AlertTriangle size={14} className="flex-none mt-0.5" />
                <span>
                  We cannot see the record yet. If you just added it, wait a few minutes and check
                  again. DNS changes can take up to an hour.
                </span>
              </div>
            )}

            {modalCheck === 'verified' && (
              <div role="status" className="p-3 bg-ok/10 border border-ok/30 rounded text-xs text-ok flex items-center gap-2">
                <CheckCircle2 size={14} className="flex-none" />
                <span>Domain verified. Updating your dashboard…</span>
              </div>
            )}
          </div>
        )}
      </Dialog>
    </div>
  );
}

function AddDomainActions({ adding, disabled }: { adding: boolean; disabled: boolean }) {
  const close = useDialogClose();
  return (
    <>
      <button type="button" onClick={close} className="btn-tactile px-3.5 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft min-h-[44px]">Cancel</button>
      <button type="submit" form="add-domain-form" disabled={adding || disabled}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 min-h-[44px]">
        {adding ? (<><RefreshCw size={13} className="animate-spin" /> Adding…</>) : 'Add domain'}
      </button>
    </>
  );
}

function VerifyActions({ checking, disabled, onCheck }: { checking: boolean; disabled: boolean; onCheck: () => void }) {
  const close = useDialogClose();
  return (
    <>
      <button type="button" onClick={close} className="btn-tactile px-4 py-1.5 rounded text-xs mono border border-line hover:bg-inset text-soft min-h-[44px]">Close</button>
      <button type="button" onClick={onCheck} disabled={disabled}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono font-medium bg-accent text-white hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 min-h-[44px]">
        {checking ? (<><RefreshCw size={13} className="animate-spin" /> Checking…</>) : 'Check now'}
      </button>
    </>
  );
}
