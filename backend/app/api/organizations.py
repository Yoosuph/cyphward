"""
Cyphward Organizations API Router (spec §34)
POST   /organizations
GET    /organizations
GET    /organizations/current
PATCH  /organizations/current
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import get_current_user, get_current_org, require_admin, log_audit, membership_role
from backend.app.services.notifications import slugify

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


class CreateOrganizationRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: Optional[str] = None
    cac_rc: Optional[str] = None
    sector: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    cac_rc: Optional[str] = None
    sector: Optional[str] = None


@router.get("")
def list_my_organizations(user: Dict[str, Any] = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """List organizations the caller belongs to."""
    return (
        execute_query(
            """
            SELECT o.id, o.name, o.slug, o.sector, o.plan, m.role
            FROM organization_members m
            JOIN organizations o ON o.id = m.org_id
            WHERE m.user_id = %s
            ORDER BY o.created_at ASC
            """,
            (user["id"],),
        )
        or []
    )


@router.post("", status_code=201)
def create_organization(
    req: CreateOrganizationRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create an organization; the caller becomes its OWNER (spec §8, §9)."""
    if not user.get("email_verified_at"):
        raise HTTPException(status_code=403, detail="Verify your email address first.")

    base_slug = slugify(req.slug or req.name)
    slug = base_slug
    suffix = 1
    while execute_one("SELECT id FROM organizations WHERE slug = %s", (slug,)):
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    org = execute_one(
        """
        INSERT INTO organizations (name, slug, cac_rc, sector)
        VALUES (%s, %s, %s, %s)
        RETURNING *
        """,
        (req.name.strip(), slug, req.cac_rc, req.sector or "Technology"),
    )

    execute_one(
        """
        INSERT INTO organization_members (user_id, org_id, role)
        VALUES (%s, %s, 'owner')
        ON CONFLICT (user_id, org_id) DO UPDATE SET role = 'owner'
        RETURNING id
        """,
        (user["id"], org["id"]),
    )

    log_audit(org["id"], user["id"], "org.created", "organization", str(org["id"]), {"slug": slug})
    return {"organization": org, "role": "owner"}


@router.get("/current")
def get_current_organization(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """Return the active organization context and the caller's role."""
    return {
        "id": org["id"],
        "name": org["name"],
        "slug": org["slug"],
        "cac_rc": org.get("cac_rc"),
        "sector": org.get("sector"),
        "plan": org.get("plan"),
        "created_at": org.get("created_at"),
        "role": membership_role(org),
        "user_id": org.get("current_user_id"),
    }


@router.patch("/current")
def update_current_organization(
    req: UpdateOrganizationRequest,
    org: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Update the active organization profile (admin/owner only; whitelisted columns)."""
    updates: List[str] = []
    params: List[Any] = []
    for col in ("name", "slug", "cac_rc", "sector"):
        val = getattr(req, col)
        if val is not None:
            updates.append(f"{col} = %s")
            params.append(val.strip() if isinstance(val, str) else val)

    if not updates:
        return {"organization": get_current_organization(org)}

    params.append(org["id"])
    updated = execute_one(
        f"UPDATE organizations SET {', '.join(updates)}, updated_at = now() WHERE id = %s RETURNING *",
        tuple(params),
    )
    log_audit(org["id"], org.get("current_user_id"), "org.updated", "organization", org["id"])
    return {"organization": updated, "role": membership_role(org)}
