"""
Cyphward Remediation API Router (spec §27, §28, §34)
Task lifecycle: OPEN -> IN_PROGRESS -> READY_FOR_VERIFICATION -> VERIFIED;
VERIFICATION failure transitions the task to REOPENED.

Verification re-checks the live asset with the detector/rule that produced
the finding — the platform never blindly trusts a user's "fixed" claim, and
when the recheck can't produce proof it returns INCONCLUSIVE instead of
closing the finding.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_org, log_audit, require_admin
from backend.app.core.database import execute_one, execute_query
from backend.app.scanner.dns_resolver import resolve_host_dns
from backend.app.scanner.http_probe import probe_http_service
from backend.app.scanner.nuclei_runner import run_nuclei_template
from backend.app.scanner.security_checks import run_security_checks
from backend.app.services.notifications import notify

router = APIRouter(prefix="/api/v1/remediation", tags=["Remediation"])

STATUSES = {"open", "in_progress", "ready_for_verification", "verified", "reopened"}
PRIORITIES = {"low", "medium", "high", "critical"}

# Categories the shared DNS/HTTP security-check detector can re-evaluate.
SHARED_CHECK_CATEGORIES = {
    "DNS & Email Security",
    "HTTP Headers",
    "SSL/TLS",
    "Exposure",
    "Information Disclosure",
    "Security Configuration",
}
DNS_ONLY_CATEGORIES = {"DNS & Email Security"}
HTTP_CATEGORIES = {"HTTP Headers", "SSL/TLS", "Information Disclosure", "Exposure"}


def _finding_detector(category: Optional[str], evidence: Any) -> Dict[str, Any]:
    """
    Classify which detector produced a finding so verification reruns that
    detector's rule — never a different one. Unknown detectors can only be
    re-checked by a fresh scan.
    """
    ev = evidence if isinstance(evidence, dict) else {}
    cat = (category or "").strip()
    if cat == "Nuclei Scan" or ev.get("template_id"):
        return {"name": "nuclei", "template_id": ev.get("template_id")}
    if cat in SHARED_CHECK_CATEGORIES:
        return {"name": "security_checks", "template_id": None}
    return {"name": "unknown", "template_id": None}


def _inconclusive(
    task: Dict[str, Any],
    org: Dict[str, Any],
    hostname: str,
    message: str,
    detector: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Recheck produced insufficient proof. The task keeps its current status
    and the finding stays open — we never mark a fix we could not observe.
    """
    log_audit(
        org["id"], org.get("current_user_id"), "remediation.recheck_inconclusive",
        "remediation_task", str(task["id"]),
        {"hostname": hostname, "detector": detector.get("name"),
         "template_id": detector.get("template_id"), "reason": message},
    )
    return {"result": "inconclusive", "message": message, "task": task}


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

    The recheck reruns the detector/rule that produced the finding:
      - shared DNS/HTTP security checks  -> rerun run_security_checks
      - Nuclei template                  -> rerun that exact template
      - anything else                    -> inconclusive (fresh scan needed)

    Pass -> task VERIFIED + finding RESOLVED. Fail -> task REOPENED.
    Insufficient proof (unreachable host, unavailable tool, unknown
    detector) -> INCONCLUSIVE: task and finding both stay as they are.
    """
    task = execute_one(
        """
        SELECT t.*, f.id AS f_id, f.title AS f_title, f.asset_id, f.status AS f_status,
               f.category AS f_category, f.evidence AS f_evidence
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
    detector = _finding_detector(task.get("f_category"), task.get("f_evidence"))

    # An unknown detector can't be rerun on demand — a fresh full scan is
    # the only honest way to re-check it.
    if detector["name"] == "unknown":
        return _inconclusive(
            task, org, hostname,
            f"Inconclusive — detector for category '{task.get('f_category') or 'unknown'}' "
            f"can't be rechecked on demand. Run a fresh scan to re-verify this finding.",
            detector,
        )

    try:
        dns_data = await resolve_host_dns(hostname) or {}
        http_data = await probe_http_service(hostname) or {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Recheck failed: {exc}")

    # A recheck is only conclusive if the probes actually observed the host.
    records = dns_data.get("records") or {}
    dns_ok = bool(dns_data.get("primary_ip")) or any(records.values())
    http_ok = http_data.get("http_status") is not None

    if detector["name"] == "nuclei":
        template_id = detector["template_id"]
        if not template_id:
            return _inconclusive(
                task, org, hostname,
                "Inconclusive — this Nuclei finding has no template id recorded, "
                "so its rule can't be rerun. Run a fresh scan to re-verify it.",
                detector,
            )
        if not http_ok:
            return _inconclusive(
                task, org, hostname,
                f"Inconclusive — {hostname} did not respond to the HTTP probe, so "
                f"template {template_id} couldn't be rerun. Try again later or run a fresh scan.",
                detector,
            )
        rerun = await run_nuclei_template(hostname, template_id, timeout=60)
        if not rerun.get("ok"):
            return _inconclusive(
                task, org, hostname,
                f"Inconclusive — couldn't rerun Nuclei template {template_id} on "
                f"{hostname}: {rerun.get('error')}. Run a fresh scan to re-verify it.",
                detector,
            )
        reproduced = any(
            (nf.get("evidence") or {}).get("template_id") == template_id
            for nf in rerun.get("findings") or []
        )
    else:
        # Shared security-check detector: the category must be observable
        # right now or the (possibly clean) result proves nothing.
        if task.get("f_category") in HTTP_CATEGORIES and not http_ok:
            return _inconclusive(
                task, org, hostname,
                f"Inconclusive — {hostname} did not respond to the HTTP probe, so "
                f"this check couldn't be re-evaluated. Try again later or run a fresh scan.",
                detector,
            )
        if task.get("f_category") in DNS_ONLY_CATEGORIES and not dns_ok:
            return _inconclusive(
                task, org, hostname,
                f"Inconclusive — DNS for {hostname} could not be resolved, so this "
                f"check couldn't be re-evaluated. Try again later or run a fresh scan.",
                detector,
            )
        try:
            fresh = await run_security_checks(hostname, dns_data, http_data, is_apex=True)
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
                  "remediation_task", task_id, {"hostname": hostname, "detector": detector["name"]})
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
              "remediation_task", task_id,
              {"hostname": hostname, "detector": detector["name"],
               "template_id": detector.get("template_id")})
    return {
        "result": "verified",
        "message": f"Recheck passed — {task['f_title']} no longer reproduces on {hostname}.",
        "task": updated_task,
    }
