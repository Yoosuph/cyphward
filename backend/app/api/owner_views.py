"""Owner console data views (stage 2): see everything, change nothing.

Every endpoint requires an owner session (`require_owner`) and writes an
owner audit row *before* it reads, so no data leaves without a record (an
audit failure returns 503). Responses use explicit column lists: password
hashes, authenticator secrets, token hashes, scan claim tokens and DNS
verification tokens are never selected.
"""
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.app.core import owner as owner_mod
from backend.app.core import owner_lists as lists
from backend.app.core import owner_reads as reads
from backend.app.core.demo_org import DEMO_ORG_ID, DEMO_USER_ID
from backend.app.core.config import BREVO_API_KEY
from backend.app.core.database import execute_one, execute_query
from backend.app.core.plans import PLANS
from backend.app.core.runtime_guard import background_status

router = APIRouter(prefix="/api/v1/owner", tags=["Owner console"])

QUEUE_DELAY_SECONDS = 600  # a queued scan older than this is "delayed", not just waiting


def _view(request: Request, owner: Dict[str, Any], section: str,
          target_type: Optional[str] = None, target_id: Optional[str] = None,
          metadata: Optional[Dict[str, Any]] = None) -> None:
    owner_mod.audit(request, f"owner.view.{section}", "success", user_id=owner["user_id"],
                    email=owner["email"], session_id=owner["session_id"],
                    target_type=target_type, target_id=target_id, metadata=metadata)


def _like(q: str) -> str:
    q = q.strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q}%"


def _uuid(value: str) -> str:
    import uuid
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found.")


def _rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return execute_query(sql, params) or []


