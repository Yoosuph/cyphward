import { useCallback, useEffect, useMemo, useState } from 'react';
import { pageCacheTicket, readPageCache, writePageCache } from '../../lib/pageCache';
import { CompliancePanelSkeleton } from '../../components/skeletons/RouteSkeleton';
import { Info, RefreshCw, UserCheck } from 'lucide-react';
import { useConfirm } from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import {
  createReviewerGrant, listReviewerGrants, revokeReviewerGrant,
  type ReviewerGrant, type ReviewerGrantList, type ReviewerGrantStatus,
} from '../../lib/api';
import { FIELD_BOX, FIELD_LABEL, GrowthGate, LoadError, errorText, fmtDayZone, fmtTimeZone } from './shared';

/**
 * Reviewer access (owners only): grant a licensed practitioner time-limited, read-only access to these
 * compliance pages, see what they did, and end the access at any time. The reviewer is not a member of the
 * organisation and cannot see anything outside the compliance pages. A review note is the practitioner's own
 * note; it never changes a status.
 */

const STATUS_TEXT: Record<ReviewerGrantStatus, string> = {
  pending: 'Waiting for the reviewer to open it',
  active: 'In use',
  expired: 'Expired',
  revoked: 'Revoked',
};

const DAY_MS = 86400000;

/** The date input value (YYYY-MM-DD) for today plus a number of days, in the browser's calendar. */
function dateValue(plusDays: number): string {
  const d = new Date();
  const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate() + plusDays));
  return utc.toISOString().slice(0, 10);
}

/** Whole calendar days from today to a picked date. The server measures the window itself, on its own clock. */
function daysUntil(value: string): number {
  const [y, m, d] = value.split('-').map(Number);
  const now = new Date();
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / DAY_MS);
}

