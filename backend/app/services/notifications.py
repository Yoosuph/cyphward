"""Notifications phase 1: one helper every trigger calls (rules in this module).

    notifications.emit("scan_failed", org_id, key=f"scan_failed:{scan_id}", params={...}, cur=cur)

`emit` writes one row per recipient per event and applies the rules in one place:

* Recipients: the organisation's members chosen by the kind (all, admins, owners) or the trigger's own list, minus
  the person who caused the event; plus every platform owner when the kind is owner-relevant (audience 'owner').
* Dedupe: `key` identifies the event. A recipient never gets two rows for one key, including keys folded into a
  grouped row. Writes for one recipient are serialised by a transaction-scoped advisory lock, and a unique index
  backs the row's own key.
* Grouping: another event of the same kind and severity for the same recipient and organisation within 15 minutes of
  the last one, while the row is unread, is folded into that row (group_count + 1, title and body re-rendered).
  A row whose email is already sending or sent is never folded into, so a later critical event gets its own row
  and its own email; events folded into a still-pending row share that row's one email, which names the count.
* Daily cap: at most 20 info rows per customer per UTC day; further info events are dropped. Warning and critical
  events are never dropped. Owner-console rows are not capped (the console must see every owner-relevant event;
  grouping still folds repeats).
* Preferences: a customer's in-app mute drops the bell row; an email mute stops the email. Owner rows ignore customer
  preferences, so a mute never hides a critical event from the owner console (every critical kind is owner-relevant).
* Email: only critical events, only to customers who have not muted email for the category. The row is marked
  'pending' and `deliver_pending_emails` sends it after the commit (finalize_scan, the suspend route, and the daily
  sweep as catch-up). A row is claimed ('sending') before it is sent, so it is emailed at most once. A finding
  notice written during a scan (`email_after_scan`) waits until that scan has completed; if the scan fails or is
  cancelled, its email is 'skipped' (the in-app row stays: the finding was recorded).

Given `cur`, the rows are written inside the caller's transaction under a savepoint; otherwise in a transaction of
their own. A notification failure never fails the caller (only ClaimLost propagates).
"""
import asyncio
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.app.core import database
from backend.app.core.config import FRONTEND_URL
from backend.app.core.execution_fence import ClaimLost
from backend.app.services import mailer
from backend.app.services import notification_messages as msg

logger = logging.getLogger("cyphward.notifications")

GROUP_WINDOW_MINUTES = 15
DAILY_INFO_CAP = 20
PAGE_CAP = 50
_ROLES = {"all": None, "admins": ("owner", "admin"), "owners": ("owner",)}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "org"


# ── Emit ───────────────────────────────────────────────────────────────────
def emit(kind: str, org_id: Any, *, key: str, params: Optional[Dict[str, Any]] = None, cur: Any = None,
         recipients: Optional[Iterable[Any]] = None, actor_id: Optional[Any] = None,
         email_after_scan: Optional[Any] = None) -> int:
    """Record one event for everyone it concerns. Returns the number of rows written or folded (0 on failure)."""
    if kind not in msg.KINDS or not org_id or not key:
        logger.warning("notification %s not emitted: unknown kind or missing key", kind)
        return 0
    try:
        if cur is not None:
            with cur.connection.transaction():  # savepoint: a failure here rolls back alone
                return _emit(cur, kind, str(org_id), key, dict(params or {}), recipients, actor_id,
                             email_after_scan)
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as own:
                    return _emit(own, kind, str(org_id), key, dict(params or {}), recipients, actor_id,
                                 email_after_scan)
    except ClaimLost:
        raise
    except Exception:
        logger.warning("notification %s for org %s not recorded", kind, org_id, exc_info=True)
        return 0


def emit_finding(org_id: Any, finding_id: Any, severity: Optional[str], hostname: Optional[str], *,
                 scan_id: Optional[Any] = None, reopened: bool = False) -> int:
    """A finding became critical or high (new, raised, or seen again after it was resolved). Lower ratings: nothing.
    Given the scan that found it, the email waits until that scan completes."""
    kind = msg.FINDING_KIND_BY_SEVERITY.get((severity or "").lower())
    if kind is None:
        return 0
    key = f"finding:{finding_id}:{severity}" + (f":reopened:{scan_id}" if reopened else "")
    return emit(kind, org_id, key=key, params={"hostname": hostname, "reopened": reopened},
                email_after_scan=scan_id)


