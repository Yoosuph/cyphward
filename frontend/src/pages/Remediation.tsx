import { useCallback, useEffect, useRef, useState } from 'react';
import {
  RefreshCw,
  ShieldCheck,
  Plus,
  PlayCircle,
  CheckCircle2,
  RotateCcw,
  ListTodo,
} from 'lucide-react';
import {
  getRemediationTasks,
  createRemediationTask,
  updateRemediationTask,
  verifyRemediationTask,
  getFindings,
  type RemediationTask,
} from '../lib/api';
import type { Finding } from '../types';
import { useToast } from '../components/Toast';
import { readPageCache, writePageCache } from '../lib/pageCache';
import Modal from '../components/Modal';
import StatusChip from '../components/StatusChip';
import { PageHead, Loading } from '../components/ui';

const STATUS_FILTERS = [
  { value: '', label: 'ALL' },
  { value: 'open', label: 'OPEN' },
  { value: 'in_progress', label: 'IN PROGRESS' },
  { value: 'ready_for_verification', label: 'READY FOR VERIFY' },
  { value: 'reopened', label: 'REOPENED' },
  { value: 'verified', label: 'VERIFIED' },
];

function statusChipLevel(status: string): 'ok' | 'warn' | 'bad' | 'idle' {
  switch (status) {
    case 'verified':
      return 'ok';
    case 'ready_for_verification':
    case 'in_progress':
      return 'warn';
    case 'reopened':
      return 'bad';
    default:
      return 'idle';
  }
}

