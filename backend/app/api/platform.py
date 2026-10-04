"""Internal platform-support routes (review P1 — workspace authorization).

Read-only operations console start: service health, tenant lookup, and
overdue-scan triage. Every route requires a live `platform_staff` grant
(an org owner/admin WITHOUT a grant gets 403), tenant-touching routes
require a support `reason`, and every such access writes an immutable
`audit_log` event. Responses carry counts/identifiers only — never scan
evidence or member personal data.
"""
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.database import execute_one, execute_query
from backend.app.core.platform import (
    PLATFORM_READ,
    audit_platform_action,
    require_platform_staff,
)

router = APIRouter(prefix="/api/v1/platform", tags=["Platform"])

REASON = Query(
    ...,
    min_length=8,
    max_length=280,
    description="Support reason for touching tenant data (recorded in audit).",
)


@router.get("/health")
def platform_health(
    staff: Dict[str, Any] = Depends(require_platform_staff(PLATFORM_READ)),
) -> Dict[str, Any]:
    started = time.perf_counter()
    execute_one("SELECT 1")
    db_ms = round((time.perf_counter() - started) * 1000, 1)
    last_run = execute_one(
        """
        SELECT run_day, status FROM cron_runs
        WHERE cron_name = 'daily-scans' AND status = 'completed'
        ORDER BY run_day DESC LIMIT 1
        """
    )
    active = execute_one(
        "SELECT count(*) AS n FROM scans WHERE status IN ('queued', 'running')"
    )
    return {
        "database": {"connected": True, "roundtrip_ms": db_ms},
        "daily_scans_last_completed": (last_run or {}).get("run_day"),
        "scans_active": (active or {}).get("n", 0),
    }


@router.get("/tenants/{org_id}")
def tenant_lookup(
    org_id: str,
    reason: str = REASON,
    staff: Dict[str, Any] = Depends(require_platform_staff(PLATFORM_READ)),
) -> Dict[str, Any]:
    org = execute_one(
        """
        SELECT id, name, slug, plan, created_at FROM organizations
        WHERE id = %s::uuid
        """,
        (org_id,),
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    members = execute_one(
        "SELECT count(*) AS n FROM organization_members WHERE org_id = %s",
        (org_id,),
    )
    domains = execute_one(
        "SELECT count(*) AS n FROM domains WHERE org_id = %s", (org_id,)
    )
    active_scans = execute_one(
        "SELECT count(*) AS n FROM scans WHERE org_id = %s AND status IN ('queued', 'running')",
        (org_id,),
    )
    audit_platform_action(
        staff, str(org["id"]), "platform.tenant_lookup", "organization",
        str(org["id"]), reason,
    )
    return {
        "id": str(org["id"]),
        "name": org["name"],
        "slug": org["slug"],
        "plan": org["plan"],
        "created_at": str(org["created_at"]),
        "member_count": (members or {}).get("n", 0),
        "domain_count": (domains or {}).get("n", 0),
        "active_scan_count": (active_scans or {}).get("n", 0),
    }


@router.get("/scans/overdue")
def overdue_scans(
    reason: str = REASON,
    limit: int = Query(50, ge=1, le=200),
    staff: Dict[str, Any] = Depends(require_platform_staff(PLATFORM_READ)),
) -> Dict[str, Any]:
    rows = execute_query(
        """
        SELECT s.id, s.org_id, o.name AS org_name, s.status,
               s.created_at, s.lease_expires_at
        FROM scans s JOIN organizations o ON o.id = s.org_id
        WHERE s.status IN ('queued', 'running')
          AND (s.lease_expires_at IS NULL OR s.lease_expires_at < now())
        ORDER BY s.created_at ASC
        LIMIT %s
        """,
        (limit,),
    )
    items = [
        {
            "id": str(r["id"]),
            "org_id": str(r["org_id"]),
            "org_name": r["org_name"],
            "status": r["status"],
            "created_at": str(r["created_at"]),
            "lease_expires_at": (
                str(r["lease_expires_at"]) if r["lease_expires_at"] else None
            ),
        }
        for r in (rows or [])
    ]
    audit_platform_action(
        staff, None, "platform.overdue_scans", "scan", None, reason,
    )
    return {"count": len(items), "scans": items}
