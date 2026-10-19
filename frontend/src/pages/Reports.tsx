import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, FileText, Plus, Send, Eye, Download } from 'lucide-react';
import { listReportsStrict, createReport, getReport, type ReportRow } from '../lib/api';
import { useToast } from '../components/Toast';
import { readPageCache, writePageCache } from '../lib/pageCache';
import Dialog, { useDialogClose } from '../components/ui/Dialog';
import { EmptyPanel, ErrorPanel, LoadingPanel, humanError } from '../components/ui/StatePanels';
import { useConfirm } from '../components/ConfirmDialog';
import { useOrgZone } from '../lib/orgZone';
import { fmtDayZone } from './compliance/shared';
import StatusChip from '../components/StatusChip';
import { PageHead } from '../components/ui';
import { sendReportEmail, getEvidenceRetention, setEvidenceRetention, type EvidenceRetention } from '../lib/api';
import { useAuth } from '../lib/auth';

const RETENTION_CHOICES = [12, 24, 36, 48, 60, 84, 120];

/** What happens to an issued report's record, in plain words, and (for the owner) how long to keep it. */
function RetentionNote() {
  const toast = useToast();
  const confirm = useConfirm();
  const { organization } = useAuth();
  const isOwner = organization?.membership_role === 'owner';
  const [info, setInfo] = useState<EvidenceRetention | null>(null);
  const [months, setMonths] = useState(36);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    getEvidenceRetention().then(res => { if (live) { setInfo(res); setMonths(res.retention_months); } }).catch(() => undefined);
    return () => { live = false; };
  }, []);

  if (!info) return null;
  const save = async () => {
    if (months < info.retention_months) {
      const ok = await confirm({
        title: 'Keep records for a shorter time?',
        body: `Issued records will be kept for ${months} months instead of ${info.retention_months}.`,
        irreversible: 'Records older than the new period can be removed, and removed records cannot be brought back.',
        confirmLabel: 'Shorten retention',
        danger: true,
      });
      if (!ok) return;
    }
    setSaving(true);
    try {
      const res = await setEvidenceRetention(months);
      setInfo(res);
      toast('Retention saved.');
    } catch (err) {
      toast(humanError(err, 'Retention was not saved. Try again in a moment.'));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="panel p-4 space-y-3" data-testid="evidence-retention">
      <p className="text-xs text-soft leading-relaxed">{info.retention}</p>
      {isOwner && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-soft">
          <label htmlFor="retention-months">Keep issued records for</label>
          <select id="retention-months" value={months} onChange={e => setMonths(Number(e.target.value))}
                  className="bg-inset border border-line rounded px-2 py-1 text-ink min-h-[44px] sm:min-h-0">
            {RETENTION_CHOICES.map(m => <option key={m} value={m}>{m} months</option>)}
          </select>
          <button type="button" onClick={save} disabled={saving || months === info.retention_months}
                  className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line text-ink disabled:opacity-50 min-h-[44px] sm:min-h-0">Save</button>
        </div>
      )}
    </div>
  );
}

