/* One row of the bell's panel (components/NotificationBell.tsx), with swipe to clear on touch screens.
 *
 * Swipe: a touch that moves left more than it moves down slides the row and shows Clear behind it. Let go past
 * the clear threshold and the row is cleared; past the reveal threshold it stays open on Clear (tap it); short of
 * that it slides back. A touch that moves down first is left to the browser (the row has touch-action: pan-y), so
 * the list still scrolls. Mouse and pen input never swipe.
 * Reduced motion: the row does not follow the finger and nothing slides; Clear appears at once over the row's end.
 * The gesture is never the only way: every row has a visible Clear button for keyboard and screen-reader users.
 * Clearing hides the row and marks it read through the existing mark-read route; nothing is deleted.
 */
import { useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { X } from 'lucide-react';
import { NOTIFY_CLEAR, SEVERITY_LABEL, timeLabel, type NotificationItem } from '../lib/notifications';

/** Movement before the row decides between a swipe and a scroll. */
export const SWIPE_SLOP = 10;
/** Width of the Clear action a swipe uncovers; letting go past half of it leaves the row open on Clear. */
export const SWIPE_REVEAL = 88;
/** Letting go this far left clears the row: 45% of its width, never less than 120px. */
export const swipeClearAt = (rowWidth: number) => Math.max(120, Math.round(rowWidth * 0.45));

interface Props {
  item: NotificationItem;
  reduceMotion: boolean;
  onOpen: (item: NotificationItem) => void;
  onMark: (item: NotificationItem) => void;
  onClear: (item: NotificationItem) => void;
}

type Gesture = { id: number; x: number; y: number; base: number; axis: 'x' | 'y' | null; width: number };

export default function NotificationRow({ item, reduceMotion, onOpen, onMark, onClear }: Props) {
  const row = useRef<HTMLLIElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const swallowClick = useRef(false);
  const [offset, setOffset] = useState(0);         // how far the row has slid left (<= 0); always 0 under reduced motion
  const [revealed, setRevealed] = useState(false); // resting open on Clear
  const [dragging, setDragging] = useState(false);
  const [showAction, setShowAction] = useState(false);

  const reset = () => { setOffset(0); setRevealed(false); setShowAction(false); setDragging(false); };

  const onPointerDown = (e: ReactPointerEvent<HTMLLIElement>) => {
    swallowClick.current = false;  // a new press: whatever the last drag left behind is over
    if (e.pointerType !== 'touch' || !e.isPrimary) return;
    gesture.current = { id: e.pointerId, x: e.clientX, y: e.clientY, base: revealed ? -SWIPE_REVEAL : 0, axis: null,
      width: row.current?.offsetWidth || 320 };
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLLIElement>) => {
    const g = gesture.current;
    if (!g || g.id !== e.pointerId) return;
    const dx = e.clientX - g.x;
    const dy = e.clientY - g.y;
    if (!g.axis) {
      if (Math.abs(dx) < SWIPE_SLOP && Math.abs(dy) < SWIPE_SLOP) return;
      g.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y';
      if (g.axis === 'y') { gesture.current = null; return; }  // a scroll: the browser has it
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* the pointer already ended */ }
      setDragging(true);
    }
    const travel = Math.min(0, Math.max(-g.width, g.base + dx));
    if (reduceMotion) setShowAction(travel <= -SWIPE_SLOP);
    else { setOffset(travel); setShowAction(travel < 0); }
  };

  const finish = (e: ReactPointerEvent<HTMLLIElement>, cancelled: boolean) => {
    const g = gesture.current;
    if (!g || g.id !== e.pointerId) return;
    gesture.current = null;
    if (g.axis !== 'x') return;
    swallowClick.current = true;  // the click a drag can leave behind must not open the item
    window.setTimeout(() => { swallowClick.current = false; }, 400);
    setDragging(false);
    if (cancelled) {
      setOffset(reduceMotion ? 0 : g.base); setRevealed(g.base < 0); setShowAction(g.base < 0);
      return;
    }
    const travel = -Math.min(0, Math.max(-g.width, g.base + (e.clientX - g.x)));
    if (travel >= swipeClearAt(g.width)) { reset(); onClear(item); return; }
    if (travel >= SWIPE_REVEAL / 2) {
      setRevealed(true); setShowAction(true); setOffset(reduceMotion ? 0 : -SWIPE_REVEAL);
      return;
    }
    reset();
  };

  const onClickCapture = (e: ReactMouseEvent) => {
    if (swallowClick.current) {
      // The click a drag can leave behind.
      e.preventDefault();
      e.stopPropagation();
      swallowClick.current = false;
      return;
    }
    if (!revealed) return;
    // On an open row, Clear (uncovered or the button) and Mark read do what they say and close the row themselves.
    // Closing it here would re-render before their own click handlers run (React flushes a click's updates between
    // the capture and bubble phases) and unmount the uncovered Clear. A tap anywhere else only closes the row.
    if ((e.target as Element).closest?.('.notif-swipe-action, .notif-actions button')) return;
    e.preventDefault();
    e.stopPropagation();
    reset();
  };

  const state = dragging ? 'dragging' : revealed ? 'revealed' : 'idle';
  return (
    <li ref={row} className={`notif-item ${item.read_at ? 'is-read' : 'is-unread'}`}
        data-testid="notif-item" data-id={item.id} data-read={item.read_at ? 'true' : 'false'} data-swipe={state}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={e => finish(e, false)} onPointerCancel={e => finish(e, true)}
        onClickCapture={onClickCapture}>
      <div className={`notif-swipe${dragging ? ' is-dragging' : ''}`}
           style={offset ? { transform: `translateX(${offset}px)` } : undefined}>
        <button type="button" className="notif-open" onClick={() => onOpen(item)}>
          <span className={`notif-sev sev-${item.severity}`}>
            {SEVERITY_LABEL[item.severity] || 'Info'}
            {!item.read_at && <span className="sr-only">, unread</span>}
          </span>
          <span className="notif-item-title">{item.title}</span>
          {item.body && <span className="notif-item-body">{item.body}</span>}
          <span className="notif-meta">
            {timeLabel(item.created_at)}
            {item.count && item.count > 1 ? ` · ${item.count} events` : ''}
          </span>
        </button>
        <div className="notif-actions">
          {!item.read_at && (
            <button type="button" className="notif-tool notif-mark" data-testid="notif-mark"
                    aria-label={`Mark read: ${item.title}`} onClick={() => { reset(); onMark(item); }}>
              Mark read
            </button>
          )}
          <button type="button" className="notif-tool notif-clear" data-testid="notif-clear"
                  aria-label={`${NOTIFY_CLEAR}: ${item.title}`} onClick={() => { reset(); onClear(item); }}>
            {NOTIFY_CLEAR}
          </button>
        </div>
      </div>
      {showAction && (
        // What the swipe uncovers. Touch only, so it is hidden from assistive technology and the Tab order: the
        // row's own Clear button above does the same thing for everyone else.
        <div className={`notif-swipe-action${reduceMotion ? ' is-over' : ''}`} aria-hidden="true" data-testid="notif-swipe-clear"
             style={{ width: reduceMotion ? SWIPE_REVEAL : Math.max(SWIPE_REVEAL, -offset) }}
             onClick={() => { reset(); onClear(item); }}>
          <X size={16} aria-hidden="true" />
          <span>{NOTIFY_CLEAR}</span>
        </div>
      )}
    </li>
  );
}
