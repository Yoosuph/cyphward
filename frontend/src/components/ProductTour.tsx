import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { TOUR_EVENT, markTourSeen } from '../lib/tour';
import { lockScroll, unlockScroll } from '../lib/scrollLock';

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
  desktopOnly?: boolean;
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
    id: 'domains', targets: ['[data-tour="nav-domains"]', '[data-tour="plate-menu"]'], menuLabel: 'Domains', placement: 'right',
    title: 'Domains',
    body: 'Scans only run on domains you have verified with a DNS TXT record. Add and verify more domains here.',
    touchBody: 'After the tour, tap Menu to find Domains, Remediation, Reports and Compliance. Start in Domains: add your domain and verify ownership with a DNS TXT record before scanning.',
  },
  {
    id: 'scans', targets: ['[data-tour="nav-scans"]', '[data-tour="plate-scans"]'], placement: 'right',
    title: 'Scans',
    body: 'Run a scan on a verified domain and follow its progress. Review which checks completed and which were unavailable. Scheduled scans depend on your workspace settings and allowance.',
  },
  {
    id: 'score', targets: ['[data-tour="score"]'],
    title: 'Your score',
    body: 'Read the score together with its assessment date and coverage. An unassessed workspace is not a clean result. Pending domains or incomplete checks can leave coverage unknown.',
  },
  {
    id: 'findings', targets: ['[data-tour="nav-findings"]', '[data-tour="plate-findings"]'], placement: 'right',
    title: 'Findings',
    body: 'Review recorded issues, their severity, supporting evidence and remediation guidance. Use the evidence to decide what needs attention first.',
  },
  {
    id: 'remediation', targets: ['[data-tour="nav-remediation"]'], placement: 'right', desktopOnly: true,
    title: 'Remediation',
    body: 'Assign and track fixes as tasks. Recheck supported finding types for fresh evidence; marking a task complete alone does not verify a fix.',
  },
  {
    id: 'reports', targets: ['[data-tour="nav-reports"]'], placement: 'right', desktopOnly: true,
    title: 'Reports',
    body: 'Prepare assessment reports with dates, scope and supporting evidence for management or customer reviews.',
  },
  {
    id: 'compliance', targets: ['[data-tour="nav-comply"]'], placement: 'right', desktopOnly: true,
    title: 'Compliance workspace',
    body: 'Organise readiness answers, documents and evidence. These records support a professional review; they are not legal advice or a compliance determination.',
  },
  {
    id: 'cyphbot', targets: ['[data-tour="cyphbot"]'],
    title: 'Ask CyphBot',
    body: import.meta.env.VITE_CYPHWARD_ARTIFACT_LAB === 'true'
      ? 'Ask about recorded security data and request charts. Reports arrive as clickable previews; you choose when to open them.'
      : 'Ask about your recorded findings, assessment scope and next steps. Open CyphBot here, or use Ctrl J (⌘J on Mac).',
    touchBody: import.meta.env.VITE_CYPHWARD_ARTIFACT_LAB === 'true'
      ? 'After the tour, tap CyphBot to ask about recorded data or request a chart. Chat starts in a small window; use its expand icon for full screen. Tap a report preview to open the artifact.'
      : 'After the tour, tap CyphBot to discuss recorded findings. Chat starts in a small window; use its expand icon for full screen.',
  },
  {
    id: 'palette', targets: ['[data-tour="palette"]', '[data-tour="plate-palette"]', '[data-tour="plate-menu"]'],
    title: 'Find anything fast',
    body: "Press Ctrl K (⌘K on Mac) to jump anywhere, and Ctrl J to ask CyphBot about your own findings. That's the tour.",
    touchBody: 'You are ready. Use the bottom dock for everyday pages, and Menu for the rest. Menu also contains command search. Finish to explore your workspace.',
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
  const [viewport, setViewport] = useState(() => ({ w: typeof window === 'undefined' ? 1280 : window.innerWidth, h: typeof window === 'undefined' ? 900 : window.innerHeight }));
  const [cardHeight, setCardHeight] = useState(220);
  const cardRef = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const direction = useRef(1);
  const mobile = viewport.w < 901;
  const steps = useMemo(() => STEPS.filter(item => !mobile || !item.desktopOnly), [mobile]);
  const currentIndex = Math.min(index, steps.length - 1);

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
    const target = returnFocus.current?.isConnected ? returnFocus.current : document.querySelector<HTMLElement>('[data-tour="checklist"] button');
    target?.focus({ preventScroll: true });
  }, [userId]);

  const go = useCallback((delta: number) => {
    direction.current = delta;
    const next = currentIndex + delta;
    if (next >= steps.length) {
      close('done');
      return;
    }
    setIndex(clamp(next, 0, steps.length - 1));
  }, [currentIndex, steps.length, close]);

  useEffect(() => {
    if (!open) return;
    lockScroll();
    return unlockScroll;
  }, [open]);

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
  const step = steps[currentIndex];
  useLayoutEffect(() => {
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
        const dockTarget = !!el.closest('[aria-label="Mobile navigation"]') || el.classList.contains('cyphbot-fab');
        if (!dockTarget && (r.top < 72 || r.bottom > window.innerHeight - 120)) {
          el.scrollIntoView({ block: 'center', behavior: mobile || reduceMotion() ? 'instant' : 'smooth' });
        }
      }
      const r = el?.getBoundingClientRect();
      const next = r ? { top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) } : null;
      setBox(current => (sameBox(current, next) ? current : next));
      const height = window.visualViewport?.height || window.innerHeight;
      setViewport(current => (current.w === window.innerWidth && current.h === height
        ? current : { w: window.innerWidth, h: height }));
      if (cardRef.current) setCardHeight(cardRef.current.offsetHeight);
    };
    measure();
    const resized = () => { scrolled = false; measure(); };
    const id = setInterval(measure, 250);
    window.addEventListener('resize', resized);
    window.addEventListener('scroll', measure, true);
    window.visualViewport?.addEventListener('resize', resized);
    return () => {
      clearInterval(id);
      window.removeEventListener('resize', resized);
      window.removeEventListener('scroll', measure, true);
      window.visualViewport?.removeEventListener('resize', resized);
    };
  }, [open, step, go, viewport.w, viewport.h]);

  useLayoutEffect(() => {
    if (!open || !cardRef.current) return;
    const element = cardRef.current;
    const measure = () => setCardHeight(element.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [open, step.id, mobile]);

  // Keyboard: Esc skips, arrows move, Tab stays inside the card.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close('skipped');
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        go(1);
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        go(-1);
      } else if ((event.ctrlKey || event.metaKey) && ['k', 'j', 'b'].includes(event.key.toLowerCase())) {
        event.preventDefault(); event.stopImmediatePropagation();
      } else if (event.key === 'Tab' && cardRef.current) {
        const items = Array.from(cardRef.current.querySelectorAll<HTMLElement>('button:not(:disabled)'));
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (!cardRef.current.contains(document.activeElement)) {
          event.preventDefault(); first.focus();
        } else if (event.shiftKey && document.activeElement === first) {
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
    if (open) cardRef.current?.querySelector<HTMLElement>('[data-tour-primary]')?.focus({ preventScroll: true });
  }, [open, currentIndex]);

  if (!open || typeof document === 'undefined') return null;

  const vw = viewport.w || window.innerWidth;
  const vh = viewport.h || window.innerHeight;
  const width = Math.min(mobile ? 400 : 360, vw - GUTTER * 2);
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

  let body = mobile && step.touchBody ? step.touchBody : step.body;
  if (!box && step.menuLabel) body += ` On this screen size, open Menu to find ${step.menuLabel}.`;
  const last = currentIndex === steps.length - 1;
  cardStyle.maxHeight = Math.max(120, vh - GUTTER * 2);
  const spotlight = box && box.top < vh && box.top + box.height > 0 ? {
    top: Math.max(8, box.top - 6), left: Math.max(8, box.left - 6),
    width: Math.max(0, Math.min(vw - 8, box.left + box.width + 6) - Math.max(8, box.left - 6)),
    height: Math.max(0, Math.min(vh - 8, box.top + box.height + 6) - Math.max(8, box.top - 6)),
  } : null;

  return createPortal(
    <div className="tour-root" data-tour-step={step.id} aria-live="polite">
      {spotlight
        ? <div key="spot" className="tour-spot" style={spotlight} />
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
          <p className="eyebrow">STEP {currentIndex + 1} OF {steps.length}</p>
          <button type="button" className="tour-close" onClick={() => close('skipped')} aria-label="Skip tour">
            <X size={14} />
          </button>
        </div>
        <h2 id="tour-title" className="font-display text-lg font-medium text-ink mt-2">{step.title}</h2>
        <p id="tour-body" className="text-sm text-soft leading-relaxed mt-1.5">{body}</p>
        <div className="tour-dots" aria-hidden="true">
          {steps.map((item, i) => <span key={item.id} className={i === currentIndex ? 'on' : i < currentIndex ? 'past' : ''} />)}
        </div>
        <div className="flex items-center justify-between gap-2 mt-4">
          <button type="button" className="text-xs text-soft hover:text-ink underline" onClick={() => close('skipped')}>
            Skip tour
          </button>
          <div className="flex items-center gap-2">
            {currentIndex > 0 && (
              <button type="button" className="btn btn-ghost btn-mini" onClick={() => go(-1)}>BACK</button>
            )}
            <button type="button" data-tour-primary className="btn btn-solid btn-mini" onClick={() => go(1)}>
              {last ? 'FINISH' : currentIndex === 0 ? 'START TOUR' : 'NEXT'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
