"""
Cyphward Members API Router (spec §8, §34)
GET    /members
POST   /members/invite
PATCH  /members/{user_id}

Invitations link an existing account (matched by email) to the organization
with a role: owner | admin | member. Invitees without a profile get a row now;
/auth/register adopts that row on signup so the membership survives.
The invitee also receives an invitation email (Brevo) — delivery outcome is
returned to the caller as `email_sent`.
"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Dict, Any, List, Optional

from backend.app.core.config import FRONTEND_URL
from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import (
    get_current_org,
    get_current_user,
    require_admin,
    log_audit,
    membership_role,
)
from backend.app.services.mailer import (
    generate_invite_email_html,
    generate_invite_email_text,
    send_email_async,
)

logger = logging.getLogger("cyphward.members")

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
async def invite_member(
    req: InviteMemberRequest,
    org: Dict[str, Any] = Depends(require_admin),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    role = (req.role or "member").lower().strip()
    if role not in MVP_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'. Must be one of {sorted(MVP_ROLES)}")
    if role == "owner" and membership_role(org) != "owner":
        raise HTTPException(status_code=403, detail="Only owners can grant the owner role")

    email_clean = req.email.strip().lower()
    invitee_name = req.full_name.strip()
    user_row = execute_one("SELECT id FROM profiles WHERE email = %s", (email_clean,))
    if not user_row:
        # Profile row is created now; when this email registers via
        # /auth/register the row is adopted (same id → membership intact).
        user_row = execute_one(
            "INSERT INTO profiles (email, full_name, role) VALUES (%s, %s, %s) RETURNING id",
            (email_clean, invitee_name, invitee_name),
        )

    execute_one(
        """
        INSERT INTO organization_members (user_id, org_id, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, org_id) DO UPDATE SET role = EXCLUDED.role
        RETURNING id
        """,
        (user_row["id"], org["id"], role),
    )

    inviter_name = (user.get("full_name") or user.get("email") or "A teammate").strip()
    org_name = (org.get("name") or "your workspace").strip()
    subject = f"{inviter_name.split(' ')[0]} invited you to {org_name} on Cyphward"
    accept_url = f"{FRONTEND_URL}/login"
    email_sent = False
    try:
        result = await send_email_async(
            email_clean,
            subject,
            generate_invite_email_html(inviter_name, invitee_name, email_clean, org_name, role, accept_url),
            generate_invite_email_text(inviter_name, invitee_name, email_clean, org_name, role, accept_url),
            recipient_name=invitee_name,
        )
        email_sent = bool(result and result.get("success"))
    except Exception:
        logger.exception(f"Invite email to {email_clean} failed (org={org['id']})")

    log_audit(org["id"], org.get("current_user_id"), "member.invited", "profile", str(user_row["id"]),
              {"email": email_clean, "role": role, "email_sent": email_sent})
    message = (
        f"Invite sent to {email_clean}."
        if email_sent
        else f"Member {email_clean} added, but the invitation email failed to send."
    )
    return {
        "message": message,
        "member": {"email": email_clean, "full_name": invitee_name, "role": role},
        "email_sent": email_sent,
    }


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
