"""
Cyphward Scans API Router
Orchestrates asynchronous security scans against VERIFIED domains only (spec §40).
Scanners never receive arbitrary targets — the backend resolves and authorizes scope.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json

from backend.app.core.database import execute_one, execute_query
from backend.app.core.config import SCANNER_MODE
from backend.app.workflows.inngest_workflow import execute_scan_pipeline, inngest_client
from backend.app.core.auth import get_current_org, require_admin, log_audit
from shared.contracts import empty_stage_progress
import inngest

router = APIRouter(prefix="/api/v1/scans", tags=["Scans"])


class LaunchScanRequest(BaseModel):
    domain_id: Optional[str] = None


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
    org: Dict[str, Any] = Depends(require_admin)
) -> Dict[str, Any]:
    """
    Launch an end-to-end security scan against a VERIFIED domain owned by this org.
    There is no bypass for unverified domains (spec §40).
    """
    org_id = org["id"]

    if req.domain_id:
        domain = execute_one(
            "SELECT * FROM domains WHERE id = %s AND org_id = %s",
            (req.domain_id, org_id),
        )
        if not domain:
            raise HTTPException(status_code=404, detail="Domain not found.")
    else:
        domain = execute_one(
            "SELECT * FROM domains WHERE org_id = %s AND verification_status = 'verified' ORDER BY created_at ASC LIMIT 1",
            (org_id,),
        )
        if not domain:
            raise HTTPException(
                status_code=400,
                detail="No verified domain found. Add and verify a domain before scanning.",
            )

    if domain["verification_status"] != "verified":
        raise HTTPException(
            status_code=403,
            detail=f"Domain {domain['domain']} is not verified. Please verify DNS TXT ownership before initiating scans.",
        )

    stage_progress = empty_stage_progress()

    new_scan = execute_one("""
        INSERT INTO scans (org_id, domain_id, scan_type, status, current_stage, stage_progress)
        VALUES (%s, %s, 'EXTERNAL_ASSESSMENT', 'queued', 'queued', %s::jsonb)
        RETURNING *;
    """, (org_id, domain["id"], json.dumps(stage_progress)))

    scan_id = str(new_scan["id"])

    # Exactly-once dispatch: the queued row is always the job record.
    # local:  Inngest event, with a local background task only as fallback
    #         when the event gateway is unavailable (never both).
    # remote: the scanner worker claims the row over outbound HTTPS — never
    #         run recon in-process; the Inngest event is informational only.
    remote = SCANNER_MODE == "remote"
    dispatched = False
    try:
        await inngest_client.send(inngest.Event(name="scan.requested", data={
            "version": 1,
            "scan_id": scan_id,
            "organization_id": str(org_id),
            "domain_id": str(domain["id"]),
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
              {"domain": domain["domain"], "dispatch": dispatch_kind})

    return {
        "message": f"Scan queued for {domain['domain']}.",
        "scan": new_scan,
        "domain": domain["domain"],
        "dispatch": dispatch_kind,
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

    execute_query("""
        UPDATE scans
        SET status = 'cancelled', completed_at = now()
        WHERE id = %s AND org_id = %s
    """, (scan_id, org["id"]))

    log_audit(org["id"], org.get("current_user_id"), "scan.cancelled", "scan", scan_id)
    return {"message": "Scan cancelled."}
