import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, FileText, Plus, Send, Eye, Download } from 'lucide-react';
import { listReports, createReport, getReport, type ReportRow } from '../lib/api';
import { useToast } from '../components/Toast';
import Modal from '../components/Modal';
import StatusChip from '../components/StatusChip';
import { PageHead, Loading } from '../components/ui';
import { sendReportEmail } from '../lib/api';

export default function Reports() {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [creating, setCreating] = useState(false);

  const [preview, setPreview] = useState<ReportRow | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [emailOpen, setEmailOpen] = useState(false);
  const [emailTo, setEmailTo] = useState('');
  const [emailName, setEmailName] = useState('');
  const [emailNote, setEmailNote] = useState('');
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listReports();
      setReports(res.reports);
    } catch (e: any) {
      toast(e.message || 'Failed to load reports');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const res = await createReport();
      if (res?.report) {
        toast('Assessment report generated');
        await load();
      } else {
        toast('Failed to generate report');
      }
    } catch (err: any) {
      toast(err.message || 'Failed to generate report');
    } finally {
      setCreating(false);
    }
  };

  const openPreview = async (id: string) => {
    setPreviewOpen(true);
    setPreviewLoading(true);
    try {
      const res = await getReport(id);
      if (res?.report) setPreview(res.report);
    } catch {
      toast('Failed to load report content');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSendEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailTo.trim()) return;
    setSending(true);
    try {
      const res = await sendReportEmail({
        to_email: emailTo.trim(),
        recipient_name: emailName.trim() || undefined,
        custom_note: emailNote.trim() || undefined,
      });
      toast(res.message || 'Report emailed');
      setEmailOpen(false);
      setEmailTo('');
      setEmailName('');
      setEmailNote('');
    } catch (err: any) {
      toast(err.message || 'Email dispatch failed');
    } finally {
      setSending(false);
    }
  };

  const downloadHtml = (report: ReportRow) => {
    if (!report.html) return;
    const blob = new Blob([report.html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.title.replace(/[^\w.-]+/g, '_')}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5 pb-10 content-fade-in">
      <PageHead
        eyebrow="LAYER 07 · REPORTS"
        title="Assessment Reports"
        note="Generate executive-ready security assessments from live posture data and dispatch them by email."
        meta={
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <button
              onClick={() => setEmailOpen(true)}
              className="btn-tactile flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink"
            >
              <Send size={13} className="text-accent" /> EMAIL BRIEFING
            </button>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="btn-tactile flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono bg-accent text-white hover:opacity-90 disabled:opacity-50"
            >
              {creating ? <RefreshCw size={13} className="animate-spin" /> : <Plus size={13} />}
              GENERATE REPORT
            </button>
          </div>
        }
      />

      {loading ? (
        <Loading label="REPORT ARCHIVE" />
      ) : reports.length === 0 ? (
        <div className="p-10 rounded-lg border border-line bg-raised text-center">
          <FileText size={28} className="mx-auto text-accent mb-3" />
          <p className="mono text-sm text-ink">No reports yet</p>
          <p className="text-xs text-soft mt-1">Generate a report to capture the current external posture for stakeholders.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-line bg-raised overflow-x-auto">
          <table className="w-full text-left text-xs mono min-w-[640px]">
            <thead>
              <tr className="border-b border-line text-soft text-[11px]">
                <th className="px-4 py-3 font-medium">TITLE</th>
                <th className="px-4 py-3 font-medium">DOMAIN</th>
                <th className="px-4 py-3 font-medium">STATUS</th>
                <th className="px-4 py-3 font-medium">SCORE</th>
                <th className="px-4 py-3 font-medium">CREATED</th>
                <th className="px-4 py-3 font-medium text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {reports.map(r => (
                <tr key={r.id} className="hover:bg-inset/40 transition-colors">
                  <td className="px-4 py-3 text-ink font-semibold max-w-[280px] truncate">{r.title}</td>
                  <td className="px-4 py-3 text-soft">{r.domain || '—'}</td>
                  <td className="px-4 py-3">
                    <StatusChip level={r.status === 'ready' ? 'ok' : r.status === 'failed' ? 'bad' : 'warn'}>
                      {r.status.toUpperCase()}
                    </StatusChip>
                  </td>
                  <td className="px-4 py-3 text-ink">
                    {r.summary?.score != null ? `${r.summary.score}/100` : '—'}
                  </td>
                  <td className="px-4 py-3 text-soft">
                    {new Date(r.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1.5">
                      <button
                        onClick={() => openPreview(r.id)}
                        className="btn-tactile px-2.5 py-1 rounded border border-line text-[10px] hover:border-line-strong hover:text-ink"
                      >
                        <Eye size={11} className="inline mr-1" />VIEW
                      </button>
                      <button
                        onClick={() => downloadHtml(r)}
                        className="btn-tactile px-2.5 py-1 rounded border border-line text-[10px] hover:border-line-strong hover:text-ink"
                      >
                        <Download size={11} className="inline mr-1" />HTML
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={previewOpen}
        onClose={() => {
          setPreviewOpen(false);
          setPreview(null);
        }}
        title={preview?.title || 'REPORT PREVIEW'}
        icon={<FileText size={16} className="text-accent" />}
        maxWidth="max-w-3xl"
      >
        {previewLoading || !preview ? (
          <Loading label="REPORT CONTENT" />
        ) : preview.html ? (
          <div
            className="max-h-[70vh] overflow-auto rounded border border-line bg-inset"
            dangerouslySetInnerHTML={{ __html: preview.html }}
          />
        ) : (
          <p className="text-xs text-soft mono">Report HTML unavailable.</p>
        )}
      </Modal>

      <Modal
        open={emailOpen}
        onClose={() => setEmailOpen(false)}
        title="EMAIL EXECUTIVE BRIEFING"
        icon={<Send size={16} className="text-accent" />}
        maxWidth="max-w-md"
      >
        <form onSubmit={handleSendEmail} className="space-y-3.5 text-xs">
          <div className="space-y-1.5">
            <label className="mono text-soft">RECIPIENT EMAIL</label>
            <input
              type="email"
              required
              value={emailTo}
              onChange={e => setEmailTo(e.target.value)}
              placeholder="board@company.ng"
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>
          <div className="space-y-1.5">
            <label className="mono text-soft">RECIPIENT NAME</label>
            <input
              type="text"
              value={emailName}
              onChange={e => setEmailName(e.target.value)}
              placeholder="Board Risk Committee"
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>
          <div className="space-y-1.5">
            <label className="mono text-soft">CUSTOM NOTE (OPTIONAL)</label>
            <textarea
              rows={3}
              value={emailNote}
              onChange={e => setEmailNote(e.target.value)}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent resize-y"
            />
          </div>
          <div className="flex justify-end gap-2 pt-3 border-t border-line">
            <button
              type="button"
              onClick={() => setEmailOpen(false)}
              className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line text-soft hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={sending || !emailTo.trim()}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono bg-accent text-white disabled:opacity-50 flex items-center gap-1.5"
            >
              {sending ? <RefreshCw size={12} className="animate-spin" /> : <Send size={12} />}
              Send
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
