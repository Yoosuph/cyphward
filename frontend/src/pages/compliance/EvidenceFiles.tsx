import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from 'react';
import { Download, Eye, Paperclip, RefreshCw, Trash2, X } from 'lucide-react';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { humanError } from '../../components/ui/StatePanels';
import {
  getEvidenceFileLink, removeEvidenceFile, uploadEvidenceFile, UploadCancelled,
  type EvidenceFile, type EvidenceFileList,
} from '../../lib/api';
import EvidencePreview from './EvidencePreview';
import { formatSize, needsAnotherFile, uploadErrorText } from './evidenceUpload';
import { fmtDayZone } from './shared';

export { formatSize };

/**
 * Files attached to the evidence of one answer. Everyone in the organisation sees the list, previews and downloads;
 * owners and admins attach and remove. The checks here mirror the server's (type and size) so a bad file is
 * refused before it is sent; the server checks again, by content.
 *
 * Upload (docs/evidence-preview-2026-11-07): one drop zone with idle, drag-over, uploading and done states. The zone
 * is a real button (Enter or Space opens the file picker) and also takes a dropped file. Progress comes from the
 * request's own upload events; Cancel aborts the request. Reduced motion makes every change instant.
 */

const EXTENSIONS: Record<string, string> = { pdf: 'PDF', png: 'PNG', jpg: 'JPEG', jpeg: 'JPEG', docx: 'DOCX' };
const TYPE_NAMES: Record<string, string> = { pdf: 'PDF', png: 'PNG image', jpg: 'JPEG image', jpeg: 'JPEG image', docx: 'Word document (DOCX)' };
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.docx';
const DEFAULT_MAX = 10 * 1024 * 1024;
const SECOND_EXTENSION = /\.[A-Za-z][A-Za-z0-9]{0,5}(?=\.|$)/;
const DONE_MS = 2400;

/** The message for a file the server would refuse by name or size, else null. */
export function fileProblem(file: File, maxBytes = DEFAULT_MAX): string | null {
  const dot = file.name.lastIndexOf('.');
  const ext = dot > 0 ? file.name.slice(dot + 1).toLowerCase() : '';
  if (!EXTENSIONS[ext]) return 'Only PDF, PNG, JPG/JPEG or DOCX files up to 10 MB can be attached.';
  if (SECOND_EXTENSION.test(file.name.slice(0, dot))) return 'File names with a second extension (such as report.exe.pdf) are not accepted. Rename the file.';
  if (file.size === 0) return 'The file is empty.';
  if (file.size > maxBytes) return `The file is ${formatSize(file.size)}. The limit is ${formatSize(maxBytes)}.`;
  return null;
}

function typeName(name: string): string {
  const dot = name.lastIndexOf('.');
  return TYPE_NAMES[dot > 0 ? name.slice(dot + 1).toLowerCase() : ''] ?? 'File';
}

type Upload =
  | { stage: 'idle' }
  | { stage: 'uploading'; file: File; progress: number }
  | { stage: 'done'; name: string }
  | { stage: 'error'; message: string; file: File | null };

type FocusTarget = 'cancel' | 'zone' | 'retry' | null;

