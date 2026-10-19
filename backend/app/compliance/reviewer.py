"""DPCO reviewer access (packet C6): customer-granted, time-limited, audited, read-only plus two notes.

An organisation OWNER grants one person (named by email) review access to that organisation's readiness
pages for 1 to 90 days. This is its own authority. It is not an organisation membership (the reviewer never
appears in members and cannot read anything outside the readiness pages), it is not platform staff, and
platform staff do not gain it. Nothing here reads a member's role, the staff tables or the owner-console
sessions to decide a reviewer's access.

Access is decided on EVERY request by one query that checks, on the database clock: the grant names the
signed-in account's own verified profile email, is not revoked, has not expired, the account is not a member
of the organisation, and the organisation is on the Growth plan. Every refusal is the same 403 so a caller
learns nothing about which organisations, grants or accounts exist.

A reviewer can do two things, both append-only and both audited (without the free text): record that they
reviewed a requirement, and mark an organisation's clause reference as reviewed. Neither changes any
evidence status.
"""
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg.errors
from fastapi import Depends, Header, HTTPException
from psycopg.types.json import Jsonb

from backend.app.compliance import practitioner, status
from backend.app.compliance.register import requirement as register_requirement
from backend.app.core import database
from backend.app.core.auth import get_current_user, log_audit
from backend.app.core.database import execute_one, execute_query

logger = logging.getLogger("cyphward.reviewer")

MIN_DAYS, DEFAULT_DAYS, MAX_DAYS = 1, 30, 90
PURPOSE_MAX = 200
LOCK_WAIT_MS = 3000
DENIED = "Reviewer access is not available for this organisation."
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ACTIONS = {"granted": "compliance.reviewer.granted", "replaced": "compliance.reviewer.replaced",
           "revoked": "compliance.reviewer.revoked", "session": "compliance.reviewer.session",
           "review": "compliance.reviewer.review_recorded", "clause": "compliance.reviewer.clause_recorded"}


class GrantError(ValueError):
    """A grant request the rules refuse. The API maps it to 422."""


class Busy(RuntimeError):
    """Another grant change for the same person is in progress (lock wait bounded). The API maps it to 503."""


class NoAccess(PermissionError):
    """The grant stopped being active between the check and the write. The API maps it to the same 403."""


class NotFound(LookupError):
    """No such grant, requirement or organisation record. The API maps it to 404."""


class AlreadyEnded(RuntimeError):
    """The grant is already revoked or expired. The API maps it to 409."""


def denied() -> HTTPException:
    return HTTPException(status_code=403, detail=DENIED)


def normalise_email(value: Optional[str]) -> str:
    email = (value or "").strip().lower()
    if not EMAIL.match(email) or not 3 <= len(email) <= 254:
        raise GrantError("Enter a valid email address.")
    return email


# ── Access check (every request) ──────────────────────────────────────────

ACTIVE_SQL = """
    SELECT g.id AS grant_id, g.org_id, g.purpose, g.expires_at, g.granted_at,
           p.id AS user_id, p.full_name, p.email
    FROM compliance_reviewer_grants g
    JOIN profiles p ON p.id = %(uid)s AND lower(p.email) = g.reviewer_email AND p.email_verified_at IS NOT NULL
    WHERE g.revoked_at IS NULL AND g.expires_at > clock_timestamp()
      AND NOT EXISTS (SELECT 1 FROM organization_members m WHERE m.org_id = g.org_id AND m.user_id = p.id)
"""


def _uuid(value: Any) -> Optional[str]:
    from uuid import UUID
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def active_grants(user_id: str) -> List[Dict[str, Any]]:
    """Every organisation this account may review right now, with the organisation's name."""
    rows = execute_query(
        "SELECT a.grant_id, a.org_id, a.purpose, a.expires_at, o.name AS org_name "
        f"FROM ({ACTIVE_SQL}) a JOIN organizations o ON o.id = a.org_id ORDER BY o.name, a.grant_id",
        {"uid": str(user_id)}) or []
    return rows


_seen: Dict[Any, bool] = {}
_seen_lock = threading.Lock()
_SEEN_MAX = 5000


