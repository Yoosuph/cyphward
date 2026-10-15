import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { TOUR_EVENT, markTourSeen } from '../lib/tour';

type Step = {
  id: string;
  title: string;
  body: string;
  touchBody?: string;
  /** First visible match wins: sidebar on desktop, bottom dock on phones. */
  targets: string[];
  /** Where to find it when no target is visible (items only in the phone menu). */
  menuLabel?: string;
  placement?: 'right';
  /** Skipped when its target is not on screen (e.g. the checklist after setup). */
  optional?: boolean;
};

// Every statement here must stay true of the product.
const STEPS: Step[] = [
  {
    id: 'welcome', targets: [],
    title: 'Welcome to Cyphward',
    body: 'A one-minute tour of where things live. Skip it any time and replay it later from the Getting started card or the command palette.',
  },
  {
    id: 'checklist', targets: ['[data-tour="checklist"]'], optional: true,
    title: 'Your setup checklist',
    body: 'Each step ticks itself off from what has actually happened in your workspace. The next step always has a button.',
  },
  {
    id: 'domains', targets: ['[data-tour="nav-domains"]'], menuLabel: 'Domains', placement: 'right',
    title: 'Domains',
    body: 'Scans only run on domains you have verified with a DNS TXT record. Add and verify more domains here.',
  },
  {
    id: 'scans', targets: ['[data-tour="nav-scans"]', '[data-tour="plate-scans"]'], placement: 'right',
    title: 'Scans',
    body: "Start a scan and follow its progress. Each scan lists what it checked, what it couldn't check and why. Verified domains are also rescanned every day.",
  },
  {
    id: 'score', targets: ['[data-tour="score"]'],
    title: 'Your score',
    body: 'A 0–100 score from the checks we declare: SPF, DMARC, HTTP headers, TLS certificates and open ports. A grade appears once every verified domain has a complete scan.',
  },
  {
    id: 'findings', targets: ['[data-tour="nav-findings"]', '[data-tour="plate-findings"]'], placement: 'right',
    title: 'Findings',
    body: 'Every issue comes with the evidence we saw, a plain-English explanation and a fix.',
  },
  {
    id: 'remediation', targets: ['[data-tour="nav-remediation"]'], menuLabel: 'Remediation', placement: 'right',
    title: 'Remediation',
    body: 'Track fixes as tasks, assign them, and run a recheck to confirm the fix worked.',
  },
  {
    id: 'reports', targets: ['[data-tour="nav-reports"]'], menuLabel: 'Reports', placement: 'right',
    title: 'Reports',
    body: 'Board-ready reports of your latest assessment, to print or send.',
  },
  {
    id: 'palette', targets: ['[data-tour="palette"]', '[data-tour="plate-palette"]'],
    title: 'Find anything fast',
    body: "Press Ctrl K (⌘K on Mac) to jump anywhere, and Ctrl J to ask CyphBot about your own findings. That's the tour.",
    touchBody: "Tap MENU to reach every page, or tap CyphBot to ask about your own findings. That's the tour.",
  },
];

const GUTTER = 16;
const GAP = 12;

function isVisible(el: Element) {
  const rect = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  // Off-canvas drawers (the phone sidebar) keep their size but sit off screen.
  const onScreen = rect.right > 0 && rect.left < window.innerWidth;
  return rect.width > 0 && rect.height > 0 && onScreen && style.visibility !== 'hidden'
    && style.display !== 'none' && !el.closest('[aria-hidden="true"], [inert]');
}

function findTarget(step: Step): HTMLElement | null {
  for (const selector of step.targets) {
    for (const el of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
      if (isVisible(el)) return el;
    }
  }
  return null;
}

