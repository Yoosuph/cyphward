"""Owner console actions (stage 3): a few safe changes, each one recorded.

Every action:

* needs an owner console session *and* the exact console Origin
  (`require_owner_mutation`), so a bearer token or a cross-site form can't
  trigger it;
* takes a written reason (kept in the owner audit log only, never shown to
  the customer);
* runs in one transaction with its `owner_audit` row (who, why, before and
  after), so a change can't commit without its record and a failed change
  never leaves a "success" row. Refusals (unknown target, wrong state) are
  audited separately as `rejected`;
* also writes the customer's own activity log entry, attributed to
  "cyphward" rather than to the owner's account.

Actions: change an organization's plan, extend a trial, cancel a queued or
running scan, sign a user out everywhere.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

from backend.app.core import database
from backend.app.core import owner as owner_mod
from backend.app.core.plans import PLANS, parse_plan
from backend.app.core.scan_cancel import CANCEL_ACTIVE_SCAN_SQL

router = APIRouter(prefix="/api/v1/owner", tags=["Owner console actions"])

MAX_TRIAL_DAYS = 60          # per extension
MAX_TRIAL_HORIZON_DAYS = 90  # a trial never ends more than this far ahead

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class ReasonBody(BaseModel):
    reason: Reason


class PlanBody(ReasonBody):
    plan: str = Field(min_length=1, max_length=32)


class TrialBody(ReasonBody):
    days: int = Field(ge=1, le=MAX_TRIAL_DAYS)


def _uuid(value: str) -> str:
    import uuid
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found.")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _run(request: Request, owner: Dict[str, Any], action: str, target_type: str, target_id: str,
         reason: str, work: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    """Run `work(cur)` and its owner audit row in one transaction.

    `work` returns {"result": ..., "audit": {...before/after...}} or raises
    HTTPException to refuse; a refusal rolls back and is audited as rejected.
    """
    try:
        with database.get_db() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    done = work(cur)
                    cur.execute(
                        "INSERT INTO owner_audit (actor_user_id, actor_email, session_id, action, outcome, "
                        "target_type, target_id, ip, user_agent, metadata) "
                        "VALUES (%s, %s, %s, %s, 'success', %s, %s, %s, %s, %s::jsonb) RETURNING id",
                        (owner["user_id"], owner["email"], owner["session_id"], action, target_type, target_id,
                         owner_mod.client_ip(request), (request.headers.get("user-agent") or "")[:200] or None,
                         json.dumps({"reason": reason, **done["audit"]}, default=_iso)),
                    )
                    if cur.fetchone() is None:
                        raise RuntimeError("owner audit insert returned no row")
    except HTTPException as refused:
        if refused.status_code < 500:
            owner_mod.audit(request, action, "rejected", user_id=owner["user_id"], email=owner["email"],
                            session_id=owner["session_id"], target_type=target_type, target_id=target_id,
                            metadata={"reason": reason, "detail": refused.detail})
        raise
    except Exception:
        owner_mod.logger.exception("owner action %s failed", action)
        raise HTTPException(status_code=503, detail="The change could not be saved. Nothing was changed.")
    return done["result"]


def _customer_log(cur, org_id: Optional[str], user_id: Optional[str], action: str,
                  resource_type: str, resource_id: str, metadata: Dict[str, Any]) -> None:
    cur.execute(
        "INSERT INTO audit_log (org_id, user_id, action, resource_type, resource_id, metadata) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
        (org_id, user_id, action, resource_type, resource_id, json.dumps({"by": "cyphward", **metadata})),
    )


def _lock_org(cur, org_id: str) -> Dict[str, Any]:
    """Same lock order as customer billing: organization row first."""
    cur.execute("SELECT id, name, plan FROM organizations WHERE id = %s FOR UPDATE", (org_id,))
    org = cur.fetchone()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    cur.execute("SELECT id, plan, status, current_period_end, trial_ends_at FROM subscriptions "
                "WHERE org_id = %s FOR UPDATE", (org_id,))
    return {"org": org, "sub": cur.fetchone()}


# ── Plan ───────────────────────────────────────────────────────────────────
@router.post("/organizations/{org_id}/plan")
def change_plan(org_id: str, body: PlanBody, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Set the plan that governs the organization. Status, period and invoices are untouched."""
    org_id = _uuid(org_id)
    plan = parse_plan(body.plan)

    def work(cur):
        locked = _lock_org(cur, org_id)
        org, sub = locked["org"], locked["sub"]
        before = (sub or {}).get("plan") or org.get("plan")
        if before == plan:
            raise HTTPException(status_code=409, detail=f"Already on the {PLANS[plan]['label']} plan.")
        cur.execute("UPDATE organizations SET plan = %s WHERE id = %s RETURNING id", (plan, org_id))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The organization changed; reload and try again.")
        if sub:
            cur.execute("UPDATE subscriptions SET plan = %s, updated_at = now() WHERE id = %s RETURNING id",
                        (plan, sub["id"]))
            if cur.fetchone() is None:
                raise HTTPException(status_code=409, detail="The subscription changed; reload and try again.")
        _customer_log(cur, org_id, None, "billing.plan_changed", "organization", org_id,
                      {"from": before, "plan": plan})
        return {"result": {"plan": plan, "previous_plan": before},
                "audit": {"from": before, "to": plan, "subscription": bool(sub)}}

    return _run(request, owner, "owner.action.change_plan", "organization", org_id, body.reason, work)


