"""
Cyphward Members API Router (spec §8, §34)
GET    /members
POST   /members/invite
PATCH  /members/{user_id}

MVP uses Supabase Auth — invitations link an existing Supabase account (by email)
to the organization with a role: owner | admin | member.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Dict, Any, List, Optional

from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import get_current_org, require_admin, log_audit, membership_role

router = APIRouter(prefix="/api/v1/members", tags=["Members"])

MVP_ROLES = {"owner", "admin", "member"}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: Optional[str] = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


@router.get("")
def list_members(org: Dict[str, Any] = Depends(get_current_org)) -> List[Dict[str, Any]]:
    return (
        execute_query(
            """
            SELECT p.id, p.email, p.full_name, p.role AS job_title, m.role, m.created_at
            FROM organization_members m
            JOIN profiles p ON p.id = m.user_id
            WHERE m.org_id = %s
            ORDER BY m.created_at ASC
            """,
            (org["id"],),
        )
        or []
    )


@router.post("/invite", status_code=201)
def invite_member(
    req: InviteMemberRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    role = (req.role or "member").lower().strip()
    if role not in MVP_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'. Must be one of {sorted(MVP_ROLES)}")
    if role == "owner" and membership_role(org) != "owner":
        raise HTTPException(status_code=403, detail="Only owners can grant the owner role")

    email_clean = req.email.strip().lower()
    user = execute_one("SELECT id FROM profiles WHERE email = %s", (email_clean,))
    if not user:
        # Profile row is created now; the person still registers via Supabase Auth
        # with this email and is linked on login via email match (upsert path in auth).
        user = execute_one(
            "INSERT INTO profiles (email, full_name, role) VALUES (%s, %s, %s) RETURNING id",
            (email_clean, req.full_name.strip(), req.full_name.strip()),
        )

    execute_one(
        """
        INSERT INTO organization_members (user_id, org_id, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, org_id) DO UPDATE SET role = EXCLUDED.role
        RETURNING id
        """,
        (user["id"], org["id"], role),
    )

    log_audit(org["id"], org.get("current_user_id"), "member.invited", "profile", str(user["id"]),
              {"email": email_clean, "role": role})
    return {"message": f"Member {email_clean} invited.", "member": {"email": email_clean, "full_name": req.full_name, "role": role}}


@router.patch("/{user_id}")
def update_member_role(
    user_id: str,
    req: UpdateMemberRoleRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    role = req.role.lower().strip()
    if role not in MVP_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'. Must be one of {sorted(MVP_ROLES)}")

    target = execute_one(
        "SELECT role FROM organization_members WHERE user_id = %s AND org_id = %s",
        (user_id, org["id"]),
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in this organization.")
    if (role == "owner" or target["role"] == "owner") and membership_role(org) != "owner":
        raise HTTPException(status_code=403, detail="Only owners can modify owner roles")

    execute_one(
        "UPDATE organization_members SET role = %s WHERE user_id = %s AND org_id = %s RETURNING id",
        (role, user_id, org["id"]),
    )
    log_audit(org["id"], org.get("current_user_id"), "member.role_changed", "profile", user_id,
              {"from": target["role"], "to": role})
    return {"message": "Member role updated.", "member_id": user_id, "role": role}
