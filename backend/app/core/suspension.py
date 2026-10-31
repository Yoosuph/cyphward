"""Organisation suspension, enforced for customers (admin phase 2, docs/admin-phase2-2026-10-31/README.md).

The rule the founder approved:

* A suspended organisation can still sign in and read its own data: dashboards, scans, findings, reports and the
  compliance views. Read endpoints are unchanged.
* It cannot add or extend anything: no new scan (manual, scheduled or re-check), no domain added or verified, no
  settings, no member invited, promoted or re-added, no compliance record created or changed, no new reviewer
  access, no document generated or approved, no pack or snapshot issued, no subscription change that adds cost.
* Protective changes stay open (founder decision, 2026-10-31): cancelling the subscription, revoking reviewer
  access, withdrawing a pending invitation and lowering a member's role. Promotions are refused in the role-change
  handler (api/members.py), since the same route also lowers roles.
* An owner of a suspended organisation cannot create a new organisation (`refuse_suspended_owner`); people who own
  no suspended organisation are unaffected.
* Scheduled scans and scans already waiting in the queue pause. Their rows stay and they run again once the
  suspension is lifted.
* Owner console actions are never blocked.

Every customer write route takes one of the gate dependencies below (`require_active_org` or a role gate built on
it). `test_suspension_gate.py` walks every POST/PUT/PATCH/DELETE route under /api/v1 and fails if one neither uses
a gate nor sits on its short, reviewed allow-list, so a new route cannot forget the check.

The refusal is HTTP 403 with a stable code and reviewed wording, shaped like the billing refusal the frontend
already reads: {"detail": {"code": "organization_suspended", "message": "..."}}.
"""
from typing import Any, Callable, Dict, Iterable, Optional, Set

from fastapi import Depends, HTTPException

from backend.app.core.auth import get_current_org, get_current_user, membership_role
from backend.app.core.database import execute_one

SUSPENDED_CODE = "organization_suspended"
# Reviewed wording. Plain English, no claim language (test_suspension_gate.py).
SUSPENDED_MESSAGE = (
    "This organisation is suspended, so changes are paused. You can still sign in and read your dashboards, "
    "scans, findings, reports and compliance pages. To ask about it, contact us at info@cyphward.com or through "
    "the contact page."
)


# Reviewed wording for the new-organisation refusal (same stable code).
SUSPENDED_OWNER_MESSAGE = (
    "An organisation you own is suspended, so you cannot create a new one for now. To ask about it, contact us at "
    "info@cyphward.com or through the contact page."
)


def suspended_refusal() -> HTTPException:
    return HTTPException(status_code=403, detail={"code": SUSPENDED_CODE, "message": SUSPENDED_MESSAGE})


def is_suspended(org_id: Any) -> bool:
    """True when the organisation's suspension row says 'suspended'. No row means active."""
    if not org_id:
        return False
    row = execute_one("SELECT status FROM organization_suspensions WHERE org_id = %s", (str(org_id),))
    return bool(row) and row.get("status") == "suspended"


def suspended_ids(org_ids: Iterable[Any]) -> Set[str]:
    """The suspended organisations among `org_ids`, in one query (for the sign-in bootstrap)."""
    ids = [str(i) for i in org_ids if i]
    if not ids:
        return set()
    from backend.app.core.database import execute_query
    rows = execute_query(
        "SELECT org_id FROM organization_suspensions WHERE status = 'suspended' AND org_id = ANY(%s::uuid[])",
        (ids,),
    ) or []
    return {str(r["org_id"]) for r in rows}


def ensure_active(org_id: Any) -> None:
    """Refuse (403, organization_suspended) when the organisation is suspended."""
    if is_suspended(org_id):
        raise suspended_refusal()


def suspension_gate(fn: Callable) -> Callable:
    """Mark a dependency as a suspension gate. The route-enumeration test looks for this marker."""
    fn.__suspension_gate__ = True
    return fn


@suspension_gate
def require_active_org(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    """The caller's organisation, refused with 403 when it is suspended. Use on every customer write route."""
    ensure_active(org.get("id"))
    return org


@suspension_gate
def refuse_suspended_owner(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """For creating a new organisation: refused (403, organization_suspended) when the person owns any suspended
    organisation, so a suspension cannot be stepped around with a fresh workspace."""
    row = execute_one(
        "SELECT 1 AS owns FROM organization_members m JOIN organization_suspensions os ON os.org_id = m.org_id "
        "WHERE m.user_id = %s AND m.role = 'owner' AND os.status = 'suspended' LIMIT 1",
        (str(user["id"]),),
    )
    if row:
        raise HTTPException(status_code=403, detail={"code": SUSPENDED_CODE, "message": SUSPENDED_OWNER_MESSAGE})
    return user


def require_active_role(*roles: str) -> Callable:
    """Role gate for write routes: the role check of core.auth.require_role, on an active organisation."""
    allowed = tuple(r.lower() for r in roles)

    @suspension_gate
    def dependency(org: Dict[str, Any] = Depends(require_active_org)) -> Dict[str, Any]:
        if membership_role(org) not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return org

    return dependency


require_active_admin = require_active_role("owner", "admin")
require_active_owner = require_active_role("owner")


def is_gate(call: Optional[Callable]) -> bool:
    return bool(getattr(call, "__suspension_gate__", False))
