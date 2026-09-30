"""
Cyphward Remediation API Router (spec §27, §28, §34)
Task lifecycle: OPEN -> IN_PROGRESS -> READY_FOR_VERIFICATION -> VERIFIED;
VERIFICATION failure transitions the task to REOPENED.

Verification re-checks the live asset — the platform never blindly trusts a
user's "fixed" claim.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_org, log_audit, require_admin
from backend.app.core.database import execute_one, execute_query
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.security_checks import run_security_checks
from backend.app.services.notifications import notify

router = APIRouter(prefix="/api/v1/remediation", tags=["Remediation"])

STATUSES = {"open", "in_progress", "ready_for_verification", "verified", "reopened"}
PRIORITIES = {"low", "medium", "high", "critical"}


class CreateTaskRequest(BaseModel):
    finding_id: Optional[str] = None
    title: str = Field(min_length=3, max_length=300)
    instructions: Optional[str] = None
    assignee_id: Optional[str] = None
    priority: Optional[str] = "medium"
    due_date: Optional[date] = None


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    instructions: Optional[str] = None
    assignee_id: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[date] = None


@router.get("")
def list_tasks(
    status: Optional[str] = None,
    finding_id: Optional[str] = None,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    query = """
        SELECT t.*, f.title AS finding_title, f.severity, f.status AS finding_status,
               p.full_name AS assignee_name, p.email AS assignee_email
        FROM remediation_tasks t
        LEFT JOIN findings f ON f.id = t.finding_id
        LEFT JOIN profiles p ON p.id = t.assignee_id
        WHERE t.org_id = %s
    """
    params: List[Any] = [org["id"]]
    if status:
        query += " AND t.status = %s"
        params.append(status.lower())
    if finding_id:
        query += " AND t.finding_id = %s"
        params.append(finding_id)
    query += """
        ORDER BY CASE t.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                 WHEN 'medium' THEN 3 ELSE 4 END,
                 t.created_at DESC
    """
    tasks = execute_query(query, tuple(params)) or []
    return {"tasks": tasks, "total": len(tasks)}


@router.post("", status_code=201)
def create_task(req: CreateTaskRequest, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    priority = (req.priority or "medium").lower()
    if priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority '{priority}'")

    if req.finding_id:
        finding = execute_one(
            "SELECT id, title FROM findings WHERE id = %s AND org_id = %s",
            (req.finding_id, org["id"]),
        )
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found in this organization.")

    if req.assignee_id:
        member = execute_one(
            "SELECT user_id FROM organization_members WHERE user_id = %s AND org_id = %s",
            (req.assignee_id, org["id"]),
        )
        if not member:
            raise HTTPException(status_code=400, detail="Assignee is not a member of this organization.")

    task = execute_one(
        """
        INSERT INTO remediation_tasks
            (org_id, finding_id, title, instructions, assignee_id, priority, due_date, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (org["id"], req.finding_id, req.title.strip(), req.instructions, req.assignee_id,
         priority, req.due_date, org.get("current_user_id")),
    )
    log_audit(org["id"], org.get("current_user_id"), "remediation.created", "remediation_task",
              str(task["id"]), {"finding_id": req.finding_id})
    return {"task": task}


