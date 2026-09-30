"""
Cyphward Authentication & Tenant Authorization (spec §6, §7, §8, §35).

Flow:
    Authorization: Bearer <Supabase access token>
        -> verify JWT (HS256 secret or Supabase JWKS)
        -> upsert profile (id = auth sub)
        -> resolve organization membership (server-derived, never trusted from client)
        -> optional X-Organization-Id selects among the user's memberships (verified)
        -> role (owner/admin/member) available for RBAC checks

There is NO fallback organization. Requests without a valid membership fail closed.
"""
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Query
from jwt import PyJWKClient

from backend.app.core.config import SUPABASE_JWT_SECRET, SUPABASE_URL
from backend.app.core.database import execute_one

_JWKS_CLIENT: Optional[PyJWKClient] = None


def _verify_token(token: str) -> Dict[str, Any]:
    """Verify a Supabase Auth access token and return its claims."""
    errors: List[str] = []

    if SUPABASE_JWT_SECRET:
        try:
            return jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            errors.append(f"HS256: {exc}")

    if SUPABASE_URL:
        global _JWKS_CLIENT
        try:
            if _JWKS_CLIENT is None:
                _JWKS_CLIENT = PyJWKClient(f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json")
            signing_key = _JWKS_CLIENT.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            errors.append(f"RS256: {exc}")
        except Exception as exc:  # network / JWKS fetch failure
            errors.append(f"JWKS: {exc}")

    raise HTTPException(
        status_code=401,
        detail="Authentication is not configured on the server."
        if not errors
        else f"Invalid token ({'; '.join(errors)})",
    )


def get_current_user(
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Verify the Supabase JWT and return (creating if needed) the caller's profile."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    claims = _verify_token(authorization.split(" ", 1)[1].strip())
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")

    email = (claims.get("email") or "").strip().lower()
    meta = claims.get("user_metadata") or {}
    full_name = (meta.get("full_name") or meta.get("name") or email or "Cyphward User").strip()

    profile = execute_one(
        """
        INSERT INTO profiles (id, email, full_name, role)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE
            SET email = COALESCE(EXCLUDED.email, profiles.email),
                full_name = COALESCE(EXCLUDED.full_name, profiles.full_name),
                updated_at = now()
        RETURNING *
        """,
        (user_id, email or None, full_name, "Member"),
    )
    if not profile:
        raise HTTPException(status_code=500, detail="Failed to load profile")
    return profile


def get_current_org(
    user: Dict[str, Any] = Depends(get_current_user),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
    org_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """
    Resolve the caller's organization from their memberships.

    X-Organization-Id / org_id may select among the caller's own organizations
    (UUID or slug) but is verified against organization_members — it can never
    grant access to a tenant the user does not belong to.
    """
    target = (x_organization_id or org_id or "").strip() or None

    if target:
        org = execute_one(
            """
            SELECT o.*, m.role AS membership_role, %s::uuid AS current_user_id
            FROM organization_members m
            JOIN organizations o ON o.id = m.org_id
            WHERE m.user_id = %s
              AND (o.id::text = %s OR o.slug = %s)
            LIMIT 1
            """,
            (user["id"], user["id"], target, target),
        )
        if not org:
            raise HTTPException(status_code=403, detail="Not a member of the requested organization")
        return org

    memberships = execute_query_memberships(user["id"])
    if not memberships:
        raise HTTPException(status_code=403, detail="No organization membership")
    if len(memberships) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple organizations: specify X-Organization-Id",
        )
    return memberships[0]


def execute_query_memberships(user_id: str) -> List[Dict[str, Any]]:
    from backend.app.core.database import execute_query

    return (
        execute_query(
            """
            SELECT o.*, m.role AS membership_role, %s::uuid AS current_user_id
            FROM organization_members m
            JOIN organizations o ON o.id = m.org_id
            WHERE m.user_id = %s
            ORDER BY o.created_at ASC
            """,
            (user_id, user_id),
        )
        or []
    )


def membership_role(org: Dict[str, Any]) -> str:
    return (org.get("membership_role") or "member").lower()


def require_role(*roles: str) -> Callable:
    """RBAC dependency factory — e.g. Depends(require_role('owner', 'admin'))."""

    allowed = tuple(r.lower() for r in roles)

    def dependency(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
        if membership_role(org) not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return org

    return dependency


# Common role gates (spec §8)
require_member = get_current_org  # any member may read
require_admin = require_role("owner", "admin")
require_owner = require_role("owner")


def log_audit(
    org_id: Optional[str],
    user_id: Optional[str],
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort audit trail write (spec §39)."""
    import json
    import logging

    logger = logging.getLogger("cyphward.audit")
    try:
        execute_one(
            """
            INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (org_id, user_id, action, resource_type, resource_id, json.dumps(metadata or {}, default=str)),
        )
    except Exception as e:
        logger.warning(f"Failed to write audit log ({action}): {e}")
