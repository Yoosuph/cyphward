import { useEffect, useRef, useState } from 'react';
import { useDialogClose } from './ui/Dialog';

/** A report is a complete HTML document. Keep its styles inside its own document. */
export default function ReportPreview({ html, title }: { html: string; title: string }) {
  const close = useDialogClose();
  const frame = useRef<HTMLIFrameElement>(null);
  const cleanup = useRef<() => void>();
  const [height, setHeight] = useState(280);
  useEffect(() => () => cleanup.current?.(), []);

  const loaded = () => {
    cleanup.current?.();
    const element = frame.current;
    const doc = element?.contentDocument;
    if (!element || !doc?.body) return;
    // The parent may measure this document; report scripts remain disabled.
    const measure = () => setHeight(Math.max(280, Math.ceil(doc.body.scrollHeight)));
    const observer = new ResizeObserver(measure);
    observer.observe(doc.body);
    measure();
    doc.querySelectorAll('a[href]').forEach(link => {
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    });
    // Keyboard events do not bubble across documents. Preserve dialog dismissal
    // and move Tab back to its controls at the report's first/last link.
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key !== 'Tab') return;
      const links = [...doc.querySelectorAll<HTMLElement>('a[href], [tabindex="0"]')]
        .filter(link => link.getClientRects().length > 0);
      const atBoundary = links.length === 0 || (event.shiftKey
        ? doc.activeElement === links[0] : doc.activeElement === links[links.length - 1]);
      if (!atBoundary) return;
      const panel = element.closest('[role="dialog"]');
      const controls = [...(panel?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], iframe, input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]') ?? [])]
        .filter(control => control.getClientRects().length > 0);
      if (!controls.length) return;
      event.preventDefault();
      const next = (controls.indexOf(element) + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
      controls[next].focus();
    };
    doc.addEventListener('keydown', onKey);
    cleanup.current = () => { observer.disconnect(); doc.removeEventListener('keydown', onKey); };
  };

  return <div data-testid="report-preview" className="overflow-hidden rounded border border-line bg-inset">
    <iframe ref={frame} title={title} srcDoc={html} onLoad={loaded}
      sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer" className="block w-full border-0" style={{ height }} />
  </div>;
}
