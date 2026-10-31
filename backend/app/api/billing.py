"""Owner billing endpoints (manual provider — nothing is charged).

GET    /billing/subscription   current subscription + entitlements + invoices
POST   /billing/subscription   refuse self-activation; arrange manual billing
POST   /billing/subscription/renew    refuse unconfirmed renewal
POST   /billing/subscription/cancel   cancel at period end
GET    /billing/invoices       invoice ledger
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.billing.provider import provider
from backend.app.billing.subscriptions import effective_status, resolve_plan
from backend.app.core.auth import get_current_org, log_audit, membership_role, require_owner
from backend.app.core.suspension import require_active_owner
from backend.app.core.database import execute_one, execute_query, get_db
from backend.app.core.plans import parse_plan

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


class SetPlanRequest(BaseModel):
    plan: str = Field(min_length=1, max_length=32)


def _get_subscription(org_id: str) -> Optional[Dict[str, Any]]:
    return execute_one("SELECT * FROM subscriptions WHERE org_id = %s", (org_id,))


def _recent_invoices(org_id: str) -> List[Dict[str, Any]]:
    return (
        execute_query(
            "SELECT id, number, plan, amount_kobo, currency, status, provider_ref, "
            "period_start, period_end, created_at FROM invoices "
            "WHERE org_id = %s ORDER BY created_at DESC LIMIT 20",
            (org_id,),
        )
        or []
    )


def manual_billing_required() -> None:
    raise HTTPException(status_code=409, detail={
        "code": "manual_billing_review_required",
        "message": "Contact Cyphward through /contact to arrange a plan or renewal. Paid access starts after payment is confirmed; this request has not changed your plan or trial.",
    })


@router.get("/subscription")
def get_subscription(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    sub = _get_subscription(str(org["id"]))
    return {
        "subscription": sub,
        "effective_status": effective_status(sub),
        "entitlements": resolve_plan(org, sub),
        "provider": provider.name,
        "role": membership_role(org),
        "billing_mode": "manual_confirmation",
        "trial_days": 30,
    }


@router.get("/invoices")
def list_invoices(org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    return {"invoices": _recent_invoices(str(org["id"]))}


@router.post("/subscription")
def set_subscription(
    req: SetPlanRequest,
    org: Dict[str, Any] = Depends(require_active_owner),
) -> Dict[str, Any]:
    """Choosing a plan cannot create a paid period or restart a trial."""
    parse_plan(req.plan)
    manual_billing_required()


@router.post("/subscription/renew")
def renew_subscription(org: Dict[str, Any] = Depends(require_active_owner)) -> Dict[str, Any]:
    """Keep the endpoint explicit for older clients, without granting time."""
    manual_billing_required()


@router.post("/subscription/cancel")
def cancel_subscription(org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    """Owner cancels at period end (quotas hold until the period lapses).

    Allowed while the organisation is suspended (founder decision: a customer can always stop paying). Plan and
    renewal requests, which add cost, stay refused (core/suspension.py)."""
    org_id = str(org["id"])
    with get_db() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM organizations WHERE id = %s FOR UPDATE", (org_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Workspace not found.")
                cur.execute(
                    "UPDATE subscriptions SET cancel_at_period_end = true, updated_at = now() "
                    "WHERE org_id = %s RETURNING *",
                    (org_id,),
                )
                sub = cur.fetchone()
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription — set a plan first.")
    log_audit(org_id, org.get("current_user_id"), "billing.cancelled",
              "subscription", str(sub["id"]), {})
    return {"subscription": sub}
