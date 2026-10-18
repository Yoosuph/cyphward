import { useCallback, useEffect, useState } from 'react';
import { Download, FileText, Info, Plus, RefreshCw } from 'lucide-react';
import { useToast } from '../../components/Toast';
import { downloadPack, issuePack, listPacks, type EvidencePack, type PackKind, type PackList } from '../../lib/api';
import { GrowthGate, LoadError, ReadOnlyNote, errorText, fmtTimeZone, isGrowthGate } from './shared';

/**
 * Evidence packs: generate from a frozen snapshot, list, download the stored HTML or PDF.
 * Supporting evidence for a DPCO. It is not a Compliance Audit Return.
 */

const KIND_LABEL: Record<PackKind, string> = {
  readiness_pack: 'NDPA readiness evidence pack',
  dpo_section: 'DPO six-monthly data-security section',
};

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function PacksTab({ canEdit, zone }: { canEdit: boolean; zone: string }) {
  const toast = useToast();
  const [data, setData] = useState<PackList | null>(null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await listPacks());
      setError(null);
    } catch (e) {
      if (isGrowthGate(e)) setGated(true);
      else setError(errorText(e, 'Could not load the packs.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const generate = async (kind: PackKind) => {
    setBusy(kind);
    try {
      await issuePack({ request_key: `ui-${crypto.randomUUID()}`, kind });
      toast('Pack issued');
      await load();
    } catch (e) {
      toast(errorText(e, 'Could not issue the pack.'));
    } finally {
      setBusy(null);
    }
  };

  const download = async (p: EvidencePack, format: 'html' | 'pdf') => {
    try {
      save(await downloadPack(p.id, format), `cyphward-${p.kind}-${p.id.slice(0, 8)}.${format}`);
    } catch (e) {
      toast(errorText(e, 'The download failed.'));
    }
  };

  if (gated) return <GrowthGate what="Evidence packs" />;
  if (error && !data) return <LoadError message={error} onRetry={() => void load()} />;
  if (!data) return <p className="text-xs mono text-soft">LOADING PACKS…</p>;

  return (
    <div className="space-y-5" data-testid="packs">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-line bg-raised text-xs text-ink leading-relaxed" data-testid="packs-notice">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>
          A pack freezes your current evidence at the moment you issue it and does not change afterwards. It is supporting
          evidence for a licensed DPCO. It is not a Compliance Audit Return.
        </span>
      </div>
      {data?.retention && <p className="text-xs text-soft leading-relaxed" data-testid="packs-retention">{data.retention}</p>}

      {canEdit ? (
        <div className="flex flex-wrap gap-2">
          {(Object.keys(KIND_LABEL) as PackKind[]).map(kind => (
            <button key={kind} type="button" onClick={() => void generate(kind)} disabled={busy !== null}
                    className="btn-mini flex items-center gap-1.5" data-testid={`issue-${kind}`}>
              {busy === kind ? <RefreshCw size={12} className="animate-spin" /> : <Plus size={12} />}
              ISSUE {KIND_LABEL[kind].toUpperCase()}
            </button>
          ))}
        </div>
      ) : (
        <ReadOnlyNote />
      )}

      {data.packs.length === 0 ? (
        <div className="p-8 rounded-lg border border-line bg-raised text-center" data-testid="packs-empty">
          <FileText size={26} className="mx-auto text-accent mb-3" />
          <p className="mono text-sm text-ink">No packs issued yet</p>
          <p className="text-xs text-soft mt-1">Nothing here is evidence until a pack is issued from your current records.</p>
        </div>
      ) : (
        <ul className="space-y-3" data-testid="pack-list">
          {data.packs.map(p => (
            <li key={p.id} className="p-4 rounded-lg border border-line bg-raised flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-ink font-semibold">{KIND_LABEL[p.kind]}</p>
                <p className="mono text-[11px] text-soft">
                  Issued {fmtTimeZone(p.issued_at, zone)} · kept until {fmtTimeZone(p.retain_until, zone).split(',')[0]} · from snapshot {p.snapshot_id.slice(0, 8)} · sha256 {p.html_sha256.slice(0, 12)}…
                </p>
              </div>
              <div className="flex gap-2">
                <button type="button" className="btn-mini flex items-center gap-1" onClick={() => void download(p, 'pdf')} data-testid="download-pdf">
                  <Download size={11} />PDF
                </button>
                <button type="button" className="btn-mini flex items-center gap-1" onClick={() => void download(p, 'html')} data-testid="download-html">
                  <Download size={11} />HTML
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
