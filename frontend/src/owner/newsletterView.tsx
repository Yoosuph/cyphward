import { useCallback, useContext, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { NewsletterDraftSkeleton, NewsletterListSkeleton, SubtitleSkeleton } from './skeletons';
import { cacheTicket, readQueryCache, writeQueryCache } from '../lib/queryCache';
import { Link, useParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, CalendarClock, FileText, Inbox, Mail, Send, UserMinus, Users } from 'lucide-react';
import Dialog, { useDialogClose } from '../components/ui/Dialog';
import { EmptyPanel, humanError } from '../components/ui/StatePanels';
import {
  OwnerApiError, newsletterDrafts, newsletterSend, newsletterStats,
  type NewsletterDrafts, type NewsletterIssue, type NewsletterStats, type NewsletterTheme,
} from './ownerApi';
import { PageHead, Panel, Pill, SessionEndedContext, Stat, ViewState, fmtDate } from './ui';

/**
 * Owner console: newsletter. Reads GrokBot's drafts and the subscriber counts, shows each draft as subscribers
 * will see it, and sends one only after the owner types its subject exactly. The server checks the approval and
 * the subject again and sends an issue at most once; this screen never retries a send.
 */

// The sender configured on the server (backend/app/core/config.py NEWSLETTER_SENDER); a test keeps them in step.
export const NEWSLETTER_SENDER_NAME = 'Cyphward News';
export const NEWSLETTER_SENDER_ADDRESS = 'news@cyphward.com';

const RULES_OK = 'Follows the draft rules';
const RULES_FAIL = 'This draft does not follow the draft rules, so it cannot be sent. Ask GrokBot for a new draft.';
const SEND_UNFINISHED = 'A send was started for this draft and did not finish, so it cannot be sent again. Check Brevo, then ask for a new draft if needed.';
const SEND_UNCONFIRMED = 'The server did not confirm the send. It may or may not have gone out: check the campaign in Brevo before doing anything else.';

// The email style chosen in the send dialog. Light is the default; the confirmation email is always light.
const EMAIL_STYLES: { value: NewsletterTheme; label: string; help: string }[] = [
  { value: 'light', label: 'Light', help: 'Dark text on a white card. This is the default.' },
  { value: 'dark', label: 'Dark', help: 'Light text on a near-black card. Same layout, links and footer.' },
];
const styleLabel = (theme: NewsletterTheme | null | undefined) =>
  EMAIL_STYLES.find(s => s.value === theme)?.label ?? 'Light';

const SECTION_TYPE: Record<string, string> = {
  product: 'Product',
  security_tip: 'Security tip',
  regulation: 'Regulation',
};

type Loaded = { drafts: NewsletterDrafts; stats: NewsletterStats | null };

/** Drafts and counts together. A 404 from the drafts route means the newsletter is switched off on the server. */
function useNewsletter() {
  const onSessionEnded = useContext(SessionEndedContext);
  // Through the shared cache (owner scope): a revisit paints the last drafts at once, then asks again.
  const [data, setData] = useState<Loaded | null>(() => readQueryCache<Loaded>('newsletter:drafts', 'owner')?.data ?? null);
  const [off, setOff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const live = useRef(true);

  const load = useCallback(async () => {
    const ticket = cacheTicket('owner');
    setLoading(true);
    setError(null);
    try {
      const [drafts, stats] = await Promise.all([
        newsletterDrafts(),
        newsletterStats().catch((e: OwnerApiError) => {
          if (e.status === 401) throw e;
          return null; // counts are a convenience; the drafts still show
        }),
      ]);
      if (!live.current) return;
      setOff(false);
      writeQueryCache('newsletter:drafts', { drafts, stats }, ticket);
      setData({ drafts, stats });
    } catch (e) {
      const err = e as OwnerApiError;
      if (!live.current) return;
      if (err.status === 401) onSessionEnded();
      else if (err.status === 404) { setOff(true); setData(null); }
      else setError(humanError(err, 'The newsletter drafts did not load. Try again in a moment.', { passDetail: false }));
    } finally {
      if (live.current) setLoading(false);
    }
  }, [onSessionEnded]);

  useEffect(() => {
    live.current = true;
    void load();
    return () => { live.current = false; };
  }, [load]);

  return { data, off, error, loading, reload: load };
}

function hostOf(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return 'not a valid web address';
  }
}

function confirmedCount(data: Loaded) {
  return data.stats?.confirmed ?? data.drafts.confirmed_subscribers ?? 0;
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function NewsletterOff() {
  return (
    <EmptyPanel
      icon={<Mail size={20} />}
      title="The newsletter is switched off"
      help="The server has the newsletter turned off, so there are no drafts to read and nothing can be sent. It shows here once it is turned on."
    />
  );
}

function StatusPill({ issue }: { issue: NewsletterIssue }) {
  if (issue.status === 'sent') return <Pill tone="good">sent</Pill>;
  return <Pill tone="warn">draft</Pill>;
}

/* ── List ──────────────────────────────────────────────────────────────── */
export function NewsletterView() {
  const { data, off, error, loading, reload } = useNewsletter();
  const [newestFirst, setNewestFirst] = useState(true);

  const issues = useMemo(() => {
    const list = [...(data?.drafts.issues || [])];
    const at = (i: NewsletterIssue) => (i.created_at ? new Date(i.created_at).getTime() : 0);
    list.sort((a, b) => (newestFirst ? at(b) - at(a) : at(a) - at(b)));
    return list;
  }, [data, newestFirst]);

  const waiting = issues.filter(i => i.status === 'draft' && i.sendable).length;
  const lastSent = issues.reduce<string | null>((latest, i) => (
    i.sent_at && (!latest || new Date(i.sent_at) > new Date(latest)) ? i.sent_at : latest
  ), null);
  const sortLabel = newestFirst ? 'Newest first' : 'Oldest first';

  return (
    <>
      <PageHead title="Newsletter" subtitle="GrokBot writes drafts; nothing reaches subscribers until you send a draft from here." />
      {off ? <NewsletterOff /> : (
        <ViewState loading={loading} error={error} onRetry={reload} empty={!data} label="newsletter drafts" skeleton={<NewsletterListSkeleton />}>
          {data && (
            <>
              <section aria-label="Newsletter overview" className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
                <Stat label="Confirmed subscribers" value={confirmedCount(data).toLocaleString()} icon={Users}
                      hint={data.stats?.pending ? `${data.stats.pending.toLocaleString()} waiting from the earlier sign-up flow` : 'receive the next issue'} />
                <Stat label="Unsubscribed" value={data.stats ? data.stats.unsubscribed.toLocaleString() : '—'} icon={UserMinus}
                      hint={data.stats ? 'never receive an issue' : 'count not available'} />
                <Stat label="Drafts waiting" value={waiting} icon={Inbox} hint="ready to read and send" />
                <Stat label="Last sent" value={<span className="text-lg">{lastSent ? fmtDate(lastSent, false) : 'Never'}</span>} icon={CalendarClock}
                      hint={lastSent ? fmtDate(lastSent) : 'no issue sent yet'} />
              </section>

              {issues.length === 0 ? (
                <EmptyPanel icon={<FileText size={20} />} title="No drafts yet"
                            help="Drafts from GrokBot appear here. Nothing is sent until you open a draft and send it." />
              ) : (
                <Panel
                  title={`Drafts (${issues.length})`}
                  right={(
                    <button type="button" className="btn-mini whitespace-nowrap" onClick={() => setNewestFirst(v => !v)}
                            aria-label={`Sort by created time: ${sortLabel.toLowerCase()}. Press to reverse.`}
                            data-testid="newsletter-sort">
                      {newestFirst ? <ArrowDown size={12} aria-hidden="true" /> : <ArrowUp size={12} aria-hidden="true" />} {sortLabel.toUpperCase()}
                    </button>
                  )}
                >
                  <div className="ledger-wrap -mx-5 -mt-5">
                    <table className="ledger table-stack" data-testid="newsletter-drafts">
                      <caption className="sr-only">Newsletter drafts, sorted by created time, {sortLabel.toLowerCase()}</caption>
                      <thead>
                        <tr>
                          <th scope="col">SUBJECT</th>
                          <th scope="col">STATUS</th>
                          <th scope="col" aria-sort={newestFirst ? 'descending' : 'ascending'}>
                            <button type="button" onClick={() => setNewestFirst(v => !v)} className="inline-flex items-center gap-1 uppercase hover:text-ink"
                                    aria-label={`Created, sorted ${sortLabel.toLowerCase()}. Press to reverse.`}>
                              CREATED {newestFirst ? <ArrowDown size={11} aria-hidden="true" /> : <ArrowUp size={11} aria-hidden="true" />}
                            </button>
                          </th>
                          <th scope="col">CREATED BY</th>
                          <th scope="col">SECTIONS</th>
                        </tr>
                      </thead>
                      <tbody>
                        {issues.map(issue => (
                          <tr key={issue.id} data-testid="newsletter-row" data-id={issue.id}>
                            <td className="stack-title">
                              <Link to={`/newsletter/${issue.id}`} className="hover:text-accent break-words">{issue.subject}</Link>
                            </td>
                            <td data-label="Status">
                              <span className="inline-flex flex-wrap items-center gap-1.5">
                                <StatusPill issue={issue} />
                                {issue.status === 'draft' && !issue.sendable && (
                                  <span className="text-xs text-soft">{issue.send_claimed_at ? 'send not finished' : 'cannot be sent'}</span>
                                )}
                              </span>
                            </td>
                            <td data-label="Created">{fmtDate(issue.created_at)}</td>
                            <td data-label="Created by"><span className="mono text-xs">{issue.created_by || '—'}</span></td>
                            <td data-label="Sections">{issue.sections.length}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              )}
            </>
          )}
        </ViewState>
      )}
    </>
  );
}

/**
 * Keyboard focus inside the preview frame lives in the frame's own document, so the frame element never matches
 * :focus here. Mark it while the page's focus sits on it, so it draws the same ring as every other control.
 */
function useFrameFocusRing() {
  const ref = useRef<HTMLIFrameElement | null>(null);
  useEffect(() => {
    let timer = 0;
    const apply = () => {
      const frame = ref.current;
      if (frame) frame.dataset.focused = String(document.activeElement === frame);
    };
    const sync = () => {
      apply(); // the window's blur already reports the frame as the active element
      window.clearTimeout(timer);
      timer = window.setTimeout(apply, 0);
    };
    window.addEventListener('blur', sync);
    window.addEventListener('focus', sync);
    document.addEventListener('focusin', sync);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('blur', sync);
      window.removeEventListener('focus', sync);
      document.removeEventListener('focusin', sync);
    };
  }, []);
  return ref;
}

/* ── Detail ────────────────────────────────────────────────────────────── */
export function NewsletterDraftView() {
  const { id = '' } = useParams();
  const { data, off, error, loading, reload } = useNewsletter();
  const [sending, setSending] = useState(false);
  const issue = data?.drafts.issues.find(i => i.id === id) || null;
  const rulesOk = !!issue && issue.preview_html !== null;
  const canSend = !!issue && issue.status === 'draft' && issue.sendable && rulesOk;

  const frameRef = useFrameFocusRing();
  const back = <Link to="/newsletter" className="btn-mini whitespace-nowrap">← ALL DRAFTS</Link>;

  return (
    <>
      <PageHead
        title={issue ? issue.subject : 'Newsletter draft'}
        subtitle={issue ? issue.preview : <SubtitleSkeleton />}
        actions={(
          <div className="flex flex-wrap gap-2">
            {canSend && (
              <button type="button" className="btn btn-solid btn-mini touch-target whitespace-nowrap" onClick={() => setSending(true)}
                      data-testid="newsletter-send-open">
                <Send size={12} aria-hidden="true" /> SEND TO CONFIRMED SUBSCRIBERS
              </button>
            )}
            {back}
          </div>
        )}
      />
      {off ? <NewsletterOff /> : (
        <ViewState loading={loading} error={error} onRetry={reload} empty={!data} label="this draft" skeleton={<NewsletterDraftSkeleton />}>
          {data && !issue && (
            <EmptyPanel icon={<FileText size={20} />} title="This draft is not in the list"
                        help="It may be older than the 50 most recent drafts, or the link may be wrong. Go back to the list to pick a draft."
                        action={back} />
          )}
          {data && issue && (
            <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-5 items-start">
              <div className="space-y-5 min-w-0">
                <Panel title="Summary">
                  <dl className="grid grid-cols-[auto,minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
                    <dt className="text-soft">Status</dt>
                    <dd><StatusPill issue={issue} /></dd>
                    <dt className="text-soft">Subject</dt>
                    <dd className="break-words">{issue.subject}</dd>
                    <dt className="text-soft">Preview line</dt>
                    <dd className="break-words">{issue.preview}</dd>
                    <dt className="text-soft">Created</dt>
                    <dd>{fmtDate(issue.created_at)}</dd>
                    <dt className="text-soft">Created by</dt>
                    <dd className="mono text-xs">{issue.created_by || '—'}</dd>
                    <dt className="text-soft">Sections</dt>
                    <dd>{issue.sections.length}</dd>
                    {issue.sent_at && (<><dt className="text-soft">Sent</dt><dd>{fmtDate(issue.sent_at)}</dd></>)}
                    {issue.send_claimed_at && (
                      <><dt className="text-soft">Email style</dt><dd data-testid="newsletter-style">{styleLabel(issue.send_theme)}</dd></>
                    )}
                    <dt className="text-soft">Draft rules</dt>
                    <dd data-testid="newsletter-rules">
                      {rulesOk ? <Pill tone="good">{RULES_OK}</Pill> : <span className="text-accent">{RULES_FAIL}</span>}
                    </dd>
                  </dl>
                  {issue.status === 'draft' && issue.send_claimed_at && (
                    <p className="text-xs text-soft mt-4" role="note">{SEND_UNFINISHED}</p>
                  )}
                </Panel>

                <Panel title={`Sections (${issue.sections.length})`}>
                  <ol className="space-y-5">
                    {issue.sections.map((section, n) => (
                      <li key={n} className="min-w-0">
                        <article aria-labelledby={`nl-section-${n}`}>
                          <span className="tag uppercase">{SECTION_TYPE[section.type] || section.type}</span>
                          <h3 id={`nl-section-${n}`} className="text-sm font-semibold text-ink mt-2 break-words">{section.heading}</h3>
                          <p className="text-sm text-soft mt-1 whitespace-pre-line break-words">{section.body}</p>
                          {(section.links || []).length > 0 && (
                            <div className="mt-2">
                              <p className="text-[10.5px] mono uppercase tracking-[.12em] text-soft">Links</p>
                              <ul className="text-xs mt-1 space-y-1">
                                {(section.links || []).map((l, i) => (
                                  <li key={i} className="break-words">
                                    <span className="text-ink">{l.label}</span>
                                    <span className="text-soft"> · {hostOf(l.url)}</span>
                                    <span className="block mono text-soft break-all">{l.url}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {(section.sources || []).length > 0 && (
                            <div className="mt-2">
                              <p className="text-[10.5px] mono uppercase tracking-[.12em] text-soft">Sources</p>
                              <ul className="text-xs mt-1 space-y-1">
                                {(section.sources || []).map((s, i) => (
                                  <li key={i} className="break-words">
                                    <span className="text-ink">{s.title}</span>
                                    <span className="text-soft"> · {hostOf(s.url)}</span>
                                    <span className="block mono text-soft break-all">{s.url}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </article>
                      </li>
                    ))}
                  </ol>
                  <p className="text-xs text-soft mt-4">Links and sources are shown as text. Open one only by copying it into a browser.</p>
                </Panel>
              </div>

              <Panel title="The email as subscribers see it" className="min-w-0">
                {issue.preview_html ? (
                  <>
                    <iframe
                      ref={frameRef}
                      title={`Email preview: ${issue.subject}`}
                      sandbox=""
                      referrerPolicy="no-referrer"
                      srcDoc={issue.preview_html}
                      className="w-full rounded border border-line bg-white data-[focused=true]:outline data-[focused=true]:outline-2 data-[focused=true]:outline-offset-2 data-[focused=true]:outline-[color:var(--accent)]"
                      style={{ height: 'min(760px, 75vh)' }}
                      data-testid="newsletter-preview-frame"
                    />
                    <p className="text-xs text-soft mt-2">The unsubscribe link in this preview is a placeholder; each subscriber gets their own.</p>
                  </>
                ) : (
                  <p className="text-sm text-soft">{RULES_FAIL}</p>
                )}
                {issue.preview_text && (
                  <details className="mt-4">
                    <summary className="text-[11px] mono uppercase tracking-[.12em] text-soft cursor-pointer">Plain text version</summary>
                    <pre className="mt-2 p-3 rounded border border-line bg-inset text-xs whitespace-pre-wrap break-words max-h-[480px] overflow-auto">{issue.preview_text}</pre>
                  </details>
                )}
              </Panel>
            </div>
          )}
        </ViewState>
      )}
      {issue && data && (
        <SendDialog open={sending} issue={issue} subscribers={confirmedCount(data)}
                    onClose={() => setSending(false)} onSent={() => void reload()} />
      )}
    </>
  );
}

/* ── Send ──────────────────────────────────────────────────────────────── */
type Outcome =
  | { kind: 'sent'; recipients: number }
  | { kind: 'already'; message: string }
  | { kind: 'error'; message: string };

/** What the owner sees when a send fails: the server's own plain sentence where it wrote one, never internals. */
function sendFailure(err: OwnerApiError): Outcome {
  const text = (err.message || '').trim();
  const plain = err.serverWording && text.length > 0 && text.length <= 300
    && !/traceback|exception|psycopg|sql|\.py\b|stack|internal server error|^request failed|^\{|^\[/i.test(text);
  if (err.status === 409) {
    return { kind: 'already', message: plain ? text : 'This issue has already been sent or a send was already attempted.' };
  }
  if (err.status === 403) {
    return { kind: 'error', message: 'Nothing was sent: the server accepts a send only from the owner console address. Reload the console and try again.' };
  }
  if (err.status === 404) {
    return { kind: 'error', message: 'Nothing was sent: this draft no longer exists, or the newsletter is switched off.' };
  }
  if ((err.status === 422 || err.status === 502) && plain) return { kind: 'error', message: text };
  if (err.status === 422) return { kind: 'error', message: 'Nothing was sent: the server did not accept this draft. Reload it and check the draft rules.' };
  return { kind: 'error', message: SEND_UNCONFIRMED };
}

function SendDialog({ open, issue, subscribers, onClose, onSent }: {
  open: boolean; issue: NewsletterIssue; subscribers: number; onClose: () => void; onSent: () => void;
}) {
  const onSessionEnded = useContext(SessionEndedContext);
  const [typed, setTyped] = useState('');
  const [theme, setTheme] = useState<NewsletterTheme>('light');
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (open) {
      setTyped('');
      setTheme('light');
      setOutcome(null);
      setBusy(false);
    }
  }, [open]);

  const matches = typed === issue.subject;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    // Enter in the field submits the form, so the match is checked here as well as on the button.
    if (busy || outcome || typed !== issue.subject) return;
    setBusy(true);
    try {
      const result = await newsletterSend(issue.id, typed, theme);
      setOutcome({ kind: 'sent', recipients: result.recipients });
    } catch (err) {
      const e2 = err as OwnerApiError;
      if (e2.status === 401) {
        onSessionEnded();
        return;
      }
      setOutcome(sendFailure(e2));
    } finally {
      setBusy(false);
      onSent(); // refresh the list whatever happened: a claimed draft can no longer be sent
    }
  };

  return (
    <Dialog open={open} onClose={busy ? () => {} : onClose} title="Send to confirmed subscribers" maxWidth="max-w-lg"
            icon={<Send size={15} />} dirty={!busy && !outcome && typed.length > 0}>
      {outcome ? <SendOutcome outcome={outcome} onClose={onClose} /> : (
        <form className="space-y-5" onSubmit={submit} noValidate>
          <p className="text-sm text-soft leading-relaxed">
            This sends the draft below to <strong className="text-ink">{plural(subscribers, 'confirmed subscriber')}</strong>,
            once. It cannot be called back, and the same draft cannot be sent again.
          </p>
          <dl className="grid grid-cols-[auto,minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-soft">From</dt>
            <dd className="break-words">{NEWSLETTER_SENDER_NAME}, <span className="mono text-xs">{NEWSLETTER_SENDER_ADDRESS}</span></dd>
            <dt className="text-soft">To</dt>
            <dd>{plural(subscribers, 'confirmed subscriber')}</dd>
            <dt className="text-soft">Subject</dt>
            <dd className="break-words text-ink" data-testid="newsletter-send-subject">{issue.subject}</dd>
          </dl>
          <fieldset className="min-w-0" data-testid="newsletter-send-style" disabled={busy}>
            <legend className="text-[11px] mono uppercase tracking-[.12em] text-soft mb-2">Email style</legend>
            <div className="grid sm:grid-cols-2 gap-2">
              {EMAIL_STYLES.map(option => (
                <label key={option.value}
                       className={`flex items-start gap-2.5 p-3 min-h-[44px] rounded border cursor-pointer ${theme === option.value ? 'border-ink' : 'border-line'}`}>
                  <input type="radio" name="newsletter-theme" value={option.value} checked={theme === option.value}
                         onChange={() => setTheme(option.value)} aria-describedby={`newsletter-theme-${option.value}-help`}
                         className="mt-0.5 accent-[var(--accent)]" />
                  <span className="min-w-0">
                    <span className="block text-sm text-ink">{option.label}</span>
                    <span id={`newsletter-theme-${option.value}-help`} className="block text-xs text-soft mt-0.5">{option.help}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="field !mb-0">
            <label htmlFor="newsletter-confirm-subject">TYPE THE SUBJECT EXACTLY TO SEND</label>
            <input
              id="newsletter-confirm-subject"
              data-autofocus
              type="text"
              value={typed}
              onChange={e => setTyped(e.target.value)}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              aria-describedby="newsletter-confirm-hint"
              disabled={busy}
              className="app-form-control"
            />
            <p id="newsletter-confirm-hint" className="text-[11px] mono text-soft mt-1.5" aria-live="polite">
              {typed.length === 0 ? 'Capitals, spaces and punctuation must match.' : matches ? 'The subject matches.' : 'Not a match yet.'}
            </p>
          </div>
          <SendButtons busy={busy} ready={matches} />
        </form>
      )}
    </Dialog>
  );
}

function SendButtons({ busy, ready }: { busy: boolean; ready: boolean }) {
  const close = useDialogClose();
  return (
    <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
      <button type="button" className="btn btn-ghost justify-center touch-target" onClick={close} disabled={busy}>CANCEL</button>
      <button type="submit" className="btn btn-solid justify-center touch-target" disabled={!ready || busy} data-testid="newsletter-send-confirm">
        {busy ? 'SENDING…' : 'SEND NOW'}
      </button>
    </div>
  );
}

function SendOutcome({ outcome, onClose }: { outcome: Outcome; onClose: () => void }) {
  return (
    <div className="space-y-5" data-testid="newsletter-send-result" data-kind={outcome.kind}>
      {outcome.kind === 'sent' && (
        <div role="status" className="p-3 rounded border border-line bg-inset text-sm text-ink">
          Sent to {plural(outcome.recipients, 'confirmed subscriber')}.
        </div>
      )}
      {outcome.kind === 'already' && (
        <div role="status" className="p-3 rounded border border-line bg-inset text-sm text-ink">
          Already sent. {outcome.message}
        </div>
      )}
      {outcome.kind === 'error' && (
        <div role="alert" className="p-3 bg-red-500/10 border border-red-500/30 rounded text-sm text-red-500">
          {outcome.message}
        </div>
      )}
      <div className="flex justify-end">
        <button type="button" className="btn btn-solid justify-center touch-target" data-autofocus onClick={onClose}>CLOSE</button>
      </div>
    </div>
  );
}
