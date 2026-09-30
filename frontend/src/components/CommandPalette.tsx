import { useEffect, useMemo, useRef, useState, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowUpRight,
  Moon,
  Play,
  Server,
  ShieldAlert,
  Radar,
  Globe,
  Sliders,
  Copy,
  LogOut,
} from 'lucide-react';
import { toggleTheme } from '../lib/theme';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';

interface Cmd { label: string; hint: string; icon: ReactNode; run: () => void }

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const toast = useToast();
  const { signOut, tenant } = useAuth();
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const cmds: Cmd[] = useMemo(() => ([
    { label: 'Go to Overview', hint: '01', icon: <ArrowUpRight size={15} />, run: () => nav('/') },
    { label: 'Go to Assets inventory', hint: '02', icon: <Server size={15} />, run: () => nav('/assets') },
    { label: 'Go to Security findings', hint: '03', icon: <ShieldAlert size={15} />, run: () => nav('/findings') },
    { label: 'Go to Inngest Scans tracker', hint: '04', icon: <Radar size={15} />, run: () => nav('/scans') },
    { label: 'Go to Domain verification', hint: '05', icon: <Globe size={15} />, run: () => nav('/domains') },
    { label: 'Go to Settings & credentials', hint: '06', icon: <Sliders size={15} />, run: () => nav('/settings') },
    { label: 'Launch security scan', hint: 'inngest', icon: <Play size={15} />, run: () => nav('/scans') },
    { label: 'Toggle theme (Light / Dark)', hint: 'appearance', icon: <Moon size={15} />, run: toggleTheme },
    {
      label: 'Copy build manifest', hint: 'clipboard', icon: <Copy size={15} />,
      run: () => {
        const m = { app: 'cyphward', version: '2.0.0', tenant: tenant?.name, region: 'ng-lagos' };
        navigator.clipboard?.writeText(JSON.stringify(m, null, 2));
        toast('Build manifest copied to clipboard');
      },
    },
    {
      label: 'Sign out', hint: 'session', icon: <LogOut size={15} />,
      run: () => { signOut(); nav('/login', { replace: true }); },
    },
  ]), [nav, toast, signOut, tenant]);

  const filtered = cmds.filter(c => !q || c.label.toLowerCase().includes(q.toLowerCase()));

  useEffect(() => {
    if (open) {
      setQ(''); setSel(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => { setSel(0); }, [q]);
  if (!open) return null;

  const run = (i: number) => {
    const c = filtered[i];
    onClose();
    if (c) c.run();
  };

  return (
    <div className="palette" role="dialog" aria-modal="true"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pal-box">
        <div className="pal-input">
          <ArrowUpRight size={15} />
          <input
            ref={inputRef}
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Type a command or jump to page…"
            onKeyDown={e => {
              if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                const n = filtered.length; if (!n) return;
                setSel(s => (s + (e.key === 'ArrowDown' ? 1 : -1) + n) % n);
              } else if (e.key === 'Enter') {
                e.preventDefault();
                run(sel);
              }
            }}
          />
          <button
            type="button"
            onClick={onClose}
            className="kbd hover:bg-inset cursor-pointer hover:text-ink transition-colors"
            title="Close command palette (Esc)"
            aria-label="Close command palette"
          >
            esc ✕
          </button>
        </div>
        <ul className="pal-list">
          {filtered.map((c, i) => (
            <li
              key={c.label}
              className={`pal-item${i === sel ? ' sel' : ''}`}
              onClick={() => run(i)}
              onPointerMove={() => setSel(i)}
            >
              {c.icon}
              <span className="pl">{c.label}</span>
              <span className="ph">{c.hint}</span>
            </li>
          ))}
          {!filtered.length && <li className="pal-empty">No matching command.</li>}
        </ul>
        <div className="pal-foot">
          <span className="hidden sm:inline">↑↓ NAVIGATE</span>
          <span className="hidden sm:inline">↵ RUN</span>
          <span className="sm:hidden">TAP ANY ACTION TO RUN</span>
          <span>ESC / TAP OUTSIDE TO CLOSE</span>
        </div>
      </div>
    </div>
  );
}
