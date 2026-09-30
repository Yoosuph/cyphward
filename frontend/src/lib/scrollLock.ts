let lockCount = 0;

/**
 * Reference-counted body scroll lock.
 * Prevents background scroll when modals, drawers, or command palette overlays are active,
 * and handles nested or sequential overlays without prematurely restoring scroll.
 */
export function lockScroll(): void {
  if (typeof document === 'undefined') return;
  lockCount++;
  if (lockCount === 1) {
    document.body.classList.add('scroll-locked', 'modal-open', 'drawer-open');
  }
}

export function unlockScroll(): void {
  if (typeof document === 'undefined') return;
  lockCount = Math.max(0, lockCount - 1);
  if (lockCount === 0) {
    document.body.classList.remove('scroll-locked', 'modal-open', 'drawer-open');
  }
}
