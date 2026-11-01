import { useCallback, useEffect, useState } from 'react';
import { pageCacheTicket, readPageCache, writePageCache } from '../../lib/pageCache';
import { CompliancePanelSkeleton } from '../../components/skeletons/RouteSkeleton';
import { Download, FileText, Info, Plus, RefreshCw } from 'lucide-react';
import Dialog from '../../components/ui/Dialog';
import { EmptyPanel } from '../../components/ui/StatePanels';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { downloadPack, issuePack, listPacks, type EvidencePack, type PackKind, type PackList } from '../../lib/api';
import { GrowthGate, LoadError, ReadOnlyNote, errorText, fmtDayZone, fmtTimeZone, isGrowthGate } from './shared';

/**
 * Evidence packs: generate from a frozen snapshot, list, look at the details, download the stored HTML or PDF.
 * Supporting evidence for a DPCO. It is not a Compliance Audit Return.
 */

const KIND_LABEL: Record<PackKind, string> = {
  readiness_pack: 'NDPA readiness evidence pack',
  dpo_section: 'DPO six-monthly data-security section',
};
const KIND_BUTTON: Record<PackKind, string> = { readiness_pack: 'Issue readiness pack', dpo_section: 'Issue DPO section' };

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function PackDetails({ p, zone, onDownload, onClose }: { p: EvidencePack; zone: string; onDownload: (format: 'html' | 'pdf') => void; onClose: () => void }) {
  const rows: [string, string][] = [
    ['Kind', KIND_LABEL[p.kind]],
    ['Issued', `${fmtTimeZone(p.issued_at, zone)} (${zone})`],
    ['Kept until', `${fmtDayZone(p.retain_until, zone)}`],
    ['Evidence snapshot', p.snapshot_id],
    ['HTML fingerprint (SHA-256)', p.html_sha256],
    ['PDF fingerprint (SHA-256)', p.pdf_sha256],
  ];
  return (
    <Dialog open onClose={onClose} title="Pack details" maxWidth="max-w-xl"
            footer={
              <>
                <button type="button" className="btn-mini touch-target" onClick={() => onDownload('pdf')} data-testid="details-download-pdf"><Download size={12} /> Download PDF</button>
                <button type="button" className="btn-mini touch-target" onClick={() => onDownload('html')} data-testid="details-download-html"><Download size={12} /> Download HTML</button>
              </>
            }>
      <div className="space-y-4" data-testid="pack-details">
        <p className="text-xs text-soft leading-relaxed">This pack was saved as it was when it was issued. It does not change. It is supporting evidence for a licensed DPCO. It is not a Compliance Audit Return.</p>
        <dl className="space-y-3">
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt className="mono text-[10px] tracking-[.16em] text-soft uppercase">{k}</dt>
              <dd className="text-sm text-ink mt-0.5 break-all">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Dialog>
  );
}

export default function PacksTab({ canEdit, zone }: { canEdit: boolean; zone: string }) {
  const toast = useToast();
  const confirm = useConfirm();
  // Last-seen list paints at once on a revisit (lib/queryCache); load() refreshes it.
  const [data, setData] = useState<PackList | null>(() => readPageCache<PackList>('comply:packs') ?? null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [details, setDetails] = useState<EvidencePack | null>(null);

  const load = useCallback(async () => {
    try {
      { const ticket = pageCacheTicket(); const fresh = await listPacks(); writePageCache('comply:packs', fresh, ticket); setData(fresh); }
      setError(null);
    } catch (e) {
      if (isGrowthGate(e)) setGated(true);
      else setError(errorText(e, 'Something went wrong on our side. Try again in a moment.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const generate = async (kind: PackKind) => {
    const ok = await confirm({
      title: `${KIND_BUTTON[kind]}?`,
      body: `This saves your ${KIND_LABEL[kind]} using your evidence as it is right now.`,
      irreversible: 'An issued pack cannot be edited or taken back.',
      confirmLabel: 'Issue pack',
    });
    if (!ok) return;
    setBusy(kind);
    try {
      await issuePack({ request_key: `ui-${crypto.randomUUID()}`, kind });
      toast('Pack issued.');
      await load();
    } catch (e) {
      toast(errorText(e, 'The pack was not issued. Try again in a moment.'));
    } finally {
      setBusy(null);
      // The button was disabled while the pack was issued, which drops its focus: put it back.
      window.setTimeout(() => document.querySelector<HTMLElement>(`[data-testid="issue-${kind}"]`)?.focus(), 0);
    }
  };

  const download = async (p: EvidencePack, format: 'html' | 'pdf') => {
    try {
      save(await downloadPack(p.id, format), `cyphward-${p.kind}-${p.id.slice(0, 8)}.${format}`);
      toast(`${format.toUpperCase()} downloaded.`);
    } catch (e) {
      toast(errorText(e, 'The download did not work. Try again.'));
    }
  };

  if (gated) return <GrowthGate what="Evidence packs" />;
  if (error && !data) return <LoadError title="We could not load your packs" message={error} onRetry={() => void load()} />;
  if (!data) return <CompliancePanelSkeleton section="packs" />;

  return (
    <div className="space-y-5" data-testid="packs">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-line bg-raised text-xs text-ink leading-relaxed" data-testid="packs-notice">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>
          A pack saves your evidence exactly as it is when you issue it, and it does not change afterwards. It is supporting
          evidence for a licensed DPCO. It is not a Compliance Audit Return.
        </span>
      </div>
      {data?.retention && <p className="text-xs text-soft leading-relaxed" data-testid="packs-retention">{data.retention}</p>}

      {canEdit ? (
        <div className="flex flex-wrap gap-2">
          {(Object.keys(KIND_LABEL) as PackKind[]).map(kind => (
            <button key={kind} type="button" onClick={() => void generate(kind)} disabled={busy !== null}
                    className="btn-mini touch-target flex items-center gap-1.5" data-testid={`issue-${kind}`}>
              {busy === kind ? <RefreshCw size={12} className="animate-spin" /> : <Plus size={12} />}
              {busy === kind ? 'Issuing…' : KIND_BUTTON[kind]}
            </button>
          ))}
        </div>
      ) : (
        <ReadOnlyNote />
      )}

      {data.packs.length === 0 ? (
        <div data-testid="packs-empty">
          <EmptyPanel icon={<FileText size={26} />} title="No packs issued yet"
                      help={canEdit ? 'Issue a pack to save your evidence as it is today. You can then download it as a PDF or HTML file.' : 'An owner or admin can issue a pack. It will appear here.'} />
        </div>
      ) : (
        <ul className="space-y-3" data-testid="pack-list">
          {data.packs.map(p => (
            <li key={p.id} className="p-4 rounded-lg border border-line bg-raised flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-ink font-semibold">{KIND_LABEL[p.kind]}</p>
                <p className="mono text-[11px] text-soft break-words">
                  Issued {fmtTimeZone(p.issued_at, zone)} · kept until {fmtDayZone(p.retain_until, zone)} · snapshot {p.snapshot_id.slice(0, 8)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-mini touch-target" onClick={() => setDetails(p)} data-testid="pack-details-open">Details</button>
                <button type="button" className="btn-mini touch-target flex items-center gap-1" onClick={() => void download(p, 'pdf')} data-testid="download-pdf">
                  <Download size={11} />PDF
                </button>
                <button type="button" className="btn-mini touch-target flex items-center gap-1" onClick={() => void download(p, 'html')} data-testid="download-html">
                  <Download size={11} />HTML
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {details && <PackDetails p={details} zone={zone} onClose={() => setDetails(null)} onDownload={f => void download(details, f)} />}
    </div>
  );
}
