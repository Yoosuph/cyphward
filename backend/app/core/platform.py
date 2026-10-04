"""Platform-staff authorization gate (review P1 — workspace authorization).

Organization roles (owner/admin/member) NEVER grant platform rights: every
internal support path requires a separate, time-boxed row in
`platform_staff`, checked here. Tenant-data endpoints additionally require
a support `reason`, and every grant check outcome that touches tenant data
is recorded in the append-only `audit_log`.
"""
from typing import Any, Callable, Dict

from fastapi import Depends, HTTPException

from backend.app.core.auth import get_current_user, log_audit
from backend.app.core.database import execute_one

PLATFORM_READ = "platform:read"


def active_grant(user_id: str) -> Dict[str, Any] | None:
    """Newest live platform grant for a user (revoked/expired rows excluded)."""
    return execute_one(
        """
        SELECT id, scopes FROM platform_staff
        WHERE user_id = %s
          AND revoked_at IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id,),
    )


def require_platform_staff(*required_scopes: str) -> Callable:
    """Dependency factory — e.g. Depends(require_platform_staff(PLATFORM_READ))."""

    def dependency(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if not user.get("email_verified_at"):
            raise HTTPException(
                status_code=403,
                detail="Platform access requires a verified email address.",
            )
        grant = active_grant(str(user["id"]))
        if not grant:
            raise HTTPException(status_code=403, detail="Platform access required.")
        have = set(grant.get("scopes") or [])
        missing = [s for s in required_scopes if s not in have]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing platform scope: {', '.join(missing)}.",
            )
        return {"user": user, "grant": grant, "scopes": sorted(have)}

    return dependency


def audit_platform_action(
    staff: Dict[str, Any],
    org_id: str | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    reason: str,
) -> None:
    """Immutable audit event for a staff tenant-data read/action."""
    user = staff["user"]
    log_audit(
        org_id,
        str(user["id"]),
        action,
        resource_type,
        resource_id,
        {"reason": reason, "scopes": staff["scopes"]},
    )