def _fetchone(cur, sql: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    cur.execute(sql, tuple(params))
    return cur.fetchone()


def _fetchall(cur, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    cur.execute(sql, tuple(params))
    return list(cur.fetchall() or [])


def _customer_recipients(cur, kind: msg.Kind, org_id: str, recipients: Optional[Iterable[Any]]) -> List[str]:
    if recipients is not None:
        wanted = [str(r) for r in recipients if r]
        if not wanted:
            return []
        rows = _fetchall(cur, "SELECT user_id FROM organization_members WHERE org_id = %s AND user_id = ANY(%s::uuid[])",
                         (org_id, wanted))
    elif _ROLES[kind.recipients] is None:
        rows = _fetchall(cur, "SELECT user_id FROM organization_members WHERE org_id = %s", (org_id,))
    else:
        rows = _fetchall(cur, "SELECT user_id FROM organization_members WHERE org_id = %s AND role = ANY(%s)",
                         (org_id, list(_ROLES[kind.recipients])))
    return sorted({str(r["user_id"]) for r in rows})


def _emit(cur, kind_name: str, org_id: str, key: str, params: Dict[str, Any],
          recipients: Optional[Iterable[Any]], actor_id: Optional[Any], email_after_scan: Optional[Any]) -> int:
    kind = msg.KINDS[kind_name]
    org = _fetchone(cur, "SELECT o.name, EXISTS (SELECT 1 FROM organization_suspensions os WHERE os.org_id = o.id "
                         "AND os.status = 'deleted') AS deleted FROM organizations o WHERE o.id = %s", (org_id,))
    if org is None:
        return 0
    params.setdefault("org_name", org["name"])
    if params.get("scan_id") and not params.get("domain"):
        row = _fetchone(cur, "SELECT d.domain FROM scans s JOIN domains d ON d.id = s.domain_id WHERE s.id = %s",
                        (str(params["scan_id"]),))
        params["domain"] = row["domain"] if row else None
    # A soft-deleted organisation (core/org_guard.py) notifies and emails none of its members; the owner console
    # still records owner-relevant events about it.
    targets: List[Tuple[str, str]] = [] if org.get("deleted") else [
        ("customer", uid) for uid in _customer_recipients(cur, kind, org_id, recipients)
        if not actor_id or uid != str(actor_id)]
    if kind.owner:
        targets += [("owner", str(r["user_id"])) for r in
                    _fetchall(cur, "SELECT user_id FROM platform_owners ORDER BY user_id", ())]
    written = 0
    for audience, user_id in targets:
        written += _write_one(cur, kind_name, kind, org_id, key, params, audience, user_id,
                              str(email_after_scan) if email_after_scan else None)
    return written


def _write_one(cur, kind_name: str, kind: msg.Kind, org_id: str, key: str, params: Dict[str, Any],
               audience: str, user_id: str, email_scan_id: Optional[str] = None) -> int:
    in_app, email = True, False
    if audience == "customer":
        pref = _fetchone(cur, "SELECT in_app_muted, email_muted FROM notification_preferences "
                              "WHERE user_id = %s AND category = %s", (user_id, kind.category)) or {}
        in_app = not pref.get("in_app_muted", False)
        email = kind.severity == "critical" and not pref.get("email_muted", False)
        if not in_app and not email:
            return 0
    # Serialise this recipient's writes so dedupe, grouping and the cap see each other.
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"notifications:{audience}:{user_id}",))
    if _fetchone(cur, "SELECT 1 AS seen FROM notifications WHERE audience = %s AND user_id = %s "
                      "AND (dedupe_key = %s OR group_keys @> ARRAY[%s]::text[]) LIMIT 1",
                 (audience, user_id, key, key)):
        return 0
    group = _fetchone(
        cur,
        "SELECT id, group_count FROM notifications WHERE audience = %s AND user_id = %s AND org_id = %s "
        "AND type = %s AND severity = %s AND in_app = %s AND read_at IS NULL "
        f"AND coalesce(last_event_at, created_at) >= now() - interval '{GROUP_WINDOW_MINUTES} minutes' "
        # Only into a row whose email is in the same state: none, or still waiting (never sending or sent), and
        # waiting on the same scan.
        "AND email_status IS NOT DISTINCT FROM %s AND email_scan_id IS NOT DISTINCT FROM %s::uuid "
        "ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
        (audience, user_id, org_id, kind_name, kind.severity, in_app, "pending" if email else None,
         email_scan_id if email else None))
    if group:
        count = int(group["group_count"]) + 1
        title, body = msg.render(kind_name, params, count, audience)
        cur.execute("UPDATE notifications SET group_count = %s, group_keys = array_append(group_keys, %s), "
                    "last_event_at = now(), title = %s, body = %s WHERE id = %s",
                    (count, key, title, body, group["id"]))
        return 1
    if kind.severity == "info" and in_app and audience == "customer":
        today = _fetchone(
            cur,
            "SELECT count(*) AS n FROM notifications WHERE audience = %s AND user_id = %s AND severity = 'info' "
            "AND in_app AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",
            (audience, user_id))
        if int((today or {}).get("n") or 0) >= DAILY_INFO_CAP:
            return 0
    title, body = msg.render(kind_name, params, 1, audience)
    row = _fetchone(
        cur,
        "INSERT INTO notifications (org_id, user_id, audience, type, category, severity, title, body, link, "
        "dedupe_key, last_event_at, in_app, email_status, email_scan_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s) "
        "ON CONFLICT (audience, user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING RETURNING id",
        (org_id, user_id, audience, kind_name, kind.category, kind.severity, title, body, kind.link, key, in_app,
         "pending" if email else None, email_scan_id if email else None))
    return 1 if row else 0


