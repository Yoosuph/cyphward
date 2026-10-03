import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles,
  Send,
  X,
  RotateCcw,
  Copy,
  Check,
  ShieldAlert,
  ArrowUpRight,
  Terminal,
  Cpu,
  ShieldCheck,
  FileText,
  Lock,
} from 'lucide-react';
import { askCyphBot, streamCyphBot, type CyphBotMessage } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';

interface Props {
  open: boolean;
  onClose: () => void;
}

interface ChatEntry {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  isStreaming?: boolean;
  sources?: Array<{ id: string; label: string }>;
  actions?: Array<{ label: string; kind?: string; path?: string; toast?: string }>;
  timestamp: string;
}

const QUICK_PROMPTS = [
  {
    icon: ShieldAlert,
    label: 'Email spoofing (DMARC)',
    prompt: 'How do we stop email spoofing with DMARC, and how do we turn on p=reject?',
  },
  {
    icon: ShieldCheck,
    label: 'NDPA 2023 duties',
    prompt: 'What does NDPA 2023 Section 39 require us to do to protect data?',
  },
  {
    icon: Terminal,
    label: 'Nginx HSTS & TLS 1.3',
    prompt: 'Give me a ready-to-use Nginx config for HSTS, TLS 1.3, and security headers.',
  },
  {
    icon: FileText,
    label: 'Board security update',
    prompt: 'Draft a 3-point security update for our Board of Directors.',
  },
];

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-2.5 rounded-xl border border-line bg-inset overflow-hidden shadow-xs">
      <div className="flex items-center justify-between px-3.5 py-1.5 border-b border-line bg-inset/80 text-[10.5px] mono text-soft">
        <span className="font-medium tracking-wider">{lang?.toUpperCase() || 'CODE'}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2 py-0.5 rounded text-soft hover:text-ink hover:bg-raised transition-all text-[11px]"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check size={11} className="text-ok" />
              <span className="text-ok font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={11} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto mono text-ink font-mono text-[11.5px] leading-relaxed select-text">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// Inline formatting: **bold** and `code` → real elements (they used to show