# ── Trial ──────────────────────────────────────────────────────────────────
@router.post("/organizations/{org_id}/trial")
def extend_trial(org_id: str, body: TrialBody, request: Request,
                 owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Push a trialing subscription's end out by `days` (from now if it has already lapsed)."""
    org_id = _uuid(org_id)

    def work(cur):
        sub = _lock_org(cur, org_id)["sub"]
        if not sub or (sub.get("status") or "").lower() != "trialing":
            raise HTTPException(status_code=409, detail="This organization isn't on a trial.")
        now = datetime.now(timezone.utc)
        current = sub.get("trial_ends_at") or sub.get("current_period_end") or now
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        new_end = max(current, now) + timedelta(days=body.days)
        if new_end > now + timedelta(days=MAX_TRIAL_HORIZON_DAYS):
            raise HTTPException(status_code=409,
                                detail=f"A trial can't end more than {MAX_TRIAL_HORIZON_DAYS} days from today.")
        # effective_status() expires a trial at current_period_end, so both move together.
        cur.execute(
            "UPDATE subscriptions SET trial_ends_at = %s, current_period_end = %s, updated_at = now() "
            "WHERE id = %s AND status = 'trialing' RETURNING trial_ends_at",
            (new_end, new_end, sub["id"]))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The subscription changed; reload and try again.")
        _customer_log(cur, org_id, None, "billing.trial_extended", "subscription", str(sub["id"]),
                      {"days": body.days, "trial_ends_at": new_end.isoformat()})
        return {"result": {"trial_ends_at": new_end.isoformat(), "previous_trial_ends_at": _iso(current)},
                "audit": {"days": body.days, "from": current, "to": new_end}}

    return _run(request, owner, "owner.action.extend_trial", "organization", org_id, body.reason, work)


# ── Scan ───────────────────────────────────────────────────────────────────
@router.post("/scans/{scan_id}/cancel")
def cancel_scan(scan_id: str, body: ReasonBody, request: Request,
                owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """Cancel a queued or running scan (e.g. one whose worker stopped), fencing its worker."""
    scan_id = _uuid(scan_id)

    def work(cur):
        cur.execute("SELECT id, org_id, status, claimed_by, lease_expires_at FROM scans WHERE id = %s FOR UPDATE",
                    (scan_id,))
        scan = cur.fetchone()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found.")
        if scan["status"] not in ("queued", "running"):
            raise HTTPException(status_code=409, detail=f"Scan is already {scan['status']}.")
        cur.execute(CANCEL_ACTIVE_SCAN_SQL, (scan_id, scan["org_id"]))
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="The scan changed state; reload and try again.")
        _customer_log(cur, str(scan["org_id"]), None, "scan.cancelled", "scan", scan_id, {})
        return {"result": {"status": "cancelled", "previous_status": scan["status"]},
                "audit": {"from": scan["status"], "to": "cancelled", "org_id": str(scan["org_id"]),
                          "claimed_by": scan.get("claimed_by"), "lease_expires_at": scan.get("lease_expires_at")}}

    return _run(request, owner, "owner.action.cancel_scan", "scan", scan_id, body.reason, work)


# ── User ───────────────────────────────────────────────────────────────────
@router.post("/users/{user_id}/sign-out")
def sign_out_everywhere(user_id: str, body: ReasonBody, request: Request,
                        owner: Dict[str, Any] = Depends(owner_mod.require_owner_mutation)) -> Dict[str, Any]:
    """End every customer-app session and forget every remembered browser for a user.

    Access tokens stop working at once (each request checks its session). The
    user's owner-console sessions, if any, are not touched here.
    """
    user_id = _uuid(user_id)

    def work(cur):
        if user_id == owner["user_id"]:
            raise HTTPException(status_code=409, detail="That's your own account — use Sign out instead.")
        cur.execute("SELECT id FROM profiles WHERE id = %s", (user_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="User not found.")
        cur.execute("UPDATE auth_sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL "
                    "RETURNING id", (user_id,))
        sessions = len(cur.fetchall())
        cur.execute("DELETE FROM trusted_browsers WHERE user_id = %s RETURNING id", (user_id,))
        browsers = len(cur.fetchall())
        _customer_log(cur, None, user_id, "auth.signed_out_everywhere", "user", user_id,
                      {"sessions": sessions, "remembered_browsers": browsers})
        return {"result": {"sessions_revoked": sessions, "remembered_browsers_cleared": browsers},
                "audit": {"sessions_revoked": sessions, "remembered_browsers_cleared": browsers}}

    return _run(request, owner, "owner.action.sign_out_everywhere", "user", user_id, body.reason, work)