def _note_session(ctx: Dict[str, Any]) -> None:
    """Audit the first request of a grant per UTC day. A process-local cache keeps the per-request cost at zero;
    a restart or another replica may write a second row for the same day, which is harmless."""
    day = datetime.now(timezone.utc).date()
    key = (str(ctx["grant_id"]), day)
    with _seen_lock:
        if key in _seen:
            return
        if len(_seen) >= _SEEN_MAX:
            _seen.clear()
        _seen[key] = True
    try:
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        done = execute_one(
            "SELECT 1 AS x FROM audit_log WHERE org_id = %s AND created_at >= %s AND action = %s AND resource_id = %s "
            "LIMIT 1", (ctx["org_id"], start, ACTIONS["session"], str(ctx["grant_id"])))
        if not done:
            log_audit(str(ctx["org_id"]), str(ctx["user_id"]), ACTIONS["session"], "reviewer_grant",
                      str(ctx["grant_id"]), {"grant_id": str(ctx["grant_id"])})
    except Exception as exc:  # the audit of a view must never break the view
        logger.warning("reviewer session audit failed: %s", exc)


def require_reviewer(
    user: Dict[str, Any] = Depends(get_current_user),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
) -> Dict[str, Any]:
    """Dependency for the reviewer endpoints: the caller's active grant for the organisation in X-Organization-Id.

    Only a UUID selects the organisation. Anything else, and every reason the grant is not usable, is the same 403."""
    org_id = _uuid((x_organization_id or "").strip())
    if not org_id:
        raise denied()
    grant = execute_one(f"SELECT a.* FROM ({ACTIVE_SQL}) a WHERE a.org_id = %(org)s",
                        {"uid": str(user["id"]), "org": org_id})
    if not grant:
        raise denied()
    org = execute_one("SELECT * FROM organizations WHERE id = %s", (org_id,))
    if not org or status.is_starter(org):
        raise denied()
    ctx = {**grant, "org": org, "user": user}
    _note_session(ctx)
    return ctx


# ── Owner side: grant, revoke, list ───────────────────────────────────────


def _lock(conn, key: str) -> None:
    conn.execute(f"SET LOCAL lock_timeout = '{LOCK_WAIT_MS}ms'")
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))


GRANT_COLUMNS = "id, org_id, reviewer_email, purpose, granted_by, granted_at, expires_at, revoked_at, revoked_by"


def grant_access(org: Dict[str, Any], owner_id: str, email: str, days: int, purpose: str) -> Dict[str, Any]:
    """Grant (or replace) one reviewer's access in ONE transaction: the previous grant for the same person is
    revoked, the new one inserted and both audited, or nothing happens. A grant is never extended in place."""
    reviewer = normalise_email(email)
    if not MIN_DAYS <= int(days) <= MAX_DAYS:
        raise GrantError(f"Access can last from {MIN_DAYS} to {MAX_DAYS} days.")
    try:
        text = practitioner.clean_text(purpose, "Purpose", PURPOSE_MAX, required=True)
    except practitioner.TextError as exc:
        raise GrantError(str(exc))
    org_id = str(org["id"])
    try:
        with database.get_db() as conn:
            with conn.transaction():
                _lock(conn, f"reviewer-grant:{org_id}:{reviewer}")
                if conn.execute(
                        "SELECT 1 FROM organization_members m JOIN profiles p ON p.id = m.user_id "
                        "WHERE m.org_id = %s AND lower(p.email) = %s", (org_id, reviewer)).fetchone():
                    raise GrantError("That person is already a member of this organisation. A reviewer is someone "
                                     "outside it; use a different address.")
                old = conn.execute(
                    "UPDATE compliance_reviewer_grants SET revoked_at = LEAST(clock_timestamp(), expires_at), "
                    "revoked_by = %s WHERE org_id = %s AND reviewer_email = %s AND revoked_at IS NULL "
                    "RETURNING id, expires_at, revoked_at", (owner_id, org_id, reviewer)).fetchall()
                row = conn.execute(
                    f"INSERT INTO compliance_reviewer_grants (org_id, reviewer_email, purpose, granted_by, granted_at, "
                    f"expires_at) VALUES (%s, %s, %s, %s, now(), now() + make_interval(days => %s)) "
                    f"RETURNING {GRANT_COLUMNS}", (org_id, reviewer, text, owner_id, int(days))).fetchone()
                for prior in old:
                    conn.execute(
                        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                        "VALUES (%s, %s, %s, 'reviewer_grant', %s, %s)",
                        (org_id, owner_id, ACTIONS["replaced"], str(prior["id"]),
                         Jsonb({"grant_id": str(prior["id"]), "replaced_by": str(row["id"])})))
                conn.execute(
                    "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                    "VALUES (%s, %s, %s, 'reviewer_grant', %s, %s)",
                    (org_id, owner_id, ACTIONS["granted"], str(row["id"]),
                     Jsonb({"grant_id": str(row["id"]), "days": int(days), "expires_at": row["expires_at"].isoformat(),
                            "replaced_grant_ids": [str(p["id"]) for p in old]})))
    except psycopg.errors.LockNotAvailable as exc:
        raise Busy("Another change to this reviewer's access is in progress.") from exc
    return row


