import { useEffect, useMemo, useRef, useState, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, Moon, FileText, Copy, LogOut } from 'lucide-react';
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
    { label: 'Go to command center', hint: '01', icon: <ArrowUpRight size={15} />, run: () => nav('/') },
    { label: 'Go to compliance', hint: '02', icon: <ArrowUpRight size={15} />, run: () => nav('/comply') },
    { label: 'Go to detection', hint: '03', icon: <ArrowUpRight size={15} />, run: () => nav('/detect') },
    { label: 'Go to score', hint: '04', icon: <ArrowUpRight size={15} />, run: () => nav('/score') },
    { label: 'Go to academy', hint: '05', icon: <ArrowUpRight size={15} />, run: () => nav('/academy') },
    { label: 'Go to copilot', hint: '06', icon: <ArrowUpRight size={15} />, run: () => nav('/copilot') },
    { label: 'Toggle theme', hint: 'light · dark', icon: <Moon size={15} />, run: toggleTheme },
    {
      label: 'Draft breach-notification policy', hint: 'comply', icon: <FileText size={15} />,
      run: () => toast('Policy draft queued — Breach Notification (NDPA-24(1))'),
    },
    {
      label: 'Copy build manifest', hint: 'clipboard', icon: <Copy size={15} />,
      run: () => {
        const m = { app: 'cyphward', version: '0.1.0', tenant: tenant?.name, region: tenant?.region };
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
            placeholder="Type a command…"
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
          <span className="kbd">esc</span>
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
        <div className="pal-foot"><span>↑↓ NAVIGATE</span><span>↵ RUN</span><span>ESC CLOSE</span></div>
      </div>
    </div>
  );
}
