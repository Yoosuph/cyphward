"""
Cyphward Scans API Router
Orchestrates asynchronous security scans against VERIFIED domains only (spec §40).
Scanners never receive arbitrary targets — the backend resolves and authorizes scope.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from uuid import UUID

from backend.app.core.database import execute_one, execute_query
from backend.app.core.config import SCANNER_MODE
from backend.app.workflows.inngest_workflow import execute_scan_pipeline, inngest_client
from backend.app.core.auth import get_current_org, require_admin, log_audit
from backend.app.core.scan_admission import admit_scan, AdmissionConflict
import inngest

router = APIRouter(prefix="/api/v1/scans", tags=["Scans"])


class LaunchScanRequest(BaseModel):
    domain_id: Optional[UUID] = None


@router.get("")
def list_scans(org: Dict[str, Any] = Depends(get_current_org)) -> List[Dict[str, Any]]:
    """List historical and active security scans."""

    scans = execute_query("""
        SELECT s.*, d.domain,
               COUNT(f.id) as findings_discovered
        FROM scans s
        JOIN domains d ON s.domain_id = d.id
        LEFT JOIN findings f ON f.scan_id = s.id
        WHERE s.org_id = %s
        GROUP BY s.id, d.domain
        ORDER BY s.created_at DESC
    """, (org["id"],))

    return scans


@router.get("/{scan_id}")
def get_scan_detail(
    scan_id: str,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """Retrieve detailed scan status and live multi-stage tracker (org-scoped)."""
    scan = execute_one("""
        SELECT s.*, d.domain,
               COUNT(f.id) as findings_discovered
        FROM scans s
        JOIN domains d ON s.domain_id = d.id
        LEFT JOIN findings f ON f.scan_id = s.id
        WHERE s.id = %s AND s.org_id = %s
        GROUP BY s.id, d.domain
    """, (scan_id, org["id"]))

    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")

    raw_results = execute_query("""
        SELECT stage, raw_data, created_at
        FROM scan_results
        WHERE scan_id = %s
        ORDER BY created_at ASC
    """, (scan_id,))

    targets = execute_query("""
        SELECT hostname, ip_address, status, first_seen, last_seen
        FROM scan_targets
        WHERE scan_id = %s
        ORDER BY hostname ASC
    """, (scan_id,))

    return {
        "scan": scan,
        "raw_results": raw_results,
        "targets": targets,
    }


@router.post("/launch")
async def launch_scan(
    req: LaunchScanRequest,
    background_tasks: BackgroundTasks,
    org: Dict[str, Any] = Depends(require_admin),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> Dict[str, Any]:
    """
    Launch an end-to-end security scan against a VERIFIED domain owned by this org.
    There is no bypass for unverified domains (spec §40).
    """
    org_id = str(org["id"])
    try:
        admission = admit_scan(
            org_id,
            str(req.domain_id) if req.domain_id else None,
            request_scope=f"user:{org.get('current_user_id') or 'unknown'}",
            request_key=idempotency_key,
        )
    except AdmissionConflict as conflict:
        return JSONResponse(status_code=409, content={
            "detail": conflict.message,
            "code": conflict.code,
            **({"scan_id": conflict.scan_id} if conflict.scan_id else {}),
        })

    if admission.outcome == "quota":
        raise HTTPException(status_code=402, detail=(
            f"Scans quota reached for the {admission.plan_label} plan "
            f"({admission.used}/{admission.limit} this month). Upgrade or contact support."
        ))
    if admission.outcome == "active":
        return JSONResponse(status_code=409, content={
            "detail": f"A scan is already queued or running for {admission.domain}.",
            "code": "scan_already_active",
            "scan_id": str(admission.scan["id"]),
        })

    new_scan = admission.scan
    domain_name = admission.domain
    scan_id = str(new_scan["id"])

    # Persisted replay returns the original job and never dispatches it again.
    if admission.outcome == "replayed":
        return {
            "message": f"Existing scan returned for {domain_name}.",
            "scan": new_scan,
            "domain": domain_name,
            "dispatch": "replayed",
            "replayed": True,
        }

    # Admission is committed before dispatch. This makes retries return the
    # same job; it does not guarantee exactly-once execution after crashes.
    # local: Inngest event, with a background task only as fallback.
    # remote: the worker claims the durable queued row; never run recon here.
    remote = SCANNER_MODE == "remote"
    dispatched = False
    try:
        await inngest_client.send(inngest.Event(name="scan.requested", data={
            "version": 1,
            "scan_id": scan_id,
            "organization_id": str(org_id),
            "domain_id": str(new_scan["domain_id"]),
        }))
        dispatched = True
    except Exception as e:
        import logging
        logging.getLogger("cyphward.scans").warning(
            f"Inngest dispatch failed for scan {scan_id}: {e}"
        )
        dispatched = False

    if remote:
        dispatch_kind = "scanner_queue"
    elif not dispatched:
        background_tasks.add_task(execute_scan_pipeline, scan_id)
        dispatch_kind = "local"
    else:
        dispatch_kind = "inngest"

    log_audit(org_id, org.get("current_user_id"), "scan.started", "scan", scan_id,
              {"domain": domain_name, "dispatch": dispatch_kind})

    return {
        "message": f"Scan queued for {domain_name}.",
        "scan": new_scan,
        "domain": domain_name,
        "dispatch": dispatch_kind,
        "replayed": False,
    }


@router.post("/{scan_id}/cancel")
def cancel_scan(
    scan_id: str,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Cancel an active or queued scan (admin/owner only; org-scoped)."""
    scan = execute_one(
        "SELECT * FROM scans WHERE id = %s AND org_id = %s",
        (scan_id, org["id"]),
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")

    if scan["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Scan is already {scan['status']}.")

    # Conditional cancel: only an active scan may transition to cancelled,
    # so a completion racing this request can never be overwritten.
    # Clearing the lease also fences any worker that already holds the job
    # (its next progress/complete/fail call gets 409 and aborts).
    cancelled = execute_one("""
        UPDATE scans
        SET status = 'cancelled', completed_at = now(),
            claimed_by = NULL, lease_expires_at = NULL
        WHERE id = %s AND org_id = %s AND status IN ('queued', 'running')
        RETURNING id
    """, (scan_id, org["id"]))
    if not cancelled:
        fresh = execute_one(
            "SELECT status FROM scans WHERE id = %s AND org_id = %s",
            (scan_id, org["id"]),
        )
        status = (fresh or {}).get("status", "unknown")
        raise HTTPException(status_code=400, detail=f"Scan is already {status}.")

    log_audit(org["id"], org.get("current_user_id"), "scan.cancelled", "scan", scan_id)
    return {"message": "Scan cancelled."}