def revoke(org_id: str, grant_id: str, actor_id: str) -> Dict[str, Any]:
    gid = _uuid(grant_id)
    if not gid:
        raise NotFound()
    try:
        with database.get_db() as conn:
            with conn.transaction():
                conn.execute(f"SET LOCAL lock_timeout = '{LOCK_WAIT_MS}ms'")
                row = conn.execute(
                    f"SELECT {GRANT_COLUMNS} FROM compliance_reviewer_grants WHERE id = %s AND org_id = %s FOR UPDATE",
                    (gid, str(org_id))).fetchone()
                if not row:
                    raise NotFound()
                ended = conn.execute("SELECT %s <= clock_timestamp() AS e", (row["expires_at"],)).fetchone()["e"]
                if row["revoked_at"] is not None or ended:
                    raise AlreadyEnded()
                row = conn.execute(
                    f"UPDATE compliance_reviewer_grants SET revoked_at = clock_timestamp(), revoked_by = %s "
                    f"WHERE id = %s AND org_id = %s AND revoked_at IS NULL RETURNING {GRANT_COLUMNS}",
                    (actor_id, gid, str(org_id))).fetchone()
                conn.execute(
                    "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                    "VALUES (%s, %s, %s, 'reviewer_grant', %s, %s)",
                    (str(org_id), actor_id, ACTIONS["revoked"], gid, Jsonb({"grant_id": gid})))
    except psycopg.errors.LockNotAvailable as exc:
        raise Busy("The grant is being used right now. Try again in a moment.") from exc
    return row


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def grant_status(row: Dict[str, Any], used: bool, now: datetime) -> str:
    """revoked / expired / pending (the reviewer has not opened it yet) / active (they have).

    pending-versus-active comes from the reviewer's own use, never from whether an account exists."""
    if row["revoked_at"] is not None and row["revoked_at"] < row["expires_at"]:
        return "revoked"
    if row["revoked_at"] is not None or row["expires_at"] <= now:
        return "expired"
    return "active" if used else "pending"


def list_grants(org_id: str) -> List[Dict[str, Any]]:
    now = (execute_one("SELECT clock_timestamp() AS t") or {})["t"]
    rows = execute_query(
        f"SELECT {GRANT_COLUMNS}, (SELECT full_name FROM profiles WHERE id = granted_by) AS granted_by_name "
        "FROM compliance_reviewer_grants WHERE org_id = %s ORDER BY granted_at DESC, id LIMIT 200", (str(org_id),)) or []
    used = {r["resource_id"] for r in execute_query(
        "SELECT DISTINCT resource_id FROM audit_log WHERE org_id = %s AND action = %s",
        (str(org_id), ACTIONS["session"])) or []}
    return [{"id": str(r["id"]), "reviewer_email": r["reviewer_email"], "purpose": r["purpose"],
             "status": grant_status(r, str(r["id"]) in used, now), "granted_at": _iso(r["granted_at"]),
             "granted_by_name": r.get("granted_by_name"), "expires_at": _iso(r["expires_at"]),
             "revoked_at": _iso(r["revoked_at"])} for r in rows]


