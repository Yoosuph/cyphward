import { useContext, useEffect, useState, type ReactNode } from 'react';
import { AlertCircle, AlertTriangle, CalendarPlus, LogOut, Layers, PauseCircle, PlayCircle, UserMinus, UserPlus, XCircle, type LucideIcon } from 'lucide-react';
import Dialog from '../components/ui/Dialog';
import { TypedNameGate, typedNameMatches } from '../components/ui/ConfirmDialog';
import { useToast } from '../components/Toast';
import { OwnerApiError, ownerPost } from './ownerApi';
import { SessionEndedContext, fmtDate } from './ui';

/**
 * Owner console actions. Each one opens a confirmation dialog (the shared Dialog) that says exactly what will
 * change and asks for a written reason (kept in the owner audit log, never shown to the customer). Every
 * organization action also has the shared typed-name gate (components/ConfirmDialog.tsx TypedNameGate): the
 * confirm button stays disabled until the organization's name is typed exactly, and the server checks the name
 * again under its row lock: the text the owner typed is what is sent as confirm_name. Cancel scan and sign out
 * everywhere use the same gate on the domain or the email address (checked in the console only; the server needs a
 * reason). Errors show reviewed wording only (ownerApi.ownerErrorText).
 */

const REASON_MIN = 5;

