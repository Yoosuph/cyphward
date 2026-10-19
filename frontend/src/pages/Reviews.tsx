import { useCallback, useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ChevronDown, Info } from 'lucide-react';
import CyphwardLogo from '../components/CyphwardLogo';
import Modal from '../components/Modal';
import StatusChip, { type ChipLevel } from '../components/StatusChip';
import { useToast } from '../components/Toast';
import { useAuth } from '../lib/auth';
import {
  getMyReviewGrants, getReviewerOverview, recordClauseReference, recordPractitionerReview,
  type ComplianceRequirement, type ComplianceStatus, type MyReviewGrant, type ReviewerOverview,
} from '../lib/api';
import { FIELD_BOX, FIELD_LABEL, LoadError, errorText, fmtDayZone } from './compliance/shared';

/**
 * Reviews: the limited area for a licensed practitioner who an organisation's owner has given time-limited,
 * read-only access. It lists the organisations they may review and shows one organisation's readiness
 * evidence exactly as that organisation sees it, without notes, free text or files. The practitioner can
 * record that they reviewed a requirement and mark a clause reference as reviewed. Neither changes a status,
 * and neither is a statement about the organisation's obligations. The server checks the grant on every request.
 */

const CHIP: Record<ComplianceStatus, ChipLevel> = { present: 'ok', gap: 'bad', not_assessed: 'warn', not_applicable: 'idle', awaiting_input: 'idle' };
const CARD = 'rounded-lg border border-line bg-raised';
const ZONE = 'Africa/Lagos';
const REVIEW_COPY = 'This records that you reviewed this requirement. It does not change its status and it says nothing about the organisation’s obligations. It is added to the record under your name and today’s date and cannot be edited or removed; you can add a newer one later.';
const CLAUSE_COPY = 'This records your opinion about the clause reference only: the citation shown for this requirement. It replaces “reference pending review” for this organisation, under your name. It does not change the register for anyone else and it does not change any status. The newest entry is the one shown.';

type Dialog = { kind: 'review' | 'clause'; req: ComplianceRequirement } | null;