@router.get("/{task_id}")
def get_task(task_id: str, org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    task = execute_one(
        """
        SELECT t.*, f.title AS finding_title, f.description AS finding_description,
               f.severity, f.status AS finding_status, f.remediation AS finding_instructions,
               a.hostname, p.full_name AS assignee_name, p.email AS assignee_email
        FROM remediation_tasks t
        LEFT JOIN findings f ON f.id = t.finding_id
        LEFT JOIN assets a ON a.id = f.asset_id
        LEFT JOIN profiles p ON p.id = t.assignee_id
        WHERE t.id = %s AND t.org_id = %s
        """,
        (task_id, org["id"]),
    )
    if not task:
        raise HTTPException(status_code=404, detail="Remediation task not found.")
    return {"task": task}


@router.patch("/{task_id}")
def update_task(
    task_id: str,
    req: UpdateTaskRequest,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    existing = execute_one(
        "SELECT id, status, assignee_id FROM remediation_tasks WHERE id = %s AND org_id = %s",
        (task_id, org["id"]),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Remediation task not found.")

    updates: List[str] = []
    params: List[Any] = []

    if req.title is not None:
        updates.append("title = %s")
        params.append(req.title.strip())
    if req.instructions is not None:
        updates.append("instructions = %s")
        params.append(req.instructions)
    if req.priority is not None:
        if req.priority.lower() not in PRIORITIES:
            raise HTTPException(status_code=400, detail=f"Invalid priority '{req.priority}'")
        updates.append("priority = %s")
        params.append(req.priority.lower())
    if req.due_date is not None:
        updates.append("due_date = %s")
        params.append(req.due_date)
    if req.assignee_id is not None:
        member = execute_one(
            "SELECT user_id FROM organization_members WHERE user_id = %s AND org_id = %s",
            (req.assignee_id, org["id"]),
        )
        if not member:
            raise HTTPException(status_code=400, detail="Assignee is not a member of this organization.")
        updates.append("assignee_id = %s")
        params.append(req.assignee_id)

    if req.status is not None:
        st = req.status.lower().strip()
        if st not in STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status '{st}'. Must be one of {sorted(STATUSES)}")
        if st == "verified":
            raise HTTPException(
                status_code=400,
                detail="Use POST /remediation/{id}/verify — verification requires a live recheck.",
            )
        updates.append("status = %s")
        params.append(st)

    if not updates:
        task = execute_one("SELECT * FROM remediation_tasks WHERE id = %s", (task_id,))
        return {"task": task}

    updates.append("updated_at = now()")
    params.extend([task_id, org["id"]])
    task = execute_one(
        f"UPDATE remediation_tasks SET {', '.join(updates)} WHERE id = %s AND org_id = %s RETURNING *",
        tuple(params),
    )
    log_audit(org["id"], org.get("current_user_id"), "remediation.updated", "remediation_task", task_id,
              {"status": req.status} if req.status else {})
    return {"task": task}


@router.post("/{task_id}/verify")
async def verify_task(task_id: str, org: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """
    Recheck a READY_FOR_VERIFICATION task against the live asset (spec §28).
    Pass -> task VERIFIED + finding RESOLVED. Fail -> task REOPENED.
    """
    task = execute_one(
        """
        SELECT t.*, f.id AS f_id, f.title AS f_title, f.asset_id, f.status AS f_status
        FROM remediation_tasks t
        JOIN findings f ON f.id = t.finding_id
        WHERE t.id = %s AND t.org_id = %s
        """,
        (task_id, org["id"]),
    )
    if not task:
        raise HTTPException(status_code=404, detail="Remediation task with linked finding not found.")
    if task["status"] not in ("ready_for_verification", "reopened", "in_progress", "open"):
        raise HTTPException(status_code=400, detail=f"Task in status '{task['status']}' cannot be verified.")

    asset = execute_one(
        "SELECT hostname, domain_id FROM assets WHERE id = %s AND org_id = %s",
        (task["asset_id"], org["id"]),
    )
    if not asset or not asset.get("hostname"):
        raise HTTPException(status_code=400, detail="Linked asset missing — cannot recheck.")

    hostname = asset["hostname"]
    try:
        dns_data = await resolve_host_dns(hostname)
        http_data = await probe_http_service(hostname)
        fresh = await run_security_checks(hostname, dns_data or {}, http_data or {}, is_apex=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Recheck failed: {exc}")

    target_title = (task["f_title"] or "").strip().lower()
    reproduced = any((f.get("title") or "").strip().lower() == target_title for f in fresh)

    if reproduced:
        updated_task = execute_one(
            """
            UPDATE remediation_tasks
            SET status = 'reopened', updated_at = now()
            WHERE id = %s AND org_id = %s
            RETURNING *
            """,
            (task_id, org["id"]),
        )
        execute_one(
            """
            UPDATE findings SET status = 'open', resolved_at = NULL, last_seen_at = now(), updated_at = now()
            WHERE id = %s AND org_id = %s
            """,
            (task["f_id"], org["id"]),
        )
        notify(org["id"], "finding_reopened",
               f"Reopened: {task['f_title']}",
               f"Recheck against {hostname} shows the issue still exists.",
               "high", "/findings")
        log_audit(org["id"], org.get("current_user_id"), "remediation.recheck_failed",
                  "remediation_task", task_id, {"hostname": hostname})
        return {
            "result": "reopened",
            "message": f"Recheck failed — {task['f_title']} still reproduces on {hostname}.",
            "task": updated_task,
        }

    updated_task = execute_one(
        """
        UPDATE remediation_tasks
        SET status = 'verified', verified_at = now(), updated_at = now()
        WHERE id = %s AND org_id = %s
        RETURNING *
        """,
        (task_id, org["id"]),
    )
    execute_one(
        """
        UPDATE findings SET status = 'resolved', resolved_at = now(), last_seen_at = now(), updated_at = now()
        WHERE id = %s AND org_id = %s
        """,
        (task["f_id"], org["id"]),
    )
    notify(org["id"], "finding_resolved",
           f"Resolved: {task['f_title']}",
           f"Recheck against {hostname} confirms the issue is fixed.",
           "info", "/findings")
    log_audit(org["id"], org.get("current_user_id"), "remediation.verified",
              "remediation_task", task_id, {"hostname": hostname})
    return {
        "result": "verified",
        "message": f"Recheck passed — {task['f_title']} no longer reproduces on {hostname}.",
        "task": updated_task,
    }
