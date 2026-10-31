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
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Query, Request

from backend.app.core.config import ACCESS_TOKEN_TTL_SECONDS, AUTH_JWT_SECRET
from backend.app.core.database import execute_one


ACCESS_TOKEN_TYPE = "access"

# POST routes that only read: they interpret existing evidence and write no customer record (AI use is only
# metered in rate_limits). The public demo allows them, and a suspended organisation keeps them
# (test_suspension_gate.py).
READ_ONLY_POSTS = frozenset({"/api/v1/ai/explain", "/api/v1/ai/remediate", "/api/v1/ai/executive-summary",
                             "/api/v1/ai/chat", "/api/v1/ai/chat/stream"})


def issue_access_token(profile: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """Mint a Cyphward access token for a profile row.

    `sid` binds the token to its auth_sessions row so every authenticated
    request can check revocation (logout / password reset) — issued access
    JWTs stop working the moment the session is revoked.
    """
    now = int(time.time())
    claims = {
        "typ": ACCESS_TOKEN_TYPE,
        "sub": str(profile["id"]),
        "email": (profile.get("email") or "").strip().lower(),
        "full_name": (profile.get("full_name") or "").strip(),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
    }
    if session_id:
        claims["sid"] = str(session_id)
    if profile.get("session_demo_org_id"):
        claims["demo_org_id"] = str(profile["session_demo_org_id"])
    return jwt.encode(claims, AUTH_JWT_SECRET, algorithm="HS256")


def _verify_token(token: str) -> Dict[str, Any]:
    """Verify a Cyphward access token and return its claims.

    Other artifacts are signed with the same secret (the sign-in step-up
    challenge, the Google OAuth state). They carry a `purpose` claim and must
    never authenticate an API call: a step-up challenge used as a bearer token
    would skip the second factor. Access tokens carry typ=access; tokens minted
    before that claim existed are accepted until they expire (they still need
    a live session, checked in get_current_user).
    """
    if not AUTH_JWT_SECRET:
        raise HTTPException(status_code=401, detail="Authentication is not configured on the server.")
    try:
        claims = jwt.decode(
            token,
            AUTH_JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token ({exc})")
    if claims.get("purpose") is not None or claims.get("typ", ACCESS_TOKEN_TYPE) != ACCESS_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid token (not an access token)")
    return claims


def get_current_user(
    authorization: Optional[str] = Header(None),
    request: Request = None,
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
    # Every access token is bound to a live auth_sessions row of the same user.
    sid = claims.get("sid")
    if not _is_uuid(sid):
        raise HTTPException(status_code=401, detail="Session expired — sign in again.")

    profile = execute_one(
        """
        SELECT p.*, s.id AS session_id, s.revoked_at AS session_revoked_at, s.expires_at AS session_expires_at
        FROM profiles p
        JOIN auth_sessions s ON s.id = %s::uuid AND s.user_id = p.id
        WHERE p.id = %s
        """,
        (sid, user_id),
    )
    if not profile:
        # Profile deleted, unknown session, or a session of another user —
        # never resurrect anything from claims.
        raise HTTPException(status_code=401, detail="Session no longer valid — sign in again.")
    if profile.get("session_revoked_at") is not None:
        raise HTTPException(status_code=401, detail="Session expired — sign in again.")
    expires_at = profile.get("session_expires_at")
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Session expired — sign in again.")
    if "demo_org_id" in claims:
        if not _is_uuid(claims["demo_org_id"]):
            raise HTTPException(status_code=401, detail="Invalid public demo session.")
        profile = {**profile, "session_demo_org_id": str(claims["demo_org_id"])}
        from backend.app.core.demo_org import public_demo_session_valid
        if not public_demo_session_valid(profile, profile["session_demo_org_id"]):
            raise HTTPException(status_code=401, detail="The public demo session has ended.")
        # These POSTs interpret existing evidence. All account/workspace mutations
        # are refused, including routes that do not use organisation role gates.
        if request and request.method not in {"GET", "HEAD", "OPTIONS"} and not (
            request.method == "POST" and request.url.path in READ_ONLY_POSTS
        ):
            raise HTTPException(status_code=403, detail="The public demo is view-only. Create your own account to make changes.")
    return profile


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return bool(value)
    except (TypeError, ValueError):
        return False


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
              AND NOT EXISTS (SELECT 1 FROM organization_suspensions os
                              WHERE os.org_id = o.id AND os.status = 'deleted')
            LIMIT 1
            """,
            (user["id"], user["id"], target, target),
        )
        if not org:
            if _member_of_deleted(user["id"], target):
                raise HTTPException(status_code=404, detail=DELETED_ORG_NOT_FOUND)
            raise HTTPException(status_code=403, detail="Not a member of the requested organization")
        if user.get("session_demo_org_id"):
            if str(org["id"]) != str(user["session_demo_org_id"]):
                raise HTTPException(status_code=403, detail="The demo session is restricted to its workspace.")
            org = {**org, "membership_role": "member", "demo_session": True}
        return org

    memberships = session_memberships(user)
    if not memberships:
        if not user.get("session_demo_org_id") and _member_of_deleted(user["id"]):
            raise HTTPException(status_code=404, detail=DELETED_ORG_NOT_FOUND)
        raise HTTPException(status_code=403, detail="No organization membership")
    if len(memberships) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple organizations: specify X-Organization-Id",
        )
    return memberships[0]


# A deleted organisation (owner console, core/suspension.py) is left out of every membership query above, so a
# customer can neither sign in to it nor select it. Asking for it by id or slug, or having no other organisation,
# answers 404 rather than describing it.
DELETED_ORG_NOT_FOUND = "Organization not found."


def _member_of_deleted(user_id: Any, target: Optional[str] = None) -> bool:
    from backend.app.core.database import execute_query

    rows = execute_query(
        """
        SELECT 1 AS deleted_member FROM organization_members m
        JOIN organizations o ON o.id = m.org_id
        JOIN organization_suspensions os ON os.org_id = o.id AND os.status = 'deleted'
        WHERE m.user_id = %s AND (%s::text IS NULL OR o.id::text = %s OR o.slug = %s)
        LIMIT 1
        """,
        (user_id, target, target, target),
    )
    return bool(rows)


def session_memberships(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    memberships = execute_query_memberships(user["id"])
    scope = user.get("session_demo_org_id")
    if scope:
        return [{**org, "membership_role": "member", "demo_session": True}
                for org in memberships if str(org["id"]) == str(scope)]
    return memberships


def execute_query_memberships(user_id: str) -> List[Dict[str, Any]]:
    from backend.app.core.database import execute_query

    return (
        execute_query(
            """
            SELECT o.*, m.role AS membership_role, %s::uuid AS current_user_id
            FROM organization_members m
            JOIN organizations o ON o.id = m.org_id
            WHERE m.user_id = %s
              AND NOT EXISTS (SELECT 1 FROM organization_suspensions os
                              WHERE os.org_id = o.id AND os.status = 'deleted')
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
    from backend.app.core.execution_fence import ClaimLost

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
    except ClaimLost:
        raise
    except Exception as e:
        logger.warning(f"Failed to write audit log ({action}): {e}")
