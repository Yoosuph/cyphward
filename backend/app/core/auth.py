"""
Cyphward Authentication & Tenant Authorization (spec §6, §7, §8, §35).

Flow:
    Authorization: Bearer <Cyphward access token>
        -> verify our own HS256 JWT (AUTH_JWT_SECRET)
        -> load/create the profile (id = token sub)
        -> resolve organization membership (server-derived, never trusted from client)
        -> optional X-Organization-Id selects among the user's memberships (verified)
        -> role (owner/admin/member) available for RBAC checks

There is NO fallback organization. Requests without a valid membership fail closed.
"""
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Query

from backend.app.core.config import ACCESS_TOKEN_TTL_SECONDS, AUTH_JWT_SECRET
from backend.app.core.database import execute_one


def issue_access_token(profile: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """Mint a Cyphward access token for a profile row.

    `sid` binds the token to its auth_sessions row so every authenticated
    request can check revocation (logout / password reset) — issued access
    JWTs stop working the moment the session is revoked.
    """
    now = int(time.time())
    claims = {
        "sub": str(profile["id"]),
        "email": (profile.get("email") or "").strip().lower(),
        "full_name": (profile.get("full_name") or "").strip(),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
    }
    if session_id:
        claims["sid"] = str(session_id)
    return jwt.encode(claims, AUTH_JWT_SECRET, algorithm="HS256")


def _verify_token(token: str) -> Dict[str, Any]:
    """Verify a Cyphward access token and return its claims."""
    if not AUTH_JWT_SECRET:
        raise HTTPException(status_code=401, detail="Authentication is not configured on the server.")
    try:
        return jwt.decode(
            token,
            AUTH_JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token ({exc})")


def get_current_user(
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Verify the Cyphward JWT and return the caller's profile.

    Single roundtrip: the profile lookup also joins the token's auth_sessions
    row (sid claim) so a revoked session invalidates the access token
    immediately. A missing profile is a hard 401 — we never re-create profile
    rows from token claims (a deleted account must stay deleted).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    claims = _verify_token(authorization.split(" ", 1)[1].strip())
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    sid = claims.get("sid")  # absent on tokens issued before session binding

    profile = execute_one(
        """
        SELECT p.*, s.revoked_at AS session_revoked_at
        FROM profiles p
        LEFT JOIN auth_sessions s ON s.id = NULLIF(%s, '')::uuid
        WHERE p.id = %s
        """,
        (sid or None, user_id),
    )
    if not profile:
        # Profile deleted (or orphaned token) — do NOT resurrect it from claims.
        raise HTTPException(status_code=401, detail="Session no longer valid — sign in again.")
    if profile.get("session_revoked_at") is not None:
        raise HTTPException(status_code=401, detail="Session expired — sign in again.")
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
