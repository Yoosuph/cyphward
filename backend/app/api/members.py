"""
Cyphward Members API Router (spec §8, §34)
GET    /members
GET    /members/invites
POST   /members/invite
POST   /members/invites/accept
DELETE /members/invites/{invite_id}
PATCH  /members/{user_id}

Invitations are tokenized records: inviting stores a single-use, time-limited
token (only its hash is kept) and emails it to the invited address. No profile
and no membership is created up front — the membership row is created solely
by /members/invites/accept, which requires an authenticated account whose
email matches the invite and whose email is verified (review P0-2).
Role changes never ride on invitations; they go through PATCH /members/{id}.
"""
import logging
from datetime import datetime, timezone

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
from backend.app.core.security import hash_opaque_token, new_opaque_token
from backend.app.services.mailer import (
    generate_invite_email_html,
    generate_invite_email_text,
    send_email_async,
)

logger = logging.getLogger("cyphward.members")

router = APIRouter(prefix="/api/v1/members", tags=["Members"])

MVP_ROLES = {"owner", "admin", "member"}
INVITE_TTL_DAYS = 7


class InviteMemberRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: Optional[str] = "member"


class AcceptInviteRequest(BaseModel):
    token: str


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


@router.get("/invites")
def list_invites(org: Dict[str, Any] = Depends(require_admin)) -> List[Dict[str, Any]]:
    return (
        execute_query(
            """
            SELECT i.id, i.email, i.full_name, i.role, i.created_at, i.expires_at,
                   i.invited_by, p.full_name AS invited_by_name
            FROM organization_invites i
            LEFT JOIN profiles p ON p.id = i.invited_by
            WHERE i.org_id = %s AND i.accepted_at IS NULL AND i.revoked_at IS NULL
            ORDER BY i.created_at DESC
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

    # Invitations never modify an existing membership — role changes go
    # through PATCH. This also stops an admin from downgrading an owner by
    # re-inviting their address with a lesser role.
    existing_member = execute_one(
        """
        SELECT m.role FROM organization_members m
        JOIN profiles p ON p.id = m.user_id
        WHERE lower(p.email) = %s AND m.org_id = %s
        """,
        (email_clean, org["id"]),
    )
    if existing_member:
        raise HTTPException(
            status_code=409,
            detail=f"{email_clean} is already a member of this workspace.",
        )

    # Replace any outstanding invitation for this address: each send is a
    # fresh single-use token.
    execute_query(
        """
        DELETE FROM organization_invites
        WHERE org_id = %s AND lower(email) = %s AND accepted_at IS NULL AND revoked_at IS NULL
        """,
        (org["id"], email_clean),
    )
    token = new_opaque_token()
    invite_row = execute_one(
        f"""
        INSERT INTO organization_invites (org_id, email, full_name, role, token_hash, invited_by, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, now() + interval '{INVITE_TTL_DAYS} days')
        RETURNING id
        """,
        (org["id"], email_clean, invitee_name, role, hash_opaque_token(token), str(user["id"])),
    )
    if not invite_row:
        raise HTTPException(status_code=500, detail="Could not create the invitation.")

    inviter_name = (user.get("full_name") or user.get("email") or "A teammate").strip()
    org_name = (org.get("name") or "your workspace").strip()
    subject = f"{inviter_name.split(' ')[0]} invited you to {org_name} on Cyphward"
    accept_url = f"{FRONTEND_URL}/login?invite={token}"
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

    log_audit(org["id"], str(user["id"]), "member.invited", "invite", str(invite_row["id"]),
              {"email": email_clean, "role": role, "email_sent": email_sent})
    message = (
        f"Invite sent to {email_clean}."
        if email_sent
        else f"Invitation for {email_clean} saved, but the email failed to send."
    )
    return {
        "message": message,
        "member": {"email": email_clean, "full_name": invitee_name, "role": role},
        "email_sent": email_sent,
    }


@router.post("/invites/accept")
def accept_invite(
    req: AcceptInviteRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    token = (req.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing invitation token.")

    invite = execute_one(
        "SELECT * FROM organization_invites WHERE token_hash = %s",
        (hash_opaque_token(token),),
    )
    if not invite:
        raise HTTPException(status_code=400, detail="This invitation link is not valid.")
    if invite.get("revoked_at"):
        raise HTTPException(status_code=400, detail="This invitation was cancelled.")
    if invite.get("accepted_at"):
        raise HTTPException(status_code=409, detail="This invitation has already been used.")

    expires_at = invite.get("expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at:
            raise HTTPException(status_code=400, detail="This invitation has expired — ask for a new one.")

    # The invite binds to the invited mailbox: the accepting account must own
    # that exact address, and the address must be verified (OTP or Google).
    if (invite.get("email") or "").lower() != (user.get("email") or "").strip().lower():
        raise HTTPException(status_code=400, detail="This invitation was sent to a different email address.")
    if not user.get("email_verified_at"):
        raise HTTPException(status_code=403, detail="Verify your email address to join this workspace.")

    # Single-use consume first — conditional write, so a double submit can
    # never grant two memberships or re-open the token.
    consumed = execute_one(
        """
        UPDATE organization_invites
        SET accepted_at = now(), accepted_user_id = %s
        WHERE id = %s AND accepted_at IS NULL AND revoked_at IS NULL
        RETURNING id
        """,
        (str(user["id"]), str(invite["id"])),
    )
    if not consumed:
        raise HTTPException(status_code=409, detail="This invitation has already been used.")

    try:
        # DO NOTHING: an already-present membership keeps its current role —
        # accepting an invite can never escalate or downgrade anyone.
        execute_one(
            """
            INSERT INTO organization_members (user_id, org_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, org_id) DO NOTHING
            RETURNING id
            """,
            (str(user["id"]), invite["org_id"], invite["role"]),
        )
    except Exception:
        # Give the token back so a failed membership write can't strand the
        # invitee with a consumed invite and no membership.
        execute_one(
            """
            UPDATE organization_invites
            SET accepted_at = NULL, accepted_user_id = NULL
            WHERE id = %s AND accepted_user_id = %s AND accepted_at IS NOT NULL
            """,
            (str(invite["id"]), str(user["id"])),
        )
        logger.exception(f"Membership write failed for invite={invite['id']}")
        raise HTTPException(status_code=500, detail="Could not complete the invitation. Try again.")

    log_audit(invite["org_id"], str(user["id"]), "member.invite_accepted", "invite", str(invite["id"]),
              {"email": invite.get("email"), "role": invite.get("role")})
    return {
        "message": "Invitation accepted — welcome to the team.",
        "member": {"email": invite.get("email"), "role": invite.get("role")},
    }


@router.delete("/invites/{invite_id}")
def revoke_invite(
    invite_id: str,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    row = execute_one(
        """
        UPDATE organization_invites SET revoked_at = now()
        WHERE id = %s AND org_id = %s AND accepted_at IS NULL AND revoked_at IS NULL
        RETURNING id
        """,
        (invite_id, org["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    log_audit(org["id"], org.get("current_user_id"), "member.invite_revoked", "invite", invite_id, {})
    return {"message": "Invitation revoked."}


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

    # Never demote the last owner — the workspace would become unmanageable.
    if target["role"] == "owner" and role != "owner":
        owners = execute_one(
            "SELECT COUNT(*) AS n FROM organization_members WHERE org_id = %s AND role = 'owner'",
            (org["id"],),
        )
        if owners is None or int(owners.get("n") or 0) <= 1:
            raise HTTPException(status_code=403, detail="An organization must keep at least one owner.")

    # Never demote the last owner — and enforce it inside the UPDATE itself,
    # not with a separate read. Two concurrent demotes could both pass a
    # read-then-write owner count; this single statement locks the org's
    # owner rows (ordered, deadlock-free) and refuses when the target would
    # be the last one left (review P1: preserve at least one owner
    # transactionally). The read above stays as a fast path for a friendly
    # error message.
    demoted = execute_one(
        """
        WITH locked AS (
            SELECT user_id FROM organization_members
            WHERE org_id = %s AND role = 'owner'
            ORDER BY user_id
            FOR UPDATE
        )
        UPDATE organization_members m SET role = %s
         WHERE m.user_id = %s AND m.org_id = %s
           AND (m.role <> 'owner'
                OR %s = 'owner'
                OR (SELECT COUNT(*) FROM locked) > 1)
        RETURNING id
        """,
        (org["id"], role, user_id, org["id"], role),
    )
    if not demoted:
        raise HTTPException(status_code=403, detail="An organization must keep at least one owner.")
    log_audit(org["id"], org.get("current_user_id"), "member.role_changed", "profile", user_id,
              {"from": target["role"], "to": role})
    return {"message": "Member role updated.", "member_id": user_id, "role": role}
