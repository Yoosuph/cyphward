/**
 * Reviewed wording for evidence file uploads and previews (docs/evidence-preview-2026-11-07).
 *
 * Only these sentences reach the screen. A server message is shown only when it is one of the fixed messages the
 * evidence file API sends (backend/app/compliance/evidence_files.py, evidence_file_store.py and the evidence section
 * of backend/app/api/compliance.py); anything else becomes the plain fallback, so no raw server text is shown.
 */

const FIXED_MESSAGES = new Set([
  'The file needs a name.',
  'Only PDF, PNG, JPG/JPEG or DOCX files up to 10 MB can be attached.',
  'File names with a second extension (such as report.exe.pdf) are not accepted. Rename the file.',
  'The file name is too long.',
  'The file is empty.',
  'The file is larger than 10 MB.',
  'This is not a valid DOCX file.',
  'This DOCX file has too many parts to accept.',
  'This DOCX file expands to an unsafe size, so it was not accepted.',
  'Password-protected DOCX files cannot be attached.',
  'Macro-enabled documents cannot be attached.',
  'File uploads are not available right now.',
  'Your organisation already has uploads running. Try again in a few seconds.',
  'Many uploads are running. Try again in a few seconds.',
  'Another upload is being saved. Try again in a few seconds.',
  'The upload took too long. Try again on a faster connection.',
  'The file could not be stored. Try again.',
  'The upload could not be sent. Check your connection and try again.',
]);

/** Fixed messages that carry a number or a type name. */
const FIXED_PATTERNS = [
  /^The file's contents do not match its (PDF|PNG image|JPEG image|Word document \(DOCX\)) name\. Check the file and try again\.$/,
  /^Your organisation already has \d+ evidence files attached\. Remove one before adding another\.$/,
  /^Your organisation's evidence files are limited to \d+ MB in total\. Remove a file to make room\.$/,
  /^Up to \d+ files can be uploaded per hour\. Try again shortly\.$/,
];

export const UPLOAD_FALLBACK = 'The file could not be attached. Try again.';
export const REFUSED_FALLBACK = 'This file was not accepted. Check the file, or choose another one.';

export function uploadErrorText(e: unknown): string {
  const err = e as { status?: number; message?: string } | null;
  const text = (err?.message || '').trim();
  if (FIXED_MESSAGES.has(text) || FIXED_PATTERNS.some(p => p.test(text))) return text;
  const status = err?.status;
  if (status === 401) return 'Your session has ended. Sign in again to carry on.';
  if (status === 403) return 'Your role cannot do this. Ask an owner or an admin.';
  if (status === 413) return 'The file is larger than 10 MB.';
  if (status === 429) return 'Too many uploads. Wait a moment and try again.';
  if (status === 422) return REFUSED_FALLBACK;
  return UPLOAD_FALLBACK;
}

/** Errors that sending the same file again will not fix: the person needs to choose another file. */
export function needsAnotherFile(e: unknown): boolean {
  const status = (e as { status?: number } | null)?.status;
  return status === 413 || status === 422;
}

export function previewErrorText(e: unknown): string {
  const err = e as { status?: number; message?: string; name?: string } | null;
  const status = err?.status;
  if (status === undefined && (e instanceof TypeError || /failed to fetch|network|load failed/i.test(err?.message || ''))) {
    return 'We could not reach Cyphward. Check your connection and try again.';
  }
  if (status === 401) return 'Your session has ended. Sign in again to carry on.';
  if (status === 404) return 'This file is no longer available. It may have been removed.';
  if (status === 429) return 'Too many previews in a short time. Wait a moment and try again.';
  return 'The preview could not be loaded. Try again, or download the file instead.';
}

export type PreviewKind = 'image' | 'pdf' | 'none';

export function previewKind(contentType: string): PreviewKind {
  if (contentType === 'image/png' || contentType === 'image/jpeg') return 'image';
  if (contentType === 'application/pdf') return 'pdf';
  return 'none';
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
