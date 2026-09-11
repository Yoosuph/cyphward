import { FormEvent, useEffect, useRef, useState } from 'react';
import { FileText, Send } from 'lucide-react';
import { getCopilotSession } from '../lib/api';
import { useAsync } from '../lib/hooks';
import ChatBubble, { BubbleAction } from '../components/ChatBubble';
import { PageHead, Loading } from '../components/ui';
import { useToast } from '../components/Toast';
import type { Source } from '../data/mock';

interface Msg {
  id: number;
  role: 'user' | 'ai';
  text: string;
  sources?: Source[];
  actions?: BubbleAction[];
  fresh?: boolean;
}

export default function Copilot() {
  const qa = useAsync(getCopilotSession);
  const toast = useToast();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [thinking, setThinking] = useState(false);
  const [input, setInput] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [msgs, thinking]);

  const send = (q: string) => {
    const text = q.trim();
    if (!text || thinking || !qa.data) return;
    const match = qa.data.pairs.find(p => p.q.toLowerCase() === text.toLowerCase());
    const ans = match ?? qa.data.fallback;
    setMsgs(m => [...m, { id: Date.now(), role: 'user', text }]);
    setThinking(true);
    setInput('');
    setTimeout(() => {
      setThinking(false);
      setMsgs(m => [
        ...m,
        {
          id: Date.now() + 1,
          role: 'ai',
          text: ans.a,
          sources: ans.sources,
          actions: ans.actions?.map(a => ({ label: a.label, kind: a.kind, run: () => toast(a.toast) })),
          fresh: true,
        },
      ]);
    }, 900);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  return (
    <>
      <PageHead
        eyebrow="LAYER 06 · COPILOT"
        title="Ask the substrate."
        note="Grounded answers over your compliance corpus — every claim cites its source, and every fix can become a draft or a remediation in one click."
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="panel chat-panel lg:col-span-8">
          <div className="chat-scroll">
            {msgs.length === 0 && qa.data && (
              <div className="chat-empty">
                <p className="eyebrow mb-3">SUGGESTED</p>
                {qa.data.pairs.map(p => (
                  <button key={p.q} className="chip" onClick={() => send(p.q)}>
                    {p.q}
                  </button>
                ))}
                <p className="chat-hint">
                  ANSWERS ARE GROUNDED IN {qa.data.sources.length} CONNECTED SOURCES ·
                  NOTHING LEAVES THIS BROWSER
                </p>
              </div>
            )}
            {msgs.map(m => (
              <ChatBubble
                key={m.id}
                role={m.role}
                text={m.text}
                sources={m.sources}
                actions={m.actions}
                animate={m.fresh}
              />
            ))}
            {thinking && <p className="thinking">RETRIEVING SOURCES —</p>}
            <div ref={endRef} />
          </div>

          <form className="chat-input" onSubmit={onSubmit}>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask about NDPA duties, gaps, breaches…"
            />
            <button className="btn btn-solid" type="submit">
              <Send size={13} />SEND
            </button>
          </form>
        </div>

        <div className="lg:col-span-4 flex flex-col gap-6">
          <div className="panel">
            <header className="panel-head">
              <p className="eyebrow">GROUNDING CORPUS</p>
              <span className="ph-hint mono">RAG</span>
            </header>
            <div className="panel-body">
              {qa.data ? (
                <div className="src-stack">
                  {qa.data.sources.map(s => (
                    <span key={s.id} className="src-chip mono"><FileText size={11} />{s.label}</span>
                  ))}
                </div>
              ) : (
                <Loading label="CORPUS" />
              )}
            </div>
          </div>
          <div className="panel">
            <div className="panel-body">
              <p className="eyebrow">HOW IT ANSWERS</p>
              <p className="corpus-note">
                Retrieval first, generation second. The copilot pulls the exact sections that
                answer your question, cites them, and only then writes — so every sentence is
                traceable to a source in the corpus.
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