def _filters_meta(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The list filters for the owner audit row (search text trimmed; defaults left out)."""
    meta = {k: (v[:100] if isinstance(v, str) else v) for k, v in filters.items() if v not in ("", None)}
    return meta or None


# ── Overview ───────────────────────────────────────────────────────────────
@router.get("/overview")
def overview(request: Request, owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    _view(request, owner, "overview")
    # The sample-data demo organisation and its owner are left out of every count here (core/demo_org.py).
    demo_org = f"'{DEMO_ORG_ID}'"
    demo_user = f"'{DEMO_USER_ID}'"
    counts = execute_one(
        f"""
        SELECT
          (SELECT count(*) FROM profiles WHERE id <> {demo_user}) AS users_total,
          (SELECT count(*) FROM profiles WHERE id <> {demo_user} AND created_at > now() - interval '7 days') AS users_7d,
          (SELECT count(*) FROM profiles WHERE id <> {demo_user} AND created_at > now() - interval '30 days') AS users_30d,
          (SELECT count(*) FROM organizations WHERE id <> {demo_org}) AS orgs_total,
          (SELECT count(*) FROM organizations WHERE id <> {demo_org} AND created_at > now() - interval '7 days') AS orgs_7d,
          (SELECT count(*) FROM domains WHERE org_id <> {demo_org} AND revoked_at IS NULL AND verification_status = 'verified') AS domains_verified,
          (SELECT count(*) FROM domains WHERE org_id <> {demo_org} AND revoked_at IS NULL AND verification_status <> 'verified') AS domains_pending,
          (SELECT count(*) FROM scans WHERE org_id <> {demo_org} AND created_at > now() - interval '24 hours') AS scans_24h,
          (SELECT count(*) FROM scans WHERE org_id <> {demo_org} AND created_at > now() - interval '24 hours' AND status = 'failed') AS scans_failed_24h,
          (SELECT count(*) FROM scans WHERE org_id <> {demo_org} AND status = 'queued') AS scans_queued,
          (SELECT count(*) FROM scans WHERE org_id <> {demo_org} AND status = 'running') AS scans_running,
          (SELECT count(*) FROM scans WHERE org_id <> {demo_org} AND status = 'running' AND lease_expires_at < now()) AS scans_lease_expired,
          (SELECT EXTRACT(EPOCH FROM now() - min(created_at))::int FROM scans WHERE org_id <> {demo_org} AND status = 'queued') AS oldest_queued_seconds
        """
    ) or {}
    signups = _rows(
        "SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, count(*) AS users "
        f"FROM profiles WHERE id <> {demo_user} AND created_at > now() - interval '14 days' GROUP BY 1 ORDER BY 1"
    )
    subscriptions = _rows(f"SELECT plan, status, count(*) AS n FROM subscriptions WHERE org_id <> {demo_org} "
                          "GROUP BY 1, 2 ORDER BY 3 DESC")
    invoices = _rows(
        "SELECT currency, status, count(*) AS n, COALESCE(sum(amount_kobo), 0) AS amount_minor "
        f"FROM invoices WHERE org_id <> {demo_org} GROUP BY 1, 2 ORDER BY 1, 2"
    )
    activity = _rows(
        """
        SELECT a.action, a.created_at, a.resource_type, o.name AS org_name, p.email AS user_email
        FROM audit_log a
        LEFT JOIN organizations o ON o.id = a.org_id
        LEFT JOIN profiles p ON p.id = a.user_id
        ORDER BY a.created_at DESC LIMIT 12
        """
    )
    return {"as_of": time.time(), "counts": counts, "signups_14d": signups,
            "subscriptions": subscriptions, "invoices": invoices, "recent_activity": activity,
            "queue_delay_seconds": QUEUE_DELAY_SECONDS}


# ── Organizations ──────────────────────────────────────────────────────────
# Lists: search, filter, sort and pages on the server (core/owner_lists.py). Sizes above 100 are capped; a size
# below 1, a negative offset or an unknown filter or sort value is refused with 422.
@router.get("/organizations")
def organizations(request: Request, q: str = Query("", max_length=100), billing: lists.OrgBilling = "",
                  plan: lists.PlanFilter = "", suspended: lists.YesNo = "", sort: lists.OrgSort = "created",
                  dir: lists.Dir = "desc", limit: int = Query(50, ge=1), offset: int = Query(0, ge=0, le=100000),
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    limit = reads.page_size(limit)
    filters = {"q": q, "billing": billing, "plan": plan, "suspended": suspended, "sort": sort, "dir": dir}
    _view(request, owner, "organizations", metadata=_filters_meta(filters))
    rows, total = reads.bounded_read(lists.organizations(q, billing, plan, suspended, sort, dir, limit, offset))
    return {"items": rows, "total": (total[0] if total else {}).get("n", 0), "limit": limit, "offset": offset,
            "sort": sort, "dir": dir}


@router.get("/organizations/{org_id}")
def organization_detail(org_id: str, request: Request,
                        owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    org_id = _uuid(org_id)
    _view(request, owner, "organization", "organization", org_id)
    org = execute_one(
        "SELECT id, name, slug, plan, sector, cac_rc, created_at, updated_at FROM organizations WHERE id = %s",
        (org_id,),
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    members = _rows(
        """
        SELECT p.id, p.email, p.full_name, m.role, m.created_at AS joined_at,
               (SELECT max(COALESCE(s.last_used_at, s.created_at)) FROM auth_sessions s WHERE s.user_id = p.id) AS last_seen_at
        FROM organization_members m JOIN profiles p ON p.id = m.user_id
        WHERE m.org_id = %s ORDER BY m.created_at
        """,
        (org_id,),
    )
    domains = _rows(
        "SELECT id, domain, verification_status, verified_at, created_at, revoked_at FROM domains "
        "WHERE org_id = %s ORDER BY created_at",
        (org_id,),
    )
    subscriptions = _rows(
        "SELECT plan, status, provider, current_period_start, current_period_end, trial_ends_at, "
        "cancel_at_period_end, created_at FROM subscriptions WHERE org_id = %s ORDER BY created_at DESC",
        (org_id,),
    )
    invoices = _rows(
        "SELECT number, plan, amount_kobo, currency, status, period_start, period_end, created_at "
        "FROM invoices WHERE org_id = %s ORDER BY created_at DESC LIMIT 24",
        (org_id,),
    )
    scans = _rows(
        """
        SELECT s.id, d.domain, s.status, s.scan_type, s.score, s.created_at, s.completed_at,
               s.stage_progress->'scoring'->'coverage'->>'state' AS coverage_state
        FROM scans s LEFT JOIN domains d ON d.id = s.domain_id
        WHERE s.org_id = %s ORDER BY s.created_at DESC LIMIT 20
        """,
        (org_id,),
    )
    findings = _rows(
        "SELECT severity, count(*) AS n FROM findings WHERE org_id = %s AND status <> 'resolved' GROUP BY 1",
        (org_id,),
    )
    activity = _rows(
        """
        SELECT a.action, a.resource_type, a.created_at, p.email AS user_email
        FROM audit_log a LEFT JOIN profiles p ON p.id = a.user_id
        WHERE a.org_id = %s ORDER BY a.created_at DESC LIMIT 30
        """,
        (org_id,),
    )
    suspension = execute_one(
        "SELECT status, changed_at, first_suspended_at FROM organization_suspensions WHERE org_id = %s", (org_id,))
    # Owner actions on this organization (changes and refusals; views are left out), newest first.
    owner_actions = _rows(
        """
        SELECT created_at, action, outcome, actor_email, metadata->>'reason' AS reason
        FROM owner_audit
        WHERE target_type = 'organization' AND target_id = %s AND action LIKE 'owner.action.%%'
        ORDER BY created_at DESC LIMIT 20
        """,
        (org_id,),
    )
    org = {**org, "suspended": bool(suspension and suspension["status"] == "suspended"),
           "suspension_changed_at": (suspension or {}).get("changed_at")}
    return {"organization": org, "members": members, "domains": domains, "subscriptions": subscriptions,
            "invoices": invoices, "scans": scans, "open_findings": findings, "activity": activity,
            "owner_actions": owner_actions,
            "plans": [{"slug": slug, "label": spec["label"]} for slug, spec in PLANS.items()]}


# ── Users ──────────────────────────────────────────────────────────────────
@router.get("/users")
def users(request: Request, q: str = Query("", max_length=100), mfa: lists.UserMfa = "", verified: lists.YesNo = "",
          sort: lists.UserSort = "created", dir: lists.Dir = "desc", limit: int = Query(50, ge=1),
          offset: int = Query(0, ge=0, le=100000),
          owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    limit = reads.page_size(limit)
    filters = {"q": q, "mfa": mfa, "verified": verified, "sort": sort, "dir": dir}
    _view(request, owner, "users", metadata=_filters_meta(filters))
    rows, total = reads.bounded_read(lists.users(q, mfa, verified, sort, dir, limit, offset))
    return {"items": rows, "total": (total[0] if total else {}).get("n", 0), "limit": limit, "offset": offset,
            "sort": sort, "dir": dir}


@router.get("/users/{user_id}")
def user_detail(user_id: str, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    user_id = _uuid(user_id)
    _view(request, owner, "user", "user", user_id)
    profile = execute_one(
        """
        SELECT id, email, full_name, provider, created_at, updated_at, email_verified_at,
               mfa_enrolled_at, totp_enrolled_at,
               EXISTS (SELECT 1 FROM platform_owners po WHERE po.user_id = profiles.id) AS platform_owner
        FROM profiles WHERE id = %s
        """,
        (user_id,),
    )
    if not profile:
        raise HTTPException(status_code=404, detail="User not found.")
    memberships = _rows(
        "SELECT o.id, o.name, m.role, m.created_at AS joined_at FROM organization_members m "
        "JOIN organizations o ON o.id = m.org_id WHERE m.user_id = %s ORDER BY m.created_at",
        (user_id,),
    )
    sessions = _rows(
        "SELECT left(id::text, 8) AS ref, created_at, last_used_at, expires_at, revoked_at FROM auth_sessions "
        "WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
        (user_id,),
    )
    remembered = execute_one(
        "SELECT count(*) AS n FROM trusted_browsers WHERE user_id = %s AND expires_at > now()", (user_id,)
    ) or {}
    activity = _rows(
        """
        SELECT a.action, a.resource_type, a.created_at, a.metadata, o.name AS org_name
        FROM audit_log a LEFT JOIN organizations o ON o.id = a.org_id
        WHERE a.user_id = %s ORDER BY a.created_at DESC LIMIT 40
        """,
        (user_id,),
    )
    return {"user": profile, "memberships": memberships, "sessions": sessions,
            "remembered_browsers": remembered.get("n", 0), "activity": activity}


# ── Subscriptions & invoices ───────────────────────────────────────────────
@router.get("/subscriptions")
def subscriptions(request: Request, q: str = Query("", max_length=100), status: lists.SubStatus = "",
                  plan: lists.PlanFilter = "", sort: lists.SubSort = "period_end", dir: lists.Dir = "asc",
                  limit: int = Query(50, ge=1), offset: int = Query(0, ge=0, le=100000),
                  owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    limit = reads.page_size(limit)
    filters = {"q": q, "status": status, "plan": plan, "sort": sort, "dir": dir}
    _view(request, owner, "subscriptions", metadata=_filters_meta(filters))
    rows_q, total_q = lists.subscriptions(q, status, plan, sort, dir, limit, offset)
    rows, total, invoices = reads.bounded_read([rows_q, total_q, (
        """
        SELECT i.number, o.id AS org_id, o.name AS org_name, i.plan, i.amount_kobo, i.currency, i.status,
               i.period_start, i.period_end, i.created_at
        FROM invoices i JOIN organizations o ON o.id = i.org_id
        ORDER BY i.created_at DESC LIMIT 50
        """, ())])
    return {"items": rows, "total": (total[0] if total else {}).get("n", 0), "limit": limit, "offset": offset,
            "sort": sort, "dir": dir, "invoices": invoices}


# ── Scans ──────────────────────────────────────────────────────────────────
_SCAN_COLUMNS = f"""
    s.id, o.id AS org_id, o.name AS org_name, d.domain, s.status, s.scan_type, s.current_stage,
    s.created_at, s.started_at, s.completed_at, s.score, s.claimed_by, s.lease_expires_at,
    EXTRACT(EPOCH FROM (COALESCE(s.completed_at, now()) - COALESCE(s.started_at, s.created_at)))::int AS duration_seconds,
    s.stage_progress->'scoring'->'coverage'->>'state' AS coverage_state,
    (SELECT array_agg(key ORDER BY key) FROM jsonb_each(COALESCE(s.stage_progress, '{{}}'::jsonb)) e
       WHERE jsonb_typeof(e.value) = 'object' AND e.value->>'status' = 'failed') AS failed_stages,
    CASE
      WHEN s.status = 'queued' AND s.created_at < now() - interval '{QUEUE_DELAY_SECONDS} seconds' THEN 'queued_delayed'
      WHEN s.status = 'queued' THEN 'queued'
      WHEN s.status = 'running' AND s.lease_expires_at < now() THEN 'running_lease_expired'
      ELSE s.status
    END AS state
"""


@router.get("/scans")
def scans(request: Request, q: str = "", state: str = "", limit: int = Query(50, ge=1, le=100),
          offset: int = Query(0, ge=0, le=100000),
          owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    _view(request, owner, "scans", metadata={k: v[:100] for k, v in (("q", q), ("state", state)) if v} or None)
    params = {"q": q.strip(), "like": _like(q), "state": state.strip(), "limit": limit, "offset": offset}
    rows = _rows(
        f"""
        SELECT * FROM (
          SELECT {_SCAN_COLUMNS}
          FROM scans s JOIN organizations o ON o.id = s.org_id LEFT JOIN domains d ON d.id = s.domain_id
          WHERE (%(q)s = '' OR d.domain ILIKE %(like)s OR o.name ILIKE %(like)s)
        ) x
        WHERE (%(state)s = '' OR x.state = %(state)s)
        ORDER BY x.created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    )
    return {"items": rows, "limit": limit, "offset": offset, "queue_delay_seconds": QUEUE_DELAY_SECONDS}


