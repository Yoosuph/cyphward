"""Subscription-aware entitlements (billing follow-up).

Precedence: a live `subscriptions` row governs; otherwise the legacy
`organizations.plan` text applies. Effective status is computed in code —
`trialing`/`active` get full plan quotas; anything else (`past_due`,
`canceled`, or an expired period with no renewal) falls back to the
growth floor so the workspace stays readable but heavy use stops.
Provider webhooks do not exist yet; renewal is an explicit manual step.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.app.core.plans import PLANS, LEGACY_PLAN_FALLBACK

FLOOR_PLAN = "starter"


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def effective_status(sub: Optional[Dict[str, Any]]) -> Optional[str]:
    """Live status with period-expiry applied (no cron needed)."""
    if not sub:
        return None
    status = (sub.get("status") or "").strip().lower()
    if status in ("trialing", "active"):
        end = _parse_ts(sub.get("current_period_end"))
        if end is not None and datetime.now(timezone.utc) >= end:
            return "past_due"
    return status


def _org_plan_slug(org: Dict[str, Any]) -> str:
    slug = (org.get("plan") or "").strip().lower() if isinstance(org.get("plan"), str) else ""
    return slug if slug in PLANS else LEGACY_PLAN_FALLBACK


def resolve_plan(org: Dict[str, Any], sub: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Entitlements for an org: subscription plan when live, else org text.

    Returns {plan, label, quotas..., subscription: {status, ...} | None}.
    """
    status = effective_status(sub)
    if sub is not None and status in ("trialing", "active"):
        slug = (sub.get("plan") or "").strip().lower()
        if slug not in PLANS:
            slug = _org_plan_slug(org)
    elif sub is not None and status in ("past_due", "canceled"):
        slug = FLOOR_PLAN
    else:
        slug = _org_plan_slug(org)
    ent = {"plan": slug, **PLANS[slug]}
    ent["subscription"] = (
        {"status": status,
         "current_period_end": str(sub.get("current_period_end")) if sub else None,
         "cancel_at_period_end": bool(sub.get("cancel_at_period_end")) if sub else False}
        if sub else None
    )
    return ent
