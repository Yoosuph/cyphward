import { Fragment, useEffect, useId, useState, type MouseEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Copy } from 'lucide-react';
import { useToast } from '../components/Toast';
import { ListState, useListParams } from './table';
import { FilterChip, PageHead, Pager, Pill, SearchBox, fmtDate, useOwnerView } from './ui';

/**
 * Owner console logs (docs/owner-logs-2026-10-29). Each row has a disclosure button in its first cell; clicking the
 * button, or anywhere on the row that is not a link, opens the full entry in a full-width row underneath. One entry
 * is open at a time: opening another closes the first, so the list stays short enough to scan.
 *
 * The open entry shows the exact time in UTC and in the viewer's own time zone, the action, who did it, what it
 * targeted, the organization, the result and the written reason, the details as a label and value list (long
 * values wrap; a long list shows its first entries and offers the rest), and a button that copies the row id.
 */

type Row = Record<string, any>;
type Source = 'customer' | 'owner';

/** How many detail entries show before "Show all". */
const DETAIL_CAP = 8;

/** Owner audit outcomes as the API writes them: success, rejected, denied, throttled, failed. */
function resultTone(outcome?: string | null): 'good' | 'warn' | 'bad' | 'neutral' {
  const o = (outcome || '').toLowerCase();
  if (o === 'success') return 'good';
  if (o === 'throttled') return 'warn';
  if (['rejected', 'denied', 'failed', 'error'].includes(o)) return 'bad';
  return 'neutral';
}

