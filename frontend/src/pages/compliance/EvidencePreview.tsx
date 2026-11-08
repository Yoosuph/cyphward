import { useEffect, useState } from 'react';
import { Download, Eye, FileText } from 'lucide-react';
import Dialog from '../../components/ui/Dialog';
import { SkBlock, SkLine, SkeletonRegion } from '../../components/ui/Skeleton';
import { ErrorPanel } from '../../components/ui/StatePanels';
import { getEvidenceFilePreview, type EvidenceFile } from '../../lib/api';
import { formatSize, previewErrorText, previewKind } from './evidenceUpload';
import { fmtDayZone } from './shared';

/**
 * The preview of one attached file, in the shared Dialog (focus trap, Escape, focus back to the row's Preview button,
 * full screen on phones with the close control pinned at the top).
 *
 * Security (docs/evidence-preview-2026-11-07):
 *  - PNG and JPG: the bytes come through the API with the session, become a blob URL in memory and are shown in an <img>.
 *  - PDF: the same blob, in an <object type="application/pdf">. When the browser cannot show a PDF there (no built-in
 *    viewer, or the page's security policy refuses embedded objects) the fallback text and the Download button show.
 *  - DOCX: never shown. The dialog lists the file's details and offers the download only.
 *  - No storage URL is ever put in the page or a frame. Download uses the existing attachment-only link.
 *  - Nothing is cached: the blob URL is revoked when the dialog closes (or the file changes), and a request still in
 *    flight is aborted.
 */

/** What the dialog shows. `forId` ties a state to one file, so another file never shows a stale (revoked) blob. */
type Phase =
  | { phase: 'loading'; forId: string | null }
  | { phase: 'ready'; forId: string; url: string }
  | { phase: 'error'; forId: string; message: string }
  | { phase: 'pdf-fallback'; forId: string };

