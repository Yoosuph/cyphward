"""
Cyphward Settings API Router
Organization profile settings. Team membership lives in /api/v1/members (spec §34).
Auth is handled by our own accounts (password + Google) — no API keys (spec §6).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import get_current_org, require_admin, log_audit, membership_role

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])


class UpdateCompanyRequest(BaseModel):
    name: Optional[str] = None
    cac_rc: Optional[str] = None
    sector: Optional[str] = None


@router.get("")
def get_settings(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """Retrieve organization profile, membership role, and team roster."""
    members = execute_query("""
        SELECT p.id, p.email, p.full_name, p.role AS job_title, m.role, m.created_at
        FROM profiles p
        JOIN organization_members m ON m.user_id = p.id
        WHERE m.org_id = %s
        ORDER BY m.created_at ASC
    """, (org["id"],))

    return {
        "organization": {
            "id": org["id"],
            "name": org["name"],
            "slug": org["slug"],
            "cac_rc": org.get("cac_rc"),
            "sector": org.get("sector"),
            "plan": org.get("plan"),
            "created_at": org["created_at"],
        },
        "membership": {
            "role": membership_role(org),
            "user_id": org.get("current_user_id"),
        },
        "members": members,
    }


@router.post("/company")
def update_company(
    req: UpdateCompanyRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Update organization profile (admin/owner only). Whitelisted columns only."""
    updates = []
    params: List[Any] = []
    if req.name:
        updates.append("name = %s")
        params.append(req.name.strip())
    if req.cac_rc:
        updates.append("cac_rc = %s")
        params.append(req.cac_rc.strip())
    if req.sector:
        updates.append("sector = %s")
        params.append(req.sector.strip())

    if not updates:
        return {"message": "No updates provided."}

    params.append(org["id"])
    sql = f"UPDATE organizations SET {', '.join(updates)}, updated_at = now() WHERE id = %s RETURNING *"
    updated_org = execute_one(sql, tuple(params))

    log_audit(org["id"], org.get("current_user_id"), "org.profile_updated", "organization", org["id"])

    return {
        "message": "Organization profile updated successfully.",
        "organization": updated_org
    }