export default function Remediation() {
  const toast = useToast();
  // Last-seen list paints at once on a revisit; load() refreshes it.
  const [loading, setLoading] = useState(() => readPageCache('remediation:') === undefined);
  const [tasks, setTasks] = useState<RemediationTask[]>(() => readPageCache<RemediationTask[]>('remediation:') ?? []);
  const shownKey = useRef<string | null>(null); // cache key of the rows on screen
  const [statusFilter, setStatusFilter] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [findingId, setFindingId] = useState('');
  const [title, setTitle] = useState('');
  const [instructions, setInstructions] = useState('');
  const [priority, setPriority] = useState('medium');
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const cacheKey = `remediation:${statusFilter}`;
    const cached = readPageCache<RemediationTask[]>(cacheKey);
    if (cached) setTasks(cached);
    // Skeleton only when this view has nothing to show yet (not on a refresh).
    if (cached === undefined && shownKey.current !== cacheKey) setLoading(true);
    else if (cached) setLoading(false);
    shownKey.current = cacheKey;
    try {
      const res = await getRemediationTasks(statusFilter ? { status: statusFilter } : undefined);
      setTasks(res.tasks);
      writePageCache(cacheKey, res.tasks);
    } catch (e: any) {
      toast(e.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = async () => {
    setCreateOpen(true);
    try {
      const res = await getFindings({ status: 'open' });
      setFindings(res.findings);
    } catch {
      setFindings([]);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setCreating(true);
    try {
      const res = await createRemediationTask({
        title: title.trim(),
        instructions: instructions.trim() || undefined,
        finding_id: findingId || undefined,
        priority,
      });
      if (res?.task) {
        toast('Task created');
        setCreateOpen(false);
        setTitle('');
        setInstructions('');
        setFindingId('');
        setPriority('medium');
        await load();
      } else {
        toast('Failed to create task');
      }
    } catch (err: any) {
      toast(err.message || 'Failed to create task');
    } finally {
      setCreating(false);
    }
  };

  const advance = async (task: RemediationTask) => {
    setBusyId(task.id);
    try {
      const next =
        task.status === 'open' ? 'in_progress'
        : task.status === 'in_progress' ? 'ready_for_verification'
        : task.status === 'reopened' ? 'in_progress'
        : null;

      if (next) {
        const res = await updateRemediationTask(task.id, { status: next });
        if (res?.task) {
          setTasks(prev => prev.map(t => (t.id === task.id ? { ...t, ...res.task } : t)));
          toast(`Status → ${next.replace('_', ' ')}`);
        }
        return;
      }
      toast('Use Verify for ready tasks');
    } catch (err: any) {
      toast(err.message || 'Update failed');
    } finally {
      setBusyId(null);
    }
  };

  const verify = async (task: RemediationTask) => {
    setBusyId(task.id);
    try {
      const res = await verifyRemediationTask(task.id);
      if (res) {
        toast(res.message);
        await load();
      } else {
        toast('Verification request failed');
      }
    } catch (err: any) {
      toast(err.message || 'Verification failed');
    } finally {
      setBusyId(null);
    }
  };

  const counts = {
    open: tasks.filter(t => t.status === 'open').length,
    progress: tasks.filter(t => t.status === 'in_progress').length,
    ready: tasks.filter(t => t.status === 'ready_for_verification').length,
    verified: tasks.filter(t => t.status === 'verified').length,
  };

  return (
    <div className="space-y-5 pb-10 content-fade-in">
      <PageHead
        title="Remediation"
        note="Track each fix to done. A recheck confirms it against the live host."
        actions={
          <button
            onClick={openCreate}
            className="btn-tactile flex items-center gap-1.5 px-3 py-2 rounded text-xs mono bg-accent text-white hover:opacity-90"
          >
            <Plus size={13} /> NEW TASK
          </button>
        }
      />

      <div className="chip-row flex flex-wrap items-center gap-1.5">
        {STATUS_FILTERS.map(f => (
          <button
            key={f.value}
            type="button"
            onClick={() => setStatusFilter(f.value)}
            className={`px-3 py-1.5 rounded text-[11px] mono border transition-colors ${
              statusFilter === f.value
                ? 'border-accent text-ink bg-accent/10'
                : 'border-line text-soft hover:text-ink hover:border-line-strong'
            }`}
          >
            {f.label}
          </button>
        ))}
        <button
          type="button"
          onClick={load}
          className="ml-auto p-2 rounded border border-line text-soft hover:text-ink"
          title="Refresh"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {loading ? (
        <Loading label="REMEDIATION QUEUE" />
      ) : tasks.length === 0 ? (
        <div className="p-10 rounded-lg border border-line bg-raised text-center">
          <ShieldCheck size={28} className="mx-auto text-accent mb-3" />
          <p className="mono text-sm text-ink">No tasks yet</p>
          <p className="text-xs text-soft mt-1">Create a task from an open finding to start fixing and verifying.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-line bg-raised overflow-x-auto">
          <table className="table-stack w-full text-left text-xs mono sm:min-w-[720px]">
            <thead>
              <tr className="border-b border-line text-soft text-[11px]">
                <th className="px-4 py-3 font-medium">TASK</th>
                <th className="px-4 py-3 font-medium">PRIORITY</th>
                <th className="px-4 py-3 font-medium">STATUS</th>
                <th className="px-4 py-3 font-medium">ASSIGNEE</th>
                <th className="px-4 py-3 font-medium text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {tasks.map(task => (
                <tr key={task.id} className="hover:bg-inset/40 transition-colors">
                  <td className="stack-title px-4 py-3 max-w-[320px]">
                    <p className="text-ink font-semibold truncate">{task.title}</p>
                    {task.finding_title && task.finding_title !== task.title && (
                      <p className="text-[11px] text-soft truncate">From: {task.finding_title}</p>
                    )}
                  </td>
                  <td data-label="Priority" className="px-4 py-3">
                    <span className="tag uppercase">{task.priority}</span>
                  </td>
                  <td data-label="Status" className="px-4 py-3">
                    <StatusChip level={statusChipLevel(task.status)}>
                      {task.status.replace(/_/g, ' ').toUpperCase()}
                    </StatusChip>
                  </td>
                  <td data-label="Assignee" className="px-4 py-3 text-soft">{task.assignee_name || task.assignee_email || '—'}</td>
                  <td className="stack-actions px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1.5">
                      {task.status !== 'verified' && task.status !== 'ready_for_verification' && (
                        <button
                          onClick={() => advance(task)}
                          disabled={busyId === task.id}
                          className="btn-tactile px-2.5 py-1 rounded border border-line text-[10px] hover:border-line-strong hover:text-ink disabled:opacity-50"
                        >
                          {task.status === 'open' || task.status === 'reopened' ? (
                            <><RotateCcw size={11} className="inline mr-1" />START</>
                          ) : (
                            <>MARK READY</>
                          )}
                        </button>
                      )}
                      {(task.status === 'ready_for_verification' || task.status === 'reopened' || task.status === 'in_progress') && (
                        <button
                          onClick={() => verify(task)}
                          disabled={busyId === task.id}
                          className="btn-tactile px-2.5 py-1 rounded bg-accent/10 border border-accent/40 text-accent text-[10px] hover:bg-accent/20 disabled:opacity-50"
                        >
                          {busyId === task.id ? <RefreshCw size={11} className="inline animate-spin" /> : <><CheckCircle2 size={11} className="inline mr-1" />VERIFY</>}
                        </button>
                      )}
                      {task.status === 'verified' && (
                        <span className="text-ok text-[10px] mono">VERIFIED</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="NEW FIX TASK"
        icon={<Plus size={16} className="text-accent" />}
        maxWidth="max-w-lg"
      >
        <form onSubmit={handleCreate} className="space-y-3.5 text-xs">
          <div className="space-y-1.5">
            <label className="mono text-soft">LINK OPEN FINDING (OPTIONAL)</label>
            <select
              value={findingId}
              onChange={e => {
                setFindingId(e.target.value);
                const f = findings.find(x => x.id === e.target.value);
                if (f && !title.trim()) setTitle(f.title);
              }}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            >
              <option value="">— none —</option>
              {findings.map(f => (
                <option key={f.id} value={f.id}>
                  [{f.severity}] {f.title}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label className="mono text-soft">TITLE</label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              required
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            />
          </div>

          <div className="space-y-1.5">
            <label className="mono text-soft">INSTRUCTIONS</label>
            <textarea
              value={instructions}
              onChange={e => setInstructions(e.target.value)}
              rows={4}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent resize-y"
            />
          </div>

          <div className="space-y-1.5">
            <label className="mono text-soft">PRIORITY</label>
            <select
              value={priority}
              onChange={e => setPriority(e.target.value)}
              className="w-full bg-inset border border-line rounded px-3 py-2 text-ink mono focus:outline-none focus:border-accent"
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-line">
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              className="btn-tactile px-3 py-1.5 rounded text-xs mono border border-line text-soft hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating || !title.trim()}
              className="btn-tactile px-4 py-1.5 rounded text-xs mono bg-accent text-white disabled:opacity-50 flex items-center gap-1.5"
            >
              {creating ? <RefreshCw size={12} className="animate-spin" /> : null}
              Create Task
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
