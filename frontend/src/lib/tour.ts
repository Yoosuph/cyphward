/** First-run product tour: start signal and per-user "seen" flag. */
export const TOUR_EVENT = 'cyphward:start-tour';
const TOUR_VERSION = 1;

const key = (userId: string | undefined) => `cyphward-tour-v${TOUR_VERSION}:${userId || 'anonymous'}`;

/** Replay the tour from anywhere (checklist, command palette). */
export function startTour(): void {
  window.dispatchEvent(new CustomEvent(TOUR_EVENT));
}

/** Storage that is blocked or unavailable counts as seen, so the tour never nags. */
export function tourSeen(userId: string | undefined): boolean {
  try {
    return localStorage.getItem(key(userId)) !== null;
  } catch {
    return true;
  }
}

export function markTourSeen(userId: string | undefined, outcome: 'done' | 'skipped'): void {
  try {
    localStorage.setItem(key(userId), outcome);
  } catch {
    /* best effort */
  }
}
