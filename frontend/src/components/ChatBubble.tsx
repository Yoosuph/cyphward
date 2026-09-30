import { useEffect, useState } from 'react';
import { FileText } from 'lucide-react';
import type { Source } from '../types';

export interface BubbleAction { label: string; kind: 'solid' | 'ghost'; run: () => void }

interface Props {
  role: 'user' | 'ai';
  text: string;
  sources?: Source[];
  actions?: BubbleAction[];
  animate?: boolean;
}

export default function ChatBubble({ role, text, sources, actions, animate }: Props) {
  const [n, setN] = useState(animate ? 0 : text.length);

  useEffect(() => {
    if (!animate) { setN(text.length); return; }
    setN(0);
    const iv = setInterval(() => {
      setN(prev => {
        if (prev >= text.length) { clearInterval(iv); return prev; }
        return prev + 3;
      });
    }, 16);
    return () => clearInterval(iv);
  }, [text, animate]);

  const done = n >= text.length;

  if (role === 'user') {
    return <div className="msg-user">{text}</div>;
  }

  return (
    <div className="msg-ai">
      <p className="eyebrow who">CYPHWARD COPILOT</p>
      <p className="msg-body">
        {text.slice(0, n)}
        {!done && <span className="caret" />}
      </p>
      {done && sources && sources.length > 0 && (
        <div className="src-row">
          <span className="src-lbl mono">SOURCES</span>
          {sources.map(s => (
            <span key={s.id} className="src-chip mono"><FileText size={11} />{s.label}</span>
          ))}
        </div>
      )}
      {done && actions && actions.length > 0 && (
        <div className="msg-actions">
          {actions.map(a => (
            <button key={a.label} className={`btn ${a.kind === 'solid' ? 'btn-solid' : 'btn-ghost'}`} onClick={a.run}>
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