export default function Reports() {
  const toast = useToast();
  // Last-seen list paints at once on a revisit; load() refreshes it.
  const [loading, setLoading] = useState(() => readPageCache('reports') === undefined);
  const [reports, setReports] = useState<ReportRow[]>(() => readPageCache<ReportRow[]>('reports') ?? []);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const zone = useOrgZone();

  const [preview, setPreview] = useState<ReportRow | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);

  const [emailOpen, setEmailOpen] = useState(false);
  const [emailTo, setEmailTo] = useState('');
  const [emailName, setEmailName] = useState('');
  const [emailNote, setEmailNote] = useState('');
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    // The skeleton is only for a first visit; refreshes keep the list on screen.
    try {
      const res = await listReportsStrict();
      setReports(res.reports);
      writePageCache('reports', res.reports);
      setLoadError(null);
    } catch (e) {
      setLoadError(humanError(e, 'Something went wrong on our side. Try again in a moment.'));
      toast('The reports were not refreshed.');
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
      // One key per click: a double-click or a retry finds the first report instead of using another unit of the quota.
      const res = await createReport({ request_key: `ui-${crypto.randomUUID()}` });
      if (res?.report) {
        toast('Report ready. You can open it from the list.');
        await load();
      } else {
        toast('The report was not created. Try again in a moment.');
      }
    } catch (err) {
      toast(humanError(err, 'The report was not created. Try again in a moment.'));
    } finally {
      setCreating(false);
    }
  };

  const openPreview = async (id: string) => {
    setPreviewOpen(true);
    setPreviewId(id);
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const res = await getReport(id);
      if (res?.report) setPreview(res.report);
      else setPreviewError('We could not open this report. Try again.');
    } catch (e) {
      setPreviewError(humanError(e, 'We could not open this report. Try again.'));
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
      toast(res.message || 'Report sent.');
      setEmailOpen(false);
      setEmailTo('');
      setEmailName('');
      setEmailNote('');
    } catch (err) {
      toast(humanError(err, 'The report was not sent. Check the address and try again.'));
    } finally {
      setSending(false);
    }
  };

  const downloadHtml = (report: ReportRow) => {
    if (!report.html) {
      toast('Open the report once, then download it.');
      return;
    }
    const blob = new Blob([report.html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.title.replace(/[^\w.-]+/g, '_')}.html`;
    a.click();
    URL.revokeObjectURL(url);
    toast('Report downloaded.');
  };

  return (
    <div className="space-y-5 pb-10 content-fade-in">
      <PageHead
        title="Reports"
        note="Create a report from your latest score and share it with your team or board."
        actions={
          <>
            <button
              onClick={() => setEmailOpen(true)}
              className="btn-tactile flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-xs mono border border-line bg-raised hover:border-line-strong hover:text-ink min-h-[44px] sm:min-h-0"
            >
              <Send size={13} className="text-accent" /> Email report
            </button>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="btn-tactile flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-xs mono bg-accent text-white hover:opacity-90 disabled:opacity-50 min-h-[44px] sm:min-h-0"
            >
              {creating ? <RefreshCw size={13} className="animate-spin" /> : <Plus size={13} />}
              {creating ? 'Making the report…' : 'Generate report'}
            </button>
          </>
        }
      />

      <RetentionNote />

      {loading ? (
        <LoadingPanel label="saved reports" />
      ) : loadError && reports.length === 0 ? (
        <ErrorPanel title="We could not load your reports" message={loadError} onRetry={() => { setLoading(true); void load(); }} />
      ) : reports.length === 0 ? (
        <EmptyPanel icon={<FileText size={28} />} title="No reports yet"
                    help="A report is a saved copy of your current security score that you can share with your team or board."
                    action={<button type="button" onClick={handleCreate} disabled={creating}
                                    className="btn-tactile flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono bg-accent text-white disabled:opacity-50 min-h-[44px]"><Plus size={13} /> Generate your first report</button>} />
      ) : (
        <div className="rounded-lg border border-line bg-raised overflow-x-auto">
          <table className="table-stack w-full text-left text-xs mono sm:min-w-[640px]">
            <thead>
              <tr className="border-b border-line text-soft text-[11px]">
                <th className="px-4 py-3 font-medium">TITLE</th>
                <th className="px-4 py-3 font-medium">DOMAIN</th>
                <th className="px-4 py-3 font-medium">STATUS</th>
                <th className="px-4 py-3 font-medium">SCORE</th>
                <th className="px-4 py-3 font-medium">CREATED ({zone})</th>
                <th className="px-4 py-3 font-medium text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {reports.map(r => (
                <tr key={r.id} className="hover:bg-inset/40 transition-colors">
                  <td className="stack-title px-4 py-3 text-ink font-semibold max-w-[280px]">
                    <div className="truncate">{r.title}</div>
                    <div
                      className="mt-1 text-[10px] font-normal text-soft whitespace-normal"
                      title={r.integrity_label}
                      data-testid="report-integrity"
                    >
                      {r.integrity === 'snapshot' ? 'FROZEN SNAPSHOT' : r.integrity === 'legacy' ? 'LEGACY · LIMITED EVIDENCE' : 'NOT CONFIRMED AS UNCHANGED'}
                    </div>
                  </td>
                  <td data-label="Domain" className="px-4 py-3 text-soft">{r.domain || '—'}</td>
                  <td data-label="Status" className="px-4 py-3">
                    <StatusChip level={r.status === 'ready' ? 'ok' : r.status === 'failed' ? 'bad' : 'warn'}>
                      {r.status.toUpperCase()}
                    </StatusChip>
                  </td>
                  <td data-label="Score" className="px-4 py-3 text-ink">
                    {r.summary?.score != null ? `${r.summary.score}/100` : '—'}
                  </td>
                  <td data-label="Created" className="px-4 py-3 text-soft">
                    {fmtDayZone(r.created_at, zone)}
                  </td>
                  <td className="stack-actions px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1.5">
                      <button
                        onClick={() => openPreview(r.id)}
                        className="btn-tactile px-2.5 py-1 rounded border border-line text-[10px] hover:border-line-strong hover:text-ink min-h-[44px] sm:min-h-0"
                      >
                        <Eye size={11} className="inline mr-1" />VIEW
                      </button>
                      <button
                        onClick={() => downloadHtml(r)}
                        className="btn-tactile px-2.5 py-1 rounded border border-line text-[10px] hover:border-line-strong hover:text-ink min-h-[44px] sm:min-h-0"
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

      <Dialog
        open={previewOpen}
        onClose={() => {
          setPreviewOpen(false);
          setPreview(null);
          setPreviewError(null);
        }}
        title={preview?.title || 'Report preview'}
        icon={<FileText size={16} className="text-accent" />}
        maxWidth="max-w-3xl"
      >
        {previewLoading ? (
          <LoadingPanel label="the report" />
        ) : previewError ? (
          <ErrorPanel title="We could not open this report" message={previewError} onRetry={() => previewId && void openPreview(previewId)} />
        ) : preview?.html ? (
          <div data-testid="report-preview" className="overflow-x-auto rounded border border-line bg-inset" dangerouslySetInnerHTML={{ __html: preview.html }} />
        ) : (
          <EmptyPanel title="This report has no preview" help="You can still download it from the list." />
        )}
      </Dialog>

      <Dialog
        open={emailOpen}
        onClose={() => setEmailOpen(false)}
        title="Email this report"
        icon={<Send size={16} className="text-accent" />}
        maxWidth="max-w-md"
        dirty={!!(emailTo || emailName || emailNote)}
        footer={<EmailActions sending={sending} disabled={!emailTo.trim()} />}
      >
        <form id="report-email-form" onSubmit={handleSendEmail} className="space-y-3.5 text-xs">
          <div className="space-y-1.5">
            <label htmlFor="report-to" className="mono text-soft block">Send to (email address)</label>
            <input
              id="report-to"
              type="email"
              required
              value={emailTo}
              onChange={e => setEmailTo(e.target.value)}
              placeholder="board@company.ng"
              className="w-full bg-inset border border-line rounded px-3 py-2 min-h-[44px] text-ink mono focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="report-name" className="mono text-soft block">Their name (optional)</label>
            <input
              id="report-name"
              type="text"
              value={emailName}
              onChange={e => setEmailName(e.target.value)}
              placeholder="Board Risk Committee"
              className="w-full bg-inset border border-line rounded px-3 py-2 min-h-[44px] text-ink mono focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="report-note" className="mono text-soft block">A short note (optional)</label>
            <textarea
              id="report-note"
              rows={3}
              value={emailNote}
              onChange={e => setEmailNote(e.target.value)}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent resize-y"
            />
          </div>
        </form>
      </Dialog>
    </div>
  );
}

function EmailActions({ sending, disabled }: { sending: boolean; disabled: boolean }) {
  const close = useDialogClose();
  return (
    <>
      <button type="button" onClick={close} className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line text-soft hover:text-ink min-h-[44px]">Cancel</button>
      <button type="submit" form="report-email-form" disabled={sending || disabled}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono bg-accent text-white disabled:opacity-50 flex items-center justify-center gap-1.5 min-h-[44px]">
        {sending ? <RefreshCw size={12} className="animate-spin" /> : <Send size={12} />}
        {sending ? 'Sending…' : 'Send report'}
      </button>
    </>
  );
}