const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));
type Box = { top: number; left: number; width: number; height: number };
const sameBox = (a: Box | null, b: Box | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

export default function ProductTour() {
  const { user } = useAuth();
  const location = useLocation();
  const nav = useNavigate();
  const userId = user?.id;

  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const [viewport, setViewport] = useState({ w: 0, h: 0 });
  const [cardHeight, setCardHeight] = useState(220);
  const cardRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const direction = useRef(1);

  const begin = useCallback(() => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    direction.current = 1;
    setIndex(0);
    setOpen(true);
  }, []);

  const close = useCallback((outcome: 'done' | 'skipped') => {
    markTourSeen(userId, outcome);
    setOpen(false);
    setBox(null);
    returnFocus.current?.focus?.();
  }, [userId]);

  const go = useCallback((delta: number) => {
    direction.current = delta;
    const next = index + delta;
    if (next >= STEPS.length) {
      close('done');
      return;
    }
    setIndex(clamp(next, 0, STEPS.length - 1));
  }, [index, close]);

  // Started by Overview on a genuine first run (no completed scan yet), or
  // replayed from the checklist or the command palette. Never auto-started
  // for an established workspace.
  useEffect(() => {
    const onStart = () => {
      if (location.pathname !== '/overview') nav('/overview');
      begin();
    };
    window.addEventListener(TOUR_EVENT, onStart);
    return () => window.removeEventListener(TOUR_EVENT, onStart);
  }, [begin, nav, location.pathname]);

  // Track the current target (pages render asynchronously), keep it in view.
  const step = STEPS[index];
  useEffect(() => {
    if (!open) return;
    const startedAt = Date.now();
    let scrolled = false;
    const measure = () => {
      const el = findTarget(step);
      if (!el && step.optional && Date.now() - startedAt > 1200) {
        go(direction.current >= 0 ? 1 : -1);
        return;
      }
      if (el && !scrolled) {
        scrolled = true;
        const r = el.getBoundingClientRect();
        if (r.top < 72 || r.bottom > window.innerHeight - 120) {
          el.scrollIntoView({ block: 'center', behavior: reduceMotion() ? 'auto' : 'smooth' });
        }
      }
      const r = el?.getBoundingClientRect();
      const next = r ? { top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) } : null;
      setBox(current => (sameBox(current, next) ? current : next));
      setViewport(current => (current.w === window.innerWidth && current.h === window.innerHeight
        ? current : { w: window.innerWidth, h: window.innerHeight }));
      if (cardRef.current) setCardHeight(cardRef.current.offsetHeight);
    };
    measure();
    const id = setInterval(measure, 250);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      clearInterval(id);
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [open, step, go]);

  // Keyboard: Esc skips, arrows move, Tab stays inside the card.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close('skipped');
      } else if (event.key === 'ArrowRight') {
        go(1);
      } else if (event.key === 'ArrowLeft') {
        go(-1);
      } else if (event.key === 'Tab' && cardRef.current) {
        const items = Array.from(cardRef.current.querySelectorAll<HTMLElement>('button'));
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, go, close]);

  // Move focus to the primary action on every step.
  useEffect(() => {
    if (open) cardRef.current?.querySelector<HTMLElement>('[data-tour-primary]')?.focus();
  }, [open, index]);

  if (!open || typeof document === 'undefined') return null;

  const vw = viewport.w || window.innerWidth;
  const vh = viewport.h || window.innerHeight;
  const width = Math.min(360, vw - GUTTER * 2);
  let cardStyle: CSSProperties;
  if (!box) {
    cardStyle = { width, left: (vw - width) / 2, top: clamp(vh / 2 - cardHeight / 2, GUTTER, vh - cardHeight - GUTTER) };
  } else {
    const roomRight = vw - (box.left + box.width) - GAP - GUTTER;
    const roomBelow = vh - (box.top + box.height) - GAP - GUTTER;
    const roomAbove = box.top - GAP - GUTTER;
    if (step.placement === 'right' && roomRight >= width) {
      cardStyle = { width, left: box.left + box.width + GAP, top: clamp(box.top + box.height / 2 - cardHeight / 2, GUTTER, vh - cardHeight - GUTTER) };
    } else {
      const left = clamp(box.left + box.width / 2 - width / 2, GUTTER, vw - width - GUTTER);
      const top = roomBelow >= cardHeight ? box.top + box.height + GAP
        : roomAbove >= cardHeight ? box.top - GAP - cardHeight
        : clamp(vh - cardHeight - GUTTER, GUTTER, vh);
      cardStyle = { width, left, top };
    }
  }

  const touch = window.matchMedia('(pointer: coarse)').matches;
  let body = touch && step.touchBody ? step.touchBody : step.body;
  if (!box && step.menuLabel) body += ` On this screen size, open Menu to find ${step.menuLabel}.`;
  const last = index === STEPS.length - 1;

  return createPortal(
    <div className="tour-root" aria-live="polite">
      {box
        ? <div key="spot" className="tour-spot" style={{ top: box.top - 6, left: box.left - 6, width: box.width + 12, height: box.height + 12 }} />
        : <div key="scrim" className="tour-scrim" />}
      <div className="tour-blocker" />
      <div
        ref={cardRef}
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        style={cardStyle}
      >
        <div className="flex items-center justify-between gap-3">
          <p className="eyebrow">STEP {index + 1} OF {STEPS.length}</p>
          <button type="button" className="tour-close" onClick={() => close('skipped')} aria-label="Skip tour">
            <X size={14} />
          </button>
        </div>
        <h2 id="tour-title" className="font-display text-lg font-medium text-ink mt-2">{step.title}</h2>
        <p id="tour-body" className="text-sm text-soft leading-relaxed mt-1.5">{body}</p>
        <div className="tour-dots" aria-hidden="true">
          {STEPS.map((item, i) => <span key={item.id} className={i === index ? 'on' : i < index ? 'past' : ''} />)}
        </div>
        <div className="flex items-center justify-between gap-2 mt-4">
          <button type="button" className="text-xs text-soft hover:text-ink underline" onClick={() => close('skipped')}>
            Skip tour
          </button>
          <div className="flex items-center gap-2">
            {index > 0 && (
              <button type="button" className="btn btn-ghost btn-mini" onClick={() => go(-1)}>BACK</button>
            )}
            <button type="button" data-tour-primary className="btn btn-solid btn-mini" onClick={() => go(1)}>
              {last ? 'FINISH' : index === 0 ? 'START TOUR' : 'NEXT'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
