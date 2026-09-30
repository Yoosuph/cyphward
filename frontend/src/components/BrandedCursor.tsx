import { useEffect, useState, useRef } from 'react';

export default function BrandedCursor() {
  const [pos, setPos] = useState({ x: -100, y: -100 });
  const [trailingPos, setTrailingPos] = useState({ x: -100, y: -100 });
  const [hovered, setHovered] = useState(false);
  const [clicked, setClicked] = useState(false);
  const [visible, setVisible] = useState(false);

  const targetPos = useRef({ x: -100, y: -100 });
  const currentPos = useRef({ x: -100, y: -100 });
  const rafId = useRef<number>(0);

  useEffect(() => {
    // Check if touch device
    const isTouch = window.matchMedia('(pointer: coarse)').matches;
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (isTouch || prefersReduced) return;

    const onMouseMove = (e: MouseEvent) => {
      targetPos.current = { x: e.clientX, y: e.clientY };
      setPos({ x: e.clientX, y: e.clientY });
      if (!visible) setVisible(true);

      // Check if hovering over clickable element
      const target = e.target as HTMLElement | null;
      if (target) {
        const isInteractive = target.closest(
          'a, button, input, select, textarea, [role="button"], .chip, .btn, .clickable, .nav-item, .auth-persona-btn, .layer-tab-btn'
        );
        setHovered(!!isInteractive);
      }
    };

    const onMouseDown = () => setClicked(true);
    const onMouseUp = () => setClicked(false);
    const onMouseLeave = () => setVisible(false);
    const onMouseEnter = () => setVisible(true);

    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mouseup', onMouseUp);
    document.addEventListener('mouseleave', onMouseLeave);
    document.addEventListener('mouseenter', onMouseEnter);

    // Smooth animation loop for the trailing outer ring
    const loop = () => {
      const ease = 0.18;
      currentPos.current.x += (targetPos.current.x - currentPos.current.x) * ease;
      currentPos.current.y += (targetPos.current.y - currentPos.current.y) * ease;
      setTrailingPos({ x: currentPos.current.x, y: currentPos.current.y });
      rafId.current = requestAnimationFrame(loop);
    };
    rafId.current = requestAnimationFrame(loop);

    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mouseup', onMouseUp);
      document.removeEventListener('mouseleave', onMouseLeave);
      document.removeEventListener('mouseenter', onMouseEnter);
      cancelAnimationFrame(rafId.current);
    };
  }, [visible]);

  if (!visible) return null;

  return (
    <div className="branded-cursor-host" aria-hidden="true">
      {/* Outer tracking reticle */}
      <div
        className={`cursor-ring ${hovered ? 'hovered' : ''} ${clicked ? 'clicked' : ''}`}
        style={{
          transform: `translate3d(${trailingPos.x}px, ${trailingPos.y}px, 0) translate(-50%, -50%)`,
        }}
      >
        {/* Hairline crosshair tick marks on outer reticle */}
        <span className="tick tick-top" />
        <span className="tick tick-bottom" />
        <span className="tick tick-left" />
        <span className="tick tick-right" />
      </div>

      {/* Center sharp oxide dot / diamond */}
      <div
        className={`cursor-dot ${hovered ? 'hovered' : ''} ${clicked ? 'clicked' : ''}`}
        style={{
          transform: `translate3d(${pos.x}px, ${pos.y}px, 0) translate(-50%, -50%)`,
        }}
      />
    </div>
  );
}
