/**
 * Wall-clock time in the organisation's display zone <-> UTC.
 *
 * The browser's own zone never matters here: a person types a time as it reads on the wall in the
 * organisation's zone (default Africa/Lagos), and the API gets a UTC moment. Two wall-clock times are
 * not a single UTC moment: when a clock moves forward one never happens, and when it moves back one
 * happens twice. For those we return a clear message and no value. We never pick one for the person.
 *
 * Inputs look like `2026-10-15T09:30` (datetime-local) or `2026-10-15` (date).
 */

export const DEFAULT_ZONE = 'Africa/Lagos';

const WALL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(zone: string): Intl.DateTimeFormat {
  let f = formatters.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-CA', {
      timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    formatters.set(zone, f);
  }
  return f;
}

export function isValidZone(zone: string | null | undefined): zone is string {
  if (!zone) return false;
  try {
    formatter(zone);
    return true;
  } catch {
    return false;
  }
}

/** The zone to use: the organisation's when it is a real zone, else Africa/Lagos. */
export function resolveZone(zone: string | null | undefined): string {
  return isValidZone(zone) ? zone : DEFAULT_ZONE;
}

function wallParts(utcMs: number, zone: string) {
  const out: Record<string, number> = {};
  for (const p of formatter(zone).formatToParts(new Date(utcMs))) if (p.type !== 'literal') out[p.type] = Number(p.value);
  return out;
}

/** The wall clock in `zone` at a UTC instant, read as if it were UTC (milliseconds). */
function wallAsUtcMs(utcMs: number, zone: string): number {
  const p = wallParts(utcMs, zone);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
}

/** Minutes east of UTC that `zone` is at a UTC instant. */
export function offsetMinutes(utcMs: number, zone: string): number {
  const whole = Math.floor(utcMs / 1000) * 1000;
  return Math.round((wallAsUtcMs(whole, zone) - whole) / 60000);
}

const pad = (n: number) => String(n).padStart(2, '0');

/** `2026-10-15T09:30` for a UTC instant, as it reads in `zone`. */
export function utcToLocalInput(iso: string | Date | null | undefined, zone: string): string {
  if (!iso) return '';
  const ms = (iso instanceof Date ? iso : new Date(iso)).getTime();
  if (Number.isNaN(ms)) return '';
  const p = wallParts(ms, resolveZone(zone));
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}

export type ZoneResult =
  | { ok: true; utc: string; ms: number }
  | { ok: false; reason: 'invalid' | 'nonexistent' | 'ambiguous'; message: string };

/**
 * A wall-clock time in `zone` as a UTC ISO string (`2026-10-15T08:30:00.000Z`).
 * Fails with a message when the time does not exist in the zone or can be read two ways.
 */
export function localToUtc(wall: string, zone: string): ZoneResult {
  const z = resolveZone(zone);
  const m = WALL.exec(wall);
  if (!m) return { ok: false, reason: 'invalid', message: 'Enter a date and a time.' };
  const [y, mo, d, h, mi, s] = [m[1], m[2], m[3], m[4], m[5], m[6] || '0'].map(Number);
  const asUtc = Date.UTC(y, mo - 1, d, h, mi, s);
  const real = new Date(asUtc);
  if (real.getUTCFullYear() !== y || real.getUTCMonth() !== mo - 1 || real.getUTCDate() !== d || h > 23 || mi > 59 || s > 59) {
    return { ok: false, reason: 'invalid', message: 'That date or time is not valid.' };
  }
  // A clock change is at most a day away on either side, so the two offsets around the wall time cover every reading.
  const offsets = new Set([offsetMinutes(asUtc - 86400000, z), offsetMinutes(asUtc + 86400000, z)]);
  const matches = new Set<number>();
  for (const off of offsets) {
    const candidate = asUtc - off * 60000;
    if (wallAsUtcMs(candidate, z) === asUtc) matches.add(candidate);
  }
  if (matches.size === 0) {
    return { ok: false, reason: 'nonexistent', message: `That time does not exist in ${z}: the clocks skip it when they change. Pick a different time.` };
  }
  if (matches.size > 1) {
    return { ok: false, reason: 'ambiguous', message: `That time happens twice in ${z}, because the clocks go back. Pick a time just before or after it.` };
  }
  const [ms] = [...matches];
  return { ok: true, utc: new Date(ms).toISOString(), ms };
}

/** Today's date in `zone` as `YYYY-MM-DD`. */
export function todayIn(zone: string, now: Date = new Date()): string {
  return utcToLocalInput(now, zone).slice(0, 10);
}

/** `YYYY-MM-DD` plus whole days (calendar arithmetic, no zone involved). */
export function addDays(day: string, days: number): string {
  const m = DAY.exec(day);
  if (!m) return day;
  const t = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + days));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** The last minute (23:59) of a calendar day in `zone`, as UTC. Steps back a minute at a time if a clock change swallowed it. */
export function endOfDayUtc(day: string, zone: string): ZoneResult {
  for (const minute of [59, 58, 30, 0]) {
    const r = localToUtc(`${day}T23:${pad(minute)}`, zone);
    if (r.ok || r.reason === 'invalid') return r;
  }
  return localToUtc(`${day}T22:00`, zone);
}

/** `Africa/Lagos (UTC+01:00)`, for the label beside a field. */
export function zoneLabel(zone: string, at: Date = new Date()): string {
  const z = resolveZone(zone);
  const off = offsetMinutes(at.getTime(), z);
  const sign = off < 0 ? '-' : '+';
  const abs = Math.abs(off);
  return `${z} (UTC${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)})`;
}

/** The message to show under a date-time field, or null when the wall time is fine (or not typed yet). */
export function wallProblem(wall: string, zone: string): string | null {
  if (!wall || !WALL.test(wall)) return null;
  const r = localToUtc(wall, zone);
  return r.ok ? null : r.message;
}
