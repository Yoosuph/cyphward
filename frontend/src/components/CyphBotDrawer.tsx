import { useState, useRef, useEffect, lazy, Suspense } from 'react';
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
  ShieldCheck,
  FileText,
  ChevronDown,
  LoaderCircle,
  Square,
  ArrowDown,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import { streamCyphBot, type CyphBotMessage, type CyphBotActivityStep } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useToast } from './Toast';
import { reportReference, type ReportArtifact } from '../lib/reportArtifacts';
import './cyphbot-artifacts.css';
import CyphBotReportPreview from './CyphBotReportPreview';
import { lockScroll, unlockScroll } from '../lib/scrollLock';

const CyphBotReportPanel = lazy(() => import('./CyphBotReportPanel'));
const ARTIFACT_LAB = import.meta.env.VITE_CYPHWARD_ARTIFACT_LAB === 'true';
const ACTIVITY_LABELS: Record<CyphBotActivityStep, string> = {
  request_sent: 'Request sent',
  reading_workspace: 'Reading recorded workspace data',
  reviewing_request: 'Reviewing your question and available metrics',
  building_report: 'Preparing the requested chart data',
  querying_period: 'Retrieving the requested period and filters',
  writing_answer: 'Writing an explanation from the results',
  retrying_provider: 'Gemini is temporarily unavailable; retrying the request',
};

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
  artifact?: { id: string; version: number };
  artifactLoading?: boolean;
  activity?: CyphBotActivityStep[];
  failed?: boolean;
  stopped?: boolean;
  error?: string;
  retryPrompt?: string;
}

const QUICK_PROMPTS = [
  ...(ARTIFACT_LAB ? [{ icon: FileText, label: 'Performance report with charts', prompt: 'Generate a report with charts about the performance of our organisation over the last 90 days.' }] : []),
  {
    icon: ShieldAlert,
    label: 'What should we fix first?',
    prompt: 'Prioritise our recorded unresolved findings. Explain which issue to address first and why, using the available evidence.',
  },
  {
    icon: ShieldCheck,
    label: 'Explain our latest assessment',
    prompt: 'Explain our latest recorded security assessment, what it covers and what we still cannot conclude from it.',
  },
  {
    icon: FileText,
    label: 'Board security update',
    prompt: 'Draft a 3-point security update for our Board of Directors.',
  },
];

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const copyTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopyError(''); setCopied(true);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch { setCopyError('Copy is unavailable. Select the text to copy it.'); }
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
      {copyError && <p role="status" className="px-3 pb-2 text-xs text-soft">{copyError}</p>}
    </div>
  );
}