function ActionDialog({ open, onClose, title, danger, confirmLabel, summary, children, ready = true, typedName, typedWhat, run, testId }: {
  open: boolean;
  onClose: () => void;
  title: string;
  danger?: boolean;
  confirmLabel: string;
  summary: ReactNode;
  children?: ReactNode;
  ready?: boolean;
  /** The exact text to type before the action can run (the organization name for organization actions). */
  typedName?: string;
  /** What the typed text is, for the gate's label ("the organization name" by default). */
  typedWhat?: string;
  /** Receives the reason and the text the owner typed; organization actions send the typed text as confirm_name. */
  run: (reason: string, typed: string) => Promise<string>;
  testId?: string;
}) {
  const onSessionEnded = useContext(SessionEndedContext);
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setReason('');
      setTyped('');
      setError('');
    }
  }, [open]);

  const trimmed = reason.trim();
  const nameOk = typedName === undefined || typedNameMatches(typed, typedName);
  const canSubmit = ready && nameOk && trimmed.length >= REASON_MIN && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError('');
    try {
      const message = await run(trimmed, typed);
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
    <Dialog open={open} onClose={busy ? () => {} : onClose} title={title} maxWidth="max-w-md" compact
            dirty={!busy && (reason.length > 0 || typed.length > 0)}
            icon={danger ? <AlertTriangle size={15} /> : undefined}>
      <form className="space-y-5" data-testid={testId || 'owner-action-dialog'} onSubmit={e => { e.preventDefault(); void submit(); }}>
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
        {typedName !== undefined && <TypedNameGate name={typedName} value={typed} onChange={setTyped} id="owner-action-typed-name" what={typedWhat} />}
        {error && (
          <div role="alert" data-testid="owner-action-error" className="p-3 bg-red-500/10 border border-red-500/30 rounded text-xs mono text-red-500 flex items-start gap-2">
            <AlertCircle size={14} className="flex-none mt-0.5" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <button type="button" className="btn btn-ghost justify-center touch-target" onClick={onClose} disabled={busy}
                  data-testid="confirm-cancel">CANCEL</button>
          <button type="submit" className="btn btn-solid justify-center touch-target" disabled={!canSubmit} data-testid="confirm-ok">
            {busy ? 'WORKING…' : confirmLabel}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ActionButton({ icon: Icon, label, onClick, danger, testId }: { icon: LucideIcon; label: string; onClick: () => void; danger?: boolean; testId?: string }) {
  return (
    <button type="button" onClick={onClick} data-testid={testId}
            className={`btn-mini whitespace-nowrap ${danger ? 'hover:!border-accent hover:!text-accent' : ''}`}>
      <Icon size={12} aria-hidden="true" /> {label}
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
      <ActionButton icon={Layers} label="CHANGE PLAN" onClick={() => setOpen(true)} testId="org-plan-open" />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Change plan"
        confirmLabel="CHANGE PLAN"
        ready={!!plan}
        typedName={orgName}
        summary={<>Moves <span className="text-ink">{orgName}</span> from <span className="text-ink">{label(current)}</span> to the plan below. Its status, renewal date and invoices stay as they are; nothing is charged.</>}
        run={async (reason, typed) => {
          await ownerPost(`/organizations/${orgId}/plan`, { plan, reason, confirm_name: typed });
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
      <ActionButton icon={CalendarPlus} label="EXTEND TRIAL" onClick={() => setOpen(true)} testId="org-trial-open" />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Extend trial"
        confirmLabel="EXTEND TRIAL"
        ready={days >= 1 && days <= 60}
        typedName={orgName}
        summary={<>{orgName}'s trial {lapsed ? 'ended' : 'ends'} {fmtDate(trialEndsAt, false)}. {lapsed ? 'It restarts from today and ' : 'It '}will end <span className="text-ink">{fmtDate(newEnd, false)}</span>. A trial can't run more than 90 days ahead.</>}
        run={async (reason, typed) => {
          await ownerPost(`/organizations/${orgId}/trial`, { days, reason, confirm_name: typed });
          onDone();
          return `Trial extended to ${fmtDate(newEnd, false)}.`;
        }}
      >
        <div>
          <p className="mono text-[10px] tracking-[.18em] text-soft mb-2">ADD DAYS</p>
          <div className="flex flex-wrap items-center gap-2">
            {[7, 14, 30].map(d => (
              <button key={d} type="button" onClick={() => setDays(d)} aria-pressed={days === d}
                      className={`btn-mini touch-target ${days === d ? '!border-[var(--ink)] !text-ink bg-inset' : ''}`}>{d} DAYS</button>
            ))}
            <input type="number" min={1} max={60} value={days} aria-label="Days to add"
                   onChange={e => setDays(Math.max(0, Math.min(60, Number(e.target.value) || 0)))}
                   className="w-20 touch-target mono text-[12.5px] bg-inset border border-line rounded-[3px] px-3 py-2 text-ink outline-none focus:border-[var(--ink)]" />
          </div>
        </div>
      </ActionDialog>
    </>
  );
}

/* ── Organization: suspend / unsuspend ──────────────────────────────────── */
const SUSPENSION_RULE = 'While suspended, its members can still sign in and read their data, but changes that add something are refused: no new scans, domains, settings, new members or promotions, compliance records, documents, packs or snapshots, and its owners cannot create a new organization. They can still cancel their subscription, revoke reviewer access, withdraw an invitation and lower a role. Scheduled scans and queued scans pause until you lift it. Owner actions keep working. You can lift it at any time.';

export function SuspendAction({ orgId, orgName, suspended, onDone }: {
  orgId: string; orgName: string; suspended: boolean; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const verb = suspended ? 'unsuspend' : 'suspend';
  return (
    <>
      <ActionButton icon={suspended ? PlayCircle : PauseCircle} label={suspended ? 'UNSUSPEND' : 'SUSPEND'}
                    danger={!suspended} onClick={() => setOpen(true)} testId={`org-${verb}-open`} />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title={suspended ? 'Unsuspend organization' : 'Suspend organization'}
        danger={!suspended}
        confirmLabel={suspended ? 'UNSUSPEND' : 'SUSPEND'}
        typedName={orgName}
        testId={`org-${verb}-dialog`}
        summary={suspended
          ? <>Lifts the suspension of <span className="text-ink">{orgName}</span>. The change and your reason are kept in the owner log.</>
          : <>Marks <span className="text-ink">{orgName}</span> as suspended. {SUSPENSION_RULE}</>}
        run={async (reason, typed) => {
          await ownerPost(`/organizations/${orgId}/${verb}`, { reason, confirm_name: typed });
          onDone();
          return suspended ? `${orgName} is no longer suspended.` : `${orgName} is suspended.`;
        }}
      />
    </>
  );
}

/* ── Organization: remove a member ──────────────────────────────────────── */
export function RemoveMemberAction({ orgId, orgName, userId, email, role, onDone }: {
  orgId: string; orgName: string; userId: string; email: string; role: string; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <ActionButton icon={UserMinus} label="REMOVE" danger onClick={() => setOpen(true)} testId="member-remove-open" />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Remove member"
        danger
        confirmLabel="REMOVE MEMBER"
        typedName={orgName}
        testId="member-remove-dialog"
        summary={<>Removes <span className="text-ink break-all">{email}</span> ({role}) from <span className="text-ink">{orgName}</span>. They lose access to this organization at their next request. Their account and the organization's data stay; the owner log keeps their email, role and join date, and the membership can be restored from it once. An organization always keeps at least one owner.</>}
        run={async (reason, typed) => {
          await ownerPost(`/organizations/${orgId}/members/${userId}/remove`, { reason, confirm_name: typed });
          onDone();
          return `${email} was removed from ${orgName}.`;
        }}
      />
    </>
  );
}

/* ── Organization: restore a removed member ─────────────────────────────── */
export function RestoreMemberAction({ orgId, orgName, auditId, email, role, onDone }: {
  orgId: string; orgName: string; auditId: string; email: string; role: string; onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <ActionButton icon={UserPlus} label="RESTORE" onClick={() => setOpen(true)} testId="member-restore-open" />
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Restore member"
        confirmLabel="RESTORE MEMBER"
        typedName={orgName}
        testId="member-restore-dialog"
        summary={<>Adds <span className="text-ink break-all">{email}</span> back to <span className="text-ink">{orgName}</span> as {role}, with the join date from the removal record. Refused if they are already a member, if this removal was already restored, or while the organization is suspended. The change and your reason are kept in the owner log, and the customer's activity log shows it was done by Cyphward.</>}
        run={async (reason, typed) => {
          await ownerPost(`/organizations/${orgId}/members/restore`, { reason, confirm_name: typed, audit_id: auditId });
          onDone();
          return `${email} was restored to ${orgName}.`;
        }}
      />
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
        typedName={domain}
        typedWhat="the domain"
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
        typedName={email}
        typedWhat="the email address"
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