/** "2026-10-29 08:14:07.512 UTC" (milliseconds only when the entry has them). */
function fmtUtc(value?: string | null) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const iso = d.toISOString();
  const ms = iso.slice(19, 23);
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}${ms === '.000' ? '' : ms} UTC`;
}

/** The same moment in the viewer's time zone, with the zone named. */
function fmtLocal(value?: string | null) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const text = d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  });
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return zone ? `${text} (${zone})` : text;
}

/** "from_plan" → "From plan"; "filters.q" → "Filters q". */
function labelOf(key: string) {
  const words = key.replace(/[._-]+/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

function ValueText({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') return <span className="text-soft">—</span>;
  if (Array.isArray(value) && value.every(v => v === null || ['string', 'number', 'boolean'].includes(typeof v))) {
    return <span className="log-value">{value.length ? value.map(String).join(', ') : '—'}</span>;
  }
  if (typeof value === 'object') return <pre className="log-value log-value-block">{JSON.stringify(value, null, 2)}</pre>;
  if (typeof value === 'boolean') return <span className="log-value">{value ? 'yes' : 'no'}</span>;
  return <span className="log-value">{String(value)}</span>;
}

/** One level of nesting becomes its own entries; anything deeper is shown as indented text that wraps. */
function detailEntries(metadata: unknown, skip: string[]): [string, ReactNode][] {
  if (metadata === null || metadata === undefined) return [];
  if (typeof metadata !== 'object' || Array.isArray(metadata)) return [['Value', <ValueText value={metadata} />]];
  const out: [string, ReactNode][] = [];
  for (const [k, v] of Object.entries(metadata as Record<string, unknown>)) {
    if (skip.includes(k)) continue;
    if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length) {
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) out.push([`${labelOf(k)} · ${labelOf(k2)}`, <ValueText value={v2} />]);
    } else {
      out.push([labelOf(k), <ValueText value={v} />]);
    }
  }
  return out;
}

function Pair({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="log-pair" data-testid={testId}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function targetLink(type?: string | null, id?: string | null): string | null {
  if (!id) return null;
  if (type === 'organization') return `/organizations/${id}`;
  if (type === 'scan') return `/scans/${id}`;
  if (type === 'user') return `/users/${id}`;
  return null;
}

function CopyId({ id }: { id: string }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      toast('Row id copied.');
    } catch {
      toast('Could not copy. Select the id and copy it by hand.');
    }
  };
  return (
    <button type="button" className="btn-mini whitespace-nowrap" onClick={() => void copy()} aria-label="Copy row id" data-testid="log-copy-id">
      <Copy size={12} aria-hidden="true" /> COPY
    </button>
  );
}

/** The full entry, shown in the row beneath the one that was opened. */
function LogDetail({ row, source }: { row: Row; source: Source }) {
  const [showAll, setShowAll] = useState(false);
  const meta = (row.metadata && typeof row.metadata === 'object' && !Array.isArray(row.metadata)) ? row.metadata as Record<string, unknown> : {};
  const reason = typeof meta.reason === 'string' && meta.reason.trim() ? meta.reason : null;
  const refusal = typeof meta.detail === 'string' && meta.detail.trim() ? meta.detail : null;
  const entries = detailEntries(row.metadata, [...(reason ? ['reason'] : []), ...(refusal ? ['detail'] : [])]);
  const visible = showAll ? entries : entries.slice(0, DETAIL_CAP);

  const actorName = source === 'owner' ? row.actor_name : row.user_name;
  const actorEmail = source === 'owner' ? row.actor_email : row.user_email;
  const targetType = source === 'owner' ? row.target_type : row.resource_type;
  const targetId = source === 'owner' ? row.target_id : row.resource_id;
  const targetTo = targetLink(targetType, targetId);

  return (
    <div className="log-detail" data-testid="log-detail">
      <dl className="log-pairs">
        <Pair label="Time (UTC)" testId="log-utc"><span className="log-value">{fmtUtc(row.created_at)}</span></Pair>
        <Pair label="Your local time" testId="log-local"><span className="log-value">{fmtLocal(row.created_at)}</span></Pair>
        <Pair label="Action" testId="log-action"><span className="log-value">{row.action || '—'}</span></Pair>
        <Pair label="Result" testId="log-result">
          {source === 'owner'
            ? <Pill tone={resultTone(row.outcome)}>{row.outcome || 'unknown'}</Pill>
            : <span className="text-soft">Not recorded. Customer events record what happened, not a result.</span>}
          {refusal && <span className="log-value block mt-1">{refusal}</span>}
        </Pair>
        <Pair label="Reason" testId="log-reason">
          {reason ? <span className="log-value">{reason}</span> : <span className="text-soft">None written</span>}
        </Pair>
        <Pair label={source === 'owner' ? 'Who' : 'User'} testId="log-actor">
          {actorName && <span className="log-value block">{actorName}</span>}
          {actorEmail
            ? (source === 'customer' && row.user_id
                ? <Link to={`/users/${row.user_id}`} className="log-value hover:text-accent">{actorEmail}</Link>
                : <span className="log-value">{actorEmail}</span>)
            : <span className="text-soft">—</span>}
          {source === 'owner' && row.ip && <span className="log-value block text-soft">{row.ip}</span>}
        </Pair>
        <Pair label="Target" testId="log-target">
          {targetType || targetId ? (
            <span className="log-value">
              {targetType || 'item'}{' '}
              {targetTo ? <Link to={targetTo} className="hover:text-accent">{targetId}</Link> : (targetId || '')}
            </span>
          ) : <span className="text-soft">None</span>}
        </Pair>
        <Pair label="Organization" testId="log-org">
          {row.org_name
            ? (row.org_id ? <Link to={`/organizations/${row.org_id}`} className="log-value hover:text-accent">{row.org_name}</Link> : <span className="log-value">{row.org_name}</span>)
            : <span className="text-soft">None</span>}
        </Pair>
        <Pair label="Row id" testId="log-id">
          {row.id ? (
            <span className="log-id">
              <span className="log-value">{row.id}</span>
              <CopyId id={String(row.id)} />
            </span>
          ) : <span className="text-soft">Not available</span>}
        </Pair>
      </dl>

      <div className="log-details-head">DETAILS{entries.length ? ` · ${entries.length}` : ''}</div>
      {entries.length === 0 ? (
        <p className="text-xs text-soft" data-testid="log-details-none">No further details were recorded with this entry.</p>
      ) : (
        <>
          <dl className="log-pairs" data-testid="log-details">
            {visible.map(([label, value], i) => <Pair key={`${label}-${i}`} label={label}>{value}</Pair>)}
          </dl>
          {entries.length > DETAIL_CAP && (
            <button type="button" className="btn-mini mt-3" onClick={() => setShowAll(s => !s)} aria-expanded={showAll}
                    data-testid="log-show-all">
              {showAll ? 'SHOW FEWER' : `SHOW ALL ${entries.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}

/** A short, readable line for the collapsed row (the full details are one click away). */
function summaryOf(row: Row) {
  const meta = (row.metadata && typeof row.metadata === 'object' && !Array.isArray(row.metadata)) ? row.metadata as Record<string, unknown> : {};
  if (typeof meta.reason === 'string' && meta.reason.trim()) return meta.reason;
  const n = Object.keys(meta).length;
  return n ? `${n} detail${n === 1 ? '' : 's'}` : '';
}

