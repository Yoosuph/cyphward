import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Check, Copy, Download, FileText, Info, Sparkles } from 'lucide-react';
import StatusChip, { type ChipLevel } from '../../components/StatusChip';
import { useToast } from '../../components/Toast';
import {
  approveDocument, generateDocument, getDocument, listDocuments,
  type DocumentFull, type DocumentKind, type DocumentList, type DocumentStatus, type DocumentSummary, type DocumentVersion,
} from '../../lib/api';
import { GrowthGate, LoadError, ReadOnlyNote, errorText, fmtTimeZone, isGrowthGate } from './shared';

/**
 * Drafts built from the organisation's own answers and observations. Every draft is labelled as a draft and
 * not legal advice. Approving one records who read it and when (their own statement); it says nothing about
 * the document being published or in force, and it never changes a readiness status.
 */

const LABEL = 'Draft — not legal advice';
const STATUS_TEXT: Record<DocumentStatus, string> = { not_generated: 'Not generated', draft: 'Draft', approved: 'Approved' };
const STATUS_LEVEL: Record<DocumentStatus, ChipLevel> = { not_generated: 'idle', draft: 'warn', approved: 'ok' };
const PLACEHOLDER = /(\[MISSING: [^\[\]\n]{1,200}\])/g;

/** The stored text is Markdown; the plain-text copy drops the heading and emphasis marks and nothing else. */
export function plainText(markdown: string): string {
  return markdown.replace(/^#{1,6}\s+/gm, '').replace(/\*\*/g, '');
}

export function whenText(value: string): string {
  return `${fmtTimeZone(value, 'UTC')} UTC`;
}

function Highlighted({ text }: { text: string }) {
  const parts: ReactNode[] = text.split(PLACEHOLDER).map((part, i) =>
    i % 2 === 1
      ? <mark key={i} data-testid="placeholder" className="bg-accent/15 text-ink rounded-[2px] px-0.5">{part}</mark>
      : <span key={i}>{part}</span>);
  return <>{parts}</>;
}

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function Viewer({ doc, canEdit, onApproved, onClose }: { doc: DocumentFull; canEdit: boolean; onApproved: () => void; onClose: () => void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `${doc.kind.replace(/_/g, '-')}-v${doc.version}`;

  const copy = async (body: string, what: string) => {
    try {
      await navigator.clipboard.writeText(body);
      toast(`${what} copied.`);
    } catch {
      toast('Could not copy. Use download instead.');
    }
  };
  const approve = async () => {
    setBusy(true);
    setError(null);
    try {
      await approveDocument(doc.id);
      toast('Approval recorded.');
      setConfirming(false);
      onApproved();
    } catch (e) {
      setError(errorText(e, 'Could not record the approval.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-line bg-raised p-4 sm:p-5 space-y-4" aria-label={`${doc.title} version ${doc.version}`} data-testid="doc-viewer">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-accent/30 bg-accent/5 text-xs text-ink leading-relaxed" data-testid="doc-banner">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span><strong>{LABEL}.</strong> Written from your own answers. Have a qualified practitioner review it before you rely on it.</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm text-ink font-medium">{doc.title} · version {doc.version}</h2>
        <button type="button" className="btn-mini" onClick={onClose}>CLOSE</button>
      </div>
      <p className="text-xs mono text-soft">
        Generated {whenText(doc.generated_at)}{doc.generated_by ? ` by ${doc.generated_by}` : ''} · {doc.generator === 'template' ? 'standard wording' : 'reworded by AI'} · {doc.open_placeholders} to fill in
        {!doc.is_latest ? ' · an older version' : ''}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-mini" onClick={() => void copy(plainText(doc.text), 'Text')}><Copy size={12} /> COPY TEXT</button>
        <button type="button" className="btn-mini" onClick={() => void copy(doc.text, 'Markdown')}><Copy size={12} /> COPY MARKDOWN</button>
        <button type="button" className="btn-mini" onClick={() => download(`${base}.txt`, plainText(doc.text), 'text/plain;charset=utf-8')}><Download size={12} /> DOWNLOAD TEXT</button>
        <button type="button" className="btn-mini" onClick={() => download(`${base}.md`, doc.text, 'text/markdown;charset=utf-8')}><Download size={12} /> DOWNLOAD MARKDOWN</button>
      </div>
      <pre className="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed font-mono bg-inset border border-line rounded p-3 sm:p-4 max-h-[32rem] overflow-y-auto min-w-0"
           data-testid="doc-text"><Highlighted text={doc.text} /></pre>
      {doc.approval ? (
        <p className="text-xs mono text-ink" data-testid="doc-approval">
          Approved by {doc.approval.approved_by || 'a former member'} on {whenText(doc.approval.approved_at)}. Their own record of reading this draft, not a check by Cyphward.
          {doc.approval.open_placeholders > 0 ? ` ${doc.approval.open_placeholders} items were still to fill in.` : ''}
        </p>
      ) : canEdit && doc.is_latest ? (
        confirming ? (
          <div className="space-y-2" data-testid="approve-confirm">
            <p className="text-xs text-soft leading-relaxed">
              This records that you read this version, with your name and the time. It does not mean the document is published or in force, and it does not change your readiness page.
              {doc.open_placeholders > 0 ? ` ${doc.open_placeholders} items are still marked to fill in.` : ''}
            </p>
            {error && <p role="alert" className="text-xs mono text-accent break-words">{error}</p>}
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-solid btn-mini" disabled={busy} onClick={() => void approve()}>{busy ? 'SAVING…' : 'CONFIRM APPROVAL'}</button>
              <button type="button" className="btn-mini" disabled={busy} onClick={() => setConfirming(false)}>CANCEL</button>
            </div>
          </div>
        ) : (
          <button type="button" className="btn-mini" onClick={() => setConfirming(true)}><Check size={12} /> APPROVE THIS VERSION</button>
        )
      ) : !canEdit ? <ReadOnlyNote /> : null}
    </section>
  );
}

function Card({ d, canEdit, busy, onGenerate, onView }: {
  d: DocumentSummary; canEdit: boolean; busy: boolean; onGenerate: () => void; onView: (v: DocumentVersion) => void;
}) {
  const latest = d.latest;
  return (
    <li className="px-4 sm:px-5 py-4 space-y-2.5 border-t border-line first:border-t-0" data-testid={`doc-${d.kind}`}>
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
        <p className="text-sm text-ink font-medium min-w-0 break-words flex items-center gap-2"><FileText size={14} className="flex-none text-soft" /> {d.title}</p>
        <span className="uppercase self-start" data-testid={`doc-status-${d.kind}`}><StatusChip level={STATUS_LEVEL[d.status]}>{STATUS_TEXT[d.status]}</StatusChip></span>
      </div>
      {latest ? (
        <p className="text-xs mono text-soft break-words">
          Version {latest.version} · generated {whenText(latest.generated_at)} · {latest.open_placeholders} to fill in
          {latest.approval ? ` · approved by ${latest.approval.approved_by || 'a former member'} on ${whenText(latest.approval.approved_at)}` : ''}
        </p>
      ) : <p className="text-xs text-soft">Nothing generated yet.</p>}
      {latest?.stale && <p className="text-xs text-soft" data-testid={`doc-stale-${d.kind}`}>Your answers have changed since this version. Generate a new version to use them.</p>}
      <div className="flex flex-wrap gap-2">
        {latest && <button type="button" className="btn-mini" onClick={() => onView(latest)}>VIEW</button>}
        {canEdit && (
          <button type="button" className="btn-mini" disabled={busy} onClick={onGenerate}>
            <Sparkles size={12} /> {busy ? 'GENERATING…' : latest ? 'GENERATE NEW VERSION' : 'GENERATE'}
          </button>
        )}
      </div>
      {d.history.length > 1 && (
        <details className="text-xs" data-testid={`doc-history-${d.kind}`}>
          <summary className="cursor-pointer mono text-soft uppercase tracking-[.12em]">Version history ({d.history.length})</summary>
          <ul className="mt-2 space-y-1.5">
            {d.history.map(v => (
              <li key={v.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 mono text-soft">
                <span className="text-ink">Version {v.version}</span>
                <span>{whenText(v.generated_at)}</span>
                <span>{v.approval ? `approved by ${v.approval.approved_by || 'a former member'}` : 'not approved'}</span>
                <button type="button" className="btn-mini" onClick={() => onView(v)}>VIEW</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

export default function DocumentsTab({ canEdit }: { canEdit: boolean }) {
  const toast = useToast();
  const [data, setData] = useState<DocumentList | null>(null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyKind, setBusyKind] = useState<DocumentKind | null>(null);
  const [viewing, setViewing] = useState<DocumentFull | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await listDocuments());
      setGated(false);
    } catch (e) {
      if (isGrowthGate(e)) setGated(true);
      else setError(errorText(e, 'Could not load the documents.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const open = useCallback(async (id: string) => {
    setActionError(null);
    try {
      setViewing(await getDocument(id));
    } catch (e) {
      setActionError(errorText(e, 'Could not open the document.'));
    }
  }, []);

  const generate = async (kind: DocumentKind) => {
    setBusyKind(kind);
    setActionError(null);
    try {
      const made = await generateDocument(kind);
      toast('Draft generated.');
      await load();
      await open(made.id);
    } catch (e) {
      setActionError(errorText(e, 'Could not generate the draft.'));
    } finally {
      setBusyKind(null);
    }
  };

  if (gated) return <GrowthGate what="The documents" />;
  if (error && !data) return <LoadError message={error} onRetry={() => void load()} />;
  if (!data) return <p className="text-xs mono text-soft">LOADING DOCUMENTS…</p>;

  return (
    <div className="space-y-5" data-testid="documents">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-accent/30 bg-accent/5 text-xs text-ink leading-relaxed" data-testid="documents-disclaimer">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>{LABEL}. These drafts use only what you told us and what Cyphward observed. Anything missing is marked for you to fill in. Approving a draft records that you read it. It does not publish it and does not change your readiness page.</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs mono text-soft" data-testid="doc-quota">{data.generated_today} of {data.daily_cap} drafts used today</p>
        {!canEdit && <ReadOnlyNote />}
      </div>
      {actionError && <p role="alert" className="text-xs mono text-accent break-words" data-testid="doc-error">{actionError}</p>}
      <section className="rounded-lg border border-line bg-raised" aria-label="Documents">
        <ul>
          {data.documents.map(d => (
            <Card key={d.kind} d={d} canEdit={canEdit} busy={busyKind === d.kind}
                  onGenerate={() => void generate(d.kind)} onView={v => void open(v.id)} />
          ))}
        </ul>
      </section>
      {viewing && (
        <Viewer key={viewing.id} doc={viewing} canEdit={canEdit}
                onClose={() => setViewing(null)}
                onApproved={() => { void load(); void open(viewing.id); }} />
      )}
    </div>
  );
}