export default function EvidenceFiles({ questionKey, info, zone, canEdit, onChanged }: {
  questionKey: string; info: EvidenceFileList; zone: string; canEdit: boolean; onChanged: () => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const hintId = useId();
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const focusNext = useRef<FocusTarget>(null);
  const lastPreviewId = useRef<string | null>(null);
  const [upload, setUpload] = useState<Upload>({ stage: 'idle' });
  const [dragOver, setDragOver] = useState(false);
  const [announce, setAnnounce] = useState('');
  const [newId, setNewId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<EvidenceFile | null>(null);
  // One Dialog per opened file: the shared Dialog remembers the control that first opened it, so a new instance per
  // file is what returns focus to the right row's Preview button.
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const files = info.files.filter(f => f.question_key === questionKey);
  const maxBytes = info.limits?.max_bytes ?? DEFAULT_MAX;
  const uploading = upload.stage === 'uploading';

  // Move focus when the control that had it goes away (the zone becomes the progress panel and back).
  useEffect(() => {
    const target = focusNext.current;
    if (!target || !root.current) return;
    focusNext.current = null;
    const active = document.activeElement;
    if (active && active !== document.body && !root.current.contains(active)) return; // the person moved on
    root.current.querySelector<HTMLElement>(`[data-focus="${target}"]`)?.focus();
  }, [upload]);

  // The done state settles back to idle.
  useEffect(() => {
    if (upload.stage !== 'done') return;
    const timer = window.setTimeout(() => setUpload(u => (u.stage === 'done' ? { stage: 'idle' } : u)), DONE_MS);
    return () => window.clearTimeout(timer);
  }, [upload]);

  const send = useCallback(async (file: File) => {
    const problem = fileProblem(file, maxBytes);
    if (problem) {
      focusNext.current = 'retry';
      setUpload({ stage: 'error', message: problem, file: null });
      return;
    }
    const controller = new AbortController();
    abort.current = controller;
    focusNext.current = 'cancel';
    setUpload({ stage: 'uploading', file, progress: 0 });
    setAnnounce(`Uploading ${file.name}.`);
    try {
      const saved = await uploadEvidenceFile(questionKey, file, fraction => {
        setUpload(u => (u.stage === 'uploading' && u.file === file ? { ...u, progress: Math.min(1, Math.max(0, fraction)) } : u));
      }, controller.signal);
      setNewId(saved?.id ?? null);
      focusNext.current = 'zone';
      setUpload({ stage: 'done', name: file.name });
      setAnnounce(`${file.name} attached.`);
      onChanged();
    } catch (e) {
      if (e instanceof UploadCancelled || controller.signal.aborted) {
        focusNext.current = 'zone';
        setUpload({ stage: 'idle' });
        setAnnounce('Upload cancelled.');
        onChanged(); // an abort after the last byte may still have been saved: show what the server has
        return;
      }
      focusNext.current = 'retry';
      setUpload({ stage: 'error', message: uploadErrorText(e), file: needsAnotherFile(e) ? null : file });
    } finally {
      if (abort.current === controller) abort.current = null;
    }
  }, [maxBytes, onChanged, questionKey]);

  if (!canEdit && files.length === 0) return null;

  const choose = (file: File | undefined) => {
    if (input.current) input.current.value = '';
    if (file) void send(file);
  };
  const openPicker = () => input.current?.click();

  const acceptsDrag = (e: DragEvent) => !uploading && [...(e.dataTransfer?.types ?? [])].includes('Files');
  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!acceptsDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    if (!dragOver) setDragOver(true);
  };
  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    if (e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget)) return;
    setDragOver(false);
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (uploading) return;
    const dropped = e.dataTransfer?.files;
    if (!dropped || dropped.length === 0) return;
    if (dropped.length > 1) {
      focusNext.current = 'retry';
      setUpload({ stage: 'error', message: 'Drop one file at a time.', file: null });
      return;
    }
    void send(dropped[0]);
  };

  const download = async (f: EvidenceFile) => {
    setBusyId(f.id);
    setRowError(null);
    try {
      const link = await getEvidenceFileLink(f.id);
      if (!link?.url) throw new Error('no link');
      // The signed link answers with an attachment: the browser saves the file, the page never shows it.
      const a = document.createElement('a');
      a.href = link.url;
      a.rel = 'noopener';
      a.setAttribute('download', link.display_name || f.display_name);
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      setRowError(humanError(e, 'The download link could not be created. Try again.', { passDetail: false }));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (f: EvidenceFile) => {
    const ok = await confirm({
      title: 'Remove this file?',
      body: <>“{f.display_name}” will no longer be listed or downloadable.</>,
      irreversible: 'A removed file cannot be brought back.',
      confirmLabel: 'Remove file', danger: true,
    });
    if (!ok) return;
    setBusyId(f.id);
    setRowError(null);
    try {
      await removeEvidenceFile(f.id);
      toast('File removed.');
      onChanged();
    } catch (e) {
      setRowError(humanError(e, 'The file could not be removed. Try again.', { passDetail: false }));
    } finally {
      setBusyId(null);
    }
  };

  const zoneState = uploading ? 'uploading' : dragOver ? 'dragover' : upload.stage === 'done' ? 'done' : 'idle';
  const percent = uploading ? Math.round(upload.progress * 100) : 0;
  const openPreview = (f: EvidenceFile) => { lastPreviewId.current = f.id; setRowError(null); setPreviewKey(f.id); setPreviewing(f); };
  const previewButton = () => (lastPreviewId.current
    ? root.current?.querySelector<HTMLElement>(`[data-preview-for="${lastPreviewId.current}"]`) ?? null : null);

  return (
    <div ref={root} className="space-y-2 pt-1" data-testid={`files-${questionKey}`}>
      {files.length > 0 && (
        <ul className="rounded border border-line divide-y divide-line" aria-label="Attached files">
          {files.map(f => (
            <li key={f.id} className={`px-3 py-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2 ${f.id === newId ? 'evf-row-new' : ''}`}
                data-testid={`file-${f.id}`}>
              <div className="min-w-0">
                <p className="text-xs text-ink break-all" data-testid="file-name">{f.display_name}</p>
                <p className="text-[11px] mono text-soft break-words">
                  {f.type_label} · {formatSize(f.size_bytes)} · {fmtDayZone(f.uploaded_at, zone)} · {f.uploaded_by || 'a former member'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 shrink-0">
                <button type="button" className="btn-mini" onClick={() => openPreview(f)} data-preview-for={f.id}
                        aria-haspopup="dialog" aria-label={`Preview ${f.display_name}`}>
                  <Eye size={12} aria-hidden="true" /> PREVIEW
                </button>
                <button type="button" className="btn-mini" disabled={busyId === f.id} onClick={() => void download(f)}
                        aria-label={`Download ${f.display_name}`}>
                  <Download size={12} aria-hidden="true" /> DOWNLOAD
                </button>
                {canEdit && (
                  <button type="button" className="btn-mini" disabled={busyId === f.id} onClick={() => void remove(f)}
                          aria-label={`Remove ${f.display_name}`}>
                    <Trash2 size={12} aria-hidden="true" /> REMOVE
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <div className="space-y-1.5">
          <input ref={input} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-hidden="true"
                 data-testid={`file-input-${questionKey}`} onChange={e => choose(e.target.files?.[0])} />
          {info.uploads_available ? (
            <>
              <div className="evf-drop" data-state={zoneState} data-testid={`drop-zone-${questionKey}`}
                   onDragEnter={onDragOver} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
                {upload.stage === 'uploading' ? (
                  <div className="evf-progress" data-testid="upload-progress">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs text-ink break-all">Uploading {upload.file.name}</p>
                        <p className="text-[11px] mono text-soft break-words" data-testid="upload-meta">
                          {typeName(upload.file.name)} · {formatSize(upload.file.size)}
                        </p>
                      </div>
                      <button type="button" className="btn-mini shrink-0" data-focus="cancel" data-testid="upload-cancel"
                              onClick={() => abort.current?.abort()} aria-label={`Cancel uploading ${upload.file.name}`}>
                        <X size={12} aria-hidden="true" /> CANCEL
                      </button>
                    </div>
                    <div className="evf-track" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100}
                         aria-valuenow={percent} aria-valuetext={upload.progress >= 1 ? 'Sent, checking the file' : `${percent}%`}
                         data-testid="upload-bar">
                      <span style={{ transform: `scaleX(${upload.progress})` }} />
                    </div>
                    <p className="text-[11px] mono text-soft" aria-hidden="true" data-testid="upload-percent">
                      {upload.progress >= 1 ? 'Sent. Checking the file…' : `${percent}%`}
                    </p>
                  </div>
                ) : (
                  <button type="button" className="evf-drop-button" data-focus="zone" data-testid={`attach-${questionKey}`}
                          onClick={openPicker} aria-describedby={hintId}>
                    <span className="evf-drop-icon" aria-hidden="true">
                      {zoneState === 'done' ? (
                        <svg viewBox="0 0 24 24" width="18" height="18" className="evf-check"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
                      ) : <Paperclip size={16} />}
                    </span>
                    <span className="evf-drop-text">
                      <span className="evf-drop-label">ATTACH EVIDENCE</span>
                      <span className="evf-drop-hint" data-testid="drop-hint">
                        {zoneState === 'dragover' ? 'Release to attach this file'
                          : upload.stage === 'done' ? `“${upload.name}” attached. Drop or choose another file.`
                          : 'Drop a file here, or choose one'}
                      </span>
                    </span>
                  </button>
                )}
              </div>
              <p id={hintId} className="text-[11px] text-soft">PDF, PNG, JPG or DOCX, up to {formatSize(maxBytes)}. Stored privately for your organisation. Cyphward does not read or review it.</p>
            </>
          ) : (
            <p className="text-[11px] text-soft" data-testid="uploads-unavailable">File uploads are not available right now.</p>
          )}
          {upload.stage === 'error' && (
            <div role="alert" className="evf-error" data-testid="file-error">
              <p className="text-xs mono text-accent break-words" data-testid="file-error-text">{upload.message}</p>
              {info.uploads_available && (
                upload.file ? (
                  <button type="button" className="btn-mini shrink-0" data-focus="retry" data-testid="upload-retry"
                          onClick={() => { const again = upload.file; if (again) void send(again); }}>
                    <RefreshCw size={12} aria-hidden="true" /> TRY AGAIN
                  </button>
                ) : (
                  <button type="button" className="btn-mini shrink-0" data-focus="retry" data-testid="upload-choose-again" onClick={openPicker}>
                    <Paperclip size={12} aria-hidden="true" /> CHOOSE ANOTHER FILE
                  </button>
                )
              )}
            </div>
          )}
          <p className="sr-only" aria-live="polite" data-testid="upload-announce">{announce}</p>
        </div>
      )}
      {rowError && !previewing && <p role="alert" className="text-xs mono text-accent break-words" data-testid="file-row-error">{rowError}</p>}

      <EvidencePreview key={previewKey ?? 'none'} file={previewing} zone={zone} onClose={() => setPreviewing(null)} onDownload={f => void download(f)}
                       downloading={!!previewing && busyId === previewing.id} downloadError={previewing ? rowError : null}
                       returnFocusTo={previewButton} />
    </div>
  );
}