# ── Email delivery (after the commit) ──────────────────────────────────────
# A finding notice from a scan that failed, was cancelled or no longer exists is never emailed.
SKIP_SQL = """
UPDATE notifications n SET email_status = 'skipped'
WHERE n.email_status = 'pending' AND n.email_scan_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM scans s WHERE s.id = n.email_scan_id AND s.status IN ('queued', 'running', 'completed'))
RETURNING n.id
"""
# Only rows with no scan to wait for, or whose scan has completed.
CLAIM_SQL = """
UPDATE notifications n SET email_status = 'sending', email_attempted_at = now()
FROM (SELECT id FROM notifications x WHERE x.email_status = 'pending'
        AND (x.email_scan_id IS NULL
             OR EXISTS (SELECT 1 FROM scans s WHERE s.id = x.email_scan_id AND s.status = 'completed'))
      ORDER BY x.created_at LIMIT %s FOR UPDATE SKIP LOCKED) p
WHERE n.id = p.id
RETURNING n.id, n.org_id, n.user_id, n.category, n.title, n.body, n.link
"""
RECIPIENT_SQL = """
SELECT p.email, p.full_name,
       EXISTS (SELECT 1 FROM organization_members m WHERE m.org_id = %s AND m.user_id = p.id
               AND NOT EXISTS (SELECT 1 FROM organization_suspensions os
                               WHERE os.org_id = m.org_id AND os.status = 'deleted')) AS member,
       coalesce((SELECT email_muted FROM notification_preferences np
                 WHERE np.user_id = p.id AND np.category = %s), false) AS email_muted
FROM profiles p WHERE p.id = %s
"""


def preferences_url(category: Optional[str]) -> str:
    return f"{FRONTEND_URL}/settings?tab=notifications&category={category or ''}"


async def _send(to_email: str, subject: str, html: str, text: str, name: Optional[str], unsubscribe: str) -> Any:
    """The one place notification email leaves the process (tests replace it; see conftest.py)."""
    return await mailer.send_email_async(to_email, subject, html, text, name, kind="general",
                                         mail_headers={"List-Unsubscribe": f"<{unsubscribe}>"})


def _mark(ids: List[Any], status: str) -> None:
    if ids:
        database.execute_query(
            "UPDATE notifications SET email_status = %s, email_sent = %s WHERE id = ANY(%s::uuid[]) "
            "AND email_status = 'sending' RETURNING id", (status, status == "sent", [str(i) for i in ids]))


