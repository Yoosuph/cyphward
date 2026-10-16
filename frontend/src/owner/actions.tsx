import { useContext, useEffect, useState, type ReactNode } from 'react';
import { AlertCircle, AlertTriangle, CalendarPlus, LogOut, Layers, XCircle, type LucideIcon } from 'lucide-react';
import Modal from '../components/Modal';
import { useToast } from '../components/Toast';
import { OwnerApiError, ownerPost } from './ownerApi';
import { SessionEndedContext, fmtDate } from './ui';

/**
 * Owner console actions. Each one opens a dialog that says exactly what will
 * change, asks for a written reason (kept in the owner audit log, never shown
 * to the customer) and only then calls the API. The server re-checks
 * everything and records the action with the reason.
 */

const REASON_MIN = 5;

function ActionDialog({ open, onClose, title, danger, confirmLabel, summary, children, ready = true, run }: {
  open: boolean;
  onClose: () => void;
  title: string;
  danger?: boolean;
  confirmLabel: string;
  summary: ReactNode;
  children?: ReactNode;
  ready?: boolean;
  run: (reason: string) => Promise<string>;
}) {
  const onSessionEnded = useContext(SessionEndedContext);
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setReason('');
      setError('');
    }
  }, [open]);

  const trimmed = reason.trim();
  const canSubmit = ready && trimmed.length >= REASON_MIN && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError('');
    try {
      const message = await run(trimmed);
      toast(message);
      onClose();
    } catch (e) {
      const err = e as OwnerApiError;
      if (err.status === 401) onSessionEnded();
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={busy ? () => {} : onClose} title={title} maxWidth="max-w-md"
           icon={danger ? <AlertTriangle size={15} /> : undefined}>
      <form className="space-y-5" onSubmit={e => { e.preventDefault(); void submit(); }}>
        <div className="text-sm text-soft leading-relaxed">{summary}</div>
        {children}
        <div>
          <label htmlFor="owner-action-reason" className="block mono text-[10px] tracking-[.18em] text-soft mb-2">
            REASON (KEPT IN THE OWNER LOG)
          </label>
          <textarea
            id="owner-action-reason"
            rows={3}
            maxLength={500}
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="e.g. Customer asked by email, ticket 42"
            className="w-full mono text-[12.5px] bg-inset border border-line rounded-[3px] px-3.5 py-3 text-ink outline-none focus:border-[var(--ink)] placeholder:text-soft resize-y"
          />
          {trimmed.length > 0 && trimmed.length < REASON_MIN && (
            <p className="text-[11px] mono text-soft mt-1.5">A few more words, please.</p>
          )}
        </div>
        {error && (
          <div role="alert" className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
            <AlertCircle size={14} className="flex-none mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <button type="button" className="btn btn-ghost justify-center" onClick={onClose} disabled={busy}>CANCEL</button>
          <button type="submit" className="btn btn-solid justify-center" disabled={!canSubmit}>
            {busy ? 'WORKING…' : confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ActionButton({ icon: Icon, label, onClick, danger }: { icon: LucideIcon; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={`btn-mini whitespace-nowrap ${danger ? 'hover:!border-accent hover:!text-accent' : ''}`}>
      <Icon size={12} /> {label}
    </button>
  );
}

/* ── Organization: plan ─────────────────────────────────────────────────── */
export function ChangePlanAction({ orgId, orgName, current, plans, onDone }: {
  orgId: string; orgName: string; current: string; plans: { slug: string; label: string }[]; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const choices = plans.filter(p => p.slug !== current);
  const [plan, setPlan] = useState('');
  useEffect(() => { if (open) setPlan(choices[0]?.slug || ''); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const label = (slug: string) => plans.find(p => p.slug === slug)?.label || slug;
  if (choices.length === 0) return null;
  return (
    <>
      <ActionButton icon={Layers} label="CHANGE PLAN" onClick={() => setOpen(true)} />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Change plan"
        confirmLabel="CHANGE PLAN"
        ready={!!plan}
        summary={<>Moves <span className="text-ink">{orgName}</span> from <span className="text-ink">{label(current)}</span> to the plan below. Its status, renewal date and invoices stay as they are; nothing is charged.</>}
        run={async reason => {
          await ownerPost(`/organizations/${orgId}/plan`, { plan, reason });
          onDone();
          return `${orgName} is now on ${label(plan)}.`;
        }}
      >
        <div className="field">
          <label htmlFor="owner-plan">NEW PLAN</label>
          <select id="owner-plan" value={plan} onChange={e => setPlan(e.target.value)}>
            {choices.map(p => <option key={p.slug} value={p.slug}>{p.label}</option>)}
          </select>
        </div>
      </ActionDialog>
    </>
  );
}

/* ── Organization: trial ────────────────────────────────────────────────── */
export function ExtendTrialAction({ orgId, orgName, trialEndsAt, onDone }: {
  orgId: string; orgName: string; trialEndsAt?: string | null; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(14);
  useEffect(() => { if (open) setDays(14); }, [open]);
  const base = Math.max(Date.now(), trialEndsAt ? new Date(trialEndsAt).getTime() : 0);
  const newEnd = new Date(base + days * 86400000).toISOString();
  const lapsed = !!trialEndsAt && new Date(trialEndsAt).getTime() < Date.now();
  return (
    <>
      <ActionButton icon={CalendarPlus} label="EXTEND TRIAL" onClick={() => setOpen(true)} />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Extend trial"
        confirmLabel="EXTEND TRIAL"
        ready={days >= 1 && days <= 60}
        summary={<>{orgName}'s trial {lapsed ? 'ended' : 'ends'} {fmtDate(trialEndsAt, false)}. {lapsed ? 'It restarts from today and ' : 'It '}will end <span className="text-ink">{fmtDate(newEnd, false)}</span>. A trial can't run more than 90 days ahead.</>}
        run={async reason => {
          await ownerPost(`/organizations/${orgId}/trial`, { days, reason });
          onDone();
          return `Trial extended to ${fmtDate(newEnd, false)}.`;
        }}
      >
        <div>
          <p className="mono text-[10px] tracking-[.18em] text-soft mb-2">ADD DAYS</p>
          <div className="flex flex-wrap items-center gap-2">
            {[7, 14, 30].map(d => (
              <button key={d} type="button" onClick={() => setDays(d)} aria-pressed={days === d}
                      className={`btn-mini ${days === d ? '!border-[var(--ink)] !text-ink bg-inset' : ''}`}>{d} DAYS</button>
            ))}
            <input type="number" min={1} max={60} value={days} aria-label="Days to add"
                   onChange={e => setDays(Math.max(0, Math.min(60, Number(e.target.value) || 0)))}
                   className="w-20 mono text-[12.5px] bg-inset border border-line rounded-[3px] px-3 py-2 text-ink outline-none focus:border-[var(--ink)]" />
          </div>
        </div>
      </ActionDialog>
    </>
  );
}

/* ── Scan: cancel ───────────────────────────────────────────────────────── */
export function CancelScanAction({ scanId, domain, state, onDone }: { scanId: string; domain: string; state: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const stuck = state === 'running_lease_expired' || state === 'queued_delayed';
  return (
    <>
      <ActionButton icon={XCircle} label="CANCEL SCAN" danger onClick={() => setOpen(true)} />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Cancel scan"
        danger
        confirmLabel="CANCEL SCAN"
        summary={<>Stops the scan of <span className="text-ink">{domain}</span>{stuck ? ' (it looks stuck)' : ''}. Any worker still holding it is told to stop, partial results aren't scored, and the customer's activity log shows it was cancelled by Cyphward. The customer can start a new scan.</>}
        run={async reason => {
          await ownerPost(`/scans/${scanId}/cancel`, { reason });
          onDone();
          return `Scan of ${domain} cancelled.`;
        }}
      />
    </>
  );
}

/* ── User: sign out everywhere ──────────────────────────────────────────── */
export function SignOutEverywhereAction({ userId, email, onDone }: { userId: string; email: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <ActionButton icon={LogOut} label="SIGN OUT EVERYWHERE" danger onClick={() => setOpen(true)} />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Sign out everywhere"
        danger
        confirmLabel="SIGN OUT EVERYWHERE"
        summary={<>Ends every signed-in session for <span className="text-ink">{email}</span> right away and forgets their remembered browsers, so their next sign-in asks for their second step again. Their password and authenticator don't change.</>}
        run={async reason => {
          const r = await ownerPost<{ sessions_revoked: number; remembered_browsers_cleared: number }>(`/users/${userId}/sign-out`, { reason });
          onDone();
          return `${email}: ${r.sessions_revoked} session${r.sessions_revoked === 1 ? '' : 's'} ended, ${r.remembered_browsers_cleared} remembered browser${r.remembered_browsers_cleared === 1 ? '' : 's'} forgotten.`;
        }}
      />
    </>
  );
}
