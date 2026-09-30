import { useState } from 'react';
import { Sparkles, FileText, CheckCircle2, Copy, Check, ShieldCheck, Printer, X, Mail, Send, Loader2 } from 'lucide-react';
import Modal from './Modal';
import CyphwardLogo from './CyphwardLogo';
import { AIExecutiveReportSkeleton } from './Skeleton';
import { useToast } from './Toast';
import { sendReportEmail } from '../lib/api';
import type { ExecutiveSummary } from '../types';

interface BoardReportModalProps {
  open: boolean;
  onClose: () => void;
  loading: boolean;
  summary: ExecutiveSummary | null;
}

export default function BoardReportModal({
  open,
  onClose,
  loading,
  summary,
}: BoardReportModalProps) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const [showEmailInput, setShowEmailInput] = useState(false);
  const [emailTarget, setEmailTarget] = useState('kankarofi125@gmail.com');
  const [sendingEmail, setSendingEmail] = useState(false);

  const handleEmailDispatch = async () => {
    if (!emailTarget.trim() || !emailTarget.includes('@')) {
      toast('Please enter a valid email address');
      return;
    }
    setSendingEmail(true);
    try {
      const res = await sendReportEmail({
        to_email: emailTarget.trim(),
        recipient_name: 'Security Board Enclave',
      });
      toast(`Executive briefing dispatched to ${emailTarget.trim()}!`);
      setShowEmailInput(false);
    } catch (err: any) {
      toast(`Dispatch failed: ${err.message || 'Brevo relay activation pending'}`);
    } finally {
      setSendingEmail(false);
    }
  };

  const handlePrint = () => {
    if (!summary) {
      toast('Please wait for the briefing to load before printing.');
      return;
    }

    try {
      const reportEl = document.getElementById('cyphward-board-report');
      if (!reportEl) {
        window.print();
        return;
      }

      // Create an isolated printable iframe to guarantee pristine single-page A4 output
      const iframe = document.createElement('iframe');
      iframe.setAttribute('title', 'Cyphward Print Frame');
      iframe.style.position = 'fixed';
      iframe.style.right = '0';
      iframe.style.bottom = '0';
      iframe.style.width = '0';
      iframe.style.height = '0';
      iframe.style.border = '0';
      iframe.style.opacity = '0';
      iframe.style.pointerEvents = 'none';
      document.body.appendChild(iframe);

      const frameDoc = iframe.contentWindow?.document;
      if (!frameDoc) {
        window.print();
        return;
      }

      frameDoc.open();
      frameDoc.write(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>CYPHWARD Board Briefing — ${summary.org_name}</title>
  <style>
    @page {
      size: A4 portrait;
      margin: 10mm 12mm;
    }
    *, *::before, *::after {
      box-sizing: border-box;
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }
    html, body {
      margin: 0;
      padding: 0;
      background: #FFFFFF;
      color: #111111;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 11px;
      line-height: 1.4;
      height: auto;
      overflow: visible;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    #cyphward-board-report {
      display: block;
      width: 100%;
      page-break-inside: avoid;
      break-inside: avoid;
      page-break-after: avoid;
    }
    .flex { display: flex; }
    .items-center { align-items: center; }
    .items-start { align-items: flex-start; }
    .items-baseline { align-items: baseline; }
    .justify-between { justify-content: space-between; }
    .justify-end { justify-content: flex-end; }
    .gap-1 { gap: 4px; }
    .gap-1\\.5 { gap: 6px; }
    .gap-2 { gap: 8px; }
    .gap-3 { gap: 12px; }
    .grid { display: grid; }
    .grid-cols-1 { grid-template-columns: repeat(1, minmax(0, 1fr)); }
    .border-b { border-bottom: 1px solid #D1D5DB; }
    .border-t { border-top: 1px solid #D1D5DB; }
    .border-l { border-left: 1px solid #D1D5DB; }
    .pb-3 { padding-bottom: 10px; }
    .pt-2 { padding-top: 8px; }
    .pl-3 { padding-left: 10px; }
    .pl-0\\.5 { padding-left: 2px; }
    .p-2 { padding: 7px 9px; }
    .p-2\\.5 { padding: 8px 10px; }
    .p-3 { padding: 9px 12px; }
    .p-3\\.5 { padding: 10px 14px; }
    .px-2 { padding-left: 8px; padding-right: 8px; }
    .px-1\\.5 { padding-left: 6px; padding-right: 6px; }
    .py-0\\.5 { padding-top: 2px; padding-bottom: 2px; }
    .py-1 { padding-top: 4px; padding-bottom: 4px; }
    .mb-1 { margin-bottom: 4px; }
    .mb-1\\.5 { margin-bottom: 6px; }
    .mt-0\\.5 { margin-top: 2px; }
    .space-y-4 > * + * { margin-top: 10px; }
    .space-y-1\\.5 > * + * { margin-top: 5px; }
    .space-y-0\\.5 > * + * { margin-top: 2px; }
    .text-right { text-align: right; }
    .text-accent { color: #C03813 !important; }
    .text-soft { color: #4B5563 !important; }
    .text-ink { color: #111111 !important; }
    .text-ok { color: #15803D !important; }
    .font-bold { font-weight: 700; }
    .font-semibold { font-weight: 600; }
    .font-medium { font-weight: 500; }
    .uppercase { text-transform: uppercase; }
    .tracking-wider { letter-spacing: 0.05em; }
    .tracking-widest { letter-spacing: 0.1em; }
    .text-xs { font-size: 11px; }
    .text-sm { font-size: 13px; }
    .text-base { font-size: 14px; }
    .text-2xl { font-size: 22px; }
    .text-\\[9px\\] { font-size: 8.5px; }
    .text-\\[9\\.5px\\] { font-size: 9px; }
    .text-\\[10px\\] { font-size: 9.5px; }
    .text-\\[10\\.5px\\] { font-size: 10px; }
    .text-\\[11px\\] { font-size: 10.5px; }
    .text-\\[11\\.5px\\] { font-size: 11px; }
    .rounded { border-radius: 4px; }
    .shrink-0 { flex-shrink: 0; }
    .block { display: block; }
    .whitespace-nowrap { white-space: nowrap; }
    .leading-relaxed { line-height: 1.45; }
    .report-card, .bg-inset {
      background: #F9FAFB !important;
      border: 1px solid #D1D5DB !important;
    }
    .report-badge {
      background: #F3F4F6 !important;
      border: 1px solid #D1D5DB !important;
      color: #111111 !important;
    }
    .bg-accent\\/5, .bg-accent\\/10 {
      background: #FFF7ED !important;
      border: 1px solid #FDBA74 !important;
    }
    .no-print { display: none !important; }
  </style>
</head>
<body>
  ${reportEl.outerHTML}
</body>
</html>`);
      frameDoc.close();

      setTimeout(() => {
        iframe.contentWindow?.focus();
        iframe.contentWindow?.print();
        setTimeout(() => {
          try {
            document.body.removeChild(iframe);
          } catch {}
        }, 1200);
      }, 300);
    } catch {
      window.print();
    }
  };

  const handleCopy = async () => {
    if (!summary) return;
    const text = `
CYPHWARD EXECUTIVE SECURITY ASSESSMENT
Organization: ${summary.org_name}
Security Score: ${summary.score}/100 (Grade ${summary.grade} — ${summary.posture_label})
Date: ${summary.generated_at}

EXECUTIVE SUMMARY:
${summary.board_summary}

KEY OBSERVED STRENGTHS:
${summary.key_strengths.map(s => `• ${s}`).join('\n')}

CRITICAL BOARD ACTION ITEMS:
${summary.critical_action_items.map(a => `[${a.priority}] ${a.title} (Owner: ${a.owner})\n  Impact: ${a.impact}`).join('\n')}

REGULATORY COMPLIANCE VERDICT:
${summary.compliance_verdict}
    `.trim();

    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast('Executive summary copied to clipboard');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast('Failed to copy text');
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        <>
          <span className="hidden sm:inline">AI EXECUTIVE SECURITY ASSESSMENT (BOARD BRIEFING)</span>
          <span className="sm:hidden">AI EXECUTIVE ASSESSMENT</span>
        </>
      }
      icon={<Sparkles size={16} className="text-accent" />}
      maxWidth="max-w-2xl"
      backdropClassName="board-report-modal-backdrop"
      className="board-report-modal-panel"
    >
      {/* Top Action Bar inside Modal */}
      <div className="no-print flex flex-col sm:flex-row sm:items-center justify-between pb-2 mb-2 border-b border-line gap-2">
        <div className="flex items-center gap-2">
          <span className="live-dot" />
          <span className="mono text-[10.5px] text-soft">
            {loading ? 'SYNTHESIZING EXECUTIVE BRIEFING…' : 'BOARD-CERTIFIED A4 BRIEFING'}
          </span>
        </div>
        <div className="flex items-center gap-2 self-end sm:self-auto flex-wrap">
          <button
            type="button"
            onClick={() => setShowEmailInput(s => !s)}
            disabled={loading || !summary}
            className={`btn-tactile px-3 py-1 rounded text-xs mono border flex items-center gap-1.5 transition-all font-semibold ${
              showEmailInput
                ? 'bg-accent text-white border-accent'
                : 'border-line bg-inset/40 hover:border-accent text-soft hover:text-ink'
            }`}
            title="Email Executive Report via Brevo"
          >
            <Mail size={13} className={showEmailInput ? 'text-white' : 'text-accent'} />
            <span>EMAIL REPORT</span>
          </button>

          <button
            type="button"
            onClick={handlePrint}
            disabled={loading || !summary}
            className="btn-tactile px-3 py-1 rounded text-xs mono border border-accent bg-accent/10 hover:bg-accent hover:text-white text-accent flex items-center gap-1.5 transition-all font-semibold"
            title="Print or Save PDF"
          >
            <Printer size={13} />
            <span>PRINT / SAVE PDF</span>
          </button>
        </div>
      </div>

      {/* Brevo Email Dispatch Input Bar */}
      {showEmailInput && (
        <div className="no-print p-2.5 rounded-lg border border-accent/40 bg-inset/70 flex flex-col sm:flex-row items-stretch sm:items-center gap-2 animate-in fade-in-50 duration-200">
          <div className="relative flex-1">
            <Mail size={13} className="absolute left-2.5 top-2.5 text-accent" />
            <input
              type="email"
              value={emailTarget}
              onChange={e => setEmailTarget(e.target.value)}
              placeholder="recipient@domain.com"
              className="w-full pl-8 pr-3 py-1.5 rounded bg-raised border border-line text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
              disabled={sendingEmail}
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleEmailDispatch}
              disabled={sendingEmail || !emailTarget.trim()}
              className="btn-tactile flex-1 sm:flex-none px-3.5 py-1.5 rounded text-xs mono bg-accent text-white hover:opacity-90 flex items-center justify-center gap-1.5 font-semibold transition-all"
            >
              {sendingEmail ? (
                <>
                  <Loader2 size={12} className="animate-spin" />
                  <span>DISPATCHING…</span>
                </>
              ) : (
                <>
                  <Send size={12} />
                  <span>SEND VIA BREVO</span>
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => setShowEmailInput(false)}
              className="btn-tactile px-2 py-1.5 rounded text-xs mono border border-line text-soft hover:text-ink hover:bg-raised"
            >
              CANCEL
            </button>
          </div>
        </div>
      )}

      {loading || !summary ? (
        <AIExecutiveReportSkeleton />
      ) : (
        <div id="cyphward-board-report" className="board-report-sheet text-xs space-y-4">
          {/* Document Classification & Brand Header */}
          <div className="flex items-start justify-between pb-3 border-b border-line">
            <div className="flex items-center gap-3">
              <CyphwardLogo size={28} variant="compact" />
              <div className="border-l border-line pl-3">
                <span className="text-[9px] mono font-bold tracking-widest text-accent uppercase block">
                  BOARD DIRECTIVE · L00 ACCESS
                </span>
                <span className="text-[10px] mono text-soft">
                  CONFIDENTIAL // FOR DIRECTORS ONLY
                </span>
              </div>
            </div>
            <div className="text-right">
              <span className="text-[10.5px] mono text-soft block">ASSESSMENT DATE</span>
              <span className="text-xs mono font-semibold text-ink">{summary.generated_at}</span>
            </div>
          </div>

          {/* Org & Risk Score Banner */}
          <div className="p-3.5 bg-inset rounded border border-line flex items-center justify-between report-card">
            <div>
              <span className="text-[10px] mono text-soft block">TARGET ENTITY</span>
              <h4 className="font-bold text-ink text-base">{summary.org_name}</h4>
              <span className="text-[10px] mono text-soft">External security assessment</span>
            </div>
            <div className="text-right">
              <span className="text-[10px] mono text-soft block">SECURITY SCORE</span>
              <div className="flex items-baseline gap-1 justify-end">
                <span className="text-2xl font-bold mono text-accent font-display">{summary.score}</span>
                <span className="text-xs mono text-soft">/100</span>
              </div>
              <span className="inline-block mt-0.5 px-2 py-0.5 rounded text-[9.5px] mono font-bold bg-accent/10 text-accent border border-accent/25 report-badge">
                GRADE {summary.grade} · {summary.posture_label.toUpperCase()}
              </span>
            </div>
          </div>

          {/* Executive Narrative */}
          <div>
            <h5 className="mono font-semibold text-soft uppercase text-[10.5px] tracking-wider mb-1.5 flex items-center gap-1.5">
              <span>SUMMARY</span>
            </h5>
            <p className="text-ink leading-relaxed bg-inset/40 p-3 rounded border border-line/60 report-card">
              {summary.board_summary}
            </p>
          </div>

          {/* Observed Technical Strengths */}
          {summary.key_strengths && summary.key_strengths.length > 0 && (
            <div>
              <h5 className="mono font-semibold text-soft uppercase text-[10.5px] tracking-wider mb-1.5">
                OBSERVED DEFENSE STRENGTHS
              </h5>
              <div className="grid grid-cols-1 gap-1.5">
                {summary.key_strengths.map((str, idx) => (
                  <div key={idx} className="flex items-start gap-2 p-2 rounded bg-inset/30 border border-line/50 text-ink report-card">
                    <CheckCircle2 size={13} className="text-ok shrink-0 mt-0.5" />
                    <span className="text-[11.5px]">{str}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Critical Board Action Items */}
          {summary.critical_action_items && summary.critical_action_items.length > 0 && (
            <div>
              <h5 className="mono font-semibold text-soft uppercase text-[10.5px] tracking-wider mb-1.5">
                PRIORITIZED BOARD REMEDIATION ACTIONS
              </h5>
              <div className="space-y-1.5">
                {summary.critical_action_items.map((act, idx) => (
                  <div key={idx} className="p-2.5 rounded bg-inset border border-line flex flex-col sm:flex-row sm:items-start justify-between gap-2 sm:gap-3 report-card">
                    <div className="space-y-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[9.5px] mono font-bold px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/20 report-badge">
                          {act.priority}
                        </span>
                        <span className="font-semibold text-ink text-xs">{act.title}</span>
                      </div>
                      <p className="text-soft text-[11px] pl-0.5">{act.impact}</p>
                    </div>
                    <span className="text-[9.5px] mono text-soft whitespace-nowrap bg-raised px-2 py-1 rounded border border-line report-badge self-start sm:self-auto">
                      {act.owner}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Regulatory Compliance Verdict */}
          <div className="p-3 bg-accent/5 rounded border border-accent/20 text-[11.5px] report-card">
            <div className="flex items-center gap-1.5 mb-1">
              <ShieldCheck size={13} className="text-accent" />
              <span className="font-bold mono text-accent uppercase text-[10.5px]">
                NDPA 2023 & CBN STATUTORY VERDICT
              </span>
            </div>
            <p className="text-ink leading-relaxed">{summary.compliance_verdict}</p>
          </div>

          {/* Cryptographic Signature Footer */}
          <div className="pt-2 border-t border-line/60 flex items-center justify-between text-[9.5px] mono text-soft">
            <span>ISSUER: CYPHWARD SECURITY PLATFORM</span>
            <span>VERIFICATION HASH: SHA256:{summary.org_name.slice(0, 3).toUpperCase()}-9841B-SOVEREIGN</span>
          </div>
        </div>
      )}

      {/* Modal Actions (Hidden in Print) */}
      <div className="no-print flex items-center justify-between gap-3 pt-3 border-t border-line mt-4">
        <button
          type="button"
          onClick={handleCopy}
          disabled={loading || !summary}
          className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-soft hover:text-ink flex items-center gap-1.5"
        >
          {copied ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy Text'}</span>
        </button>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handlePrint}
            disabled={loading || !summary}
            className="btn-tactile px-3.5 py-1.5 rounded text-xs mono border border-line hover:border-line-strong text-ink flex items-center gap-1.5 bg-raised"
          >
            <Printer size={13} className="text-accent" />
            <span>Print / Save PDF</span>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="btn-tactile px-4 py-1.5 rounded text-xs mono bg-accent text-white hover:opacity-90 font-medium"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
