"""Owner billing endpoints (manual provider — nothing is charged).

GET    /billing/subscription   current subscription + entitlements + invoices
POST   /billing/subscription   set plan (new 30-day period, open invoice)
POST   /billing/subscription/renew    extend 30 days (open invoice)
POST   /billing/subscription/cancel   cancel at period end
GET    /billing/invoices       invoice ledger
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.billing.provider import PLAN_PRICES_KOBO, provider
from backend.app.billing.subscriptions import effective_status, resolve_plan
from backend.app.core.auth import get_current_org, log_audit, membership_role, require_owner
from backend.app.core.database import execute_one, execute_query
from backend.app.core.plans import PLANS, parse_plan

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


def _open_invoice(org_id: str, plan: str) -> Optional[Dict[str, Any]]:
    if plan not in PLAN_PRICES_KOBO:
        return None  # retired/custom tiers never auto-invoice
    return execute_one(
        """
        INSERT INTO invoices (org_id, plan, amount_kobo, currency, status)
        VALUES (%s, %s, %s, 'NGN', 'open')
        RETURNING id, number, plan, amount_kobo, currency, status, created_at
        """,
        (org_id, plan, PLAN_PRICES_KOBO[plan]),
    )


@router.get("/subscription")
def get_subscription(org: Dict[str, Any] = Depends(get_current_org)) -> Dict[str, Any]:
    sub = _get_subscription(str(org["id"]))
    return {
        "subscription": sub,
        "effective_status": effective_status(sub),
        "entitlements": resolve_plan(org, sub),
        "provider": provider.name,
        "role": membership_role(org),
    }


@router.get("/invoices")
def list_invoices(org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    return {"invoices": _recent_invoices(str(org["id"]))}


@router.post("/subscription")
def set_subscription(
    req: SetPlanRequest,
    org: Dict[str, Any] = Depends(require_owner),
) -> Dict[str, Any]:
    """Owner sets the commercial plan (manual billing — records only)."""
    plan = parse_plan(req.plan)
    org_id = str(org["id"])
    sub = execute_one(
        """
        INSERT INTO subscriptions (org_id, plan, status, provider,
                                   current_period_start, current_period_end)
        VALUES (%s, %s, 'active', 'manual', now(), now() + interval '30 days')
        ON CONFLICT (org_id) DO UPDATE SET
          plan = EXCLUDED.plan,
          status = CASE WHEN subscriptions.status = 'canceled' THEN 'active'
                        ELSE subscriptions.status END,
          cancel_at_period_end = false,
          current_period_start = now(),
          current_period_end = now() + interval '30 days',
          updated_at = now()
        RETURNING *
        """,
        (org_id, plan),
    )
    invoice = _open_invoice(org_id, plan)
    provider.charge(invoice or {"id": None, "amount_kobo": 0})
    log_audit(org_id, org.get("current_user_id"), "billing.plan_changed",
              "subscription", str(sub["id"]), {"plan": plan})
    return {"subscription": sub, "invoice": invoice}


@router.post("/subscription/renew")
def renew_subscription(org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    """Owner extends the period 30 days (manual billing — records only)."""
    org_id = str(org["id"])
    sub = _get_subscription(org_id)
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription — set a plan first.")
    plan = (sub.get("plan") or "").strip().lower()
    if plan not in PLANS:
        raise HTTPException(status_code=400, detail="Subscription plan is invalid — set a plan first.")
    sub = execute_one(
        """
        UPDATE subscriptions
        SET status = 'active', cancel_at_period_end = false,
            current_period_start = now(),
            current_period_end = now() + interval '30 days',
            updated_at = now()
        WHERE org_id = %s RETURNING *
        """,
        (org_id,),
    )
    invoice = _open_invoice(org_id, plan)
    log_audit(org_id, org.get("current_user_id"), "billing.renewed",
              "subscription", str(sub["id"]), {"plan": plan})
    return {"subscription": sub, "invoice": invoice}


@router.post("/subscription/cancel")
def cancel_subscription(org: Dict[str, Any] = Depends(require_owner)) -> Dict[str, Any]:
    """Owner cancels at period end (quotas hold until the period lapses)."""
    org_id = str(org["id"])
    sub = execute_one(
        "UPDATE subscriptions SET cancel_at_period_end = true, updated_at = now() "
        "WHERE org_id = %s RETURNING *",
        (org_id,),
    )
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription — set a plan first.")
    log_audit(org_id, org.get("current_user_id"), "billing.cancelled",
              "subscription", str(sub["id"]), {})
    return {"subscription": sub}
