/**
 * Kept so existing callers keep working. New code should import the dialog from './ui/Dialog'
 * (same props, plus `dirty`, `footer`, `ariaLabel`) and read the notes at the top of that file.
 */
import Dialog from './ui/Dialog';

export default Dialog;
export type { DialogProps as ModalProps } from './ui/Dialog';