export function LogsView() {
  const { q, offset, params, set } = useListParams();
  const source: Source = params.get('source') === 'owner' ? 'owner' : 'customer';
  const limit = 100;
  const { data, error, loading, reload } = useOwnerView<Row>('/logs', { source, q, offset, limit });
  const [openKey, setOpenKey] = useState<string | null>(null);
  const baseId = useId();

  // A new page of entries closes whatever was open.
  useEffect(() => setOpenKey(null), [source, q, offset]);

  const rows = (data?.items || []) as Row[];
  const head = source === 'owner' ? ['When', 'Action', 'Result', 'Who', 'Target', 'Detail'] : ['When', 'Action', 'User', 'Organization', 'Detail'];

  return (
    <>
      <PageHead title="Logs" subtitle={source === 'owner'
        ? 'Owner console sign-ins, views and actions (this console). Open an entry to see all of it.'
        : 'Customer-side events: sign-ins, scans, plan and security changes. Open an entry to see all of it.'} />
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <div className="flex gap-2">
          {(['customer', 'owner'] as const).map(s => (
            <FilterChip key={s} active={source === s} onClick={() => set({ source: s === 'customer' ? '' : s, offset: 0 })}>
              {s === 'customer' ? 'Customer events' : 'Owner console'}
            </FilterChip>
          ))}
        </div>
        <SearchBox value={q} onChange={v => set({ q: v, offset: 0 })} placeholder={source === 'owner' ? 'Search action, outcome or email' : 'Search action, email or organization'} />
      </div>
      <ListState loading={loading} error={error} onRetry={reload} hasData={!!data} count={rows.length} label="log entries"
                 empty={{ title: 'No log entries match', help: q ? 'Nothing matches this search. Try a shorter word or clear it.' : 'Entries appear here as they are recorded.' }}>
        <div className="rounded-lg border border-line bg-raised min-w-0">
          <div className="ledger-wrap owner-table-wrap">
            <table className="ledger table-stack owner-table log-table" data-testid="log-table">
              <caption className="sr-only">{source === 'owner' ? 'Owner console log, newest first' : 'Customer events, newest first'}</caption>
              <thead>
                <tr>{head.map(h => <th key={h} scope="col">{h.toUpperCase()}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const key = String(r.id ?? `${offset + i}`);
                  const open = openKey === key;
                  const panelId = `${baseId}-log-${i}`;
                  const toggle = () => setOpenKey(open ? null : key);
                  const onRowClick = (e: MouseEvent<HTMLTableRowElement>) => {
                    // Links in the row navigate; the button toggles on its own; a text selection is not a click.
                    if ((e.target as HTMLElement).closest('a, button')) return;
                    if (window.getSelection()?.toString()) return;
                    toggle();
                  };
                  const detail = summaryOf(r);
                  return (
                    <Fragment key={key}>
                      <tr className={`clickable log-row ${open ? 'sel' : ''}`} onClick={onRowClick} data-testid="log-row" data-id={key}>
                        <td className="stack-title">
                          <button type="button" className="log-toggle" aria-expanded={open} aria-controls={panelId} onClick={toggle}
                                  data-testid="log-toggle">
                            <ChevronRight size={14} aria-hidden="true" className="log-chevron" />
                            <span>{fmtDate(r.created_at)}</span>
                            <span className="sr-only">, {r.action}: full entry</span>
                          </button>
                        </td>
                        <td data-label="Action"><span className="mono text-xs">{r.action}</span></td>
                        {source === 'owner' ? (
                          <>
                            <td data-label="Result"><Pill tone={resultTone(r.outcome)}>{r.outcome}</Pill></td>
                            <td data-label="Who"><span>{r.actor_email || '—'}</span></td>
                            <td data-label="Target"><span className="mono text-xs">{r.target_type ? `${r.target_type} ${String(r.target_id || '').slice(0, 8)}` : '—'}</span></td>
                          </>
                        ) : (
                          <>
                            <td data-label="User">{r.user_id ? <Link to={`/users/${r.user_id}`} className="tap-row hover:text-accent">{r.user_email}</Link> : '—'}</td>
                            <td data-label="Organization">{r.org_id ? <Link to={`/organizations/${r.org_id}`} className="tap-row hover:text-accent">{r.org_name}</Link> : '—'}</td>
                          </>
                        )}
                        <td data-label="Detail"><span className="text-xs text-soft log-summary">{detail || '—'}</span></td>
                      </tr>
                      <tr id={panelId} className="log-detail-row" hidden={!open}>
                        <td colSpan={head.length} className="bg-inset/40">
                          {open && <LogDetail row={r} source={source} />}
                        </td>
                      </tr>
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-5 pb-4">
            {data && <Pager offset={offset} limit={limit} count={rows.length} onChange={o => set({ offset: o })} />}
          </div>
        </div>
      </ListState>
    </>
  );
}