async def deliver_pending_emails(limit: int = 100) -> Dict[str, int]:
    """Send the pending critical emails. Best effort: never raises."""
    result = {"sent": 0, "failed": 0, "skipped": 0, "scan_not_completed": 0}
    try:
        result["scan_not_completed"] = len(await asyncio.to_thread(database.execute_query, SKIP_SQL, ()) or [])
        rows = await asyncio.to_thread(database.execute_query, CLAIM_SQL, (max(1, min(limit, 500)),)) or []
    except Exception:
        logger.warning("pending notification emails could not be claimed", exc_info=True)
        return result
    for row in rows:
        try:
            person = await asyncio.to_thread(database.execute_one, RECIPIENT_SQL,
                                             (row["org_id"], row["category"], row["user_id"]))
            if not person or not person.get("email") or not person["member"] or person["email_muted"]:
                await asyncio.to_thread(_mark, [row["id"]], "failed")
                result["skipped"] += 1
                continue
            unsubscribe = preferences_url(row["category"])
            label = msg.CATEGORIES.get(row["category"] or "", "account").lower()
            open_url = f"{FRONTEND_URL}{row['link'] or '/overview'}"
            html = mailer.generate_notification_email_html(person.get("full_name") or "", row["title"], row["body"] or "",
                                                           open_url, unsubscribe, msg.EMAIL_FOOTER.format(label=label))
            text = mailer.generate_notification_email_text(person.get("full_name") or "", row["title"], row["body"] or "",
                                                           open_url, unsubscribe, msg.EMAIL_FOOTER.format(label=label))
            await _send(person["email"], msg.email_subject(row["title"]), html, text, person.get("full_name"),
                        unsubscribe)
            await asyncio.to_thread(_mark, [row["id"]], "sent")
            result["sent"] += 1
        except Exception:
            logger.warning("a notification email failed", exc_info=True)
            try:
                await asyncio.to_thread(_mark, [row["id"]], "failed")
            except Exception:
                pass
            result["failed"] += 1
    return result


# ── Preferences ────────────────────────────────────────────────────────────
def get_preferences(user_id: str) -> List[Dict[str, Any]]:
    rows = database.execute_query("SELECT category, in_app_muted, email_muted FROM notification_preferences "
                                  "WHERE user_id = %s", (user_id,)) or []
    stored = {r["category"]: r for r in rows}
    return [{"category": c, "label": label, "hint": msg.CATEGORY_HINTS[c],
             "in_app": not stored.get(c, {}).get("in_app_muted", False),
             "email": not stored.get(c, {}).get("email_muted", False)}
            for c, label in msg.CATEGORIES.items()]


def set_preference(user_id: str, category: str, in_app: Optional[bool], email: Optional[bool]) -> Dict[str, Any]:
    current = next(p for p in get_preferences(user_id) if p["category"] == category)
    in_app = current["in_app"] if in_app is None else bool(in_app)
    email = current["email"] if email is None else bool(email)
    database.execute_one(
        "INSERT INTO notification_preferences (user_id, category, in_app_muted, email_muted) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_id, category) DO UPDATE SET in_app_muted = EXCLUDED.in_app_muted, "
        "email_muted = EXCLUDED.email_muted, updated_at = now() RETURNING category",
        (user_id, category, not in_app, not email))
    return {**current, "in_app": in_app, "email": email}


def email_muted(user_id: Any, category: str) -> bool:
    """True when the person turned email off for the category (used by the reminder emails as well)."""
    row = database.execute_one("SELECT email_muted FROM notification_preferences WHERE user_id = %s AND category = %s",
                               (str(user_id), category))
    return bool(row and row.get("email_muted"))


# ── Reading ────────────────────────────────────────────────────────────────
PUBLIC_COLUMNS = ("id, type, category, severity, title, body, link, read_at, created_at, group_count, "
                  "(user_id IS NULL) AS shared")


def _safe_link(link: Optional[str]) -> Optional[str]:
    return link if isinstance(link, str) and link.startswith("/") and not link.startswith("//") else None


def public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """The only shape a notification leaves the API in. Old rows get a category and, where their stored body could
    carry scanner text, the reviewed body instead."""
    kind = row.get("type")
    body = row.get("body")
    if row.get("shared") and kind in msg.LEGACY_REVIEWED_BODY:
        body = msg.LEGACY_REVIEWED_BODY[kind]
    return {
        "id": str(row["id"]),
        "kind": kind,
        "type": kind,
        "category": row.get("category") or msg.legacy_category(kind),
        "severity": msg.display_severity(row.get("severity")),
        "title": row.get("title"),
        "body": body,
        "link": _safe_link(row.get("link")),
        "count": int(row.get("group_count") or 1),
        "read_at": row.get("read_at").isoformat() if hasattr(row.get("read_at"), "isoformat") else row.get("read_at"),
        "created_at": (row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat")
                       else row.get("created_at")),
        **({"org_id": str(row["org_id"]), "org_name": row.get("org_name")} if "org_name" in row else {}),
    }


def _muted_legacy_types(user_id: str) -> List[str]:
    muted = {r["category"] for r in database.execute_query(
        "SELECT category FROM notification_preferences WHERE user_id = %s AND in_app_muted", (user_id,)) or []}
    return [t for t, c in msg.LEGACY_CATEGORY.items() if c in muted]


CUSTOMER_SCOPE = ("org_id = %s AND audience = 'customer' AND in_app "
                  "AND (user_id = %s OR (user_id IS NULL AND NOT (type = ANY(%s))))")