@router.get("/scans/{scan_id}")
def scan_detail(scan_id: str, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    scan_id = _uuid(scan_id)
    _view(request, owner, "scan", "scan", scan_id)
    scan = execute_one(
        f"""
        SELECT {_SCAN_COLUMNS}, s.error_message, s.execution_phase, s.claim_generation,
               s.stage_progress->'scoring'->'coverage' AS coverage
        FROM scans s JOIN organizations o ON o.id = s.org_id LEFT JOIN domains d ON d.id = s.domain_id
        WHERE s.id = %s
        """,
        (scan_id,),
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")
    stages = _rows(
        """
        SELECT key AS stage, value->>'status' AS status, value->>'error' AS error,
               (value->>'duration_ms')::bigint AS duration_ms, (value->>'items')::int AS items
        FROM jsonb_each((SELECT stage_progress FROM scans WHERE id = %s))
        WHERE jsonb_typeof(value) = 'object'
        ORDER BY key
        """,
        (scan_id,),
    )
    hosts = _rows(
        """
        SELECT DISTINCT ON (r.stage) r.stage, r.raw_data->'attempted_hosts' AS attempted_hosts,
               r.raw_data->'failed_hosts' AS failed_hosts, r.raw_data->'omitted_hosts' AS omitted_hosts
        FROM scan_results r WHERE r.scan_id = %s
        ORDER BY r.stage, r.attempt_generation DESC NULLS LAST, r.created_at DESC
        """,
        (scan_id,),
    )
    return {"scan": scan, "stages": stages, "hosts": hosts}


# ── Logs ───────────────────────────────────────────────────────────────────
@router.get("/logs")
def logs(request: Request, source: str = "customer", q: str = "", limit: int = Query(100, ge=1, le=200),
         offset: int = Query(0, ge=0, le=100000),
         owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    if source not in ("customer", "owner"):
        raise HTTPException(status_code=400, detail="Unknown log source.")
    _view(request, owner, "logs", metadata={"source": source, **({"q": q[:100]} if q else {})})
    params = {"q": q.strip(), "like": _like(q), "limit": limit, "offset": offset}
    if source == "owner":
        rows = _rows(
            """
            SELECT created_at, action, outcome, actor_email, target_type, target_id, ip, metadata
            FROM owner_audit
            WHERE (%(q)s = '' OR action ILIKE %(like)s OR actor_email ILIKE %(like)s OR outcome ILIKE %(like)s)
            ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
    else:
        rows = _rows(
            """
            SELECT a.created_at, a.action, a.resource_type, a.resource_id, a.metadata,
                   o.id AS org_id, o.name AS org_name, p.id AS user_id, p.email AS user_email
            FROM audit_log a
            LEFT JOIN organizations o ON o.id = a.org_id
            LEFT JOIN profiles p ON p.id = a.user_id
            WHERE (%(q)s = '' OR a.action ILIKE %(like)s OR p.email ILIKE %(like)s OR o.name ILIKE %(like)s)
            ORDER BY a.created_at DESC LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
    return {"source": source, "items": rows, "limit": limit, "offset": offset}


# ── System ─────────────────────────────────────────────────────────────────
@router.get("/system")
def system(request: Request, owner: Dict[str, Any] = Depends(owner_mod.require_owner)) -> Dict[str, Any]:
    _view(request, owner, "system")
    started = time.monotonic()
    db_ok = bool((execute_one("SELECT 1 AS ok") or {}).get("ok"))
    db_ms = round((time.monotonic() - started) * 1000, 1)
    scanner = execute_one(
        """
        SELECT max(started_at) AS last_scan_started_at, max(completed_at) AS last_scan_completed_at,
               count(*) FILTER (WHERE status = 'running') AS running,
               count(*) FILTER (WHERE status = 'queued') AS queued
        FROM scans
        """
    ) or {}
    crons = _rows(
        "SELECT cron_name, run_day, status, claimed_at, finished_at FROM cron_runs ORDER BY claimed_at DESC NULLS LAST LIMIT 14"
    )
    return {
        "database": {"ok": db_ok, "latency_ms": db_ms},
        "background": background_status(),
        "deploy": {"commit": (os.getenv("RENDER_GIT_COMMIT") or "")[:7] or None,
                   "service": os.getenv("RENDER_SERVICE_NAME") or None},
        "scanner": scanner,
        "scheduled_runs": crons,
        "integrations": {"email": bool(BREVO_API_KEY),
                         "ai": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))},
    }
