import { useRef, useState } from 'react';
import { Download, Paperclip, Trash2 } from 'lucide-react';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import {
  getEvidenceFileLink, removeEvidenceFile, uploadEvidenceFile,
  type EvidenceFile, type EvidenceFileList,
} from '../../lib/api';
import { errorText, fmtDayZone } from './shared';

/**
 * Files attached to the evidence of one answer. Everyone in the organisation sees the list and can download;
 * owners and admins attach and remove. The checks here mirror the server's (type and size) so a bad file is
 * refused before it is sent; the server checks again, by content.
 */

const EXTENSIONS: Record<string, string> = { pdf: 'PDF', png: 'PNG', jpg: 'JPEG', jpeg: 'JPEG', docx: 'DOCX' };
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.docx';
const DEFAULT_MAX = 10 * 1024 * 1024;
const SECOND_EXTENSION = /\.[A-Za-z][A-Za-z0-9]{0,5}(?=\.|$)/;

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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

export default function EvidenceFiles({ questionKey, info, zone, canEdit, onChanged }: {
  questionKey: string; info: EvidenceFileList; zone: string; canEdit: boolean; onChanged: () => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [uploadingName, setUploadingName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const files = info.files.filter(f => f.question_key === questionKey);
  const uploading = progress !== null;

  if (!canEdit && files.length === 0) return null;

  const choose = async (file: File | undefined) => {
    if (input.current) input.current.value = '';
    if (!file) return;
    const problem = fileProblem(file, info.limits?.max_bytes);
    if (problem) { setError(problem); return; }
    setError(null);
    setUploadingName(file.name);
    setProgress(0);
    try {
      await uploadEvidenceFile(questionKey, file, f => setProgress(f));
      toast('File attached.');
      onChanged();
    } catch (e) {
      setError(errorText(e, 'The file could not be attached.'));
    } finally {
      setProgress(null);
    }
  };

  const download = async (f: EvidenceFile) => {
    setBusyId(f.id);
    setError(null);
    try {
      const link = await getEvidenceFileLink(f.id);
      if (!link?.url) throw new Error('No download link came back.');
      const a = document.createElement('a');
      a.href = link.url;
      a.rel = 'noopener';
      a.setAttribute('download', link.display_name || f.display_name);
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      setError(errorText(e, 'The download link could not be created.'));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (f: EvidenceFile) => {
    const ok = await confirm({
      title: 'Remove this file?',
      body: <>“{f.display_name}” will no longer be listed or downloadable. This cannot be undone.</>,
      confirmLabel: 'REMOVE', danger: true,
    });
    if (!ok) return;
    setBusyId(f.id);
    setError(null);
    try {
      await removeEvidenceFile(f.id);
      toast('File removed.');
      onChanged();
    } catch (e) {
      setError(errorText(e, 'The file could not be removed.'));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-2 pt-1" data-testid={`files-${questionKey}`}>
      {files.length > 0 && (
        <ul className="rounded border border-line divide-y divide-line" aria-label="Attached files">
          {files.map(f => (
            <li key={f.id} className="px-3 py-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2" data-testid={`file-${f.id}`}>
              <div className="min-w-0">
                <p className="text-xs text-ink break-all" data-testid="file-name">{f.display_name}</p>
                <p className="text-[11px] mono text-soft break-words">
                  {f.type_label} · {formatSize(f.size_bytes)} · {fmtDayZone(f.uploaded_at, zone)} · {f.uploaded_by || 'a former member'}
                </p>
              </div>
              <div className="flex gap-2 shrink-0">
                <button type="button" className="btn-mini" disabled={busyId === f.id} onClick={() => void download(f)}
                        aria-label={`Download ${f.display_name}`}>
                  <Download size={12} /> DOWNLOAD
                </button>
                {canEdit && (
                  <button type="button" className="btn-mini" disabled={busyId === f.id} onClick={() => void remove(f)}
                          aria-label={`Remove ${f.display_name}`}>
                    <Trash2 size={12} /> REMOVE
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
                 data-testid={`file-input-${questionKey}`} onChange={e => void choose(e.target.files?.[0])} />
          {info.uploads_available ? (
            <>
              <button type="button" className="btn-mini" disabled={uploading} onClick={() => input.current?.click()}>
                <Paperclip size={12} /> ATTACH EVIDENCE
              </button>
              <p className="text-[11px] text-soft">PDF, PNG, JPG or DOCX, up to {formatSize(info.limits?.max_bytes ?? DEFAULT_MAX)}. Stored privately for your organisation. Cyphward does not read or review it.</p>
            </>
          ) : (
            <p className="text-[11px] text-soft" data-testid="uploads-unavailable">File uploads are not available right now.</p>
          )}
          {uploading && (
            <div role="status" aria-live="polite" className="text-[11px] mono text-soft" data-testid="upload-progress">
              Uploading {uploadingName}… {Math.round((progress ?? 0) * 100)}%
              <progress className="block w-full max-w-xs mt-1" max={1} value={progress ?? 0} aria-label="Upload progress" />
            </div>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-xs mono text-accent break-words" data-testid="file-error">{error}</p>}
    </div>
  );
}