// Inline formatting: **bold** and `code` → real elements (they used to show
// up as literal asterisks/backticks). Unmatched tokens while streaming stay
// as plain text until the closing marker arrives.
function inlineFormat(text: string, surface?: { next: number }): React.ReactNode[] {
  const words = (value: string) => !surface ? value : value.split(/(\s+)/).map((word, i) => {
    if (!word.trim()) return word;
    const index = surface.next++;
    return <span key={i} data-surface-word={index} className="cyphbot-surface-word" style={{ animationDelay: `${Math.min(index * 18, 900)}ms` }}>{word}</span>;
  });
  const nodes: React.ReactNode[] = [];
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(words(text.slice(last, m.index)));
    const tok = m[0];
    if (tok.startsWith('**')) {
      nodes.push(
        <strong key={key++} className="font-semibold text-ink">
          {words(tok.slice(2, -2))}
        </strong>
      );
    } else {
      nodes.push(
        <code key={key++} className="px-1 py-px rounded bg-inset border border-line mono text-[11px] text-accent">
          {words(tok.slice(1, -1))}
        </code>
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(words(text.slice(last)));
  return nodes;
}

function FormattedMessage({ content, isStreaming, animate, onRevealed }: { content: string; isStreaming?: boolean; animate?: boolean; onRevealed?: () => void }) {
  const surface = animate ? { next: 0 } : undefined;
  const parts: React.ReactNode[] = [];
  const lines = content.split('\n');
  let inCode = false;
  let codeBuffer: string[] = [];
  let codeLang = '';

  let tableEnd = -1;
  const cells = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, '|'));
  lines.forEach((line, idx) => {
    if (idx <= tableEnd) return;
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

    // A delimiter row distinguishes Markdown tables from ordinary prose.
    // Cells stay React text, and wide tables scroll within the chat bubble.
    const headers = cells(line);
    const divider = lines[idx + 1] ? cells(lines[idx + 1]) : [];
    if (line.includes('|') && divider.length === headers.length && divider.every(cell => /^:?-{3,}:?$/.test(cell))) {
      const rows: string[][] = [];
      tableEnd = idx + 1;
      while (tableEnd + 1 < lines.length && lines[tableEnd + 1].includes('|') && lines[tableEnd + 1].trim()) {
        rows.push(cells(lines[++tableEnd]));
      }
      parts.push(<div key={`table-${idx}`} className="my-2 max-w-full overflow-x-auto rounded-lg border border-line" tabIndex={0} role="region" aria-label="Findings explanation table">
        <table className="w-full text-left text-xs"><thead className="bg-inset"><tr>{headers.map((header, col) => <th scope="col" key={col} className="px-3 py-2 font-semibold text-ink">{inlineFormat(header, surface)}</th>)}</tr></thead>
          <tbody>{rows.map((row, r) => <tr key={r} className="border-t border-line">{headers.map((_, col) => <td key={col} className="px-3 py-2 min-w-[120px] max-w-[280px] break-words align-top text-ink/90">{inlineFormat(row[col] || '', surface)}</td>)}</tr>)}</tbody>
        </table>
      </div>);
      return;
    }

    // Markdown headers
    if (line.startsWith('### ')) {
      parts.push(
        <h4 key={idx} className="text-xs font-bold text-ink font-sans mt-2.5 mb-1">
          {inlineFormat(line.replace('### ', ''), surface)}
        </h4>
      );
      return;
    }
    if (line.startsWith('## ')) {
      parts.push(
        <h3 key={idx} className="text-sm font-bold text-ink font-sans mt-3 mb-1.5">
          {inlineFormat(line.replace('## ', ''), surface)}
        </h3>
      );
      return;
    }

    // Bullet points
    if (line.trim().startsWith('- ') || line.trim().startsWith('• ')) {
      parts.push(
        <div key={idx} className="flex items-start gap-2 my-1 text-ink/90 font-sans text-[12px] leading-relaxed">
          <span className="text-accent select-none mt-1 font-mono text-[10px]">•</span>
          <span>{inlineFormat(line.trim().replace(/^[-•]\s*/, ''), surface)}</span>
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
          className="my-1.5 leading-relaxed text-ink/90 font-sans text-[12px]"
        >
          {inlineFormat(line, surface)}
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
    <div className="cyphbot-message space-y-0.5" onAnimationEnd={e => {
      if (!isStreaming && e.animationName === 'cyphbotWordRise' && Number((e.target as HTMLElement).dataset.surfaceWord) === (surface?.next || 0) - 1) onRevealed?.();
    }}>
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
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const nearBottom = useRef(true);
  const pendingReply = useRef<string | null>(null);
  const [showLatest, setShowLatest] = useState(false);

  const orgName = tenant?.name || 'your workspace';

  const [messages, setMessages] = useState<ChatEntry[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: `Hi, I'm **CyphBot**. Ask me about anything in **${orgName}**'s dashboard — what we found, what it means, or how to fix it.`,
      sources: [],
      actions: [
        { label: 'Review Findings', path: '/findings' },
        { label: 'Start a scan', path: '/scans' },
      ],
      timestamp: 'Now',
    },
  ]);

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [artifacts, setArtifacts] = useState<ReportArtifact[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<ReportArtifact | null>(null);
  const [fullScreen, setFullScreen] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const referenceArtifact = useRef<ReportArtifact | null>(null);
  const emergedMessages = useRef(new Set<string>());
  const generation = useRef(0);
  const [present, setPresent] = useState(open);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    let frame = 0;
    let timer: ReturnType<typeof setTimeout>;
    if (open) {
      setPresent(true);
      // Wait for the mounted drawer to paint its initial position before entering.
      frame = requestAnimationFrame(() => { frame = requestAnimationFrame(() => setVisible(true)); });
    } else {
      setVisible(false);
      timer = setTimeout(() => setPresent(false), window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 260);
    }
    return () => { cancelAnimationFrame(frame); clearTimeout(timer); };
  }, [open]);

  useEffect(() => {
    generation.current++;
    requestRef.current?.abort();
    requestRef.current = null;
    pendingReply.current = null;
    setArtifacts([]);
    setActiveArtifact(null);
    referenceArtifact.current = null;
    emergedMessages.current.clear();
    setLoading(false);
    setMessages([{ id: 'welcome', role: 'assistant', text: `Hi, I'm **CyphBot**. Ask about **${orgName}**'s recorded security data${ARTIFACT_LAB ? ', or generate a performance report with charts' : ''}.`, timestamp: 'Now' }]);
    return () => { generation.current++; requestRef.current?.abort(); };
  }, [tenant?.id]);

  useEffect(() => {
    if (!open || !present) return;
    lockScroll();
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    if (!dialog) { unlockScroll(); return; }
    const targets = () => [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), textarea, select, summary, [tabindex="0"]')]
      .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
    const timer = setTimeout(() => (inputRef.current?.getClientRects().length ? inputRef.current : targets()[0])?.focus(), 160);
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); }
      if (event.key !== 'Tab') return;
      const items = targets(), first = items[0], last = items[items.length - 1];
      if (!items.includes(document.activeElement as HTMLElement)) { event.preventDefault(); first?.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { clearTimeout(timer); document.removeEventListener('keydown', keydown); unlockScroll(); previous?.focus(); };
  }, [open, present]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 144)}px`;
    }
  }, [input, present]);

  useEffect(() => {
    if (!activeArtifact) return;
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => dialogRef.current?.querySelector<HTMLButtonElement>('[aria-label="Back to chat"]')?.focus());
    return () => { cancelAnimationFrame(frame); if (previous?.isConnected) previous.focus(); };
  }, [Boolean(activeArtifact)]);

  useEffect(() => {
    if (scrollRef.current && nearBottom.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async (customText?: string, retryId?: string) => {
    const textToSend = customText || input;
    if (!textToSend.trim() || textToSend.trim().length > 6000 || requestRef.current || loading) return;
    const retryIndex = retryId ? messages.findIndex(m => m.id === retryId) : -1;
    if (retryId && (retryIndex !== messages.length - 1 || retryIndex < 1)) return;

    const userMsgId = `user-${crypto.randomUUID()}`;
    const botMsgId = retryId || `bot-${crypto.randomUUID()}`;
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
      activity: ['request_sent'],
      retryPrompt: textToSend.trim(),
      artifact: retryId ? messages[retryIndex].artifact : undefined,
      timestamp: timeNow,
    };

    nearBottom.current = true;
    emergedMessages.current.delete(botMsgId);
    setShowLatest(false);
    setMessages((prev) => retryId ? prev.map(m => m.id === retryId ? initialBotEntry : m) : [...prev, userEntry, initialBotEntry]);
    if (!customText) setInput('');
    setLoading(true);
    const request = new AbortController();
    requestRef.current = request;
    pendingReply.current = botMsgId;
    const requestGeneration = generation.current;
    const current = () => !request.signal.aborted && requestGeneration === generation.current;
    const previousArtifact = referenceArtifact.current || artifacts[artifacts.length - 1];
    const reference = previousArtifact ? { ...reportReference(previousArtifact), version: Math.max(...artifacts.filter(a => a.id === previousArtifact.id).map(a => a.version)) } : undefined;
    const options = { signal: request.signal, artifact_context: reference };
    const acceptArtifact = (artifact: ReportArtifact) => {
      if (!current() || artifact.org_id !== tenant?.id) return;
      setArtifacts(prev => [...prev.filter(a => a.id !== artifact.id || a.version !== artifact.version), artifact]);
      referenceArtifact.current = artifact;
      setMessages(prev => prev.map(m => m.id === botMsgId ? { ...m, artifact: { id: artifact.id, version: artifact.version }, artifactLoading: false } : m));
    };

    const historyForApi: CyphBotMessage[] = (retryId ? messages.slice(0, retryIndex - 1) : messages)
      .filter((m) => m.id !== 'welcome' && !m.failed && !m.stopped)
      .slice(-20)
      .map((m) => ({ role: m.role, content: m.text.slice(0, 6000) }));

    let accumulatedText = '';
    try {
      await streamCyphBot(
        textToSend.trim(),
        historyForApi,
        {
          onActivity: (step) => {
            if (!current()) return;
            setMessages(prev => prev.map(m => m.id === botMsgId && m.activity?.[m.activity.length - 1] !== step
              ? { ...m, activity: [...(m.activity || []), step] } : m));
          },
          onToken: (token: string) => {
            if (!current()) return;
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
            if (!current()) return;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === botMsgId
                  ? {
                      ...msg,
                      isStreaming: false,
                      artifactLoading: false,
                      sources: meta.sources || [
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
            if (err?.name !== 'AbortError') console.warn('Stream callback error:', err);
          },
          onArtifact: acceptArtifact,
          onArtifactStatus: () => { if (current()) setMessages(prev => prev.map(m => m.id === botMsgId ? { ...m, artifactLoading: true } : m)); },
        },
        options,
      );
    } catch (err) {
      if (!current()) return;
      setMessages(prev => prev.map(msg => msg.id === botMsgId ? {
        ...msg, text: accumulatedText, error: err instanceof Error ? err.message : 'CyphBot could not answer. Please retry.',
        isStreaming: false, artifactLoading: false, sources: [], actions: [], failed: true,
      } : msg));
    } finally {
      if (current()) { setLoading(false); requestRef.current = null; pendingReply.current = null; }
    }
  };

  const handleStop = () => {
    const id = pendingReply.current;
    generation.current++;
    requestRef.current?.abort();
    requestRef.current = null;
    pendingReply.current = null;
    setLoading(false);
    setMessages(prev => prev.map(m => m.id === id && m.isStreaming ? { ...m, isStreaming: false, artifactLoading: false, stopped: true } : m));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    generation.current++;
    requestRef.current?.abort();
    requestRef.current = null;
    pendingReply.current = null;
    setLoading(false);
    setArtifacts([]);
    setActiveArtifact(null);
    referenceArtifact.current = null;
    emergedMessages.current.clear();
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        text: `Cleared. What should we look at next?`,
        sources: [],
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

  if (!present) return null;

  return (
    <>
      {/* Mobile transparent dismiss overlay, desktop subtle backdrop */}
      <div
        className={`cyphbot-backdrop fixed inset-0 z-[1050] bg-black/20 md:bg-black/35 md:backdrop-blur-xs ${visible ? 'is-visible' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sovereign Chatbot Window: Small on side for mobile, full drawer on desktop */}
      <aside
        ref={dialogRef}
        className={`cyphbot-window bg-raised text-ink z-[1060] flex flex-col overflow-hidden ${fullScreen ? 'cyphbot-fullscreen' : ''} ${activeArtifact ? 'cyphbot-expanded' : ''} ${visible ? 'is-visible' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="CyphBot chat"
      >
        <div className="cyphbot-chat-pane">
        {/* Header */}
        <div className="cyphbot-header flex items-center justify-between px-5 py-4 border-b border-line flex-none">
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
                  AI
                </span>
              </div>
              <p className="text-[9.5px] mono text-soft truncate">
                Your workspace, in focus
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <button type="button" className="min-[901px]:hidden p-1 text-soft hover:text-ink hover:bg-inset"
              onClick={() => setFullScreen(value => !value)} aria-pressed={fullScreen}
              aria-label={fullScreen ? 'Exit full screen' : 'Enter full screen'} title={fullScreen ? 'Exit full screen' : 'Enter full screen'}>
              {fullScreen ? <Minimize2 size={14}/> : <Maximize2 size={14}/>}
            </button>
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

        <div className="cyphbot-context flex items-center gap-2 min-w-0 px-5 py-2.5 border-b border-line text-[10px] text-soft">
          <ShieldCheck size={11} className="shrink-0 text-accent"/>
          <span className="truncate flex-1">{orgName}</span><span className="shrink-0 text-[9px]">Workspace context</span>
        </div>

        {/* Scrollable Message History */}
        <div ref={scrollRef} data-chat-scroll onScroll={() => {
          const el = scrollRef.current;
          if (!el) return;
          nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          setShowLatest(!nearBottom.current);
        }} className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-5 md:px-6 space-y-5 text-xs bg-raised">
          {messages.map((m) => (
            <div key={m.id} className="w-full" data-chat-role={m.role}>
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
                    {!!m.activity?.length && <details className="group rounded-lg border border-line bg-inset/40 text-soft" data-chat-activity>
                      <summary className="flex items-center gap-1.5 cursor-pointer list-none px-2 py-1.5 text-[10px] select-none [&::-webkit-details-marker]:hidden">
                        {m.isStreaming ? <LoaderCircle size={11} className="text-accent motion-safe:animate-spin"/> : m.failed || m.stopped ? <ShieldAlert size={11}/> : <Check size={11}/>}
                        <span className="flex-1">{m.isStreaming ? 'CyphBot is thinking…' : m.stopped ? 'Activity · stopped' : m.failed ? 'Activity · interrupted' : 'Activity · completed'}</span>
                        <ChevronDown size={12} className="transition-transform group-open:rotate-180 motion-reduce:transition-none"/>
                      </summary>
                      <div className="px-2 pb-2 border-t border-line">
                        <p className="text-[9px] leading-relaxed pt-1.5 pb-2">Steps taken to prepare this response.</p>
                        <ol className="space-y-1.5">{m.activity.map((step, i) => <li key={`${step}-${i}`} className="flex gap-1.5 items-start text-[10px] leading-4">
                          {i === m.activity!.length - 1 && (m.isStreaming || m.failed || m.stopped)
                            ? m.failed || m.stopped ? <ShieldAlert size={10} className="shrink-0 mt-0.5"/> : <LoaderCircle size={10} className="shrink-0 mt-0.5 text-accent motion-safe:animate-spin"/>
                            : <span className="shrink-0 mt-0.5"><Check size={10}/></span>}
                          <span>{ACTIVITY_LABELS[step]}</span>
                        </li>)}</ol>
                      </div>
                    </details>}
                    {m.text && <FormattedMessage content={m.text} isStreaming={m.isStreaming}
                      animate={m.id !== 'welcome' && !m.failed && !emergedMessages.current.has(m.id)}
                      onRevealed={() => emergedMessages.current.add(m.id)}/>}
                    {(m.error || m.stopped) && <div role={m.error ? 'alert' : 'status'} className="cyphbot-response-notice">
                      {m.artifact && <p className="font-medium text-ink mb-1">Your report is ready to open.</p>}
                      <p>{m.error || 'Response stopped. You can retry or ask another question.'}</p>
                      {m.retryPrompt && m.id === messages[messages.length - 1]?.id && <button type="button" disabled={loading} onClick={() => handleSend(m.retryPrompt, m.id)} className="mt-2 inline-flex items-center gap-1.5 text-accent text-xs font-medium disabled:opacity-40"><RotateCcw size={12}/> Try again</button>}
                    </div>}

                    {/* Sources / Citations */}
                    {m.artifactLoading && <p role="status" className="rounded-lg border border-line p-3 text-xs text-accent">Building charts from recorded telemetry…</p>}
                    {m.artifact && (() => {
                      const artifact = artifacts.find(a => a.id === m.artifact?.id && a.version === m.artifact.version);
                      return artifact ? <CyphBotReportPreview artifact={artifact} onOpen={() => {
                        referenceArtifact.current = artifact; setActiveArtifact(artifact);
                      }}/> : null;
                    })()}
                    {!m.isStreaming && m.sources && m.sources.length > 0 && (
                      <div data-chat-sources className="pt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5 claude-emerge">
                        <span className="text-[7.5px] leading-3 text-soft uppercase tracking-wide mr-0.5">
                          SOURCES:
                        </span>
                        {m.sources.map((s) => (
                          <span
                            key={s.id}
                            className="inline-flex min-w-0 max-w-full text-[8px] leading-3 px-1.5 py-0 rounded border border-line text-soft break-words"
                          >
                            {s.id === 'src_claude' || s.id === 'claude-ai' ? 'AI analysis' : s.label}
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

        {showLatest && <div className="flex justify-center h-0 relative z-10"><button type="button" onClick={() => {
          nearBottom.current = true; setShowLatest(false);
          scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
        }} className="cyphbot-jump" aria-label="Jump to latest message"><ArrowDown size={12}/> Latest message</button></div>}
        {/* Input Bar */}
        <div className="cyphbot-composer flex-none space-y-2">
          <div className="cyphbot-composer-box flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask CyphBot..."
              rows={1}
              maxLength={6000}
              aria-label="Ask CyphBot"
              className="flex-1 min-w-0 bg-transparent py-1.5 px-1 text-[13px] leading-6 text-ink placeholder:text-soft resize-none focus:outline-none"
            />
            {loading ? <button type="button" onClick={handleStop} aria-label="Stop response" title="Stop response" className="cyphbot-send"><Square size={13} fill="currentColor"/></button> : <button
              onClick={() => handleSend()}
              disabled={!input.trim() || loading}
              className="cyphbot-send disabled:opacity-40 disabled:cursor-not-allowed"
              title="Send (Enter)"
              aria-label="Send message"
            >
              <Send size={12} />
            </button>}
          </div>

          <div className="flex items-center justify-between text-[8.5px] mono text-soft px-0.5">
            <span>Enter to send · Shift + Enter for a new line</span>
            <span>{input.length > 5400 ? `${input.length}/6000` : 'CyphBot'}</span>
          </div>
        </div>
        </div>
        {activeArtifact && <Suspense fallback={<div className="flex-1 p-6 text-sm">Loading report renderer…</div>}><CyphBotReportPanel artifact={activeArtifact} versions={artifacts.filter(a => a.id === activeArtifact.id).sort((a, b) => a.version - b.version)} onVersion={artifact => { referenceArtifact.current = artifact; setActiveArtifact(artifact); }} onClose={() => setActiveArtifact(null)}/></Suspense>}
      </aside>
    </>
  );
}