def customer_list(org_id: str, user_id: str, limit: int, offset: int, unread_only: bool) -> Dict[str, Any]:
    limit = min(max(int(limit or PAGE_CAP), 1), PAGE_CAP)
    offset = max(int(offset or 0), 0)
    hidden = _muted_legacy_types(user_id)
    scope = CUSTOMER_SCOPE + (" AND read_at IS NULL" if unread_only else "")
    rows = database.execute_query(
        f"SELECT {PUBLIC_COLUMNS} FROM notifications WHERE {scope} "
        "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
        (org_id, user_id, hidden, limit + 1, offset)) or []
    unread = database.execute_one(f"SELECT count(*) AS n FROM notifications WHERE {CUSTOMER_SCOPE} AND read_at IS NULL",
                                  (org_id, user_id, hidden)) or {}
    return {"notifications": [public_row(r) for r in rows[:limit]], "unread_count": int(unread.get("n") or 0),
            "limit": limit, "offset": offset, "has_more": len(rows) > limit}


def customer_mark_read(org_id: str, user_id: str, notification_id: str) -> Optional[Dict[str, Any]]:
    """Idempotent: marking a read row again returns it unchanged. None when the person cannot see it."""
    hidden = _muted_legacy_types(user_id)
    database.execute_one(f"UPDATE notifications SET read_at = now() WHERE id = %s AND {CUSTOMER_SCOPE} "
                         "AND read_at IS NULL RETURNING id", (notification_id, org_id, user_id, hidden))
    row = database.execute_one(f"SELECT {PUBLIC_COLUMNS} FROM notifications WHERE id = %s AND {CUSTOMER_SCOPE}",
                               (notification_id, org_id, user_id, hidden))
    return public_row(row) if row else None


def customer_mark_all_read(org_id: str, user_id: str) -> int:
    rows = database.execute_query(f"UPDATE notifications SET read_at = now() WHERE {CUSTOMER_SCOPE} "
                                  "AND read_at IS NULL RETURNING id", (org_id, user_id, _muted_legacy_types(user_id)))
    return len(rows or [])


OWNER_SCOPE = "n.audience = 'owner' AND n.user_id = %s"


def owner_list(owner_id: str, limit: int, offset: int) -> Dict[str, Any]:
    limit = min(max(int(limit or PAGE_CAP), 1), PAGE_CAP)
    offset = max(int(offset or 0), 0)
    rows = database.execute_query(
        "SELECT n.id, n.org_id, o.name AS org_name, n.type, n.category, n.severity, n.title, n.body, n.link, "
        "n.read_at, n.created_at, n.group_count, false AS shared "
        f"FROM notifications n JOIN organizations o ON o.id = n.org_id WHERE {OWNER_SCOPE} "
        "ORDER BY n.created_at DESC, n.id DESC LIMIT %s OFFSET %s", (owner_id, limit + 1, offset)) or []
    return {"notifications": [public_row(r) for r in rows[:limit]], "unread_count": owner_unread(owner_id),
            "limit": limit, "offset": offset, "has_more": len(rows) > limit}


def owner_unread(owner_id: str) -> int:
    row = database.execute_one(f"SELECT count(*) AS n FROM notifications n WHERE {OWNER_SCOPE} AND n.read_at IS NULL",
                               (owner_id,)) or {}
    return int(row.get("n") or 0)


def owner_mark_read(owner_id: str, notification_id: str) -> Optional[Dict[str, Any]]:
    changed = database.execute_one(f"UPDATE notifications n SET read_at = now() WHERE n.id = %s AND {OWNER_SCOPE} "
                                   "AND n.read_at IS NULL RETURNING n.id", (notification_id, owner_id))
    row = database.execute_one(
        "SELECT n.id, n.org_id, o.name AS org_name, n.type, n.category, n.severity, n.title, n.body, n.link, "
        "n.read_at, n.created_at, n.group_count, false AS shared "
        f"FROM notifications n JOIN organizations o ON o.id = n.org_id WHERE n.id = %s AND {OWNER_SCOPE}",
        (notification_id, owner_id))
    return {"notification": public_row(row), "changed": bool(changed)} if row else None


def owner_mark_all_read(owner_id: str) -> int:
    rows = database.execute_query(f"UPDATE notifications n SET read_at = now() WHERE {OWNER_SCOPE} "
                                  "AND n.read_at IS NULL RETURNING n.id", (owner_id,))
    return len(rows or [])