export default function ReviewerAccessTab({ zone }: { zone: string }) {
  const toast = useToast();
  const confirm = useConfirm();
  // Last-seen list paints at once on a revisit (lib/queryCache); load() refreshes it.
  const [data, setData] = useState<ReviewerGrantList | null>(() => readPageCache<ReviewerGrantList>('comply:reviewers') ?? null);
  const [error, setError] = useState<string | null>(null);
  const [gated, setGated] = useState(false);
  const [email, setEmail] = useState('');
  const [purpose, setPurpose] = useState('');
  const limits = data?.limits ?? { min_days: 1, default_days: 30, max_days: 90, purpose_max: 200 };
  const [expiry, setExpiry] = useState(dateValue(30));
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      { const ticket = pageCacheTicket(); const fresh = await listReviewerGrants(); writePageCache('comply:reviewers', fresh, ticket); setData(fresh); }
      setError(null);
    } catch (e) {
      if ((e as { status?: number })?.status === 403) setGated(true);
      else setError(errorText(e, 'Could not load reviewer access.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const minDate = useMemo(() => dateValue(limits.min_days), [limits.min_days]);
  const maxDate = useMemo(() => dateValue(limits.max_days), [limits.max_days]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const days = daysUntil(expiry);
    if (!email.trim() || !purpose.trim()) return setFormError('Enter the reviewer’s email address and the purpose.');
    if (!expiry || days < limits.min_days || days > limits.max_days) {
      return setFormError(`Choose an end date between ${limits.min_days} and ${limits.max_days} days from today.`);
    }
    const ok = await confirm({
      title: 'Give this reviewer access?',
      confirmLabel: 'Give access',
      body: (
        <>
          <p><span className="mono text-ink">{email.trim()}</span> will be able to read your compliance pages until
            about {fmtDayZone(new Date(Date.now() + days * DAY_MS).toISOString(), zone)}. They are not a member of your
            organisation and cannot see scans, findings, domains, billing, settings or your team.</p>
          <p className="mt-2">They can record that they reviewed a requirement and mark a clause reference as reviewed.
            Neither changes any status. You can end the access at any time.</p>
        </>
      ),
    });
    if (!ok) return;
    setBusy(true);
    try {
      await createReviewerGrant({ email: email.trim(), days, purpose: purpose.trim() });
      toast('Reviewer access granted');
      setEmail('');
      setPurpose('');
      setExpiry(dateValue(limits.default_days));
      await load();
    } catch (err) {
      setFormError(errorText(err, 'Could not grant access.'));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (g: ReviewerGrant) => {
    const ok = await confirm({
      title: 'End this reviewer’s access?',
      confirmLabel: 'End access',
      danger: true,
      body: <p>{g.reviewer_email} will lose access to your compliance pages straight away. What they already recorded stays on file.</p>,
    });
    if (!ok) return;
    try {
      await revokeReviewerGrant(g.id);
      toast('Access ended');
      await load();
    } catch (err) {
      toast(errorText(err, 'Could not end the access.'));
      await load();
    }
  };

  if (gated) return <GrowthGate what="Reviewer access" />;
  if (error && !data) return <LoadError message={error} onRetry={() => void load()} />;
  if (!data) return <CompliancePanelSkeleton section="reviewers" />;

  return (
    <div className="space-y-6" data-testid="reviewer-access">
      <div role="note" className="flex items-start gap-2.5 p-3.5 rounded border border-line bg-raised text-xs text-ink leading-relaxed">
        <Info size={14} className="text-accent flex-none mt-0.5" />
        <span>
          Give a licensed Data Protection Compliance Organisation practitioner read-only access to these compliance pages for a
          limited time. {data.note} Cyphward does not check anyone's licence: a reviewer is whoever you name here, and their notes say so.
        </span>
      </div>

      {data.can_grant ? (
        <form onSubmit={submit} className="p-4 sm:p-5 rounded-lg border border-line bg-raised space-y-4" data-testid="grant-form" noValidate>
          <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">Give access</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="min-w-0">
              <label htmlFor="rv-email" className={FIELD_LABEL}>Reviewer's email address</label>
              <input id="rv-email" type="email" autoComplete="off" value={email} onChange={e => setEmail(e.target.value)}
                     maxLength={254} className={FIELD_BOX} placeholder="name@practice.example" />
              <p className="text-[11px] text-soft mt-1.5">They sign in with their own Cyphward account and a verified email.</p>
            </div>
            <div className="min-w-0">
              <label htmlFor="rv-expiry" className={FIELD_LABEL}>Access ends on</label>
              <input id="rv-expiry" type="date" value={expiry} min={minDate} max={maxDate} onChange={e => setExpiry(e.target.value)}
                     className={FIELD_BOX} />
              <p className="text-[11px] text-soft mt-1.5">{limits.min_days} to {limits.max_days} days from today.</p>
            </div>
          </div>
          <div>
            <label htmlFor="rv-purpose" className={FIELD_LABEL}>Purpose</label>
            <input id="rv-purpose" type="text" value={purpose} onChange={e => setPurpose(e.target.value)} maxLength={limits.purpose_max}
                   className={FIELD_BOX} placeholder="For example: annual readiness review" />
            <p className="text-[11px] text-soft mt-1.5">
              Say what the review is for, in a few words ({purpose.length}/{limits.purpose_max}). Do not include names or personal details of anyone else.
            </p>
          </div>
          {formError && <p role="alert" className="text-xs mono text-warn" data-testid="grant-error">{formError}</p>}
          <button type="submit" className="btn btn-solid btn-mini" disabled={busy} data-testid="grant-submit">
            {busy ? 'GRANTING…' : 'GIVE ACCESS'}
          </button>
        </form>
      ) : (
        <GrowthGate what="Giving reviewer access" />
      )}

      <section aria-label="Reviewer grants" className="rounded-lg border border-line bg-raised">
        <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3.5 border-b border-line">
          <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">Access you have given</h2>
          <button type="button" className="btn-mini flex items-center gap-1.5" onClick={() => void load()} aria-label="Refresh reviewer access">
            <RefreshCw size={12} />REFRESH
          </button>
        </div>
        {data.grants.length === 0 ? (
          <p className="px-4 sm:px-5 py-5 text-sm text-soft" data-testid="grants-empty">Nobody has reviewer access.</p>
        ) : (
          <ul data-testid="grant-list">
            {data.grants.map(g => (
              <li key={g.id} className="px-4 sm:px-5 py-4 border-t border-line first:border-t-0 flex flex-col sm:flex-row sm:items-center justify-between gap-3" data-testid={`grant-${g.status}`}>
                <div className="min-w-0 space-y-1">
                  <p className="text-sm text-ink font-medium break-all"><UserCheck size={13} className="inline mr-1.5 text-accent" />{g.reviewer_email}</p>
                  <p className="text-xs text-soft break-words">{g.purpose}</p>
                  <p className="mono text-[11px] text-soft">
                    <span className="tag uppercase mr-2">{STATUS_TEXT[g.status]}</span>
                    given {fmtDayZone(g.granted_at, zone)}{g.granted_by_name ? ` by ${g.granted_by_name}` : ''} · ends {fmtTimeZone(g.expires_at, zone)}
                    {g.revoked_at && g.status === 'revoked' && <> · ended {fmtTimeZone(g.revoked_at, zone)}</>}
                  </p>
                </div>
                {(g.status === 'pending' || g.status === 'active') && (
                  <button type="button" className="btn-mini whitespace-nowrap self-start" onClick={() => void revoke(g)} data-testid="revoke">
                    END ACCESS
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="What reviewers did" className="rounded-lg border border-line bg-raised">
        <div className="px-4 sm:px-5 py-3.5 border-b border-line">
          <h2 className="text-[11px] mono uppercase tracking-[.14em] text-soft">What reviewers recorded</h2>
          <p className="text-xs text-soft mt-1.5">Newest first. These are the practitioners' own notes; none of them changes a status.</p>
        </div>
        {data.activity.length === 0 ? (
          <p className="px-4 sm:px-5 py-5 text-sm text-soft" data-testid="activity-empty">Nothing recorded yet.</p>
        ) : (
          <ul data-testid="activity-list">
            {data.activity.map(a => (
              <li key={`${a.kind}-${a.id}`} className="px-4 sm:px-5 py-3.5 border-t border-line first:border-t-0 space-y-1">
                <p className="text-sm text-ink break-words">
                  {a.kind === 'review'
                    ? `${a.reviewer_name} recorded a review: ${a.outcome_label}`
                    : `${a.reviewer_name} marked the clause reference ${a.verified ? 'as reviewed' : 'as not confirmed'}`}
                  {' · '}{a.requirement_title}
                </p>
                {a.text && <p className="text-xs text-soft break-words">“{a.text}”</p>}
                <p className="mono text-[11px] text-soft">{fmtTimeZone(a.at, zone)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