def activity(org_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """What reviewers did, newest first: practitioner reviews and clause verifications."""
    rows = execute_query(
        "SELECT * FROM ("
        " SELECT 'review' AS kind, id, requirement_key, reviewer_name, reviewed_at AS at, outcome, NULL::boolean AS verified,"
        "        comment AS text, grant_id FROM compliance_practitioner_reviews WHERE org_id = %(o)s"
        " UNION ALL"
        " SELECT 'clause', id, requirement_key, reviewer_name, verified_at, NULL, verified, note, grant_id"
        "   FROM compliance_clause_verifications WHERE org_id = %(o)s) u ORDER BY at DESC, id LIMIT %(n)s",
        {"o": str(org_id), "n": limit}) or []
    out = []
    for r in rows:
        req = register_requirement(r["requirement_key"])
        out.append({"kind": r["kind"], "id": str(r["id"]), "requirement_key": r["requirement_key"],
                    "requirement_title": req["title"] if req else r["requirement_key"],
                    "reviewer_name": r["reviewer_name"], "at": _iso(r["at"]), "grant_id": str(r["grant_id"]),
                    "outcome": r["outcome"], "outcome_label": practitioner.OUTCOMES.get(r["outcome"] or ""),
                    "verified": r["verified"], "text": r["text"]})
    return out


def audit_trail(org_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    rows = execute_query(
        "SELECT a.action, a.created_at, a.resource_id, a.metadata, a.user_id, p.full_name FROM audit_log a "
        "LEFT JOIN profiles p ON p.id = a.user_id WHERE a.org_id = %s AND a.action LIKE 'compliance.reviewer.%%' "
        "ORDER BY a.created_at DESC, a.id LIMIT %s", (str(org_id), limit)) or []
    return [{"action": r["action"], "at": _iso(r["created_at"]), "grant_id": r["resource_id"],
             "by": r.get("full_name"), "metadata": r["metadata"]} for r in rows]


# ── Reviewer side: what they may see and write ───────────────────────────


def _answer_values(org_id: str) -> Dict[str, Dict[str, Any]]:
    from backend.app.compliance import attestation_store
    return {k: {"value": (r["answer"] or {}).get("value"), "date": (r["answer"] or {}).get("date")}
            for k, r in attestation_store.current_rows(org_id).items()}


def _shape(view: Dict[str, Any], values: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """An answer shows its value, date, owner name and expiry. Free text, notes and links never leave the org."""
    for answer in view.get("answers") or []:
        answer.update(values.get(answer["question_key"], {"value": None, "date": None}))
    return view


def overview(ctx: Dict[str, Any]) -> Dict[str, Any]:
    org = ctx["org"]
    data = status.overview(org)
    values = _answer_values(str(org["id"]))
    for group in data["groups"]:
        for view in group["requirements"]:
            _shape(view, values)
    data["organisation"] = {"id": str(org["id"]), "name": org["name"]}
    data["grant"] = {"id": str(ctx["grant_id"]), "purpose": ctx["purpose"], "expires_at": _iso(ctx["expires_at"])}
    return data


def requirement_detail(ctx: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    detail = status.requirement_detail(ctx["org"], key[:120])
    if detail is None or detail.get("locked"):
        return None
    return _shape(detail, _answer_values(str(ctx["org"]["id"])))


def _display_name(ctx: Dict[str, Any]) -> str:
    return ((ctx.get("full_name") or "").strip() or ctx["email"].split("@")[0])[:200]


def _write(ctx: Dict[str, Any], table: str, columns: str, values: tuple, action: str, meta: Dict[str, Any],
           key: str) -> Dict[str, Any]:
    """Insert one record under a SHARE lock on the grant, which makes a concurrent revocation wait, and audit it
    in the same transaction. The table's own trigger re-checks the grant and the writer as the last line."""
    if register_requirement(key) is None:
        raise NotFound()
    org_id, grant_id, user_id = str(ctx["org_id"]), str(ctx["grant_id"]), str(ctx["user_id"])
    try:
        with database.get_db() as conn:
            with conn.transaction():
                conn.execute(f"SET LOCAL lock_timeout = '{LOCK_WAIT_MS}ms'")
                live = conn.execute(
                    "SELECT 1 FROM compliance_reviewer_grants WHERE id = %s AND org_id = %s AND revoked_at IS NULL "
                    "AND expires_at > clock_timestamp() FOR SHARE", (grant_id, org_id)).fetchone()
                if not live:
                    raise NoAccess()
                placeholders = ", ".join(["%s"] * (len(values) + 5))
                row = conn.execute(
                    f"INSERT INTO {table} (org_id, requirement_key, grant_id, reviewer_user_id, reviewer_name, {columns}) "
                    f"VALUES ({placeholders}) RETURNING *",
                    (org_id, key, grant_id, user_id, _display_name(ctx)) + values).fetchone()
                conn.execute(
                    "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (org_id, user_id, action, "reviewer_grant", str(row["id"]),
                     Jsonb({"grant_id": grant_id, "requirement_key": key, **meta})))
    except psycopg.errors.LockNotAvailable as exc:
        raise Busy("The grant is being changed right now. Try again in a moment.") from exc
    except psycopg.errors.CheckViolation as exc:
        raise NoAccess() from exc
    return row


def record_review(ctx: Dict[str, Any], key: str, outcome: str, comment: Optional[str]) -> Dict[str, Any]:
    if outcome not in practitioner.OUTCOMES:
        raise GrantError("Choose one of the listed outcomes.")
    text = practitioner.clean_text(comment, "Comment")
    row = _write(ctx, "compliance_practitioner_reviews", "outcome, comment", (outcome, text), ACTIONS["review"],
                 {"outcome": outcome, "has_comment": text is not None}, key)
    return practitioner.review_view(row)


def record_clause(ctx: Dict[str, Any], key: str, verified: bool, note: Optional[str]) -> Dict[str, Any]:
    text = practitioner.clean_text(note, "Note")
    row = _write(ctx, "compliance_clause_verifications", "verified, note", (bool(verified), text), ACTIONS["clause"],
                 {"verified": bool(verified), "has_note": text is not None}, key)
    return practitioner.clause_view(row)
