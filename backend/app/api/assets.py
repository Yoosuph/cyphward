"""
Cyphward Assets API Router
Exposes discovered subdomains, IPs, asset types, technology stacks, and security telemetry.
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Dict, Any, Optional
from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import get_current_org

router = APIRouter(prefix="/api/v1/assets", tags=["Assets"])


@router.get("")
def list_assets(
    domain_id: Optional[str] = None,
    asset_type: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """List assets with filtering and pagination."""

    query = """
        SELECT a.*, d.domain as parent_domain,
               COUNT(f.id) as findings_count,
               COUNT(CASE WHEN f.severity IN ('critical', 'high') AND f.status = 'open' THEN 1 END) as critical_findings_count
        FROM assets a
        LEFT JOIN domains d ON a.domain_id = d.id
        LEFT JOIN findings f ON f.asset_id = a.id
        WHERE a.org_id = %s
    """
    params = [org["id"]]

    if domain_id:
        query += " AND a.domain_id = %s"
        params.append(domain_id)
    if asset_type:
        query += " AND a.asset_type = %s"
        params.append(asset_type)
    if status:
        query += " AND a.status = %s"
        params.append(status)
    if search:
        query += " AND (a.hostname ILIKE %s OR a.ip_address ILIKE %s)"
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    query += " GROUP BY a.id, d.domain ORDER BY a.last_seen DESC"

    assets = execute_query(query, tuple(params))
    return {
        "assets": assets,
        "total": len(assets)
    }


@router.get("/{asset_id}")
def get_asset_detail(
    asset_id: str,
    org: Dict[str, Any] = Depends(get_current_org),
) -> Dict[str, Any]:
    """Retrieve full technical asset profile and associated findings (org-scoped)."""
    asset = execute_one("""
        SELECT a.*, d.domain as parent_domain
        FROM assets a
        LEFT JOIN domains d ON a.domain_id = d.id
        WHERE a.id = %s AND a.org_id = %s
    """, (asset_id, org["id"]))

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found.")

    findings = execute_query("""
        SELECT id, title, description, severity, category, status, evidence, remediation, created_at
        FROM findings
        WHERE asset_id = %s AND org_id = %s
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
                ELSE 5
            END
    """, (asset_id, org["id"]))

    return {
        "asset": asset,
        "findings": findings
    }