// up as literal asterisks/backticks). Unmatched tokens while streaming stay
// as plain text until the closing marker arrives.
function inlineFormat(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('**')) {
      nodes.push(
        <strong key={key++} className="font-semibold text-ink">
          {tok.slice(2, -2)}
        </strong>
      );
    } else {
      nodes.push(
        <code key={key++} className="px-1 py-px rounded bg-inset border border-line mono text-[11px] text-accent">
          {tok.slice(1, -1)}
        </code>
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function FormattedMessage({ content, isStreaming }: { content: string; isStreaming?: boolean }) {
  const parts: React.ReactNode[] = [];
  const lines = content.split('\n');
  let inCode = false;
  let codeBuffer: string[] = [];
  let codeLang = '';

  lines.forEach((line, idx) => {
    if (line.trim().startsWith('```')) {
      if (!inCode) {
        inCode = true;
        codeLang = line.trim().replace(/^```/, '');
        codeBuffer = [];
      } else {
        inCode = false;
        parts.push(
          <CodeBlock
            key={`code-${idx}`}
            code={codeBuffer.join('\n')}
            lang={codeLang}
          />
        );
      }
      return;
    }

    if (inCode) {
      codeBuffer.push(line);
      return;
    }

    // Markdown headers
    if (line.startsWith('### ')) {
      parts.push(
        <h4 key={idx} className="text-xs font-bold text-ink font-sans mt-2.5 mb-1">
          {inlineFormat(line.replace('### ', ''))}
        </h4>
      );
      return;
    }
    if (line.startsWith('## ')) {
      parts.push(
        <h3 key={idx} className="text-sm font-bold text-ink font-sans mt-3 mb-1.5">
          {inlineFormat(line.replace('## ', ''))}
        </h3>
      );
      return;
    }

    // Bullet points
    if (line.trim().startsWith('- ') || line.trim().startsWith('• ')) {
      parts.push(
        <div key={idx} className="flex items-start gap-2 my-1 text-ink/90 font-sans text-[12px] leading-relaxed">
          <span className="text-accent select-none mt-1 font-mono text-[10px]">•</span>
          <span>{inlineFormat(line.trim().replace(/^[-•]\s*/, ''))}</span>
        </div>
      );
      return;
    }

    // Regular paragraphs
    if (line.trim()) {
      const isLast = idx === lines.length - 1;
      parts.push(
        <p
          key={idx}
          className={`my-1.5 leading-relaxed text-ink/90 font-sans text-[12px] ${
            isStreaming && isLast ? 'claude-surface-word' : ''
          }`}
        >
          {inlineFormat(line)}
          {isStreaming && isLast && <span className="claude-cursor" />}
        </p>
      );
    } else {
      parts.push(<div key={idx} className="h-1" />);
    }
  });

  if (inCode && codeBuffer.length > 0) {
    parts.push(
      <CodeBlock
        key="code-incomplete"
        code={codeBuffer.join('\n')}
        lang={codeLang}
      />
    );
  }

  return (
    <div className="space-y-0.5">
      {parts}
      {isStreaming && (!lines.some((l) => l.trim()) || inCode) && (
        <span className="claude-cursor" />
      )}
    </div>
  );
}

export default function CyphBotDrawer({ open, onClose }: Props) {
  const { tenant } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const touchStartY = useRef<number | null>(null);

  const orgName = tenant?.name || 'your workspace';

  const [messages, setMessages] = useState<ChatEntry[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: `Hi, I'm **CyphBot**. Ask me about anything in **${orgName}**'s dashboard — what we found, what it means, or how to fix it.`,
      sources: [
        { id: 'claude-ai', label: 'Claude AI' },
        { id: 'enclave-telemetry', label: `${orgName} live data` },
      ],
      actions: [
        { label: 'Review Findings', path: '/findings' },
        { label: 'Start a scan', path: '/scans' },
      ],
      timestamp: 'Now',
    },
  ]);

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [open]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleTouchStart = (e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY;
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (touchStartY.current === null) return;
    const deltaY = e.changedTouches[0].clientY - touchStartY.current;
    if (deltaY > 60) {
      onClose();
    }
    touchStartY.current = null;
  };

  const handleSend = async (customText?: string) => {
    const textToSend = customText || input;
    if (!textToSend.trim() || loading) return;

    const userMsgId = `user-${Date.now()}`;
    const botMsgId = `bot-${Date.now()}`;
    const timeNow = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const userEntry: ChatEntry = {
      id: userMsgId,
      role: 'user',
      text: textToSend.trim(),
      timestamp: timeNow,
    };

    const initialBotEntry: ChatEntry = {
      id: botMsgId,
      role: 'assistant',
      text: '',
      isStreaming: true,
      timestamp: timeNow,
    };

    setMessages((prev) => [...prev, userEntry, initialBotEntry]);
    if (!customText) setInput('');
    setLoading(true);

    const historyForApi: CyphBotMessage[] = messages
      .filter((m) => m.id !== 'welcome')
      .map((m) => ({ role: m.role, content: m.text }));
    historyForApi.push({ role: 'user', content: textToSend.trim() });

    try {
      let accumulatedText = '';
      await streamCyphBot(
        textToSend.trim(),
        historyForApi,
        {
          onToken: (token: string) => {
            accumulatedText += token;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === botMsgId
                  ? { ...msg, text: accumulatedText, isStreaming: true }
                  : msg
              )
            );
          },
          onComplete: (meta) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === botMsgId
                  ? {
                      ...msg,
                      isStreaming: false,
                      sources: meta.sources || [
                        { id: 'claude', label: 'Claude AI' },
                        { id: 'org', label: `${orgName} workspace` },
                      ],
                      actions: meta.actions || [
                        { label: 'View Assets', path: '/assets' },
                        { label: 'Findings', path: '/findings' },
                      ],
                    }
                  : msg
              )
            );
          },
          onError: (err) => {
            console.warn('Stream callback error:', err);
          },
        }
      );
    } catch (err) {
      console.warn('Streaming error, falling back to askCyphBot:', err);
      try {
        const fallback = await askCyphBot(textToSend.trim(), historyForApi);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === botMsgId
              ? {
                  ...msg,
                  text: fallback.answer,
                  isStreaming: false,
                  sources: fallback.sources || [
                    { id: 'claude', label: 'Claude AI' },
                    { id: 'org', label: `${orgName} workspace` },
                  ],
                  actions: fallback.actions,
                }
              : msg
          )
        );
      } catch (fallbackErr: any) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === botMsgId
              ? {
                  ...msg,
                  text: 'Something went wrong getting a reply. Please check that the backend is running.',
                  isStreaming: false,
                }
              : msg
          )
        );
      }
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        text: `Cleared. What should we look at next?`,
        sources: [
          { id: 'claude-ai', label: 'Claude AI' },
        ],
        timestamp: 'Now',
      },
    ]);
    toast('Conversation cleared');
  };

  const handleActionClick = (action: { label: string; path?: string; toast?: string }) => {
    if (action.path) {
      nav(action.path);
      onClose();
    }
    if (action.toast) {
      toast(action.toast);
    }
  };

  if (!open) return null;

  return (
    <>
      {/* Mobile transparent dismiss overlay, desktop subtle backdrop */}
      <div
        className="fixed inset-0 z-[1050] md:bg-black/35 md:backdrop-blur-xs transition-opacity animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sovereign Chatbot Window: Small on side for mobile, full drawer on desktop */}
      <aside
        className="fixed right-3 bottom-[74px] w-[315px] max-w-[calc(100vw-24px)] h-[415px] max-h-[52vh] rounded-2xl md:fixed md:inset-y-0 md:right-0 md:bottom-0 md:top-0 md:w-[480px] md:max-w-[90vw] md:h-full md:max-h-full md:rounded-none md:border-l md:border-y-0 md:border-r-0 bg-raised border border-accent/40 md:border-line text-ink z-[1060] flex flex-col shadow-2xl backdrop-blur-2xl animate-in zoom-in-95 md:slide-in-from-right duration-200 overflow-hidden"
        role="dialog"
        aria-label="CyphBot chat"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-3.5 py-2.5 md:px-4 md:py-3 border-b border-line bg-inset/70 flex-none">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-6 h-6 rounded-md bg-accent/10 border border-accent/30 flex items-center justify-center text-accent shrink-0">
              <Sparkles size={13} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <h2 className="text-[12px] font-bold tracking-wider mono text-ink uppercase">
                  CYPHBOT
                </h2>
                <span className="inline-flex items-center gap-1 text-[8.5px] mono px-1.5 py-0.2 rounded bg-ok/10 text-ok border border-ok/20 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-ok animate-pulse" />
                  LIVE
                </span>
              </div>
              <p className="text-[9.5px] mono text-soft truncate">
                Claude AI
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={handleClear}
              className="p-1 rounded-md hover:bg-inset text-soft hover:text-ink transition-colors btn-tactile"
              title="Reset Conversation"
            >
              <RotateCcw size={13} />
            </button>
            <button
              onClick={onClose}
              className="p-1 rounded-md hover:bg-inset text-soft hover:text-ink transition-colors btn-tactile"
              title="Minimize Chatbot (Esc)"
              aria-label="Minimize Chatbot"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Enclave Context Pill Strip */}
        <div className="px-3 py-1 border-b border-line bg-raised flex items-center justify-between gap-1.5 text-[9px] mono text-soft flex-none overflow-x-auto no-scrollbar">
          <div className="flex items-center gap-1 shrink-0">
            <Cpu size={10} className="text-accent" />
            <span className="text-ink font-medium truncate max-w-[90px]">{orgName}</span>
          </div>
          <span className="text-line">|</span>
          <div className="flex items-center gap-1 shrink-0">
            <ShieldCheck size={10} className="text-ok" />
            <span>NDPA 2023</span>
          </div>
          <span className="text-line">|</span>
          <div className="flex items-center gap-1 shrink-0">
            <Lock size={10} className="text-accent" />
            <span>CBN</span>
          </div>
        </div>

        {/* Scrollable Message History */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 md:p-4 space-y-3 text-xs bg-raised">
          {messages.map((m) => (
            <div key={m.id} className="w-full">
              {m.role === 'user' ? (
                <div className="claude-emerge flex justify-end w-full">
                  <div className="max-w-[88%] rounded-xl px-3 py-2 bg-accent-soft border border-accent/30 text-ink shadow-xs">
                    <p className="whitespace-pre-wrap leading-relaxed text-[12px] font-sans">{m.text}</p>
                    <span className="block text-[8.5px] text-soft mono mt-0.5 text-right">
                      {m.timestamp}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="claude-emerge w-full space-y-2 pt-1 pb-3 border-b border-line/60 last:border-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <div className="w-4 h-4 rounded-full bg-accent/15 border border-accent/30 flex items-center justify-center text-accent shrink-0">
                        <Sparkles size={9} />
                      </div>
                      <span className="font-semibold text-[11.5px] text-ink font-sans tracking-tight">CyphBot</span>
                      <span className="text-[9px] mono text-soft">· {m.timestamp}</span>
                    </div>
                  </div>

                  <div className="pl-5 space-y-2.5">
                    {m.text ? (
                      <FormattedMessage content={m.text} isStreaming={m.isStreaming} />
                    ) : (
                      <div className="flex items-center gap-2 py-1 text-soft">
                        <span className="text-[11px] mono text-soft">CyphBot is thinking…</span>
                        <span className="w-1.5 h-1.5 rounded-full bg-accent claude-pulse-ember" />
                      </div>
                    )}

                    {/* Sources / Citations */}
                    {!m.isStreaming && m.sources && m.sources.length > 0 && (
                      <div className="pt-1.5 flex flex-wrap items-center gap-1 claude-emerge">
                        <span className="text-[8.5px] mono text-soft uppercase font-medium mr-1">
                          SOURCES:
                        </span>
                        {m.sources.map((s) => (
                          <span
                            key={s.id}
                            className="inline-flex items-center gap-1 text-[8.5px] mono px-2 py-0.5 rounded-full bg-inset border border-line text-soft"
                          >
                            <Lock size={8} className="text-accent" />
                            {s.label}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Action Shortcuts */}
                    {!m.isStreaming && m.actions && m.actions.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1 claude-emerge">
                        {m.actions.map((act, i) => (
                          <button
                            key={i}
                            onClick={() => handleActionClick(act)}
                            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[9.5px] mono bg-accent/10 border border-accent/30 text-accent hover:bg-accent hover:text-white transition-all btn-tactile font-medium"
                          >
                            <span>{act.label}</span>
                            <ArrowUpRight size={9} />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Quick Prompts when few messages */}
          {messages.length <= 2 && !loading && (
            <div className="claude-emerge pt-1.5 space-y-1.5">
              <p className="text-[9px] mono text-soft uppercase tracking-wider font-semibold px-0.5">
                SUGGESTED QUESTIONS
              </p>
              <div className="grid grid-cols-1 gap-1.5">
                {QUICK_PROMPTS.map((qp, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSend(qp.prompt)}
                    className="flex items-center justify-between p-2 rounded-lg border border-line bg-inset/40 hover:bg-inset hover:border-accent/40 text-left transition-all group btn-tactile"
                  >
                    <div className="flex items-center gap-2 min-w-0 pr-1">
                      <qp.icon size={12} className="text-accent shrink-0" />
                      <span className="text-[11px] font-semibold text-ink group-hover:text-accent truncate font-sans">
                        {qp.label}
                      </span>
                    </div>
                    <ArrowUpRight size={11} className="text-soft group-hover:text-accent transition-colors shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="p-2.5 md:p-3 border-t border-line bg-inset/50 flex-none space-y-1.5">
          <div className="flex items-end gap-1.5 p-1 rounded-lg border border-line bg-raised focus-within:border-accent transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask CyphBot..."
              rows={1}
              className="flex-1 bg-transparent p-1 text-xs text-ink placeholder:text-soft resize-none focus:outline-none mono"
            />
            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || loading}
              className={`p-1.5 rounded-md font-mono text-xs transition-all flex items-center justify-center shrink-0 ${
                input.trim() && !loading
                  ? 'bg-accent text-white hover:opacity-90 btn-tactile'
                  : 'bg-inset text-soft/40 cursor-not-allowed'
              }`}
              title="Send (Enter)"
            >
              <Send size={12} />
            </button>
          </div>

          <div className="flex items-center justify-between text-[8.5px] mono text-soft px-0.5">
            <span>Enter to send</span>
            <span>Shortcut: ⌘J</span>
          </div>
        </div>
      </aside>
    </>
  );
}