export default function EvidencePreview({ file, zone, onClose, onDownload, downloading, downloadError, returnFocusTo }: {
  file: EvidenceFile | null;
  zone: string;
  onClose: () => void;
  onDownload: (f: EvidenceFile) => void;
  downloading: boolean;
  /** Reviewed wording only (the caller maps errors); shown above the footer. */
  downloadError?: string | null;
  returnFocusTo?: () => HTMLElement | null;
}) {
  const [state, setState] = useState<Phase>({ phase: 'loading', forId: null });
  const [attempt, setAttempt] = useState(0);
  const id = file?.id ?? null;
  const contentType = file?.content_type ?? '';
  const kind = previewKind(contentType);

  // Fetch while open; on close (or another file) abort the request and revoke the blob URL.
  useEffect(() => {
    if (!id || kind === 'none') return;
    if (kind === 'pdf' && (navigator as Navigator & { pdfViewerEnabled?: boolean }).pdfViewerEnabled === false) {
      setState({ phase: 'pdf-fallback', forId: id });
      return;
    }
    const controller = new AbortController();
    let url: string | null = null;
    let live = true;
    setState({ phase: 'loading', forId: id });
    getEvidenceFilePreview(id, contentType, controller.signal)
      .then(blob => {
        if (!live) return;
        url = URL.createObjectURL(blob);
        setState({ phase: 'ready', forId: id, url });
      })
      .catch(e => {
        if (!live || controller.signal.aborted) return;
        setState({ phase: 'error', forId: id, message: previewErrorText(e) });
      });
    return () => {
      live = false;
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, contentType, kind, attempt]);

  // A page security policy that refuses embedded objects blocks the PDF: show the fallback instead of an empty box.
  useEffect(() => {
    if (!id || kind !== 'pdf' || state.phase !== 'ready') return;
    const onViolation = (ev: SecurityPolicyViolationEvent) => {
      const directive = ev.effectiveDirective || ev.violatedDirective || '';
      if (directive.startsWith('object-src') || (directive.startsWith('default-src') && /^blob/.test(ev.blockedURI))) {
        setState({ phase: 'pdf-fallback', forId: id });
      }
    };
    document.addEventListener('securitypolicyviolation', onViolation);
    return () => document.removeEventListener('securitypolicyviolation', onViolation);
  }, [id, kind, state.phase]);

  // Word files have nothing to load; any other file shows its own state only (a skeleton until it has one).
  const shown: Phase | { phase: 'details' } = kind === 'none' ? { phase: 'details' }
    : state.forId === id ? state : { phase: 'loading', forId: id };

  const name = file?.display_name ?? '';
  const footer = file ? (
    <button type="button" className="btn btn-solid btn-mini touch-target" disabled={downloading}
            onClick={() => onDownload(file)} data-testid="preview-download">
      <Download size={12} aria-hidden="true" /> {downloading ? 'Preparing download…' : 'Download'}
    </button>
  ) : undefined;

  return (
    <Dialog open={!!file} onClose={onClose} title="File preview" icon={<Eye size={16} />} maxWidth="max-w-3xl"
            footer={footer} returnFocusTo={returnFocusTo} className="evf-preview">
      {file && (
        <div className="space-y-4" data-testid="evidence-preview" data-kind={kind}>
          <div className="min-w-0">
            <p className="text-sm text-ink font-medium break-all" data-testid="preview-name">{name}</p>
            <p className="text-[11px] mono text-soft break-words mt-1" data-testid="preview-meta">
              {file.type_label} · {formatSize(file.size_bytes)} · {fmtDayZone(file.uploaded_at, zone)}
            </p>
          </div>

          {shown.phase === 'loading' && (
            <SkeletonRegion label="the preview" className="evf-preview-stage space-y-3">
              <SkBlock height={kind === 'pdf' ? 360 : 240} rounded="md" />
              <SkLine width="40%" size={11} />
            </SkeletonRegion>
          )}

          {shown.phase === 'error' && (
            <ErrorPanel title="The preview did not load" message={shown.message} onRetry={() => setAttempt(a => a + 1)} />
          )}

          {shown.phase === 'ready' && kind === 'image' && (
            <div className="evf-preview-stage evf-preview-image" data-testid="preview-image-wrap">
              <img src={shown.url} alt={name} data-testid="preview-image"
                   onError={() => setState({ phase: 'error', forId: shown.forId, message: 'This image could not be shown. Download the file to open it on your device.' })} />
            </div>
          )}

          {shown.phase === 'ready' && kind === 'pdf' && (
            <div className="evf-preview-stage evf-preview-pdf">
              <object data={shown.url} type="application/pdf" aria-label={`PDF preview of ${name}`} data-testid="preview-pdf">
                <PdfFallback />
              </object>
            </div>
          )}

          {shown.phase === 'pdf-fallback' && <PdfFallback />}

          {downloadError && <p role="alert" className="text-xs mono text-accent break-words" data-testid="preview-download-error">{downloadError}</p>}

          {shown.phase === 'details' && (
            <div className="rounded-lg border border-line bg-inset p-4 flex gap-3" data-testid="preview-docx">
              <FileText size={18} className="text-accent shrink-0 mt-0.5" aria-hidden="true" />
              <div className="space-y-1.5 min-w-0">
                <p className="text-sm text-ink font-medium">Word documents are not shown here</p>
                <p className="text-xs text-soft leading-relaxed">
                  A Word file cannot be opened safely inside the page, so there is no preview. Download it to open it
                  on your device.
                </p>
                <p className="text-[11px] mono text-soft break-words">Uploaded by {file.uploaded_by || 'a former member'}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

function PdfFallback() {
  return (
    <div className="rounded-lg border border-line bg-inset p-4 space-y-1.5" data-testid="preview-pdf-fallback">
      <p className="text-sm text-ink font-medium">This PDF cannot be shown here</p>
      <p className="text-xs text-soft leading-relaxed">Your browser cannot display it inside the page. Download it to open it on your device.</p>
    </div>
  );
}
