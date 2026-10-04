"""
Cyphward Organizations API Router (spec §34)
POST   /organizations
GET    /organizations
GET    /organizations/current
PATCH  /organizations/current
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from backend.app.core.database import execute_one, execute_query
from backend.app.core.auth import get_current_user, get_current_org, require_admin, require_owner, log_audit, membership_role
from backend.app.core.plans import (
    DEFAULT_PLAN,
    entitlements_for,
    parse_plan,
    usage_for_org,
)
from backend.app.services.notifications import slugify

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


def json_safe(value: Any) -> Any:
    """Recursively stringify datetimes/UUIDs for the export bundle."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


class CreateOrganizationRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: Optional[str] = None
    cac_rc: Optional[str] = None
    sector: Optional[str] = None
    plan: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    cac_rc: Optional[str] = None
    sector: Optional[str] = None
    plan: Optional[str] = None


class CloseOrganizationRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=160)


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

    # The onboarding plan selector is a real plan now — validated against
    # the server allowlist, never stored as sector (review P1 line 33).
    plan = parse_plan(req.plan) if req.plan is not None else DEFAULT_PLAN

    org = execute_one(
        """
        INSERT INTO organizations (name, slug, cac_rc, sector, plan)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (req.name.strip(), slug, req.cac_rc, req.sector or "Technology", plan),
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

    log_audit(org["id"], user["id"], "org.created", "organization", str(org["id"]), {"slug": slug, "plan": plan})
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
        "plan_entitlements": entitlements_for(org),
        "plan_usage": usage_for_org(str(org["id"])),
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
    old_plan = (org.get("plan") or "").strip().lower()
    new_plan = parse_plan(req.plan) if req.plan is not None else None
    if new_plan is not None and new_plan != old_plan:
        updates.append("plan = %s")
        params.append(new_plan)

    if not updates:
        return {"organization": get_current_organization(org)}

    params.append(org["id"])
    updated = execute_one(
        f"UPDATE organizations SET {', '.join(updates)}, updated_at = now() WHERE id = %s RETURNING *",
        tuple(params),
    )
    log_audit(org["id"], org.get("current_user_id"), "org.updated", "organization", org["id"],
              ({"plan_from": old_plan, "plan_to": new_plan} if new_plan is not None and new_plan != old_plan else None))
    return {"organization": updated, "role": membership_role(org)}


@router.get("/export")
def export_organization(org: Dict[str, Any] = Depends(require_owner)) -> JSONResponse:
    """Owner-only full workspace export (data-portability right, review P2).

    One JSON bundle: organization, members, domains, assets, findings,
    scans, score snapshots, reports and invitations. Secret material
    (password hashes, tokens, session material) is never included.
    """
    org_id = org["id"]
    members = execute_query(
        """
        SELECT m.role, m.created_at, p.email, p.full_name
        FROM organization_members m JOIN profiles p ON p.id = m.user_id
        WHERE m.org_id = %s ORDER BY m.created_at ASC
        """,
        (org_id,),
    )
    domains = execute_query(
        "SELECT id, domain, verification_status, verified_at, created_at "
        "FROM domains WHERE org_id = %s ORDER BY created_at ASC",
        (org_id,),
    )
    assets = execute_query(
        "SELECT id, hostname, ip_address, asset_type, status, last_seen "
        "FROM assets WHERE org_id = %s ORDER BY hostname ASC",
        (org_id,),
    )
    findings = execute_query(
        "SELECT id, asset_id, title, description, severity, category, status, "
        "evidence, remediation, created_at, resolved_at "
        "FROM findings WHERE org_id = %s ORDER BY created_at ASC",
        (org_id,),
    )
    scans = execute_query(
        "SELECT id, domain_id, status, score, started_at, completed_at, created_at "
        "FROM scans WHERE org_id = %s ORDER BY created_at ASC",
        (org_id,),
    )
    snapshots = execute_query(
        "SELECT id, score, created_at FROM score_snapshots WHERE org_id = %s "
        "ORDER BY created_at ASC",
        (org_id,),
    )
    reports = execute_query(
        "SELECT id, domain_id, title, status, summary, created_at FROM reports "
        "WHERE org_id = %s ORDER BY created_at ASC",
        (org_id,),
    )
    invites = execute_query(
        "SELECT email, full_name, role, accepted_at, revoked_at, created_at "
        "FROM organization_invites WHERE org_id = %s ORDER BY created_at ASC",
        (org_id,),
    )
    bundle = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organization": {
            "id": str(org["id"]), "name": org["name"], "slug": org["slug"],
            "cac_rc": org.get("cac_rc"), "sector": org.get("sector"),
            "plan": org.get("plan"), "created_at": str(org.get("created_at")),
        },
        "members": members or [],
        "domains": domains or [],
        "assets": assets or [],
        "findings": findings or [],
        "scans": scans or [],
        "score_snapshots": snapshots or [],
        "reports": reports or [],
        "invitations": invites or [],
    }
    log_audit(org_id, org.get("current_user_id"), "org.exported", "organization", str(org_id))
    return JSONResponse(
        content=json_safe(bundle),
        headers={"Content-Disposition": f'attachment; filename="cyphward-{org["slug"]}-export.json"'},
    )


@router.post("/close")
def close_organization(
    req: CloseOrganizationRequest,
    org: Dict[str, Any] = Depends(require_owner),
) -> Dict[str, Any]:
    """Owner-only workspace closure (right to be forgotten, review P2).

    The typed slug guards against accidents. One DELETE cascades the whole
    tenant subtree (members, domains, assets, findings, scans, reports,
    invites, tenant audit rows — all ON DELETE CASCADE); a tombstone audit
    with NULL org_id is written first so the closure itself stays on record.
    Profiles and sessions are untouched: closing a workspace is not account
    deletion (see the privacy policy for account deletion).
    """
    if req.slug.strip() != org["slug"]:
        raise HTTPException(
            status_code=400,
            detail=f"Type the workspace slug '{org['slug']}' to confirm closure.",
        )
    log_audit(None, org.get("current_user_id"), "org.closed", "organization", str(org["id"]),
              {"slug": org["slug"], "name": org["name"]})
    deleted = execute_one(
        "DELETE FROM organizations WHERE id = %s RETURNING id", (org["id"],)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return {"closed": True, "org_id": str(org["id"])}
