import { useEffect, useLayoutEffect, useRef } from 'react';

const useIsoLayout = typeof window === 'undefined' ? useEffect : useLayoutEffect;

/** Watches [data-reveal] inside the returned node and marks each one
 * in view. Above-the-fold pieces are marked before paint so they do not
 * flash blank. */
export function usePageMotion<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useIsoLayout(() => {
    const root = ref.current;
    if (!root) return;
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-reveal]'));
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduce) document.documentElement.classList.add('motion');
    if (reduce) {
      nodes.forEach(node => node.classList.add('is-in'));
      return;
    }

    const view = window.innerHeight;
    const waiting: HTMLElement[] = [];
    nodes.forEach(node => {
      if (node.getBoundingClientRect().top < view * 0.92) node.classList.add('is-in');
      else waiting.push(node);
    });
    if (!waiting.length) return;

    const io = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { threshold: 0.16, rootMargin: '0px 0px -8% 0px' });
    waiting.forEach(node => io.observe(node));
    return () => io.disconnect();
  }, []);

  return ref;
}