function RecordDialog({ orgId, dialog, onClose, onSaved }: {
  orgId: string; dialog: Dialog; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [outcome, setOutcome] = useState('reviewed');
  const [verified, setVerified] = useState(true);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setOutcome('reviewed'); setVerified(true); setText(''); setError(null); }, [dialog]);

  const save = async () => {
    if (!dialog) return;
    setBusy(true);
    setError(null);
    try {
      const note = text.trim() || null;
      if (dialog.kind === 'review') {
        await recordPractitionerReview(orgId, dialog.req.key, { outcome, comment: note });
        toast('Practitioner review recorded');
      } else {
        await recordClauseReference(orgId, dialog.req.key, { verified, note });
        toast('Clause reference recorded');
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(errorText(e, 'Could not record this.'));
    } finally {
      setBusy(false);
    }
  };

  const isReview = dialog?.kind === 'review';
  return (
    <Modal open={!!dialog} onClose={onClose} maxWidth="max-w-lg"
           title={isReview ? 'Record practitioner review' : 'Verify clause reference'}>
      {dialog && (
        <div className="space-y-4" data-testid={`dialog-${dialog.kind}`}>
          <p className="text-sm text-ink font-medium">{dialog.req.title}</p>
          <p className="mono text-[11px] text-soft break-words">{dialog.req.clause}</p>
          <p className="text-sm text-soft leading-relaxed">{isReview ? REVIEW_COPY : CLAUSE_COPY}</p>
          {isReview ? (
            <fieldset className="space-y-2">
              <legend className={FIELD_LABEL}>Outcome</legend>
              {[['reviewed', 'Reviewed'], ['reviewed_with_comments', 'Reviewed, with comments']].map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-sm text-ink">
                  <input type="radio" name="outcome" value={value} checked={outcome === value} onChange={() => setOutcome(value)} />
                  {label}
                </label>
              ))}
            </fieldset>
          ) : (
            <fieldset className="space-y-2">
              <legend className={FIELD_LABEL}>Your note on the reference</legend>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input type="radio" name="verified" checked={verified} onChange={() => setVerified(true)} />
                I reviewed this clause reference
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input type="radio" name="verified" checked={!verified} onChange={() => setVerified(false)} />
                I could not confirm this clause reference
              </label>
            </fieldset>
          )}
          <div>
            <label htmlFor="rv-text" className={FIELD_LABEL}>{isReview ? 'Comment (optional)' : 'Note (optional)'}</label>
            <textarea id="rv-text" rows={3} maxLength={500} value={text} onChange={e => setText(e.target.value)} className={FIELD_BOX} />
            <p className="text-[11px] text-soft mt-1.5">
              Describe what you looked at ({text.length}/500). Please do not give a conclusion about the organisation, and do not include personal details.
            </p>
          </div>
          {error && <p role="alert" className="text-xs mono text-warn" data-testid="dialog-error">{error}</p>}
          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
            <button type="button" className="btn btn-ghost justify-center" onClick={onClose}>CANCEL</button>
            <button type="button" className="btn btn-solid justify-center" onClick={() => void save()} disabled={busy} data-testid="dialog-confirm">
              {busy ? 'RECORDING…' : isReview ? 'RECORD REVIEW' : 'RECORD REFERENCE'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Row({ req, onAct }: { req: ComplianceRequirement; onAct: (d: NonNullable<Dialog>) => void }) {
  const [open, setOpen] = useState(false);
  const day = (v?: string | null) => fmtDayZone(v, ZONE);
  return (
    <li className="border-t border-line first:border-t-0" data-testid="review-row">
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
              className="w-full text-left px-4 sm:px-5 py-3.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 hover:bg-inset/60 transition-colors">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-ink font-medium">{req.title}</p>
          <p className={`text-[11px] mono mt-0.5 break-words ${req.clause_verified || req.clause_review?.verified ? 'text-soft' : 'text-warn'}`}>{req.clause_label}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end shrink-0">
          <span className="uppercase"><StatusChip level={CHIP[req.status]}>{req.status_label}</StatusChip></span>
          {req.source_label ? <span className="tag uppercase">{req.source_label}</span> : <span className="text-[10.5px] mono text-soft uppercase">No evidence yet</span>}
          <ChevronDown size={14} className={`hidden sm:block text-soft transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {open && (
        <div className="px-4 sm:px-5 pb-5 space-y-4 text-sm content-fade-in">
          <p className="text-soft leading-relaxed">{req.summary}</p>
          <p className="text-xs mono text-ink">{req.reason_text}</p>
          {(req.answers || []).filter(a => a.answered).length > 0 && (
            <div className="p-3 rounded border border-line bg-inset/50 space-y-1.5">
              <p className="mono text-[10px] tracking-[.16em] text-soft">CUSTOMER ATTESTED ANSWERS</p>
              {(req.answers || []).filter(a => a.answered).map(a => (
                <p key={a.question_key} className="text-xs text-ink break-words">
                  {a.question_key}: {a.value ?? 'answered'}{a.date ? ` (${a.date})` : ''} · {a.owner_name || 'owner not recorded'} · {a.expires_at ? `expires ${day(a.expires_at)}` : 'no expiry recorded'}
                </p>
              ))}
            </div>
          )}
          {req.domains.length > 0 && (
            <ul className="space-y-2">
              {req.domains.map(d => (
                <li key={d.domain_id} className="p-3 rounded border border-line text-xs">
                  <span className="mono text-ink break-all">{d.domain}</span> · {d.status_label} · {d.source_label || 'No source'}
                  <span className="text-soft"> · {d.reason_text}{d.observed_at && <> · observed {day(d.observed_at)}</>}</span>
                </li>
              ))}
            </ul>
          )}
          {(req.open_finding_count ?? 0) > 0 && (
            <p className="text-xs text-soft">Open findings linked to this requirement: {req.open_finding_count}. Their details are not shared with reviewers.</p>
          )}
          {(req.practitioner_review || req.clause_review) && (
            <div className="p-3 rounded border border-line bg-inset/50 space-y-1.5" data-testid="existing-note">
              <p className="mono text-[10px] tracking-[.16em] text-soft">PRACTITIONER NOTES ON FILE</p>
              {req.practitioner_review && <p className="text-xs text-ink break-words">{req.practitioner_review.label}: {req.practitioner_review.outcome_label}.{req.practitioner_review.comment && <> “{req.practitioner_review.comment}”</>}</p>}
              {req.clause_review && <p className="text-xs text-ink break-words">{req.clause_review.label}.{req.clause_review.note && <> “{req.clause_review.note}”</>}</p>}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-mini" onClick={() => onAct({ kind: 'review', req })} data-testid="record-review">RECORD PRACTITIONER REVIEW</button>
            <button type="button" className="btn-mini" onClick={() => onAct({ kind: 'clause', req })} data-testid="verify-clause">VERIFY CLAUSE REFERENCE</button>
          </div>
        </div>
      )}
    </li>
  );
}

function OrgView({ orgId }: { orgId: string }) {
  const [data, setData] = useState<ReviewerOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);

  const load = useCallback(async () => {
    try {
      setData(await getReviewerOverview(orgId));
      setError(null);
    } catch (e) {
      setData(null);
      setError(errorText(e, 'Could not load this organisation.'));
    }
  }, [orgId]);

  useEffect(() => { setData(null); void load(); }, [load]);

  if (error) return <LoadError message={error} onRetry={() => void load()} />;
  if (!data) return <p className="text-xs mono text-soft">LOADING…</p>;
  const r = data.readiness;
  return (
    <div className="space-y-5" data-testid="review-org">
      <div className={`${CARD} p-5 space-y-2`}>
        <p className="text-base text-ink font-semibold">{data.organisation.name}</p>
        <p className="text-xs text-soft">Purpose of your access: {data.grant.purpose}. Access ends {fmtDayZone(data.grant.expires_at, ZONE)}.</p>
        <p className="text-sm text-ink" data-testid="review-readiness">
          {r.with_evidence} of {r.applicable} requirements have evidence · {r.awaiting_input} awaiting input or upcoming checks · {r.not_assessed} not assessed
        </p>
        <p className="text-xs text-soft">
          {data.register.references_pending_review} of {data.groups.reduce((n, g) => n + g.requirement_count, 0)} clause references are pending review for this organisation.
        </p>
      </div>
      {data.groups.map(group => (
        <section key={group.key} className={CARD} aria-label={group.title}>
          <div className="px-4 sm:px-5 py-3.5 border-b border-line">
            <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">{group.title}</h2>
          </div>
          {group.locked
            ? <p className="px-4 sm:px-5 py-4 text-sm text-soft">Not available for this organisation&rsquo;s plan.</p>
            : <ul>{group.requirements.filter(q => q.status !== 'not_applicable').map(q => <Row key={q.key} req={q} onAct={setDialog} />)}</ul>}
        </section>
      ))}
      <RecordDialog orgId={orgId} dialog={dialog} onClose={() => setDialog(null)} onSaved={() => void load()} />
    </div>
  );
}

export default function Reviews() {
  const { user, loading, signOut } = useAuth();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [grants, setGrants] = useState<MyReviewGrant[] | null>(null);
  const org = params.get('org');

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    void getMyReviewGrants().then(list => { if (!cancelled) setGrants(list); });
    return () => { cancelled = true; };
  }, [user]);

  if (loading) return <div className="p-8 mono text-xs text-soft">LOADING…</div>;
  if (!user) return <Navigate to="/login" replace />;

  const selected = grants?.find(g => g.org_id === org) ?? null;
  return (
    <div className="min-h-screen bg-base text-ink">
      <header className="border-b border-line">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <Link to="/" aria-label="Cyphward"><CyphwardLogo variant="compact" size={24} /></Link>
          <div className="flex items-center gap-2">
            <Link to="/overview" className="btn-mini">MY WORKSPACE</Link>
            <button type="button" className="btn-mini" onClick={async () => { await signOut(); nav('/login', { replace: true }); }}>SIGN OUT</button>
          </div>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-4 py-6 space-y-5">
        <h1 className="text-xl font-semibold">Reviews</h1>
        <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-line bg-raised text-xs text-ink leading-relaxed">
          <Info size={14} className="text-accent flex-none mt-0.5" />
          <span>
            You can read these organisations&rsquo; compliance readiness evidence for the time their owners allowed. You are not a
            member of them and cannot see anything else. A practitioner review is your own note about a clause reference or a requirement.
            It does not change any status and is not a statement about the organisation&rsquo;s obligations.
          </span>
        </div>
        {grants === null ? <p className="text-xs mono text-soft">LOADING…</p> : grants.length === 0 ? (
          <div className={`${CARD} p-6 text-sm text-soft`} data-testid="reviews-empty">
            You do not have reviewer access to any organisation right now. If an owner has invited you, make sure you are signed in with the same email
            address and that it is verified.
          </div>
        ) : (
          <>
            <ul className="grid gap-3 sm:grid-cols-2" data-testid="review-orgs">
              {grants.map(g => (
                <li key={g.org_id}>
                  <button type="button" onClick={() => setParams({ org: g.org_id })} aria-pressed={g.org_id === org}
                          className={`w-full text-left p-4 ${CARD} hover:border-line-strong ${g.org_id === org ? '!border-ink' : ''}`}>
                    <span className="block text-sm text-ink font-medium break-words">{g.org_name}</span>
                    <span className="block text-xs text-soft mt-1 break-words">{g.purpose}</span>
                    <span className="block mono text-[11px] text-soft mt-1">Access ends {fmtDayZone(g.expires_at, ZONE)}</span>
                  </button>
                </li>
              ))}
            </ul>
            {selected ? <OrgView orgId={selected.org_id} /> : (
              <p className="text-sm text-soft">Choose an organisation to review.</p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
