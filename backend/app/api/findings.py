"""
Cyphward Findings API Router
Delivers categorized vulnerability findings, evidence, and lifecycle management.
Statuses: open | acknowledged | in_progress | resolved (spec §23).
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import get_current_org, require_admin, log_audit

router = APIRouter(prefix="/api/v1/findings", tags=["Findings"])


class UpdateStatusRequest(BaseModel):
    status: str  # 'open', 'acknowledged', 'in_progress', 'resolved'


@router.get("")
def list_findings(
    severity: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    asset_id: Optional[str] = None,
    search: Optional[str] = None,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """Retrieve normalized findings with rich evidence filters."""

    query = """
        SELECT f.*, a.hostname, a.ip_address, a.asset_type
        FROM findings f
        LEFT JOIN assets a ON f.asset_id = a.id
        WHERE f.org_id = %s
    """
    params = [org["id"]]

    if severity:
        query += " AND f.severity = %s"
        params.append(severity.lower())
    if category:
        query += " AND f.category = %s"
        params.append(category)
    if status:
        query += " AND f.status = %s"
        params.append(status.lower())
    if asset_id:
        query += " AND f.asset_id = %s"
        params.append(asset_id)
    if search:
        query += " AND (f.title ILIKE %s OR f.description ILIKE %s OR a.hostname ILIKE %s)"
        params.append(f"%{search}%")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    query += """
        ORDER BY
            CASE f.severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
                ELSE 5
            END,
            f.created_at DESC
    """

    findings = execute_query(query, tuple(params))

    cat_counts = execute_query("""
        SELECT category, count(*) as count
        FROM findings
        WHERE org_id = %s AND status != 'resolved'
        GROUP BY category
    """, (org["id"],))

    return {
        "findings": findings,
        "total": len(findings),
        "categories": {c["category"]: c["count"] for c in cat_counts}
    }


@router.get("/{finding_id}")
def get_finding_detail(
    finding_id: str,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """Retrieve deep finding detail (org-scoped) with evidence records."""
    finding = execute_one("""
        SELECT f.*, a.hostname, a.ip_address, a.asset_type, a.technologies, a.tls_info,
               d.domain as parent_domain
        FROM findings f
        LEFT JOIN assets a ON f.asset_id = a.id
        LEFT JOIN domains d ON a.domain_id = d.id
        WHERE f.id = %s AND f.org_id = %s
    """, (finding_id, org["id"]))

    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")

    evidence = execute_query(
        "SELECT id, type, data, created_at FROM finding_evidence WHERE finding_id = %s AND org_id = %s ORDER BY created_at ASC",
        (finding_id, org["id"]),
    )

    finding["evidence_records"] = evidence
    return finding


@router.patch("/{finding_id}/status")
def update_finding_status(
    finding_id: str,
    req: UpdateStatusRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Update finding lifecycle status (admin/owner only; org-scoped)."""
    valid_statuses = {"open", "acknowledged", "in_progress", "resolved"}
    st = req.status.lower().strip()
    if st not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status '{st}'. Must be one of {sorted(valid_statuses)}")

    existing = execute_one(
        "SELECT id, status FROM findings WHERE id = %s AND org_id = %s",
        (finding_id, org["id"]),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Finding not found.")

    updated = execute_one("""
        UPDATE findings
        SET status = %s,
            resolved_at = CASE WHEN %s = 'resolved' THEN now() ELSE NULL END,
            updated_at = now()
        WHERE id = %s AND org_id = %s
        RETURNING *;
    """, (st, st, finding_id, org["id"]))

    log_audit(org["id"], org.get("current_user_id"), f"finding.{st}", "finding", finding_id,
              {"from": existing["status"], "to": st})

    return {
        "message": f"Finding status updated to '{st}'.",
        "finding": updated
    }
